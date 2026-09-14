"""Transactional access to the central control plane."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Iterator
from uuid import UUID

from sqlalchemy import Engine, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from app.control_models import AuthSession, ControlTenant, LoginThrottle, SecurityEvent


_AUDIT_CODE = re.compile(r"[a-z0-9_.-]{1,128}\Z")


class ControlConfigurationError(RuntimeError):
    pass


class InvalidTenantTransitionError(RuntimeError):
    pass


class SecurityEventRedactionError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class ControlDatabaseSettings:
    database_url: str

    @classmethod
    def from_env(cls) -> "ControlDatabaseSettings":
        value = os.getenv("SMART_CRM_CONTROL_DATABASE_URL")
        if not value:
            raise ControlConfigurationError("SMART_CRM_CONTROL_DATABASE_URL is required")
        return cls(database_url=value)

    def __repr__(self) -> str:
        return "ControlDatabaseSettings(database_url='<redacted>')"


@dataclass(frozen=True)
class ThrottleResult:
    failure_count: int
    blocked: bool
    blocked_until: datetime | None


class ControlDatabase:
    def __init__(
        self,
        settings: ControlDatabaseSettings | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        if engine is None:
            resolved = settings or ControlDatabaseSettings.from_env()
            engine = create_engine(resolved.database_url, pool_pre_ping=True)
            self.settings: ControlDatabaseSettings | None = resolved
        else:
            self.settings = settings
        self.engine = engine
        self._session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )
        self._open_sessions = 0
        self._session_lock = Lock()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self._session_factory()
        with self._session_lock:
            self._open_sessions += 1
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            with self._session_lock:
                self._open_sessions -= 1

    @property
    def open_session_count(self) -> int:
        with self._session_lock:
            return self._open_sessions

    def dispose(self) -> None:
        self.engine.dispose()


class ControlRepository:
    _TRANSITIONS = {
        "provisioning": {"provisioning", "active", "failed"},
        "failed": {"failed", "provisioning"},
        "active": {"active", "inactive"},
        "inactive": {"inactive", "active"},
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_tenant(
        self,
        *,
        tenant_id: UUID,
        slug: str,
        display_name: str,
        secret_ref: str,
        expected_tenant_revision: str,
    ) -> ControlTenant:
        tenant = ControlTenant(
            id=tenant_id,
            slug=slug,
            display_name=display_name,
            status="provisioning",
            secret_ref=secret_ref,
            expected_tenant_revision=expected_tenant_revision,
        )
        self.session.add(tenant)
        self.session.flush()
        return tenant

    def find_tenant_by_slug(self, slug: str) -> ControlTenant | None:
        return self.session.scalar(select(ControlTenant).where(ControlTenant.slug == slug))

    def get_tenant(self, tenant_id: UUID, *, for_update: bool = False) -> ControlTenant | None:
        statement = select(ControlTenant).where(ControlTenant.id == tenant_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def transition_tenant(
        self,
        tenant_id: UUID,
        status: str,
        *,
        activated_at: datetime | None = None,
        checkpoint: str | None = None,
        error_code: str | None = None,
    ) -> ControlTenant:
        tenant = self.get_tenant(tenant_id, for_update=True)
        if tenant is None:
            raise LookupError("control tenant not found")
        allowed = self._TRANSITIONS.get(tenant.status, set())
        if status not in allowed:
            raise InvalidTenantTransitionError(
                f"invalid tenant transition: {tenant.status} -> {status}"
            )
        tenant.status = status
        tenant.provisioning_checkpoint = checkpoint
        tenant.last_error_code = error_code
        if status == "active" and activated_at is not None:
            tenant.activated_at = activated_at
        self.session.flush()
        return tenant

    def create_session(
        self,
        *,
        token_digest: str,
        tenant_id: UUID,
        user_id: str,
        auth_version: int,
        created_at: datetime,
        last_seen_at: datetime,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
        correlation_digest: str,
    ) -> AuthSession:
        auth_session = AuthSession(
            token_digest=token_digest,
            tenant_id=tenant_id,
            user_id=user_id,
            auth_version=auth_version,
            created_at=created_at,
            last_seen_at=last_seen_at,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            correlation_digest=correlation_digest,
        )
        self.session.add(auth_session)
        self.session.flush()
        return auth_session

    def load_active_session(self, token_digest: str, *, now: datetime) -> AuthSession | None:
        return self.session.scalar(
            select(AuthSession).where(
                AuthSession.token_digest == token_digest,
                AuthSession.revoked_at.is_(None),
                AuthSession.idle_expires_at > now,
                AuthSession.absolute_expires_at > now,
            )
        )

    def touch_session(
        self,
        token_digest: str,
        *,
        now: datetime,
        idle_expires_at: datetime,
    ) -> bool:
        result = self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.token_digest == token_digest,
                AuthSession.revoked_at.is_(None),
                AuthSession.absolute_expires_at > now,
            )
            .values(last_seen_at=now, idle_expires_at=idle_expires_at)
        )
        return bool(result.rowcount)

    def revoke_session(
        self,
        token_digest: str,
        *,
        reason: str,
        revoked_at: datetime,
    ) -> bool:
        result = self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.token_digest == token_digest,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revocation_reason=reason)
        )
        return bool(result.rowcount)

    def revoke_user_sessions(
        self,
        tenant_id: UUID,
        user_id: str,
        *,
        reason: str,
        revoked_at: datetime,
    ) -> int:
        result = self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.tenant_id == tenant_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revocation_reason=reason)
        )
        return int(result.rowcount or 0)

    def cleanup_expired_sessions(self, *, now: datetime) -> int:
        result = self.session.execute(
            delete(AuthSession).where(
                or_(
                    AuthSession.idle_expires_at <= now,
                    AuthSession.absolute_expires_at <= now,
                )
            )
        )
        return int(result.rowcount or 0)

    def record_login_failure(
        self,
        bucket_type: str,
        subject_digest: str,
        *,
        now: datetime,
        limit: int,
        window: timedelta,
        block_for: timedelta,
    ) -> ThrottleResult:
        self.session.execute(
            insert(LoginThrottle)
            .values(
                bucket_type=bucket_type,
                subject_digest=subject_digest,
                failure_count=0,
                window_started_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    LoginThrottle.bucket_type,
                    LoginThrottle.subject_digest,
                ]
            )
        )
        throttle = self.session.scalar(
            select(LoginThrottle)
            .where(
                LoginThrottle.bucket_type == bucket_type,
                LoginThrottle.subject_digest == subject_digest,
            )
            .with_for_update()
        )
        if throttle is None:
            raise RuntimeError("throttle row was not created")

        if throttle.blocked_until is not None and throttle.blocked_until > now:
            return ThrottleResult(
                failure_count=throttle.failure_count,
                blocked=True,
                blocked_until=throttle.blocked_until,
            )

        if throttle.window_started_at + window <= now:
            throttle.failure_count = 0
            throttle.window_started_at = now
            throttle.blocked_until = None

        throttle.failure_count += 1
        throttle.updated_at = now
        if throttle.failure_count >= limit:
            throttle.failure_count = limit
            throttle.blocked_until = now + block_for

        self.session.flush()
        return ThrottleResult(
            failure_count=throttle.failure_count,
            blocked=throttle.blocked_until is not None and throttle.blocked_until > now,
            blocked_until=throttle.blocked_until,
        )

    def clear_login_throttle(self, bucket_type: str, subject_digest: str) -> bool:
        result = self.session.execute(
            delete(LoginThrottle).where(
                LoginThrottle.bucket_type == bucket_type,
                LoginThrottle.subject_digest == subject_digest,
            )
        )
        return bool(result.rowcount)

    def append_security_event(
        self,
        *,
        event_type: str,
        tenant_id: UUID | None,
        user_id: str | None,
        correlation_digest: str,
        outcome_code: str,
        occurred_at: datetime,
    ) -> SecurityEvent:
        if not _AUDIT_CODE.fullmatch(event_type) or not _AUDIT_CODE.fullmatch(outcome_code):
            raise SecurityEventRedactionError("security event accepts redacted codes only")
        if not re.fullmatch(r"[0-9a-f]{64}", correlation_digest):
            raise SecurityEventRedactionError("correlation digest must be SHA-256 hex")
        event = SecurityEvent(
            event_type=event_type,
            tenant_id=tenant_id,
            user_id=user_id,
            correlation_digest=correlation_digest,
            outcome_code=outcome_code,
            created_at=occurred_at,
        )
        self.session.add(event)
        self.session.flush()
        return event
