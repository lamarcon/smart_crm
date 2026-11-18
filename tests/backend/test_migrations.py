from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.models import Base


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
ACTIVITY_HEAD = "e1c4a7b9d2f6"
TENANT_HEAD = "f5b2d8e4a6c3"


def alembic_config(connection=None) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


@contextmanager
def runtime_role(connection, schema):  # noqa: ANN001
    role = f"smartcrm_runtime_{uuid.uuid4().hex}"
    connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
    connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
    connection.execute(
        text(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" '
            f'TO "{role}"'
        )
    )
    connection.execute(text(f'SET ROLE "{role}"'))
    try:
        yield
    finally:
        connection.execute(text("RESET ROLE"))
        connection.execute(text(f'DROP OWNED BY "{role}"'))
        connection.execute(text(f'DROP ROLE "{role}"'))


@pytest.fixture
def isolated_migration():
    engine = create_engine(TEST_DATABASE_URL)
    schema = f"migration_{uuid.uuid4().hex}"
    with engine.begin() as setup:
        setup.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    try:
        yield connection, schema, alembic_config(connection)
    finally:
        connection.close()
        with engine.begin() as cleanup:
            cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_upgrade_reaches_head_and_creates_uninitialized_singleton(isolated_migration) -> None:
    connection, schema, config = isolated_migration

    command.upgrade(config, "head")

    tables = set(inspect(connection).get_table_names(schema=schema))
    workspace = connection.execute(
        text("SELECT id, version, initialized_at FROM workspaces")
    ).one()
    assert set(Base.metadata.tables).issubset(tables)
    assert tuple(workspace) == ("default", 0, None)
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == TENANT_HEAD
    history_redaction = next(
        column
        for column in inspect(connection).get_columns(
            "custom_field_definitions", schema=schema
        )
        if column["name"] == "redact_in_history"
    )
    assert history_redaction["nullable"] is False
    assert str(history_redaction["default"]).lower() == "false"
    status_constraint = connection.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_crm_users_valid_status' "
            "AND conrelid = 'crm_users'::regclass"
        )
    )
    assert all(
        status in status_constraint
        for status in ("Ativo", "Pendente", "Inativo", "Cancelado")
    )


def test_repeated_upgrade_is_idempotent(isolated_migration) -> None:
    connection, _schema, config = isolated_migration
    command.upgrade(config, "head")

    command.upgrade(config, "head")

    assert connection.scalar(text("SELECT count(*) FROM workspaces")) == 1
    assert connection.scalar(text("SELECT version FROM workspaces WHERE id='default'")) == 0


def test_account_action_token_migration_enforces_constraints_indexes_and_rls(
    isolated_migration,
) -> None:
    connection, schema, config = isolated_migration
    command.upgrade(config, "head")
    inspector = inspect(connection)
    columns = {item["name"]: item for item in inspector.get_columns(
        "account_action_tokens", schema=schema
    )}
    checks = {
        item["name"]: item["sqltext"]
        for item in inspector.get_check_constraints(
            "account_action_tokens", schema=schema
        )
    }
    foreign_keys = {
        (
            tuple(item["constrained_columns"]),
            item["referred_table"],
            tuple(item["referred_columns"]),
            item["options"].get("ondelete"),
        )
        for item in inspector.get_foreign_keys("account_action_tokens", schema=schema)
    }
    indexes = {
        item["name"]: item
        for item in inspector.get_indexes("account_action_tokens", schema=schema)
    }

    assert set(columns) == set(Base.metadata.tables["account_action_tokens"].c.keys())
    assert columns["token_digest"]["nullable"] is False
    assert str(columns["token_digest"]["type"]) == "CHAR(64)"
    assert columns["expires_at"]["type"].timezone is True
    assert "purpose::text = ANY" in checks["ck_account_action_tokens_valid_purpose"]
    assert "delivery_status::text = ANY" in checks[
        "ck_account_action_tokens_valid_delivery_status"
    ]
    assert "char_length(token_digest) = 64" in checks[
        "ck_account_action_tokens_digest_length"
    ]
    assert "consumed_at IS NOT NULL AND invalidated_at IS NOT NULL" in checks[
        "ck_account_action_tokens_single_terminal_state"
    ]
    assert (("workspace_id",), "workspaces", ("id",), "RESTRICT") in foreign_keys
    assert (("user_id",), "crm_users", ("id",), "RESTRICT") in foreign_keys
    assert (
        ("created_by_user_id",),
        "crm_users",
        ("id",),
        "SET NULL",
    ) in foreign_keys
    index_definition = connection.scalar(
        text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = :schema "
            "AND indexname = 'ix_account_action_tokens_user_purpose_created'"
        ),
        {"schema": schema},
    )
    assert "(workspace_id, user_id, purpose, created_at DESC)" in index_definition
    assert indexes["uq_account_action_tokens_token_digest"]["unique"] is True

    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
    connection.execute(
        text(
            "INSERT INTO crm_users "
            "(id, workspace_id, name, email, normalized_email, auth_enabled, "
            "auth_version, job_title, role, status, payload) VALUES "
            "('user-default', 'default', 'Default', 'default@example.test', "
            "'default@example.test', false, 0, '', 'Vendedor', 'Pendente', '{}'::jsonb)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO account_action_tokens "
            "(id, workspace_id, user_id, purpose, token_digest, expires_at) VALUES "
            "(:id, 'default', 'user-default', 'invitation', :digest, now() + interval '1 hour')"
        ),
        {"id": uuid.uuid4(), "digest": "a" * 64},
    )

    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'other', true)"))
    connection.execute(text("INSERT INTO workspaces (id, version) VALUES ('other', 0)"))
    connection.execute(
        text(
            "INSERT INTO crm_users "
            "(id, workspace_id, name, email, normalized_email, auth_enabled, "
            "auth_version, job_title, role, status, payload) VALUES "
            "('user-other', 'other', 'Other', 'other@example.test', "
            "'other@example.test', false, 0, '', 'Vendedor', 'Pendente', '{}'::jsonb)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO account_action_tokens "
            "(id, workspace_id, user_id, purpose, token_digest, expires_at) VALUES "
            "(:id, 'other', 'user-other', 'password_reset', :digest, now() + interval '1 hour')"
        ),
        {"id": uuid.uuid4(), "digest": "b" * 64},
    )

    with runtime_role(connection, schema):
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
        assert connection.execute(
            text("SELECT token_digest FROM account_action_tokens ORDER BY token_digest")
        ).scalars().all() == ["a" * 64]
        with pytest.raises(DBAPIError) as exc_info:
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO account_action_tokens "
                        "(id, workspace_id, user_id, purpose, token_digest, expires_at) VALUES "
                        "(:id, 'other', 'user-other', 'invitation', :digest, "
                        "now() + interval '1 hour')"
                    ),
                    {"id": uuid.uuid4(), "digest": "c" * 64},
                )
        assert exc_info.value.orig.sqlstate == "42501"

    policy = connection.execute(
        text(
            "SELECT polcmd, polpermissive FROM pg_policy "
            "WHERE polrelid = 'account_action_tokens'::regclass "
            "AND polname = 'smartcrm_workspace_scope'"
        )
    ).one()
    rls_flags = connection.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'account_action_tokens'::regclass"
        )
    ).one()
    assert tuple(policy) == ("*", True)
    assert tuple(rls_flags) == (True, True)


def test_upgrade_repairs_activity_head_missing_history_redaction_column(
    isolated_migration,
) -> None:
    connection, schema, config = isolated_migration
    command.upgrade(config, "c7f3a9d8e2b1")
    definition_id = connection.scalar(
        text(
            "INSERT INTO custom_field_definitions "
            "(workspace_id, module, key, label, field_type, options, source, "
            "source_name, source_occurrence, position, user_created) "
            "VALUES ('default', 'deals', 'legacy_sensitive', 'Dado legado', "
            "'text', '[\"preservar\"]'::jsonb, 'custom', 'legacy_source', 1, 7, true) "
            "RETURNING id"
        )
    )
    definition_before = connection.scalar(
        text(
            "SELECT to_jsonb(definition) FROM custom_field_definitions AS definition "
            "WHERE id = :definition_id"
        ),
        {"definition_id": definition_id},
    )
    command.stamp(config, ACTIVITY_HEAD)

    columns_before = {
        column["name"]
        for column in inspect(connection).get_columns(
            "custom_field_definitions", schema=schema
        )
    }
    assert "redact_in_history" not in columns_before

    command.upgrade(config, "head")

    repaired = next(
        column
        for column in inspect(connection).get_columns(
            "custom_field_definitions", schema=schema
        )
        if column["name"] == "redact_in_history"
    )
    assert repaired["nullable"] is False
    assert str(repaired["default"]).lower() == "false"
    assert connection.scalar(text("SELECT count(*) FROM custom_field_definitions")) == 1
    definition_after = connection.scalar(
        text(
            "SELECT to_jsonb(definition) - 'redact_in_history' "
            "FROM custom_field_definitions AS definition WHERE id = :definition_id"
        ),
        {"definition_id": definition_id},
    )
    assert definition_after == definition_before
    assert connection.scalar(
        text(
            "SELECT redact_in_history FROM custom_field_definitions "
            "WHERE id = :definition_id"
        ),
        {"definition_id": definition_id},
    ) is False
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == TENANT_HEAD


def test_downgrade_and_upgrade_cycle_runs_only_in_isolated_schema(isolated_migration) -> None:
    connection, schema, config = isolated_migration
    command.upgrade(config, "head")

    command.downgrade(config, "base")
    tables_after_down = set(inspect(connection).get_table_names(schema=schema))
    command.upgrade(config, "head")

    assert "workspaces" not in tables_after_down
    assert set(Base.metadata.tables).issubset(
        set(inspect(connection).get_table_names(schema=schema))
    )


def test_upgrade_current_database_preserves_existing_probe(
    technical_probe_table: None,
) -> None:
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        before = connection.scalar(text("SELECT count(*) FROM _smartcrm_test_probe"))
        # An already-migrated database needs its tenant identity for the deploy
        # repair. A fresh database (as in CI) has no tables yet and nothing to repair.
        if connection.scalar(text("SELECT to_regclass('tenant_identity') IS NOT NULL")):
            connection.execute(
                text(
                    "INSERT INTO tenant_identity "
                    "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
                    "VALUES ('identity', :tenant_id, 'default', 'tenant-v1') "
                    "ON CONFLICT (singleton_key) DO NOTHING"
                ),
                {"tenant_id": uuid.UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")},
            )

    command.upgrade(alembic_config(), "head")

    with engine.connect() as connection:
        after = connection.scalar(text("SELECT count(*) FROM _smartcrm_test_probe"))
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert before >= 1
    assert after == before
    assert head == TENANT_HEAD
    engine.dispose()


def test_products_and_lead_intake_keys_have_constraints_and_tenant_rls(isolated_migration) -> None:
    connection, schema, config = isolated_migration
    command.upgrade(config, "head")
    inspector = inspect(connection)
    product_checks = {item["name"] for item in inspector.get_check_constraints("products", schema=schema)}
    assert {
        "ck_products_valid_currency", "ck_products_nonnegative_price",
        "ck_products_name_present", "ck_products_metadata_is_list",
    } <= product_checks
    quote_fks = {
        (tuple(item["constrained_columns"]), item["referred_table"])
        for item in inspector.get_foreign_keys("quotes", schema=schema)
    }
    assert (("product_id",), "products") in quote_fks
    key_uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("lead_intake_keys", schema=schema)}
    assert ("key_digest",) in key_uniques
    rows = connection.execute(
        text(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
            "EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = :schema AND p.tablename = c.relname "
            "AND p.policyname = 'smartcrm_workspace_scope') AS has_policy "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname IN ('products', 'lead_intake_keys') ORDER BY c.relname"
        ),
        {"schema": schema},
    ).all()
    assert [tuple(row) for row in rows] == [("lead_intake_keys", True, True, True), ("products", True, True, True)]

    command.downgrade(config, "c3d9a1f4b7e2")
    tables = set(inspect(connection).get_table_names(schema=schema))
    assert not {"products", "lead_intake_keys"} & tables
    assert "product_id" not in {item["name"] for item in inspect(connection).get_columns("quotes", schema=schema)}
    command.upgrade(config, "head")
    assert {"products", "lead_intake_keys"} <= set(inspect(connection).get_table_names(schema=schema))


def test_role_permissions_table_has_checks_tenant_rls_and_round_trips(isolated_migration) -> None:
    connection, schema, config = isolated_migration
    command.upgrade(config, "head")
    inspector = inspect(connection)
    checks = {item["name"] for item in inspector.get_check_constraints("role_permissions", schema=schema)}
    assert {
        "ck_role_permissions_valid_role", "ck_role_permissions_valid_module",
        "ck_role_permissions_valid_action", "ck_role_permissions_valid_scope",
    } <= checks
    assert inspector.get_pk_constraint("role_permissions", schema=schema)["constrained_columns"] == [
        "workspace_id", "role", "module", "action",
    ]
    row = connection.execute(
        text(
            "SELECT c.relrowsecurity, c.relforcerowsecurity, "
            "EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = :schema AND p.tablename = c.relname "
            "AND p.policyname = 'smartcrm_workspace_scope') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = 'role_permissions'"
        ),
        {"schema": schema},
    ).one()
    assert tuple(row) == (True, True, True)

    command.downgrade(config, "f2b8d4a6c1e9")
    assert "role_permissions" not in set(inspect(connection).get_table_names(schema=schema))
    command.upgrade(config, "head")
    assert "role_permissions" in set(inspect(connection).get_table_names(schema=schema))


def test_multiple_pipelines_keep_stage_ids_and_scope_legacy_names(isolated_migration) -> None:
    connection, schema, config = isolated_migration
    command.upgrade(config, "head")
    columns = {item["name"] for item in inspect(connection).get_columns("deal_pipelines", schema=schema)}
    assert {"position", "archived_at"} <= columns
    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
    default = connection.execute(text("SELECT id FROM deal_pipelines WHERE is_default")).scalar()
    won_default = connection.execute(
        text("SELECT id FROM deal_pipeline_stages WHERE pipeline_id = :p AND name = 'Ganho'"), {"p": default}
    ).scalar()
    other, stage_open, stage_won = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO deal_pipelines (id, workspace_id, name, version, is_default, position, default_stage_id) "
            "VALUES (:id, 'default', 'Pós-venda', 1, false, 1, :initial)"
        ),
        {"id": other, "initial": stage_open},
    )
    for stage_id, name, semantic, position in ((stage_open, "Em andamento", "open", 0), (stage_won, "Ganho", "won", 1)):
        connection.execute(
            text(
                "INSERT INTO deal_pipeline_stages (id, workspace_id, pipeline_id, name, semantic_type, color, position) "
                "VALUES (:id, 'default', :p, :name, :semantic, '#123456', :position)"
            ),
            {"id": stage_id, "p": other, "name": name, "semantic": semantic, "position": position},
        )
    connection.execute(text("INSERT INTO workspaces (id, version) VALUES ('default', 1) ON CONFLICT DO NOTHING"))

    def insert(deal_id: str, stage: str, pipeline=None, stage_id=None) -> tuple:  # noqa: ANN001
        connection.execute(
            text(
                "INSERT INTO deals (id, workspace_id, title, company_text, contact_text, amount, stage, pipeline_id, stage_id, payload, created_at, updated_at) "
                "VALUES (:id, 'default', :id, '', '', 0, :stage, :pipeline, :stage_id, '{}'::jsonb, now(), now())"
            ),
            {"id": deal_id, "stage": stage, "pipeline": pipeline, "stage_id": stage_id},
        )
        return tuple(connection.execute(text("SELECT pipeline_id, stage_id FROM deals WHERE id = :id"), {"id": deal_id}).one())

    # Ids sent by the application are kept even when another pipeline has the same stage name.
    assert insert("N-other", "Ganho", other, stage_won) == (other, stage_won)
    # ...and even when the stage text is stale: the ids win over the name.
    assert insert("N-stale", "Ganho", other, stage_open) == (other, stage_open)
    # A legacy row with only a name lands in the default pipeline...
    assert insert("N-legacy", "Ganho") == (default, won_default)
    # ...or in its own pipeline when it names one.
    assert insert("N-scoped", "Ganho", other) == (other, stage_won)

    with pytest.raises(Exception):
        connection.execute(text("UPDATE deal_pipelines SET archived_at = now() WHERE is_default"))
    connection.rollback()


def test_multiple_pipelines_downgrade_refuses_deals_outside_the_default(isolated_migration) -> None:
    connection, schema, config = isolated_migration
    command.upgrade(config, "head")
    command.downgrade(config, "e1a7c3f9b2d4")
    columns = {item["name"] for item in inspect(connection).get_columns("deal_pipelines", schema=schema)}
    assert "archived_at" not in columns
    command.upgrade(config, "head")
