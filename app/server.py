"""Central FastAPI runtime for isolated tenant databases."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from sqlalchemy import text

from app.auth import AuthSettings
from app.control_database import ControlDatabase
from app.main import STATIC_DIR, create_app as create_http_app
from app.security.database_urls import insecure_tenant_loopback_enabled
from app.security.secrets import DpapiFileSecretProvider, SecretProvider
from app.services.auth import AuthService, SecurityAuditService
from app.tenant_database import (
    ControlTenantProfileLoader,
    TenantDatabaseRouter,
    TenantDatabaseRouterSettings,
)


CONTROL_SCHEMA_REVISION = "c01a5d8e4f20"


class RuntimeBootstrapError(RuntimeError):
    """Generic startup failure that deliberately carries no connection detail."""


@dataclass(repr=False)
class CentralRuntime:
    control_database: ControlDatabase
    tenant_router: TenantDatabaseRouter
    auth_service: AuthService

    def control_is_ready(self) -> bool:
        try:
            return _control_revision(self.control_database) == CONTROL_SCHEMA_REVISION
        except Exception:
            return False

    def dispose(self) -> None:
        self.tenant_router.dispose()
        self.control_database.dispose()

    def __repr__(self) -> str:
        return "CentralRuntime(control=configured, tenant_router=lazy)"


def _control_revision(control_database: ControlDatabase) -> str | None:
    with control_database.session_scope() as session:
        value = session.scalar(text("SELECT version_num FROM alembic_control_version"))
    return str(value) if value is not None else None


def _default_secret_provider() -> SecretProvider:
    root = os.getenv("SMART_CRM_TENANT_SECRET_STORE")
    if not root:
        raise RuntimeBootstrapError("central runtime unavailable")
    return DpapiFileSecretProvider(Path(root))


def bootstrap_runtime(
    *,
    control_database: ControlDatabase | None = None,
    control_database_factory: Callable[[], ControlDatabase] = ControlDatabase,
    secret_provider: SecretProvider | None = None,
) -> CentralRuntime:
    """Validate the control lineage and compose lazy tenant routing."""

    active_control = control_database
    try:
        active_control = active_control or control_database_factory()
        if _control_revision(active_control) != CONTROL_SCHEMA_REVISION:
            raise RuntimeBootstrapError("central runtime unavailable")
        provider = secret_provider or _default_secret_provider()
        security_audit = SecurityAuditService(active_control)
        router = TenantDatabaseRouter(
            ControlTenantProfileLoader(active_control),
            provider,
            security_event_recorder=security_audit.record,
            settings=TenantDatabaseRouterSettings(
                allow_insecure_loopback=insecure_tenant_loopback_enabled(),
            ),
        )
        return CentralRuntime(
            control_database=active_control,
            tenant_router=router,
            auth_service=AuthService(
                active_control,
                router,
                security_audit=security_audit,
            ),
        )
    except Exception:
        if active_control is not None:
            try:
                active_control.dispose()
            except Exception:
                pass
        raise RuntimeBootstrapError("central runtime unavailable") from None


def create_app(
    settings=None,  # noqa: ANN001 - Uvicorn factory compatibility
    *,
    runtime: CentralRuntime | None = None,
    static_dir: Path = STATIC_DIR,
) -> FastAPI:
    """Build the production app only after the control plane is compatible."""

    del settings
    active_runtime = runtime or bootstrap_runtime()
    application = create_http_app(
        static_dir=static_dir,
        auth_service=active_runtime.auth_service,
        tenant_router=active_runtime.tenant_router,
        auth_settings=AuthSettings(
            expected_origin=os.getenv(
                "SMART_CRM_EXPECTED_ORIGIN",
                "https://sc2030.brbots.com",
            )
        ),
        health_check=active_runtime.control_is_ready,
    )
    application.state.central_runtime = active_runtime
    application.add_event_handler("shutdown", active_runtime.dispose)
    return application
