from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.security.secrets import InMemorySecretProvider
from app.tenant_database import (
    TenantDatabaseProfile,
    TenantDatabaseRouter,
    TenantDatabaseRouterSettings,
    TenantSelectorError,
    TenantUnavailableError,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "a4c9d2e7f1b6"
SCHEMA_CONTRACT = "tenant-v1"


@dataclass(frozen=True)
class TenantDatabases:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    dsn_a: str
    dsn_b: str


class MutableProfileLoader:
    def __init__(self, profiles: dict[uuid.UUID, TenantDatabaseProfile]) -> None:
        self.profiles = profiles
        self.calls: list[uuid.UUID] = []

    def __call__(self, tenant_id: uuid.UUID) -> TenantDatabaseProfile | None:
        self.calls.append(tenant_id)
        return self.profiles.get(tenant_id)


def _dsn_for(database_name: str) -> str:
    return make_url(TEST_DATABASE_URL).set(database=database_name).render_as_string(hide_password=False)


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def _initialize_tenant_database(dsn: str, tenant_id: uuid.UUID, marker: str) -> None:
    engine = create_engine(dsn)
    try:
        with engine.connect() as connection:
            command.upgrade(_tenant_config(connection), TENANT_HEAD)
            connection.execute(
                text(
                    "INSERT INTO tenant_identity "
                    "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
                    "VALUES ('identity', :tenant_id, 'default', :schema_contract)"
                ),
                {"tenant_id": tenant_id, "schema_contract": SCHEMA_CONTRACT},
            )
            connection.execute(
                text(
                    "INSERT INTO teams (id, workspace_id, name) "
                    "VALUES ('same-public-id', 'default', :marker)"
                ),
                {"marker": marker},
            )
            connection.commit()
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def tenant_databases() -> TenantDatabases:
    suffix = uuid.uuid4().hex
    name_a = f"smartcrm_tenant_a_{suffix}"
    name_b = f"smartcrm_tenant_b_{suffix}"
    admin_url = make_url(TEST_DATABASE_URL).set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    names = (name_a, name_b)
    try:
        with admin_engine.connect() as connection:
            for database_name in names:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        dsn_a = _dsn_for(name_a)
        dsn_b = _dsn_for(name_b)
        _initialize_tenant_database(dsn_a, tenant_a, "tenant-a")
        _initialize_tenant_database(dsn_b, tenant_b, "tenant-b")
        yield TenantDatabases(tenant_a=tenant_a, tenant_b=tenant_b, dsn_a=dsn_a, dsn_b=dsn_b)
    finally:
        with admin_engine.connect() as connection:
            for database_name in names:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def _profiles(databases: TenantDatabases) -> dict[uuid.UUID, TenantDatabaseProfile]:
    return {
        databases.tenant_a: TenantDatabaseProfile(
            tenant_id=databases.tenant_a,
            status="active",
            secret_ref="tenant-a",
            profile_version=1,
            expected_tenant_revision=TENANT_HEAD,
        ),
        databases.tenant_b: TenantDatabaseProfile(
            tenant_id=databases.tenant_b,
            status="active",
            secret_ref="tenant-b",
            profile_version=1,
            expected_tenant_revision=TENANT_HEAD,
        ),
    }


@pytest.fixture
def router_factory(tenant_databases):  # noqa: ANN001
    routers: list[TenantDatabaseRouter] = []

    def build(
        *,
        profiles: dict[uuid.UUID, TenantDatabaseProfile] | None = None,
        secrets: dict[str, str] | None = None,
        settings: TenantDatabaseRouterSettings | None = None,
        engine_factory=None,  # noqa: ANN001
        security_event_recorder=None,  # noqa: ANN001
    ) -> tuple[TenantDatabaseRouter, MutableProfileLoader]:
        if settings is None:
            settings = TenantDatabaseRouterSettings(allow_insecure_loopback=True)
        loader = MutableProfileLoader(profiles or _profiles(tenant_databases))
        provider = InMemorySecretProvider(
            secrets or {"tenant-a": tenant_databases.dsn_a, "tenant-b": tenant_databases.dsn_b}
        )
        router = TenantDatabaseRouter(
            loader,
            provider,
            settings=settings,
            engine_factory=engine_factory,
            security_event_recorder=security_event_recorder,
        )
        routers.append(router)
        return router, loader

    yield build
    for router in routers:
        router.dispose()


def test_router_rejects_slug_or_string_before_profile_lookup(router_factory) -> None:  # noqa: ANN001
    router, loader = router_factory()

    with pytest.raises(TenantSelectorError):
        router.get_engine("cliente-a")  # type: ignore[arg-type]

    assert loader.calls == []


def test_router_signature_accepts_no_browser_dsn_override(router_factory, tenant_databases) -> None:  # noqa: ANN001
    router, _loader = router_factory()

    with pytest.raises(TypeError):
        router.get_engine(tenant_databases.tenant_a, dsn=tenant_databases.dsn_b)  # type: ignore[call-arg]


def test_unknown_tenant_has_no_default_or_engine_creation(router_factory) -> None:  # noqa: ANN001
    factory_calls: list[str] = []

    def forbidden_factory(url: str, **_kwargs):  # noqa: ANN001
        factory_calls.append(url)
        raise AssertionError("engine factory must not run")

    router, _loader = router_factory(engine_factory=forbidden_factory)

    with pytest.raises(TenantUnavailableError, match="tenant database unavailable"):
        router.get_engine(uuid.uuid4())

    assert factory_calls == []
    assert router.cached_tenant_ids == ()


def test_remote_profile_without_verified_tls_fails_before_engine_factory(
    router_factory,
    tenant_databases,
) -> None:  # noqa: ANN001
    factory_calls: list[str] = []
    insecure = "postgresql+psycopg://tenant:top-secret@db.example.test/tenant"
    events: list[dict] = []

    def recording_factory(url: str, **_kwargs):  # noqa: ANN001, ANN201
        factory_calls.append(url)
        return object()

    router, _loader = router_factory(
        secrets={"tenant-a": insecure},
        engine_factory=recording_factory,
        security_event_recorder=lambda **values: events.append({"event_id": uuid.uuid4(), **values}),
    )

    with pytest.raises(TenantUnavailableError, match="tenant database unavailable"):
        router.get_engine(tenant_databases.tenant_a)
    assert factory_calls == []

    event = events[-1]
    assert event["event_type"] == "tenant.routing_failed"
    assert event["tenant_id"] == tenant_databases.tenant_a
    assert event["user_id"] is None
    assert event["outcome_code"] == "connection_rejected"
    assert len(event["correlation_digest"]) == 64
    assert "top-secret" not in repr(event)



def test_inactive_tenant_fails_before_secret_or_engine(router_factory, tenant_databases) -> None:  # noqa: ANN001
    profiles = _profiles(tenant_databases)
    current = profiles[tenant_databases.tenant_a]
    profiles[tenant_databases.tenant_a] = TenantDatabaseProfile(
        tenant_id=current.tenant_id,
        status="inactive",
        secret_ref="missing-ref",
        profile_version=current.profile_version,
        expected_tenant_revision=current.expected_tenant_revision,
    )
    router, _loader = router_factory(profiles=profiles, engine_factory=lambda *_args, **_kwargs: None)

    with pytest.raises(TenantUnavailableError, match="tenant database unavailable"):
        router.get_engine(tenant_databases.tenant_a)

    assert router.cached_tenant_ids == ()


def test_two_physical_databases_isolate_identical_public_ids(router_factory, tenant_databases) -> None:  # noqa: ANN001
    router, _loader = router_factory()

    with router.tenant_session_scope(tenant_databases.tenant_a) as session_a:
        marker_a = session_a.scalar(text("SELECT name FROM teams WHERE id = 'same-public-id'"))
    with router.tenant_session_scope(tenant_databases.tenant_b) as session_b:
        marker_b = session_b.scalar(text("SELECT name FROM teams WHERE id = 'same-public-id'"))

    assert marker_a == "tenant-a"
    assert marker_b == "tenant-b"


def test_swapped_profile_is_rejected_before_business_sql(router_factory, tenant_databases) -> None:  # noqa: ANN001
    statements: list[str] = []

    events: list[dict] = []
    def recording_factory(url: str, **kwargs):  # noqa: ANN001
        engine = create_engine(url, **kwargs)
        event.listen(
            engine,
            "before_cursor_execute",
            lambda _conn, _cursor, statement, _parameters, _context, _many: statements.append(statement),
        )
        return engine

    router, _loader = router_factory(
        secrets={"tenant-a": tenant_databases.dsn_b, "tenant-b": tenant_databases.dsn_a},
        engine_factory=recording_factory,
        security_event_recorder=lambda **values: events.append({"event_id": uuid.uuid4(), **values}),
    )

    with pytest.raises(TenantUnavailableError, match="tenant database unavailable"):
        with router.tenant_session_scope(tenant_databases.tenant_a):
            pytest.fail("identity mismatch must abort before yielding")

    assert any("tenant_identity" in statement for statement in statements)
    assert not any("teams" in statement for statement in statements)
    assert router.cached_tenant_ids == ()

    security_event = events[-1]
    assert security_event["event_type"] == "tenant.identity_mismatch"
    assert security_event["tenant_id"] == tenant_databases.tenant_a
    assert security_event["outcome_code"] == "identity_mismatch"
    assert security_event["user_id"] is None
    assert len(security_event["correlation_digest"]) == 64


def test_expected_revision_mismatch_fails_closed(router_factory, tenant_databases) -> None:  # noqa: ANN001
    profiles = _profiles(tenant_databases)
    current = profiles[tenant_databases.tenant_a]
    profiles[tenant_databases.tenant_a] = TenantDatabaseProfile(
        tenant_id=current.tenant_id,
        status=current.status,
        secret_ref=current.secret_ref,
        profile_version=current.profile_version,
        expected_tenant_revision="stale-revision",
    )
    router, _loader = router_factory(profiles=profiles)

    with pytest.raises(TenantUnavailableError, match="tenant database unavailable"):
        with router.tenant_session_scope(tenant_databases.tenant_a):
            pytest.fail("revision mismatch must abort before yielding")

    assert router.cached_tenant_ids == ()


def test_schema_contract_mismatch_fails_closed(router_factory, tenant_databases) -> None:  # noqa: ANN001
    direct_engine = create_engine(tenant_databases.dsn_a)
    with direct_engine.begin() as connection:
        connection.execute(text("UPDATE tenant_identity SET schema_contract = 'tenant-v0'"))
    direct_engine.dispose()
    router, _loader = router_factory()
    try:
        with pytest.raises(TenantUnavailableError, match="tenant database unavailable"):
            with router.tenant_session_scope(tenant_databases.tenant_a):
                pytest.fail("schema mismatch must abort before yielding")
        assert router.cached_tenant_ids == ()
    finally:
        repair_engine = create_engine(tenant_databases.dsn_a)
        with repair_engine.begin() as connection:
            connection.execute(
                text("UPDATE tenant_identity SET schema_contract = :schema_contract"),
                {"schema_contract": SCHEMA_CONTRACT},
            )
        repair_engine.dispose()


def test_one_tenant_outage_never_falls_back_and_keeps_other_cached(router_factory, tenant_databases) -> None:  # noqa: ANN001
    unavailable_dsn = make_url(tenant_databases.dsn_b).set(port=1, database="missing").render_as_string(hide_password=False)
    router, _loader = router_factory(secrets={"tenant-a": tenant_databases.dsn_a, "tenant-b": unavailable_dsn})

    with router.tenant_session_scope(tenant_databases.tenant_a) as session:
        assert session.scalar(text("SELECT name FROM teams WHERE id = 'same-public-id'")) == "tenant-a"
    with pytest.raises(TenantUnavailableError, match="tenant database unavailable"):
        with router.tenant_session_scope(tenant_databases.tenant_b):
            pytest.fail("outage must abort before yielding")

    assert router.cached_tenant_ids == (tenant_databases.tenant_a,)


def test_engine_cache_reuses_same_profile_version(router_factory, tenant_databases) -> None:  # noqa: ANN001
    router, loader = router_factory()

    first = router.get_engine(tenant_databases.tenant_a)
    second = router.get_engine(tenant_databases.tenant_a)

    assert first is second
    assert loader.calls == [tenant_databases.tenant_a, tenant_databases.tenant_a]


def test_profile_rotation_disposes_only_stale_engine(router_factory, tenant_databases) -> None:  # noqa: ANN001
    router, loader = router_factory()
    old_engine = router.get_engine(tenant_databases.tenant_a)
    current = loader.profiles[tenant_databases.tenant_a]
    loader.profiles[tenant_databases.tenant_a] = TenantDatabaseProfile(
        tenant_id=current.tenant_id,
        status=current.status,
        secret_ref=current.secret_ref,
        profile_version=2,
        expected_tenant_revision=current.expected_tenant_revision,
    )

    with patch.object(old_engine, "dispose", wraps=old_engine.dispose) as disposed:
        new_engine = router.get_engine(tenant_databases.tenant_a)

    assert new_engine is not old_engine
    disposed.assert_called_once_with()


def test_lru_cache_is_bounded_and_disposes_oldest(router_factory, tenant_databases) -> None:  # noqa: ANN001
    settings = TenantDatabaseRouterSettings(
        max_cached_engines=1,
        allow_insecure_loopback=True,
    )
    router, _loader = router_factory(settings=settings)
    old_engine = router.get_engine(tenant_databases.tenant_a)

    with patch.object(old_engine, "dispose", wraps=old_engine.dispose) as disposed:
        router.get_engine(tenant_databases.tenant_b)

    assert router.cached_tenant_ids == (tenant_databases.tenant_b,)
    disposed.assert_called_once_with()


def test_invalidate_removes_only_selected_tenant(router_factory, tenant_databases) -> None:  # noqa: ANN001
    router, _loader = router_factory()
    engine_a = router.get_engine(tenant_databases.tenant_a)
    router.get_engine(tenant_databases.tenant_b)

    with patch.object(engine_a, "dispose", wraps=engine_a.dispose) as disposed:
        router.invalidate(tenant_databases.tenant_a)

    assert router.cached_tenant_ids == (tenant_databases.tenant_b,)
    disposed.assert_called_once_with()


def test_session_sets_transaction_local_workspace_context(router_factory, tenant_databases) -> None:  # noqa: ANN001
    router, _loader = router_factory()

    with router.tenant_session_scope(tenant_databases.tenant_a) as session:
        assert session.scalar(text("SELECT current_setting('smartcrm.workspace_id', true)")) == "default"
    with router.get_engine(tenant_databases.tenant_a).connect() as connection:
        assert connection.scalar(text("SELECT current_setting('smartcrm.workspace_id', true)")) != "default"


def test_session_rolls_back_consumer_failure(router_factory, tenant_databases) -> None:  # noqa: ANN001
    router, _loader = router_factory()

    with pytest.raises(RuntimeError, match="deliberate rollback"):
        with router.tenant_session_scope(tenant_databases.tenant_a) as session:
            session.execute(
                text(
                    "INSERT INTO teams (id, workspace_id, name) "
                    "VALUES ('rollback-only', 'default', 'temporary')"
                )
            )
            raise RuntimeError("deliberate rollback")

    with router.tenant_session_scope(tenant_databases.tenant_a) as session:
        assert session.scalar(text("SELECT count(*) FROM teams WHERE id = 'rollback-only'")) == 0


def test_health_is_redacted_and_isolated(router_factory, tenant_databases) -> None:  # noqa: ANN001
    unavailable_dsn = make_url(tenant_databases.dsn_b).set(port=1, database="missing").render_as_string(hide_password=False)
    router, _loader = router_factory(secrets={"tenant-a": tenant_databases.dsn_a, "tenant-b": unavailable_dsn})

    assert router.health(tenant_databases.tenant_a) is True
    assert router.health(tenant_databases.tenant_b) is False
    assert "smartcrm_local_dev" not in repr(router)
    assert tenant_databases.dsn_a not in repr(router)
