"""Fail-closed routing to isolated tenant PostgreSQL databases."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock
from typing import Callable, Iterator, Protocol
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.control_database import ControlDatabase, ControlRepository
from app.security.database_urls import validate_tenant_database_url
from app.security.secrets import SecretError, SecretProvider


class TenantSelectorError(TypeError):
    """Raised before lookup when a caller supplies an untrusted selector."""


class TenantUnavailableError(RuntimeError):
    """Generic, redacted tenant database failure."""


@dataclass(frozen=True)
class TenantDatabaseProfile:
    tenant_id: UUID
    status: str
    secret_ref: str
    profile_version: int
    expected_tenant_revision: str


class TenantProfileLoader(Protocol):
    def __call__(self, tenant_id: UUID) -> TenantDatabaseProfile | None: ...


class ControlTenantProfileLoader:
    """Read connection metadata from the central control database only."""

    def __init__(self, control_database: ControlDatabase) -> None:
        self._control_database = control_database

    def __call__(self, tenant_id: UUID) -> TenantDatabaseProfile | None:
        with self._control_database.session_scope() as session:
            tenant = ControlRepository(session).get_tenant(tenant_id)
            if tenant is None:
                return None
            return TenantDatabaseProfile(
                tenant_id=tenant.id,
                status=tenant.status,
                secret_ref=tenant.secret_ref,
                profile_version=tenant.profile_version,
                expected_tenant_revision=tenant.expected_tenant_revision,
            )


@dataclass(frozen=True)
class TenantDatabaseRouterSettings:
    max_cached_engines: int = 16
    pool_size: int = 2
    max_overflow: int = 2
    pool_timeout: float = 5.0
    connect_timeout: int = 3
    allow_insecure_loopback: bool = False
    supported_schema_contract: str = "tenant-v1"

    def __post_init__(self) -> None:
        if self.max_cached_engines < 1:
            raise ValueError("max_cached_engines must be positive")
        if self.pool_size < 1:
            raise ValueError("pool_size must be positive")
        if self.max_overflow < 0:
            raise ValueError("max_overflow cannot be negative")
        if self.pool_timeout <= 0:
            raise ValueError("pool_timeout must be positive")
        if self.connect_timeout < 1:
            raise ValueError("connect_timeout must be positive")
        if not self.supported_schema_contract:
            raise ValueError("supported_schema_contract is required")


@dataclass(frozen=True)
class _EngineEntry:
    profile_version: int
    engine: Engine


class _TenantGuardFailure(RuntimeError):
    pass


EngineFactory = Callable[..., Engine]
SecurityEventRecorder = Callable[..., object | None]


class TenantDatabaseRouter:
    """Resolve trusted tenant UUIDs to bounded, identity-guarded sessions."""

    def __init__(
        self,
        profile_loader: TenantProfileLoader,
        secret_provider: SecretProvider,
        *,
        settings: TenantDatabaseRouterSettings | None = None,
        engine_factory: EngineFactory | None = None,
        security_event_recorder: SecurityEventRecorder | None = None,
    ) -> None:
        self._profile_loader = profile_loader
        self._secret_provider = secret_provider
        self._settings = settings or TenantDatabaseRouterSettings()
        self._engine_factory = engine_factory or create_engine
        self._security_event_recorder = security_event_recorder
        self._engines: OrderedDict[UUID, _EngineEntry] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _require_trusted_tenant_id(tenant_id: UUID) -> UUID:
        if not isinstance(tenant_id, UUID):
            raise TenantSelectorError("tenant routing requires a trusted UUID")
        return tenant_id

    def _audit_failure(
        self,
        tenant_id: UUID,
        *,
        event_type: str,
        outcome_code: str,
    ) -> None:
        if self._security_event_recorder is None:
            return
        try:
            self._security_event_recorder(
                event_type=event_type,
                tenant_id=tenant_id,
                user_id=None,
                correlation_digest=sha256(
                    f"tenant-routing\0{tenant_id}\0{outcome_code}".encode("ascii")
                ).hexdigest(),
                outcome_code=outcome_code,
                occurred_at=datetime.now(timezone.utc),
            )
        except Exception:
            pass


    def _load_profile(self, tenant_id: UUID) -> TenantDatabaseProfile:
        trusted_id = self._require_trusted_tenant_id(tenant_id)
        try:
            profile = self._profile_loader(trusted_id)
        except Exception:
            self._audit_failure(
                trusted_id,
                event_type="tenant.routing_failed",
                outcome_code="profile_lookup_failed",
            )
            raise TenantUnavailableError("tenant database unavailable") from None
        if (
            profile is None
            or profile.tenant_id != trusted_id
            or profile.status != "active"
            or profile.profile_version < 1
            or not profile.secret_ref
            or not profile.expected_tenant_revision
        ):
            self._audit_failure(
                trusted_id,
                event_type="tenant.routing_failed",
                outcome_code="profile_rejected",
            )
            raise TenantUnavailableError("tenant database unavailable")
        return profile

    def _engine_for_profile(self, profile: TenantDatabaseProfile) -> Engine:
        stale_engine: Engine | None = None
        evicted_engines: list[Engine] = []
        try:
            with self._lock:
                cached = self._engines.get(profile.tenant_id)
                if cached is not None and cached.profile_version == profile.profile_version:
                    self._engines.move_to_end(profile.tenant_id)
                    return cached.engine
                if cached is not None:
                    stale_engine = self._engines.pop(profile.tenant_id).engine

                database_url = self._secret_provider.get_database_secret(profile.secret_ref)
                database_url = validate_tenant_database_url(
                    database_url,
                    allow_insecure_loopback=self._settings.allow_insecure_loopback,
                )
                engine = self._engine_factory(
                    database_url,
                    pool_pre_ping=True,
                    pool_size=self._settings.pool_size,
                    max_overflow=self._settings.max_overflow,
                    pool_timeout=self._settings.pool_timeout,
                    connect_args={"connect_timeout": self._settings.connect_timeout},
                )
                self._engines[profile.tenant_id] = _EngineEntry(
                    profile_version=profile.profile_version,
                    engine=engine,
                )
                while len(self._engines) > self._settings.max_cached_engines:
                    _evicted_id, evicted = self._engines.popitem(last=False)
                    evicted_engines.append(evicted.engine)
        except (SecretError, SQLAlchemyError, TypeError, ValueError):
            self._audit_failure(
                profile.tenant_id,
                event_type="tenant.routing_failed",
                outcome_code="connection_rejected",
            )
            if stale_engine is not None:
                stale_engine.dispose()
            raise TenantUnavailableError("tenant database unavailable") from None

        if stale_engine is not None:
            stale_engine.dispose()
        for evicted_engine in evicted_engines:
            evicted_engine.dispose()
        return engine

    def get_engine(self, tenant_id: UUID) -> Engine:
        profile = self._load_profile(tenant_id)
        return self._engine_for_profile(profile)

    def _verify_identity(self, session: Session, profile: TenantDatabaseProfile) -> str:
        identity = session.execute(
            text(
                "SELECT control_tenant_id, workspace_id, schema_contract "
                "FROM tenant_identity WHERE singleton_key = 'identity'"
            )
        ).mappings().one_or_none()
        if (
            identity is None
            or identity["control_tenant_id"] != profile.tenant_id
            or identity["schema_contract"] != self._settings.supported_schema_contract
            or not identity["workspace_id"]
        ):
            raise _TenantGuardFailure

        revision = session.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != profile.expected_tenant_revision:
            raise _TenantGuardFailure
        return str(identity["workspace_id"])

    @contextmanager
    def tenant_session_scope(self, tenant_id: UUID) -> Iterator[Session]:
        profile = self._load_profile(tenant_id)
        engine = self._engine_for_profile(profile)
        session = Session(bind=engine, expire_on_commit=False)
        try:
            with session.begin():
                try:
                    workspace_id = self._verify_identity(session, profile)
                    session.execute(
                        text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
                        {"workspace_id": workspace_id},
                    )
                except (_TenantGuardFailure, DBAPIError, SQLAlchemyError):
                    raise _TenantGuardFailure from None
                yield session
        except _TenantGuardFailure:
            self._audit_failure(
                profile.tenant_id,
                event_type="tenant.identity_mismatch",
                outcome_code="identity_mismatch",
            )
            self.invalidate(profile.tenant_id)
            raise TenantUnavailableError("tenant database unavailable") from None
        except (OperationalError, DisconnectionError):
            self._audit_failure(
                profile.tenant_id,
                event_type="tenant.routing_failed",
                outcome_code="connection_lost",
            )
            self.invalidate(profile.tenant_id)
            raise TenantUnavailableError("tenant database unavailable") from None
        finally:
            session.close()

    def invalidate(self, tenant_id: UUID) -> None:
        trusted_id = self._require_trusted_tenant_id(tenant_id)
        with self._lock:
            entry = self._engines.pop(trusted_id, None)
        if entry is not None:
            entry.engine.dispose()

    def health(self, tenant_id: UUID) -> bool:
        try:
            with self.tenant_session_scope(tenant_id) as session:
                return session.scalar(text("SELECT 1")) == 1
        except (TenantSelectorError, TenantUnavailableError):
            return False

    @property
    def cached_tenant_ids(self) -> tuple[UUID, ...]:
        with self._lock:
            return tuple(self._engines)

    def dispose(self) -> None:
        with self._lock:
            entries = tuple(self._engines.values())
            self._engines.clear()
        for entry in entries:
            entry.engine.dispose()

    def __repr__(self) -> str:
        return f"TenantDatabaseRouter(cached_engines={len(self.cached_tenant_ids)})"
