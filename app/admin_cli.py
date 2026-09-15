"""Local-only administration for isolated tenant databases."""

from __future__ import annotations

import argparse
import getpass
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.control_database import ControlDatabase, ControlRepository
from app.models import CrmUser, TenantIdentity, Workspace
from app.schemas import normalize_tenant_identifier
from app.security.passwords import hash_password
from app.security.secrets import DpapiFileSecretProvider, SecretError, SecretProvider


TENANT_HEAD = "a4c9d2e7f1b6"
SCHEMA_CONTRACT = "tenant-v1"
_COMMERCIAL_TABLES = (
    "teams",
    "leads",
    "companies",
    "contacts",
    "deals",
    "lead_assistants",
    "deal_assistants",
    "deal_stage_history",
    "quotes",
    "notifications",
    "custom_field_definitions",
    "custom_field_values",
    "record_visible_custom_fields",
    "external_source_fields",
    "module_field_settings",
    "saved_filters",
    "user_module_preferences",
    "user_dashboard_preferences",
)


class AdminOperationError(RuntimeError):
    """Stable, redacted administrative failure."""


@dataclass(frozen=True)
class TenantAdminResult:
    tenant_id: UUID
    status: str
    admin_user_id: str = ""
    preservation_counts: dict[str, tuple[int, int]] | None = None


@dataclass(frozen=True)
class PasswordChangeResult:
    tenant_id: UUID
    user_id: str
    auth_version: int


class AdminService:
    """Coordinate idempotent control/tenant provisioning without cross-DB atomicity."""

    def __init__(
        self,
        control_database: ControlDatabase,
        secret_provider: SecretProvider,
        *,
        password_hasher: Callable[[str], str] = hash_password,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.control_database = control_database
        self._secret_provider = secret_provider
        self._password_hasher = password_hasher
        self._now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _slug(value: str) -> str:
        try:
            return normalize_tenant_identifier(value)
        except ValueError as error:
            raise AdminOperationError("invalid tenant identifier") from error

    def register_tenant(
        self,
        *,
        slug: str,
        display_name: str,
        secret_ref: str,
        database_secret: str,
        expected_revision: str = TENANT_HEAD,
    ) -> TenantAdminResult:
        normalized_slug = self._slug(slug)
        if not display_name.strip() or not expected_revision:
            raise AdminOperationError("tenant registration is incomplete")
        with self.control_database.session_scope() as session:
            repository = ControlRepository(session)
            existing = repository.find_tenant_by_slug(normalized_slug)
            if existing is not None:
                if (
                    existing.display_name != display_name.strip()
                    or existing.secret_ref != secret_ref
                    or existing.expected_tenant_revision != expected_revision
                ):
                    raise AdminOperationError("tenant registration conflicts with existing tenant")
                return TenantAdminResult(existing.id, existing.status)

        try:
            self._secret_provider.put_database_secret(secret_ref, database_secret)
            with self.control_database.session_scope() as session:
                repository = ControlRepository(session)
                tenant = repository.create_tenant(
                    tenant_id=uuid4(),
                    slug=normalized_slug,
                    display_name=display_name.strip(),
                    secret_ref=secret_ref,
                    expected_tenant_revision=expected_revision,
                )
                repository.transition_tenant(
                    tenant.id, "provisioning", checkpoint="registered", error_code=None
                )
                tenant_id = tenant.id
        except (SecretError, SQLAlchemyError, ValueError, TypeError) as error:
            raise AdminOperationError("tenant registration failed") from error
        return TenantAdminResult(tenant_id, "provisioning")

    def _tenant(self, slug: str):  # noqa: ANN201
        normalized_slug = self._slug(slug)
        with self.control_database.session_scope() as session:
            tenant = ControlRepository(session).find_tenant_by_slug(normalized_slug)
            if tenant is None:
                raise AdminOperationError("tenant not found")
            session.expunge(tenant)
            return tenant

    def _engine(self, tenant):  # noqa: ANN001, ANN201
        try:
            database_url = self._secret_provider.get_database_secret(tenant.secret_ref)
            return create_engine(
                database_url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 3},
            )
        except (SecretError, SQLAlchemyError, TypeError, ValueError) as error:
            raise AdminOperationError("tenant provisioning failed") from error

    @staticmethod
    def _set_workspace(session: Session, workspace_id: str) -> None:
        session.execute(
            text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
            {"workspace_id": workspace_id},
        )

    @staticmethod
    def _commercial_counts(session: Session, workspace_id: str) -> dict[str, int]:
        return {
            table: int(
                session.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE workspace_id = :workspace_id"),
                    {"workspace_id": workspace_id},
                )
                or 0
            )
            for table in _COMMERCIAL_TABLES
        }

    @staticmethod
    def _assert_revision(session: Session, expected_revision: str) -> None:
        revision = session.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != expected_revision:
            raise AdminOperationError("tenant provisioning failed")

    def _record_failure(self, tenant_id: UUID, checkpoint: str) -> None:
        correlation = sha256(f"admin:{tenant_id}:{checkpoint}".encode()).hexdigest()
        try:
            with self.control_database.session_scope() as session:
                repository = ControlRepository(session)
                tenant = repository.get_tenant(tenant_id, for_update=True)
                if tenant is None or tenant.status == "active":
                    return
                if tenant.status == "failed":
                    repository.transition_tenant(tenant_id, "provisioning")
                repository.transition_tenant(
                    tenant_id,
                    "provisioning",
                    checkpoint=checkpoint,
                    error_code="tenant_verification_failed",
                )
                repository.append_security_event(
                    event_type="tenant.provisioning_failed",
                    tenant_id=tenant_id,
                    user_id=None,
                    correlation_digest=correlation,
                    outcome_code="tenant_verification_failed",
                    occurred_at=self._now(),
                )
        except Exception:
            return

    def activate_default(
        self,
        *,
        slug: str,
        admin_email: str,
        admin_name: str,
        password: str,
    ) -> TenantAdminResult:
        return self.resume_provisioning(
            slug=slug,
            admin_email=admin_email,
            admin_name=admin_name,
            password=password,
            workspace_id="default",
        )

    def resume_provisioning(
        self,
        *,
        slug: str,
        admin_email: str,
        admin_name: str,
        password: str,
        workspace_id: str = "default",
    ) -> TenantAdminResult:
        tenant = self._tenant(slug)
        if tenant.status not in {"provisioning", "failed", "active"}:
            raise AdminOperationError("tenant is not provisionable")
        normalized_email = admin_email.strip().lower()
        if not normalized_email or not admin_name.strip():
            raise AdminOperationError("administrator identity is incomplete")

        engine = self._engine(tenant)
        checkpoint = "database_validation"
        try:
            with Session(engine, expire_on_commit=False) as tenant_session:
                with tenant_session.begin():
                    self._assert_revision(tenant_session, tenant.expected_tenant_revision)
                    self._set_workspace(tenant_session, workspace_id)
                    workspace = tenant_session.scalar(
                        select(Workspace).where(Workspace.id == workspace_id)
                    )
                    if workspace is None:
                        raise AdminOperationError("tenant provisioning failed")

                    identity = tenant_session.get(TenantIdentity, "identity")
                    if identity is None:
                        identity = TenantIdentity(
                            singleton_key="identity",
                            control_tenant_id=tenant.id,
                            workspace_id=workspace_id,
                            schema_contract=SCHEMA_CONTRACT,
                        )
                        tenant_session.add(identity)
                        tenant_session.flush()
                    if (
                        identity.control_tenant_id != tenant.id
                        or identity.workspace_id != workspace_id
                        or identity.schema_contract != SCHEMA_CONTRACT
                    ):
                        raise AdminOperationError("tenant provisioning failed")

                    before = self._commercial_counts(tenant_session, workspace_id)
                    admin = tenant_session.scalar(
                        select(CrmUser).where(
                            CrmUser.workspace_id == workspace_id,
                            CrmUser.normalized_email == normalized_email,
                        )
                    )
                    if admin is None and tenant.status == "active":
                        raise AdminOperationError("tenant provisioning failed")
                    if admin is None:
                        admin = CrmUser(
                            id=f"admin-{uuid4().hex}",
                            workspace_id=workspace_id,
                            name=admin_name.strip(),
                            email=normalized_email,
                            normalized_email=normalized_email,
                            password_hash=self._password_hasher(password),
                            auth_enabled=True,
                            auth_version=1,
                            job_title="",
                            role="Administrador",
                            status="Ativo",
                            payload={},
                        )
                        tenant_session.add(admin)
                        tenant_session.flush()
                    elif tenant.status != "active":
                        admin.name = admin_name.strip()
                        admin.email = normalized_email
                        admin.password_hash = self._password_hasher(password)
                        admin.auth_enabled = True
                        admin.auth_version += 1
                        admin.role = "Administrador"
                        admin.status = "Ativo"
                        tenant_session.flush()
                    if (
                        admin.password_hash is None
                        or not admin.password_hash.startswith("$argon2id$")
                        or not admin.auth_enabled
                        or admin.role != "Administrador"
                        or admin.status != "Ativo"
                    ):
                        raise AdminOperationError("tenant provisioning failed")
                    after = self._commercial_counts(tenant_session, workspace_id)
                    if before != after:
                        raise AdminOperationError("tenant provisioning failed")
                    admin_id = admin.id
            checkpoint = "tenant_verified"
        except Exception as error:
            self._record_failure(tenant.id, checkpoint)
            if isinstance(error, AdminOperationError):
                raise AdminOperationError("tenant provisioning failed") from None
            raise AdminOperationError("tenant provisioning failed") from None
        finally:
            engine.dispose()

        with self.control_database.session_scope() as session:
            repository = ControlRepository(session)
            current = repository.get_tenant(tenant.id, for_update=True)
            if current is None:
                raise AdminOperationError("tenant not found")
            if current.status == "failed":
                repository.transition_tenant(current.id, "provisioning")
            if current.status != "active":
                repository.transition_tenant(
                    current.id,
                    "active",
                    activated_at=self._now(),
                    checkpoint="active",
                    error_code=None,
                )
            elif current.provisioning_checkpoint != "active" or current.last_error_code:
                current.provisioning_checkpoint = "active"
                current.last_error_code = None

        return TenantAdminResult(
            tenant.id,
            "active",
            admin_user_id=admin_id,
            preservation_counts={key: (before[key], after[key]) for key in before},
        )

    def set_user_password(
        self,
        *,
        slug: str,
        user_id: str,
        password: str,
    ) -> PasswordChangeResult:
        tenant = self._tenant(slug)
        if tenant.status != "active":
            raise AdminOperationError("tenant is not active")
        engine = self._engine(tenant)
        try:
            with Session(engine, expire_on_commit=False) as session:
                with session.begin():
                    self._assert_revision(session, tenant.expected_tenant_revision)
                    identity = session.get(TenantIdentity, "identity")
                    if identity is None or identity.control_tenant_id != tenant.id:
                        raise AdminOperationError("tenant unavailable")
                    self._set_workspace(session, identity.workspace_id)
                    user = session.scalar(
                        select(CrmUser).where(
                            CrmUser.workspace_id == identity.workspace_id,
                            CrmUser.id == user_id,
                        )
                    )
                    if user is None:
                        raise AdminOperationError("tenant user not found")
                    user.password_hash = self._password_hasher(password)
                    user.auth_enabled = True
                    user.auth_version += 1
                    version = user.auth_version
        except AdminOperationError:
            raise
        except Exception:
            raise AdminOperationError("password update failed") from None
        finally:
            engine.dispose()

        with self.control_database.session_scope() as session:
            ControlRepository(session).revoke_user_sessions(
                tenant.id,
                user_id,
                reason="auth_changed",
                revoked_at=self._now(),
            )
        return PasswordChangeResult(tenant.id, user_id, version)

    def revoke_user_sessions(self, *, slug: str, user_id: str) -> int:
        tenant = self._tenant(slug)
        with self.control_database.session_scope() as session:
            return ControlRepository(session).revoke_user_sessions(
                tenant.id,
                user_id,
                reason="admin_revoked",
                revoked_at=self._now(),
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.admin_cli")
    subcommands = parser.add_subparsers(dest="command", required=True)
    register = subcommands.add_parser("register-tenant")
    register.add_argument("slug")
    register.add_argument("--display-name", required=True)
    register.add_argument("--secret-ref", required=True)
    register.add_argument("--expected-revision", default=TENANT_HEAD)
    for name in ("activate-default", "resume-provisioning"):
        command_parser = subcommands.add_parser(name)
        command_parser.add_argument("slug")
        command_parser.add_argument("--admin-email", required=True)
        command_parser.add_argument("--admin-name", required=True)
    password = subcommands.add_parser("set-user-password")
    password.add_argument("slug")
    password.add_argument("--user-id", required=True)
    revoke = subcommands.add_parser("revoke-user-sessions")
    revoke.add_argument("slug")
    revoke.add_argument("--user-id", required=True)
    return parser


def _default_service() -> AdminService:
    secret_store = os.getenv("SMART_CRM_SECRET_STORE")
    if not secret_store:
        raise AdminOperationError("SMART_CRM_SECRET_STORE is required")
    return AdminService(ControlDatabase(), DpapiFileSecretProvider(Path(secret_store)))


def main(
    argv: Sequence[str] | None = None,
    *,
    service: AdminService | object | None = None,
    secret_reader: Callable[[str], str] = getpass.getpass,
    output: Callable[[str], None] = print,
) -> int:
    args = _parser().parse_args(argv)
    admin = service or _default_service()
    try:
        if args.command == "register-tenant":
            result = admin.register_tenant(
                slug=args.slug,
                display_name=args.display_name,
                secret_ref=args.secret_ref,
                database_secret=secret_reader("Database secret: "),
                expected_revision=args.expected_revision,
            )
        elif args.command in {"activate-default", "resume-provisioning"}:
            operation = (
                admin.activate_default
                if args.command == "activate-default"
                else admin.resume_provisioning
            )
            result = operation(
                slug=args.slug,
                admin_email=args.admin_email,
                admin_name=args.admin_name,
                password=secret_reader("Password: "),
            )
        elif args.command == "set-user-password":
            result = admin.set_user_password(
                slug=args.slug,
                user_id=args.user_id,
                password=secret_reader("Password: "),
            )
        else:
            count = admin.revoke_user_sessions(slug=args.slug, user_id=args.user_id)
            output(f"revoked_sessions={count}")
            return 0
    except AdminOperationError as error:
        output(str(error))
        return 1
    output(f"tenant_id={result.tenant_id} status={getattr(result, 'status', 'updated')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

