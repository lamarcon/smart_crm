from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
LEGACY_HEAD = "9f7a2c31d5e8"
TENANT_HEAD = "a4c9d2e7f1b6"
TENANT_TABLES = {
    "workspaces",
    "teams",
    "crm_users",
    "leads",
    "contacts",
    "companies",
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
}


def tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def legacy_database():
    engine = create_engine(TEST_DATABASE_URL)
    schema = f"tenant_migration_{uuid.uuid4().hex}"
    with engine.begin() as setup:
        setup.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    config = tenant_config(connection)
    command.upgrade(config, LEGACY_HEAD)
    try:
        yield connection, schema, config
    finally:
        connection.close()
        with engine.begin() as cleanup:
            cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def seed_legacy_data(connection) -> None:  # noqa: ANN001
    connection.execute(
        text(
            "INSERT INTO crm_users "
            "(id, workspace_id, name, email, job_title, role, status, payload) "
            "VALUES ('user-1', 'default', 'Admin', 'admin@example.test', '', "
            "'Administrador', 'Ativo', '{\"marker\": \"user\"}'::jsonb)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO leads "
            "(id, workspace_id, responsible_id, name, company, email, phone, segment, source, stage, payload) "
            "VALUES ('lead-1', 'default', 'user-1', 'Lead', '', '', '', '', '', 'Novo', "
            "'{\"marker\": \"lead\"}'::jsonb)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO deals "
            "(id, workspace_id, responsible_id, title, company_text, contact_text, amount, stage, payload) "
            "VALUES ('deal-1', 'default', 'user-1', 'Deal', '', '', 100.00, 'Prospecção', "
            "'{\"marker\": \"deal\"}'::jsonb)"
        )
    )
    connection.execute(text("INSERT INTO lead_assistants (lead_id, user_id, position) VALUES ('lead-1', 'user-1', 0)"))
    connection.execute(text("INSERT INTO deal_assistants (deal_id, user_id, position) VALUES ('deal-1', 'user-1', 0)"))
    connection.execute(
        text(
            "INSERT INTO deal_stage_history "
            "(deal_id, position, from_stage, to_stage, changed_at, changed_by_id) "
            "VALUES ('deal-1', 0, NULL, 'Prospecção', now(), 'user-1')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO quotes "
            "(id, deal_id, position, description, quantity, unit_price, discount, total, state, payload) "
            "VALUES ('quote-1', 'deal-1', 0, 'Item', 1, 100, 0, 100, 'Rascunho', "
            "'{\"marker\": \"quote\"}'::jsonb)"
        )
    )


def legacy_fingerprint(connection) -> dict[str, tuple[int, str | None]]:  # noqa: ANN001
    return {
        table_name: connection.execute(
            text(
                f"SELECT count(*), md5(coalesce(string_agg(id::text || ':' || payload::text, '|' ORDER BY id::text), '')) "
                f"FROM {table_name}"
            )
        ).one()
        for table_name in ("crm_users", "leads", "deals", "quotes")
    }


@contextmanager
def runtime_role(connection, schema):  # noqa: ANN001
    role = f"smartcrm_runtime_{uuid.uuid4().hex}"
    connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
    connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
    connection.execute(text(f'SET ROLE "{role}"'))
    try:
        yield
    finally:
        connection.execute(text("RESET ROLE"))
        connection.execute(text(f'DROP OWNED BY "{role}"'))
        connection.execute(text(f'DROP ROLE "{role}"'))


def test_upgrade_preserves_default_rows_payloads_and_links(legacy_database) -> None:
    connection, _schema, config = legacy_database
    seed_legacy_data(connection)
    before = legacy_fingerprint(connection)

    command.upgrade(config, TENANT_HEAD)

    assert legacy_fingerprint(connection) == before
    assert connection.scalar(text("SELECT count(*) FROM lead_assistants")) == 1
    assert connection.scalar(text("SELECT count(*) FROM deal_stage_history")) == 1


def test_upgrade_backfills_every_child_workspace_from_parent(legacy_database) -> None:
    connection, _schema, config = legacy_database
    seed_legacy_data(connection)

    command.upgrade(config, TENANT_HEAD)

    assert connection.scalar(text("SELECT workspace_id FROM lead_assistants")) == "default"
    assert connection.scalar(text("SELECT workspace_id FROM deal_assistants")) == "default"
    assert connection.scalar(text("SELECT workspace_id FROM deal_stage_history")) == "default"
    assert connection.scalar(text("SELECT workspace_id FROM quotes")) == "default"


def test_child_workspace_columns_become_not_null(legacy_database) -> None:
    connection, schema, config = legacy_database
    command.upgrade(config, TENANT_HEAD)
    columns = {
        table_name: {item["name"]: item for item in inspect(connection).get_columns(table_name, schema=schema)}
        for table_name in ("lead_assistants", "deal_assistants", "deal_stage_history", "quotes")
    }

    assert all(columns[table_name]["workspace_id"]["nullable"] is False for table_name in columns)


def test_every_tenant_table_enables_and_forces_rls(legacy_database) -> None:
    connection, schema, config = legacy_database
    command.upgrade(config, TENANT_HEAD)
    rows = connection.execute(
        text(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = ANY(:tables) ORDER BY c.relname"
        ),
        {"schema": schema, "tables": sorted(TENANT_TABLES)},
    ).all()

    assert {row.relname for row in rows} == TENANT_TABLES
    assert all(row.relrowsecurity is True and row.relforcerowsecurity is True for row in rows)


def test_every_tenant_policy_has_using_and_with_check(legacy_database) -> None:
    connection, schema, config = legacy_database
    command.upgrade(config, TENANT_HEAD)
    policies = connection.execute(
        text(
            "SELECT tablename, qual, with_check FROM pg_policies "
            "WHERE schemaname = :schema"
        ),
        {"schema": schema},
    ).all()

    assert {row.tablename for row in policies} == TENANT_TABLES
    assert all("current_setting" in row.qual and "current_setting" in row.with_check for row in policies)


def test_missing_rls_context_returns_no_business_rows(legacy_database) -> None:
    connection, schema, config = legacy_database
    seed_legacy_data(connection)
    command.upgrade(config, TENANT_HEAD)

    with runtime_role(connection, schema):
        assert connection.scalar(text("SELECT count(*) FROM leads")) == 0


def test_rls_context_exposes_only_matching_workspace(legacy_database) -> None:
    connection, schema, config = legacy_database
    seed_legacy_data(connection)
    command.upgrade(config, TENANT_HEAD)

    with runtime_role(connection, schema):
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
        assert connection.scalar(text("SELECT count(*) FROM leads")) == 1
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'other', true)"))
        assert connection.scalar(text("SELECT count(*) FROM leads")) == 0


def test_rls_with_check_rejects_wrong_workspace_insert(legacy_database) -> None:
    connection, schema, config = legacy_database
    command.upgrade(config, TENANT_HEAD)

    with runtime_role(connection, schema):
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
        # PostgreSQL reports an RLS WITH CHECK rejection as SQLSTATE 42501
        # (insufficient_privilege), which SQLAlchemy exposes as DBAPIError.
        with pytest.raises(DBAPIError) as exc_info:
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO teams (id, workspace_id, name) "
                        "VALUES ('team-wrong', 'other', 'Wrong')"
                    )
                )
        assert exc_info.value.orig.sqlstate == "42501"
        assert "row-level security policy" in str(exc_info.value.orig)
        assert connection.scalar(text("SELECT count(*) FROM teams")) == 0


def test_identity_allows_only_the_constant_singleton(legacy_database) -> None:
    connection, _schema, config = legacy_database
    command.upgrade(config, TENANT_HEAD)
    tenant_id = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO tenant_identity "
            "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
            "VALUES ('identity', :tenant_id, 'default', 'tenant-v1')"
        ),
        {"tenant_id": tenant_id},
    )

    assert connection.scalar(text("SELECT control_tenant_id FROM tenant_identity")) == tenant_id
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO tenant_identity "
                    "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
                    "VALUES ('other', :tenant_id, 'default', 'tenant-v1')"
                ),
                {"tenant_id": uuid.uuid4()},
            )


def test_inconsistent_multi_workspace_database_aborts_upgrade(legacy_database) -> None:
    connection, schema, config = legacy_database
    # Persist the legacy baseline so rolling back the deliberately failed
    # upgrade proves that the prior revision survives unchanged.
    connection.commit()
    connection.execute(text("INSERT INTO workspaces (id, version) VALUES ('unexpected', 0)"))

    with pytest.raises(DBAPIError, match="exactly one default workspace"):
        command.upgrade(config, TENANT_HEAD)

    connection.rollback()
    # Restore the isolated fixture schema explicitly after the failed DDL
    # transaction; current_schema() is not valid in SET search_path syntax.
    connection.execute(text(f'SET search_path TO "{schema}"'))
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == LEGACY_HEAD


def test_downgrade_preserves_business_data_and_removes_tenant_security(legacy_database) -> None:
    connection, schema, config = legacy_database
    seed_legacy_data(connection)
    before = legacy_fingerprint(connection)
    command.upgrade(config, TENANT_HEAD)

    command.downgrade(config, LEGACY_HEAD)

    inspector = inspect(connection)
    assert legacy_fingerprint(connection) == before
    assert "tenant_identity" not in inspector.get_table_names(schema=schema)
    assert "workspace_id" not in {item["name"] for item in inspector.get_columns("quotes", schema=schema)}
    rls_enabled = connection.scalar(
        text("SELECT relrowsecurity FROM pg_class WHERE oid = 'leads'::regclass")
    )
    assert rls_enabled is False
