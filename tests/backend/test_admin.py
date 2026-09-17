from __future__ import annotations

import os
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.admin_cli import (
    AdminOperationError,
    AdminService,
    main,
)
from app.control_database import ControlDatabase, ControlRepository
from app.control_models import AuthSession, ControlBase, SecurityEvent
from app.models import CrmUser, Lead, TenantIdentity, Workspace
from app.security.secrets import InMemorySecretProvider


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "a4c9d2e7f1b6"
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def admin_setup():  # noqa: ANN201
    root_engine = create_engine(TEST_DATABASE_URL)
    control_schema = f"admin_control_{uuid4().hex}"
    tenant_schema = f"admin_tenant_{uuid4().hex}"
    with root_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{control_schema}"'))
        connection.execute(text(f'CREATE SCHEMA "{tenant_schema}"'))

    control_engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"options": f"-csearch_path={control_schema}"},
    )
    ControlBase.metadata.create_all(control_engine)
    control_database = ControlDatabase(engine=control_engine)

    tenant_url = make_url(TEST_DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={tenant_schema}"}
    ).render_as_string(hide_password=False)
    tenant_engine = create_engine(tenant_url)
    with tenant_engine.connect() as connection:
        command.upgrade(_config(connection), TENANT_HEAD)
        connection.commit()
    tenant_engine.dispose()

    secrets = InMemorySecretProvider()
    hashes: list[str] = []

    def fake_hash(password: str) -> str:
        hashes.append(password)
        return f"$argon2id$test${password}"

    service = AdminService(
        control_database,
        secrets,
        password_hasher=fake_hash,
        now=lambda: NOW,
        allow_insecure_loopback=True,
    )
    try:
        yield service, control_database, secrets, tenant_url, hashes
    finally:
        control_database.dispose()
        with root_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{control_schema}" CASCADE'))
            connection.execute(text(f'DROP SCHEMA "{tenant_schema}" CASCADE'))
        root_engine.dispose()


def _register(service: AdminService, tenant_url: str, *, slug: str = "cliente-a"):  # noqa: ANN201
    return service.register_tenant(
        slug=slug,
        display_name="Cliente A",
        secret_ref=f"db-{slug}",
        database_secret=tenant_url,
        expected_revision=TENANT_HEAD,
    )


def _activate(service: AdminService, slug: str = "cliente-a"):  # noqa: ANN201
    return service.activate_default(
        slug=slug,
        admin_email="admin@cliente.test",
        admin_name="Administrador",
        password="senha segura 123",
    )


def test_admin_rejects_insecure_remote_profile_before_engine_creation(monkeypatch) -> None:
    insecure = "postgresql+psycopg://tenant:top-secret@db.example.test/tenant"
    calls: list[str] = []

    def recording_create_engine(url: str, **_kwargs):  # noqa: ANN001, ANN201
        calls.append(url)
        return object()

    monkeypatch.setattr("app.admin_cli.create_engine", recording_create_engine)
    service = AdminService(
        object(),  # type: ignore[arg-type]
        InMemorySecretProvider({"remote": insecure}),
    )

    with pytest.raises(AdminOperationError, match="tenant provisioning failed") as raised:
        service._engine(SimpleNamespace(secret_ref="remote"))

    assert calls == []
    assert "top-secret" not in str(raised.value)
    assert "db.example.test" not in str(raised.value)


def test_register_keeps_tenant_non_active_and_stores_only_secret_reference(admin_setup) -> None:  # noqa: ANN001
    service, control_database, secrets, tenant_url, _hashes = admin_setup

    result = _register(service, tenant_url)

    with control_database.session_scope() as session:
        tenant = ControlRepository(session).get_tenant(result.tenant_id)
        assert tenant is not None
        assert (tenant.status, tenant.secret_ref, tenant.provisioning_checkpoint) == (
            "provisioning", "db-cliente-a", "registered"
        )
        assert tenant_url not in repr(tenant)
    assert secrets.get_database_secret("db-cliente-a") == tenant_url


def test_register_is_idempotent_without_duplicate_tenant(admin_setup) -> None:  # noqa: ANN001
    service, control_database, _secrets, tenant_url, _hashes = admin_setup

    first = _register(service, tenant_url)
    second = _register(service, tenant_url)

    assert second.tenant_id == first.tenant_id
    with control_database.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(ControlBase.metadata.tables["control_tenants"])) == 1


def test_duplicate_slug_with_different_reference_fails_closed(admin_setup) -> None:  # noqa: ANN001
    service, _control_database, _secrets, tenant_url, _hashes = admin_setup
    _register(service, tenant_url)

    with pytest.raises(AdminOperationError, match="tenant registration conflicts"):
        service.register_tenant(
            slug="cliente-a",
            display_name="Cliente A",
            secret_ref="other-ref",
            database_secret=tenant_url,
            expected_revision=TENANT_HEAD,
        )


def test_activate_default_binds_identity_and_first_admin_before_active(admin_setup) -> None:  # noqa: ANN001
    service, control_database, _secrets, tenant_url, hashes = admin_setup
    registered = _register(service, tenant_url)

    activated = _activate(service)

    assert activated.status == "active"
    assert hashes == ["senha segura 123"]
    tenant_engine = create_engine(tenant_url)
    with tenant_engine.connect() as connection:
        identity = connection.execute(
            text("SELECT control_tenant_id, workspace_id FROM tenant_identity")
        ).one()
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
        admin = connection.execute(
            text("SELECT normalized_email, role, auth_enabled, password_hash FROM crm_users")
        ).one()
    tenant_engine.dispose()
    assert tuple(identity) == (registered.tenant_id, "default")
    assert tuple(admin) == (
        "admin@cliente.test", "Administrador", True, "$argon2id$test$senha segura 123"
    )
    with control_database.session_scope() as session:
        tenant = ControlRepository(session).get_tenant(registered.tenant_id)
        assert tenant is not None
        assert (tenant.status, tenant.provisioning_checkpoint, tenant.last_error_code) == (
            "active", "active", None
        )


def test_default_activation_preserves_existing_commercial_rows_in_place(admin_setup) -> None:  # noqa: ANN001
    service, _control_database, _secrets, tenant_url, _hashes = admin_setup
    engine = create_engine(tenant_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO leads "
                "(id, workspace_id, name, company, email, phone, segment, source, stage, payload) "
                "VALUES ('lead-existing', 'default', 'Lead existente', '', '', '', '', '', "
                "'Novo', '{\"marker\": \"original\"}')"
            )
        )
    engine.dispose()
    _register(service, tenant_url)

    activated = _activate(service)

    assert activated.preservation_counts["leads"] == (1, 1)
    engine = create_engine(tenant_url)
    with engine.connect() as connection:
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
        assert connection.execute(text("SELECT id, payload FROM leads")).one()._mapping["payload"] == {"marker": "original"}
    engine.dispose()


def test_schema_mismatch_leaves_tenant_non_active_with_redacted_failure(admin_setup) -> None:  # noqa: ANN001
    service, control_database, _secrets, tenant_url, _hashes = admin_setup
    result = service.register_tenant(
        slug="cliente-a", display_name="Cliente A", secret_ref="db-cliente-a",
        database_secret=tenant_url, expected_revision="wrong-revision",
    )

    with pytest.raises(AdminOperationError, match="tenant provisioning failed"):
        _activate(service)

    with control_database.session_scope() as session:
        tenant = ControlRepository(session).get_tenant(result.tenant_id)
        assert tenant is not None
        assert tenant.status == "provisioning"
        assert tenant.last_error_code == "tenant_verification_failed"
        assert tenant_url not in (tenant.provisioning_checkpoint or "")
        event = session.scalar(select(SecurityEvent))
        assert event is not None
        assert event.outcome_code == "tenant_verification_failed"


def test_resume_after_partial_failure_is_idempotent_and_does_not_duplicate_admin(admin_setup) -> None:  # noqa: ANN001
    service, _control_database, _secrets, tenant_url, _hashes = admin_setup
    registered = service.register_tenant(
        slug="cliente-a", display_name="Cliente A", secret_ref="db-cliente-a",
        database_secret=tenant_url, expected_revision="wrong-revision",
    )
    with pytest.raises(AdminOperationError):
        _activate(service)
    with service.control_database.session_scope() as session:
        tenant = ControlRepository(session).get_tenant(registered.tenant_id, for_update=True)
        assert tenant is not None
        tenant.expected_tenant_revision = TENANT_HEAD

    first = service.resume_provisioning(
        slug="cliente-a", admin_email="admin@cliente.test", admin_name="Administrador",
        password="senha segura 123",
    )
    second = service.resume_provisioning(
        slug="cliente-a", admin_email="admin@cliente.test", admin_name="Administrador",
        password="senha segura 123",
    )

    assert first.tenant_id == second.tenant_id
    engine = create_engine(tenant_url)
    with engine.connect() as connection:
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
        assert connection.scalar(text("SELECT count(*) FROM crm_users")) == 1
        assert connection.scalar(text("SELECT count(*) FROM tenant_identity")) == 1
    engine.dispose()


def test_identity_bound_to_another_tenant_never_activates(admin_setup) -> None:  # noqa: ANN001
    service, control_database, _secrets, tenant_url, _hashes = admin_setup
    registered = _register(service, tenant_url)
    engine = create_engine(tenant_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenant_identity "
                "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
                "VALUES ('identity', :tenant_id, 'default', 'tenant-v1')"
            ),
            {"tenant_id": uuid4()},
        )
    engine.dispose()

    with pytest.raises(AdminOperationError, match="tenant provisioning failed"):
        _activate(service)

    with control_database.session_scope() as session:
        tenant = ControlRepository(session).get_tenant(registered.tenant_id)
        assert tenant is not None
        assert tenant.status != "active"


def test_missing_workspace_never_creates_or_activates_tenant(admin_setup) -> None:  # noqa: ANN001
    service, control_database, _secrets, tenant_url, _hashes = admin_setup
    registered = _register(service, tenant_url)

    with pytest.raises(AdminOperationError, match="tenant provisioning failed"):
        service.resume_provisioning(
            slug="cliente-a", admin_email="admin@cliente.test", admin_name="Administrador",
            password="senha segura 123", workspace_id="missing",
        )

    with control_database.session_scope() as session:
        tenant = ControlRepository(session).get_tenant(registered.tenant_id)
        assert tenant is not None
        assert tenant.status == "provisioning"


def test_set_password_hashes_in_tenant_and_revokes_previous_sessions(admin_setup) -> None:  # noqa: ANN001
    service, control_database, _secrets, tenant_url, hashes = admin_setup
    registered = _register(service, tenant_url)
    activated = _activate(service)
    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        repository.create_session(
            token_digest="a" * 64, tenant_id=registered.tenant_id,
            user_id=activated.admin_user_id, auth_version=1,
            created_at=NOW, last_seen_at=NOW, idle_expires_at=NOW + timedelta(minutes=30),
            absolute_expires_at=NOW + timedelta(hours=12), correlation_digest="b" * 64,
        )

    changed = service.set_user_password(
        slug="cliente-a", user_id=activated.admin_user_id, password="nova senha segura 456"
    )

    assert changed.auth_version == 2
    assert hashes[-1] == "nova senha segura 456"
    with control_database.session_scope() as session:
        stored = session.get(AuthSession, "a" * 64)
        assert stored is not None
        assert (stored.revoked_at, stored.revocation_reason) == (NOW, "auth_changed")


def test_set_password_unknown_user_fails_without_cross_database_creation(admin_setup) -> None:  # noqa: ANN001
    service, _control_database, _secrets, tenant_url, _hashes = admin_setup
    _register(service, tenant_url)
    _activate(service)

    with pytest.raises(AdminOperationError, match="tenant user not found"):
        service.set_user_password(slug="cliente-a", user_id="missing", password="nova senha segura 456")


def test_revoke_command_targets_only_selected_tenant_user(admin_setup) -> None:  # noqa: ANN001
    service, control_database, _secrets, tenant_url, _hashes = admin_setup
    registered = _register(service, tenant_url)
    activated = _activate(service)
    with control_database.session_scope() as session:
        ControlRepository(session).create_session(
            token_digest="a" * 64, tenant_id=registered.tenant_id,
            user_id=activated.admin_user_id, auth_version=1,
            created_at=NOW, last_seen_at=NOW, idle_expires_at=NOW + timedelta(minutes=30),
            absolute_expires_at=NOW + timedelta(hours=12), correlation_digest="b" * 64,
        )

    assert service.revoke_user_sessions(slug="cliente-a", user_id=activated.admin_user_id) == 1


class RecordingAdminService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def register_tenant(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(("register", kwargs))
        return type("Result", (), {"tenant_id": UUID("00000000-0000-0000-0000-000000000001"), "status": "provisioning"})()

    def activate_default(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(("activate", kwargs))
        return type("Result", (), {"tenant_id": UUID("00000000-0000-0000-0000-000000000001"), "status": "active"})()

    def resume_provisioning(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(("resume", kwargs))
        return self.activate_default(**kwargs)

    def set_user_password(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(("password", kwargs))
        return type(
            "Result",
            (),
            {
                "tenant_id": UUID("00000000-0000-0000-0000-000000000001"),
                "auth_version": 2,
            },
        )()

    def revoke_user_sessions(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(("revoke", kwargs))
        return 2


@pytest.mark.parametrize("command_name", ["activate-default", "resume-provisioning", "set-user-password"])
def test_cli_reads_password_with_hidden_input(command_name: str) -> None:
    service = RecordingAdminService()
    prompts: list[str] = []
    output: list[str] = []
    argv = [command_name, "cliente-a"]
    if command_name != "set-user-password":
        argv.extend(["--admin-email", "admin@cliente.test", "--admin-name", "Admin"])
    else:
        argv.extend(["--user-id", "user-1"])

    exit_code = main(
        argv,
        service=service,
        secret_reader=lambda prompt: prompts.append(prompt) or "segredo oculto",
        output=output.append,
    )

    assert exit_code == 0
    assert prompts == ["Password: "]
    assert all("segredo oculto" not in line for line in output)


def test_cli_reads_database_secret_with_hidden_input_and_never_prints_it() -> None:
    service = RecordingAdminService()
    output: list[str] = []

    exit_code = main(
        ["register-tenant", "cliente-a", "--display-name", "Cliente A", "--secret-ref", "db-a"],
        service=service,
        secret_reader=lambda _prompt: "postgresql://user:plain-secret@db/tenant",
        output=output.append,
    )

    assert exit_code == 0
    assert all("plain-secret" not in line for line in output)
    assert service.calls[0][1]["database_secret"] == "postgresql://user:plain-secret@db/tenant"


def test_web_app_has_no_public_tenant_or_admin_provisioning_route() -> None:
    from app.main import create_app

    paths = {route.path for route in create_app().routes}

    assert not any("provision" in path or "tenant" in path and path.startswith("/api/admin") for path in paths)

