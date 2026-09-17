"""Redacted preflight and explicit migrations for tenant database fleets."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Callable, Sequence
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.control_database import ControlDatabase
from app.control_models import ControlTenant
from app.security.database_urls import (
    insecure_tenant_loopback_enabled,
    validate_tenant_database_url,
)
from app.security.secrets import SecretError, SecretProvider


_REVISION_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


class FleetOperationError(RuntimeError):
    """Stable error for unsafe fleet requests."""


@dataclass(frozen=True)
class FleetPreflightResult:
    tenant_id: UUID
    slug: str
    status: str
    connected: bool
    identity_matches: bool | None
    revision: str | None
    ready: bool
    code: str


@dataclass(frozen=True)
class FleetMigrationResult:
    tenant_id: UUID
    slug: str
    succeeded: bool
    code: str


MigrationRunner = Callable[[ControlTenant], None]


class FleetService:
    def __init__(
        self,
        control_database: ControlDatabase,
        secret_provider: SecretProvider,
        *,
        migrations_dir: Path | None = None,
        allow_insecure_loopback: bool | None = None,
    ) -> None:
        self._control_database = control_database
        self._secret_provider = secret_provider
        self._migrations_dir = migrations_dir or Path(__file__).resolve().parents[1] / "migrations"
        self._allow_insecure_loopback = (
            insecure_tenant_loopback_enabled()
            if allow_insecure_loopback is None
            else allow_insecure_loopback
        )

    def _select(self, selectors: Sequence[str] | None) -> list[ControlTenant]:
        with self._control_database.session_scope() as session:
            tenants = list(session.scalars(select(ControlTenant).order_by(ControlTenant.slug)))
            by_slug = {tenant.slug: tenant for tenant in tenants}
            if selectors is None:
                chosen = tenants
            else:
                chosen = []
                seen: set[str] = set()
                for selector in selectors:
                    if selector in seen:
                        continue
                    tenant = by_slug.get(selector)
                    if tenant is None:
                        raise FleetOperationError("selected tenant not found")
                    chosen.append(tenant)
                    seen.add(selector)
            for tenant in chosen:
                session.expunge(tenant)
            return chosen

    def _engine(self, tenant: ControlTenant):  # noqa: ANN201
        database_url = self._secret_provider.get_database_secret(tenant.secret_ref)
        database_url = validate_tenant_database_url(
            database_url,
            allow_insecure_loopback=self._allow_insecure_loopback,
        )
        return create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )

    def _probe(self, tenant: ControlTenant) -> FleetPreflightResult:
        engine = None
        try:
            engine = self._engine(tenant)
            with engine.connect() as connection:
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                has_identity = connection.scalar(text("SELECT to_regclass('tenant_identity')")) is not None
                identity = None
                if has_identity:
                    identity = connection.execute(
                        text(
                            "SELECT control_tenant_id, schema_contract "
                            "FROM tenant_identity WHERE singleton_key = 'identity'"
                        )
                    ).mappings().one_or_none()
        except (SecretError, SQLAlchemyError, TypeError, ValueError):
            return FleetPreflightResult(
                tenant.id, tenant.slug, tenant.status, False, None, None, False, "unavailable"
            )
        finally:
            if engine is not None:
                engine.dispose()

        identity_matches = (
            identity is not None
            and identity["control_tenant_id"] == tenant.id
            and identity["schema_contract"] == "tenant-v1"
        )
        revision_matches = revision == tenant.expected_tenant_revision
        ready = tenant.status == "active" and identity_matches and revision_matches
        if ready:
            code = "ready"
        elif identity is not None and not identity_matches:
            code = "identity_mismatch"
        elif not revision_matches:
            code = "schema_outdated"
        elif identity is None:
            code = "identity_unbound"
        else:
            code = "tenant_inactive"
        return FleetPreflightResult(
            tenant.id,
            tenant.slug,
            tenant.status,
            True,
            identity_matches if identity is not None else None,
            str(revision) if revision is not None else None,
            ready,
            code,
        )

    def preflight(self, selectors: Sequence[str] | None = None) -> list[FleetPreflightResult]:
        return [self._probe(tenant) for tenant in self._select(selectors)]

    def _run_migration(self, tenant: ControlTenant) -> None:
        engine = self._engine(tenant)
        try:
            with engine.connect() as connection:
                config = Config()
                config.set_main_option("script_location", str(self._migrations_dir))
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                connection.commit()
        finally:
            engine.dispose()

    def migrate(
        self,
        selectors: Sequence[str],
        *,
        backup_acknowledged: bool,
        confirmed: bool,
        migration_runner: MigrationRunner | None = None,
        verify_after: bool = True,
    ) -> list[FleetMigrationResult]:
        if not selectors:
            raise FleetOperationError("explicit tenant selection is required")
        if not backup_acknowledged:
            raise FleetOperationError("verified backup acknowledgement is required")
        if not confirmed:
            raise FleetOperationError("operator confirmation is required")

        tenants = self._select(selectors)
        runner = migration_runner or self._run_migration
        results: list[FleetMigrationResult] = []
        for tenant in tenants:
            before = self._probe(tenant)
            if not before.connected:
                results.append(FleetMigrationResult(tenant.id, tenant.slug, False, "unavailable"))
                continue
            if tenant.status == "active" and before.identity_matches is not True:
                results.append(
                    FleetMigrationResult(tenant.id, tenant.slug, False, "identity_mismatch")
                )
                continue
            try:
                runner(tenant)
            except Exception:
                results.append(
                    FleetMigrationResult(tenant.id, tenant.slug, False, "migration_failed")
                )
                continue
            if not verify_after:
                results.append(FleetMigrationResult(tenant.id, tenant.slug, True, "migrated"))
                continue
            after = self._probe(tenant)
            revision_matches = after.revision == tenant.expected_tenant_revision
            identity_valid = after.identity_matches is True or (
                tenant.status == "provisioning" and after.identity_matches is None
            )
            if not after.connected or not revision_matches or not identity_valid:
                results.append(
                    FleetMigrationResult(tenant.id, tenant.slug, False, "verification_failed")
                )
            elif tenant.status == "provisioning":
                results.append(
                    FleetMigrationResult(
                        tenant.id, tenant.slug, True, "migrated_pending_activation"
                    )
                )
            else:
                results.append(FleetMigrationResult(tenant.id, tenant.slug, True, "migrated"))
        return results


def format_preflight(results: Sequence[FleetPreflightResult]) -> str:
    lines = []
    for result in results:
        revision = (
            result.revision
            if result.revision and _REVISION_PATTERN.fullmatch(result.revision)
            else "invalid"
        )
        identity = "unbound" if result.identity_matches is None else (
            "yes" if result.identity_matches else "no"
        )
        lines.append(
            f"{result.slug} status={result.status} "
            f"connected={'yes' if result.connected else 'no'} identity={identity} "
            f"revision={revision} ready={'yes' if result.ready else 'no'} "
            f"code={result.code}"
        )
    return "\n".join(lines)

