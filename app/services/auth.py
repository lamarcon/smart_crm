"""Authentication across the control plane and isolated tenant databases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Callable, Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.control_database import ControlDatabase, ControlRepository
from app.control_models import LoginThrottle
from app.models import CrmUser
from app.policies import CURRENT_ROLES, PrincipalScope
from app.schemas import LOGIN_FAILURE_MESSAGE
from app.security.passwords import (
    IDLE_SESSION_TTL,
    digest_session_token,
    new_session_expiry,
    new_session_token,
    verify_or_dummy,
)
from app.tenant_database import TenantDatabaseRouter, TenantUnavailableError


ACCOUNT_FAILURE_LIMIT = 5
IP_FAILURE_LIMIT = 30
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_BLOCK_DURATION = timedelta(minutes=15)


class AuthenticationError(RuntimeError):
    """Public, deliberately generic authentication failure."""


@dataclass(frozen=True)
class TenantUserIdentity:
    user_id: str
    workspace_id: str
    name: str
    email: str
    password_hash: str | None
    auth_enabled: bool
    auth_version: int
    role: str
    team_id: str | None
    status: str


@dataclass(frozen=True)
class TenantLocation:
    tenant_id: UUID
    slug: str
    display_name: str


@dataclass(frozen=True)
class SessionContext:
    principal: PrincipalScope
    tenant_slug: str
    tenant_display_name: str
    user_name: str
    email: str
    token_digest: str


@dataclass(frozen=True)
class LoginResult:
    token: str
    context: SessionContext


class TenantRouter(Protocol):
    def tenant_session_scope(self, tenant_id: UUID): ...  # noqa: ANN201


RepositoryFactory = Callable[[object], ControlRepository]
UserByEmailLoader = Callable[[object, str], TenantUserIdentity | None]
UserByIdLoader = Callable[[object, str], TenantUserIdentity | None]


class SecurityAuditService:
    """Append redacted central events without weakening the guarded operation."""

    def __init__(
        self,
        control_database: ControlDatabase,
        *,
        repository_factory: RepositoryFactory = ControlRepository,
    ) -> None:
        self._control_database = control_database
        self._repository_factory = repository_factory

    @staticmethod
    def correlation_digest(*parts: object) -> str:
        encoded = "\0".join(str(part) for part in parts).encode("utf-8")
        return sha256(encoded).hexdigest()

    def record(
        self,
        *,
        event_type: str,
        tenant_id: UUID | None,
        user_id: str | None,
        correlation_digest: str,
        outcome_code: str,
        occurred_at: datetime,
    ) -> UUID | None:
        try:
            with self._control_database.session_scope() as session:
                event = self._repository_factory(session).append_security_event(
                    event_type=event_type,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    correlation_digest=correlation_digest,
                    outcome_code=outcome_code,
                    occurred_at=occurred_at,
                )
            return event.id
        except Exception:
            return None


def _workspace_id(session: Session) -> str:
    workspace_id = session.scalar(text("SELECT current_setting('smartcrm.workspace_id', true)"))
    if not workspace_id:
        raise TenantUnavailableError("tenant database unavailable")
    return str(workspace_id)


def _identity(user: CrmUser | None) -> TenantUserIdentity | None:
    if user is None:
        return None
    return TenantUserIdentity(
        user_id=user.id,
        workspace_id=user.workspace_id,
        name=user.name,
        email=user.normalized_email or user.email.lower(),
        password_hash=user.password_hash,
        auth_enabled=user.auth_enabled,
        auth_version=user.auth_version,
        role=user.role,
        team_id=user.team_id,
        status=user.status,
    )


def load_tenant_user_by_email(session: Session, email: str) -> TenantUserIdentity | None:
    workspace_id = _workspace_id(session)
    user = session.scalar(
        select(CrmUser).where(
            CrmUser.workspace_id == workspace_id,
            CrmUser.normalized_email == email,
            CrmUser.deleted_at.is_(None),
        )
    )
    return _identity(user)


def load_tenant_user_by_id(session: Session, user_id: str) -> TenantUserIdentity | None:
    workspace_id = _workspace_id(session)
    user = session.scalar(
        select(CrmUser).where(
            CrmUser.workspace_id == workspace_id,
            CrmUser.id == user_id,
            CrmUser.deleted_at.is_(None),
        )
    )
    return _identity(user)


class AuthService:
    def __init__(
        self,
        control_database: ControlDatabase,
        router: TenantDatabaseRouter | TenantRouter,
        *,
        repository_factory: RepositoryFactory = ControlRepository,
        user_by_email_loader: UserByEmailLoader = load_tenant_user_by_email,
        user_by_id_loader: UserByIdLoader = load_tenant_user_by_id,
        security_audit: SecurityAuditService | None = None,
    ) -> None:
        self._control_database = control_database
        self._router = router
        self._repository_factory = repository_factory
        self._security_audit = security_audit or SecurityAuditService(
            control_database,
            repository_factory=repository_factory,
        )
        self._user_by_email_loader = user_by_email_loader
        self._user_by_id_loader = user_by_id_loader

    def record_security_event(self, **values) -> UUID | None:  # noqa: ANN003
        return self._security_audit.record(**values)

    @staticmethod
    def security_correlation(*parts: object) -> str:
        return SecurityAuditService.correlation_digest(*parts)

    def locate_tenant(self, slug: str) -> TenantLocation | None:
        with self._control_database.session_scope() as session:
            tenant = self._repository_factory(session).find_tenant_by_slug(slug)
            if tenant is None or tenant.status != "active":
                return None
            return TenantLocation(tenant.id, tenant.slug, tenant.display_name)

    @staticmethod
    def login_subject_digests(slug: str, email: str, ip_address: str) -> tuple[str, str]:
        account = sha256(f"{slug}\0{email}".encode("utf-8")).hexdigest()
        ip = sha256(ip_address.strip().encode("utf-8")).hexdigest()
        return account, ip

    @staticmethod
    def _blocked(repository: ControlRepository, kind: str, digest: str, now: datetime) -> bool:
        throttle = repository.session.get(
            LoginThrottle,
            {"bucket_type": kind, "subject_digest": digest},
        )
        return bool(
            throttle is not None
            and throttle.blocked_until is not None
            and throttle.blocked_until > now
        )

    def _record_failure(
        self,
        *,
        tenant_id: UUID | None,
        user_id: str | None,
        account_digest: str,
        ip_digest: str,
        now: datetime,
        outcome_code: str,
    ) -> None:
        with self._control_database.session_scope() as session:
            repository = self._repository_factory(session)
            repository.record_login_failure(
                "account",
                account_digest,
                now=now,
                limit=ACCOUNT_FAILURE_LIMIT,
                window=LOGIN_WINDOW,
                block_for=LOGIN_BLOCK_DURATION,
            )
            repository.record_login_failure(
                "ip",
                ip_digest,
                now=now,
                limit=IP_FAILURE_LIMIT,
                window=LOGIN_WINDOW,
                block_for=LOGIN_BLOCK_DURATION,
            )
            repository.append_security_event(
                event_type="login.failed",
                tenant_id=tenant_id,
                user_id=user_id,
                correlation_digest=account_digest,
                outcome_code=outcome_code,
                occurred_at=now,
            )

    def _raise_login_failure(
        self,
        *,
        tenant_id: UUID | None,
        user_id: str | None,
        account_digest: str,
        ip_digest: str,
        now: datetime,
        outcome_code: str = "invalid_credentials",
    ) -> None:
        self._record_failure(
            tenant_id=tenant_id,
            user_id=user_id,
            account_digest=account_digest,
            ip_digest=ip_digest,
            now=now,
            outcome_code=outcome_code,
        )
        raise AuthenticationError(LOGIN_FAILURE_MESSAGE)

    def login(
        self,
        slug: str,
        email: str,
        password: str,
        ip_address: str,
        *,
        now: datetime,
    ) -> LoginResult:
        account_digest, ip_digest = self.login_subject_digests(slug, email, ip_address)
        with self._control_database.session_scope() as session:
            repository = self._repository_factory(session)
            tenant = repository.find_tenant_by_slug(slug)
            blocked = self._blocked(repository, "account", account_digest, now) or self._blocked(
                repository, "ip", ip_digest, now
            )

        if blocked:
            verify_or_dummy(None, password)
            self._raise_login_failure(
                tenant_id=tenant.id if tenant is not None else None,
                user_id=None,
                account_digest=account_digest,
                ip_digest=ip_digest,
                now=now,
                outcome_code="rate_limited",
            )

        if tenant is None or tenant.status != "active":
            verify_or_dummy(None, password)
            self._raise_login_failure(
                tenant_id=tenant.id if tenant is not None else None,
                user_id=None,
                account_digest=account_digest,
                ip_digest=ip_digest,
                now=now,
            )

        try:
            with self._router.tenant_session_scope(tenant.id) as tenant_session:
                user = self._user_by_email_loader(tenant_session, email)
                password_valid = verify_or_dummy(user.password_hash if user is not None else None, password)
        except TenantUnavailableError:
            verify_or_dummy(None, password)
            self._raise_login_failure(
                tenant_id=tenant.id,
                user_id=None,
                account_digest=account_digest,
                ip_digest=ip_digest,
                now=now,
            )

        if (
            user is None
            or not password_valid
            or not user.auth_enabled
            or user.status != "Ativo"
            or user.role not in CURRENT_ROLES
        ):
            self._raise_login_failure(
                tenant_id=tenant.id,
                user_id=user.user_id if user is not None else None,
                account_digest=account_digest,
                ip_digest=ip_digest,
                now=now,
            )

        token = new_session_token()
        token_digest = digest_session_token(token)
        expiry = new_session_expiry(now)
        correlation_digest = sha256(f"session\0{token_digest}".encode("ascii")).hexdigest()
        with self._control_database.session_scope() as session:
            repository = self._repository_factory(session)
            repository.clear_login_throttle("account", account_digest)
            repository.create_session(
                token_digest=token_digest,
                tenant_id=tenant.id,
                user_id=user.user_id,
                auth_version=user.auth_version,
                created_at=now,
                last_seen_at=now,
                idle_expires_at=expiry.idle_expires_at,
                absolute_expires_at=expiry.absolute_expires_at,
                correlation_digest=correlation_digest,
            )
            repository.append_security_event(
                event_type="login.succeeded",
                tenant_id=tenant.id,
                user_id=user.user_id,
                correlation_digest=correlation_digest,
                outcome_code="authenticated",
                occurred_at=now,
            )
        return LoginResult(token=token, context=self._context(tenant, user, token_digest))

    @staticmethod
    def _context(tenant, user: TenantUserIdentity, token_digest: str) -> SessionContext:  # noqa: ANN001
        return SessionContext(
            principal=PrincipalScope(
                tenant_id=tenant.id,
                workspace_id=user.workspace_id,
                user_id=user.user_id,
                role=user.role,
                team_id=user.team_id,
                auth_version=user.auth_version,
            ),
            tenant_slug=tenant.slug,
            tenant_display_name=tenant.display_name,
            user_name=user.name,
            email=user.email,
            token_digest=token_digest,
        )

    def current_session(self, token: str, *, now: datetime) -> SessionContext:
        token_digest = digest_session_token(token)
        with self._control_database.session_scope() as session:
            repository = self._repository_factory(session)
            auth_session = repository.load_active_session(token_digest, now=now)
            if auth_session is None:
                raise AuthenticationError("Sessão inválida")
            tenant = repository.get_tenant(auth_session.tenant_id)
            if tenant is None or tenant.status != "active":
                raise AuthenticationError("Sessão inválida")

        try:
            with self._router.tenant_session_scope(auth_session.tenant_id) as tenant_session:
                user = self._user_by_id_loader(tenant_session, auth_session.user_id)
        except TenantUnavailableError:
            raise AuthenticationError("Sessão inválida") from None

        if (
            user is None
            or not user.auth_enabled
            or user.status != "Ativo"
            or user.role not in CURRENT_ROLES
            or user.auth_version != auth_session.auth_version
        ):
            self.revoke_user_sessions(
                auth_session.tenant_id,
                auth_session.user_id,
                reason="auth_changed",
                now=now,
            )
            raise AuthenticationError("Sessão inválida")

        idle_expires_at = min(now + IDLE_SESSION_TTL, auth_session.absolute_expires_at)
        with self._control_database.session_scope() as session:
            self._repository_factory(session).touch_session(
                token_digest,
                now=now,
                idle_expires_at=idle_expires_at,
            )
        return self._context(tenant, user, token_digest)

    def revoke_user_sessions(
        self,
        tenant_id: UUID,
        user_id: str,
        *,
        reason: str,
        now: datetime,
    ) -> int:
        with self._control_database.session_scope() as session:
            count = self._repository_factory(session).revoke_user_sessions(
                tenant_id,
                user_id,
                reason=reason,
                revoked_at=now,
            )
        self.record_security_event(
            event_type="session.revoked",
            tenant_id=tenant_id,
            user_id=user_id,
            correlation_digest=self.security_correlation(
                "session-revocation", tenant_id, user_id, reason, now.isoformat()
            ),
            outcome_code=reason,
            occurred_at=now,
        )
        return count

    def logout(self, token: str, *, now: datetime) -> bool:
        token_digest = digest_session_token(token)
        with self._control_database.session_scope() as session:
            repository = self._repository_factory(session)
            auth_session = repository.load_active_session(token_digest, now=now)
            revoked = repository.revoke_session(
                token_digest,
                reason="logout",
                revoked_at=now,
            )
            if revoked:
                repository.append_security_event(
                    event_type="logout",
                    tenant_id=auth_session.tenant_id if auth_session is not None else None,
                    user_id=auth_session.user_id if auth_session is not None else None,
                    correlation_digest=sha256(f"logout\0{token_digest}".encode("ascii")).hexdigest(),
                    outcome_code="revoked",
                    occurred_at=now,
                )
            return revoked
