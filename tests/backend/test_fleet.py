from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.control_database import ControlDatabase, ControlRepository
from app.control_models import ControlBase
from app.fleet import FleetOperationError, FleetService, format_preflight
from app.security.database_urls import DatabaseTransportSecurityError
from app.security.secrets import InMemorySecretProvider


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "c7f3a9d8e2b1"
OLD_REVISION = "9f7a2c31d5e8"


def _config(connection) -> Config:  # noqa: ANN001
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def fleet_setup():  # noqa: ANN201
    root_engine = create_engine(TEST_DATABASE_URL)
    suffix = uuid4().hex
    schemas = {
        "control": f"fleet_control_{suffix}",
        "ready": f"fleet_ready_{suffix}",
        "mismatch": f"fleet_mismatch_{suffix}",
        "old": f"fleet_old_{suffix}",
    }
    with root_engine.begin() as connection:
        for schema in schemas.values():
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    control_engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"options": f"-csearch_path={schemas['control']}"},
    )
    ControlBase.metadata.create_all(control_engine)
    control_database = ControlDatabase(engine=control_engine)

    tenant_ids = {name: uuid4() for name in ("ready", "mismatch", "old", "outage")}
    tenant_urls = {
        name: make_url(TEST_DATABASE_URL).update_query_dict(
            {"options": f"-csearch_path={schemas[name]}"}
        ).render_as_string(hide_password=False)
        for name in ("ready", "mismatch", "old")
    }
    tenant_urls["outage"] = make_url(TEST_DATABASE_URL).set(port=1, database="missing").render_as_string(hide_password=False)

    for name in ("ready", "mismatch"):
        engine = create_engine(tenant_urls[name])
        with engine.connect() as connection:
            command.upgrade(_config(connection), TENANT_HEAD)
            connection.execute(
                text(
                    "INSERT INTO tenant_identity "
                    "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
                    "VALUES ('identity', :tenant_id, 'default', 'tenant-v1')"
                ),
                {"tenant_id": tenant_ids[name] if name == "ready" else uuid4()},
            )
            connection.commit()
        engine.dispose()
    old_engine = create_engine(tenant_urls["old"])
    with old_engine.connect() as connection:
        command.upgrade(_config(connection), OLD_REVISION)
        connection.commit()
    old_engine.dispose()

    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        for name, status in (
            ("ready", "active"),
            ("mismatch", "active"),
            ("old", "provisioning"),
            ("outage", "active"),
        ):
            tenant = repository.create_tenant(
                tenant_id=tenant_ids[name],
                slug=f"cliente-{name}",
                display_name=f"Cliente {name}",
                secret_ref=f"db-{name}",
                expected_tenant_revision=TENANT_HEAD,
            )
            if status == "active":
                repository.transition_tenant(tenant.id, "active")

    secrets = InMemorySecretProvider(
        {f"db-{name}": url for name, url in tenant_urls.items()}
    )
    service = FleetService(control_database, secrets, allow_insecure_loopback=True)
    try:
        yield service, control_database, secrets, tenant_ids, tenant_urls
    finally:
        control_database.dispose()
        with root_engine.begin() as connection:
            for schema in schemas.values():
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root_engine.dispose()


@pytest.mark.parametrize("setting", [None, "", "0", "true", " 1", "1"])
def test_fleet_default_config_allows_loopback_only_for_literal_one(
    monkeypatch, setting: str | None
) -> None:
    local = "postgresql+psycopg://tenant:local@127.0.0.1:5432/tenant"
    calls: list[str] = []

    def recording_create_engine(url: str, **_kwargs):  # noqa: ANN001, ANN201
        calls.append(url)
        return object()

    if setting is None:
        monkeypatch.delenv("SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK", raising=False)
    else:
        monkeypatch.setenv("SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK", setting)
    monkeypatch.setattr("app.fleet.create_engine", recording_create_engine)
    service = FleetService(
        object(),  # type: ignore[arg-type]
        InMemorySecretProvider({"local": local}),
    )
    tenant = SimpleNamespace(secret_ref="local")

    if setting == "1":
        assert service._engine(tenant) is not None
        assert calls == [local]
    else:
        with pytest.raises(DatabaseTransportSecurityError):
            service._engine(tenant)
        assert calls == []


def test_fleet_rejects_insecure_remote_profile_before_engine_creation(monkeypatch) -> None:
    monkeypatch.setenv("SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK", "1")
    insecure = "postgresql+psycopg://tenant:top-secret@db.example.test/tenant"
    calls: list[str] = []

    def recording_create_engine(url: str, **_kwargs):  # noqa: ANN001, ANN201
        calls.append(url)
        return object()

    monkeypatch.setattr("app.fleet.create_engine", recording_create_engine)
    service = FleetService(
        object(),  # type: ignore[arg-type]
        InMemorySecretProvider({"remote": insecure}),
    )
    tenant = SimpleNamespace(
        id=uuid4(), slug="cliente-a", status="active", secret_ref="remote",
        expected_tenant_revision=TENANT_HEAD,
    )

    result = service._probe(tenant)  # type: ignore[arg-type]

    assert result.connected is False
    assert result.code == "unavailable"
    assert calls == []
    assert "top-secret" not in repr(result)
    assert "db.example.test" not in repr(result)


def test_preflight_reports_ready_identity_and_revision(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, tenant_ids, _urls = fleet_setup

    result = service.preflight(["cliente-ready"])[0]

    assert (result.tenant_id, result.connected, result.identity_matches) == (
        tenant_ids["ready"], True, True
    )
    assert (result.revision, result.ready, result.code) == (TENANT_HEAD, True, "ready")


def test_preflight_detects_identity_mismatch_without_business_query(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup

    result = service.preflight(["cliente-mismatch"])[0]

    assert (result.connected, result.identity_matches, result.ready, result.code) == (
        True, False, False, "identity_mismatch"
    )


def test_preflight_reports_old_provisioning_schema_independently(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup

    result = service.preflight(["cliente-old"])[0]

    assert (result.status, result.revision, result.ready, result.code) == (
        "provisioning", OLD_REVISION, False, "schema_outdated"
    )


def test_one_outage_does_not_hide_or_fail_other_tenants(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup

    results = {item.slug: item for item in service.preflight()}

    assert results["cliente-ready"].ready is True
    assert (results["cliente-outage"].connected, results["cliente-outage"].code) == (
        False, "unavailable"
    )
    assert len(results) == 4


def test_preflight_selection_never_opens_unselected_tenant(fleet_setup, monkeypatch) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup
    probed: list[str] = []
    original = service._probe
    monkeypatch.setattr(service, "_probe", lambda tenant: probed.append(tenant.slug) or original(tenant))

    results = service.preflight(["cliente-ready"])

    assert [item.slug for item in results] == ["cliente-ready"]
    assert probed == ["cliente-ready"]


def test_unknown_preflight_selection_fails_without_fallback(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup

    with pytest.raises(FleetOperationError, match="selected tenant not found"):
        service.preflight(["cliente-inexistente"])


def test_preflight_output_is_redacted(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, urls = fleet_setup

    output = format_preflight(service.preflight())

    assert "smartcrm_local_dev" not in output
    assert all(url not in output for url in urls.values())
    assert "cliente-ready status=active connected=yes identity=yes" in output


def test_preflight_sanitizes_untrusted_revision_text(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup
    result = service.preflight(["cliente-ready"])[0]

    output = format_preflight([replace(result, revision="postgresql://user:plain-secret@host/db")])

    assert "plain-secret" not in output
    assert "revision=invalid" in output

@pytest.mark.parametrize(
    ("selection", "backup", "confirmed", "message"),
    [
        ([], True, True, "explicit tenant selection is required"),
        (["cliente-ready"], False, True, "verified backup acknowledgement is required"),
        (["cliente-ready"], True, False, "operator confirmation is required"),
    ],
)
def test_migration_requires_selection_backup_and_confirmation(
    fleet_setup, selection, backup: bool, confirmed: bool, message: str  # noqa: ANN001
) -> None:
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup
    calls: list[str] = []

    with pytest.raises(FleetOperationError, match=message):
        service.migrate(
            selection,
            backup_acknowledged=backup,
            confirmed=confirmed,
            migration_runner=lambda tenant: calls.append(tenant.slug),
        )

    assert calls == []


def test_migration_invokes_only_explicitly_selected_tenants(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup
    migrated: list[str] = []

    results = service.migrate(
        ["cliente-ready"], backup_acknowledged=True, confirmed=True,
        migration_runner=lambda tenant: migrated.append(tenant.slug),
        verify_after=False,
    )

    assert migrated == ["cliente-ready"]
    assert [(item.slug, item.succeeded, item.code) for item in results] == [
        ("cliente-ready", True, "migrated")
    ]


def test_migration_continues_after_independent_tenant_failure(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup
    calls: list[str] = []

    def runner(tenant) -> None:  # noqa: ANN001
        calls.append(tenant.slug)
        if tenant.slug == "cliente-ready":
            raise RuntimeError("dsn=must-not-leak")

    results = service.migrate(
        ["cliente-ready", "cliente-old"],
        backup_acknowledged=True, confirmed=True, migration_runner=runner,
        verify_after=False,
    )

    assert calls == ["cliente-ready", "cliente-old"]
    assert [(item.slug, item.succeeded, item.code) for item in results] == [
        ("cliente-ready", False, "migration_failed"),
        ("cliente-old", True, "migrated"),
    ]
    assert "dsn=must-not-leak" not in repr(results)


def test_active_identity_mismatch_is_never_migrated(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup
    calls: list[str] = []

    results = service.migrate(
        ["cliente-mismatch"], backup_acknowledged=True, confirmed=True,
        migration_runner=lambda tenant: calls.append(tenant.slug),
    )

    assert calls == []
    assert [(item.succeeded, item.code) for item in results] == [
        (False, "identity_mismatch")
    ]


def test_provisioning_database_without_identity_can_be_migrated_then_activated(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, _urls = fleet_setup
    calls: list[str] = []

    results = service.migrate(
        ["cliente-old"], backup_acknowledged=True, confirmed=True,
        migration_runner=lambda tenant: calls.append(tenant.slug),
        verify_after=False,
    )

    assert calls == ["cliente-old"]
    assert (results[0].succeeded, results[0].code) == (True, "migrated")


def test_default_runner_upgrades_only_selected_schema(fleet_setup) -> None:  # noqa: ANN001
    service, _control, _secrets, _tenant_ids, tenant_urls = fleet_setup

    results = service.migrate(
        ["cliente-old"], backup_acknowledged=True, confirmed=True,
    )

    engine = create_engine(tenant_urls["old"])
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    engine.dispose()
    assert revision == TENANT_HEAD
    assert (results[0].succeeded, results[0].code) == (
        True, "migrated_pending_activation"
    )


def test_web_routes_never_expose_fleet_migration(fleet_setup) -> None:  # noqa: ANN001
    from app.main import create_app

    paths = {route.path for route in create_app().routes}

    assert not any("fleet" in path or "migrate" in path for path in paths)
