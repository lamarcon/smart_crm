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
PIPELINE_HEAD = "c7f3a9d8e2b1"
TENANT_HEAD = "e1c4a7b9d2f6"
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
    "deal_pipelines",
    "deal_pipeline_stages",
    "deal_pipeline_audit_events",
    "crm_activity_events",
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


@pytest.fixture
def pipeline_database():
    engine = create_engine(TEST_DATABASE_URL)
    schema = f"activity_migration_{uuid.uuid4().hex}"
    with engine.begin() as setup:
        setup.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    config = tenant_config(connection)
    command.upgrade(config, PIPELINE_HEAD)
    try:
        yield connection, schema, config
    finally:
        connection.close()
        with engine.begin() as cleanup:
            cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def seed_activity_backfill_data(connection) -> None:  # noqa: ANN001
    connection.execute(
        text(
            "INSERT INTO crm_users "
            "(id, workspace_id, name, email, job_title, role, status, payload) "
            "VALUES ('activity-user', 'default', 'Ana Histórica', 'history@example.test', '', "
            "'Administrador', 'Ativo', '{}'::jsonb)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO companies "
            "(id, workspace_id, owner_id, name, city, segment, phone, payload, created_at) "
            "VALUES ('activity-company', 'default', 'activity-user', 'Empresa Histórica', "
            "'São Paulo', 'Tecnologia', '11999999999', '{\"marker\": \"company\"}'::jsonb, "
            "'2026-01-01 03:00:00+00')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO deals "
            "(id, workspace_id, company_id, responsible_id, title, company_text, "
            "contact_text, amount, stage, payload) "
            "VALUES ('activity-deal', 'default', 'activity-company', 'activity-user', "
            "'Negócio Histórico', 'Empresa Histórica', '', 10.00, 'Em Contato', "
            "'{\"marker\": \"deal\"}'::jsonb)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO deal_stage_history "
            "(workspace_id, deal_id, position, from_stage, to_stage, changed_at, changed_by_id) "
            "VALUES ('default', 'activity-deal', 0, NULL, 'Em Contato', "
            "'2026-01-02 03:04:05+00', 'activity-user')"
        )
    )


def table_fingerprint(connection, table_name: str) -> str:  # noqa: ANN001
    return connection.scalar(
        text(
            f"SELECT md5(coalesce(string_agg(to_jsonb(row_data)::text, '|' "
            f"ORDER BY to_jsonb(row_data)::text), '')) FROM {table_name} AS row_data"
        )
    )


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
            "VALUES ('deal-1', 'default', 'user-1', 'Deal', '', '', 100.00, 'Em Contato', "
            "'{\"marker\": \"deal\"}'::jsonb)"
        )
    )
    connection.execute(text("INSERT INTO lead_assistants (lead_id, user_id, position) VALUES ('lead-1', 'user-1', 0)"))
    connection.execute(text("INSERT INTO deal_assistants (deal_id, user_id, position) VALUES ('deal-1', 'user-1', 0)"))
    connection.execute(
        text(
            "INSERT INTO deal_stage_history "
            "(deal_id, position, from_stage, to_stage, changed_at, changed_by_id) "
            "VALUES ('deal-1', 0, NULL, 'Em Contato', now(), 'user-1')"
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


def test_pipeline_upgrade_seeds_exact_legacy_registry_and_default(legacy_database) -> None:
    connection, _schema, config = legacy_database

    command.upgrade(config, TENANT_HEAD)

    rows = connection.execute(
        text(
            "SELECT id, name, semantic_type, color, position, system_key "
            "FROM deal_pipeline_stages ORDER BY position"
        )
    ).all()
    pipeline = connection.execute(
        text("SELECT version, is_default, default_stage_id FROM deal_pipelines")
    ).one()

    assert [row.name for row in rows] == [
        "Em Contato", "Orçamento Proposta Preço", "Orçamentos enviados",
        "Negociação Revisão", "Pedido aprovado Consultar", "Faturando",
        "Ganho", "Orçamento Não Aprovado", "Analisar falha",
    ]
    assert [row.semantic_type for row in rows] == [
        "open", "open", "open", "open", "open", "open", "won", "lost", "lost"
    ]
    assert [row.color for row in rows] == [
        "#2E90FA", "#2E90FA", "#2E90FA", "#7F56D9", "#DC6803",
        "#DC6803", "#039855", "#D92D20", "#D92D20",
    ]
    assert [row.position for row in rows] == list(range(9))
    assert [row.system_key for row in rows] == ["initial", None, None, None, None, "billing", None, None, None]
    assert pipeline.version == 1
    assert pipeline.is_default is True
    assert pipeline.default_stage_id == rows[0].id
    assert connection.execute(
        text(
            "SELECT p.workspace_id, count(s.id) "
            "FROM deal_pipelines p JOIN deal_pipeline_stages s ON s.pipeline_id = p.id "
            "GROUP BY p.workspace_id"
        )
    ).one() == ("default", 9)


def test_pipeline_upgrade_backfills_deal_history_and_packed_ids(legacy_database) -> None:
    connection, _schema, config = legacy_database
    seed_legacy_data(connection)

    command.upgrade(config, TENANT_HEAD)

    deal = connection.execute(
        text("SELECT pipeline_id, stage_id, stage, payload FROM deals WHERE id = 'deal-1'")
    ).one()
    history = connection.execute(
        text("SELECT from_stage_id, to_stage_id, from_stage, to_stage FROM deal_stage_history")
    ).one()
    assert deal.pipeline_id is not None
    assert deal.stage_id is not None
    assert deal.stage == "Em Contato"
    assert deal.payload == {"marker": "deal"}
    assert history.from_stage_id is None
    assert history.to_stage_id == deal.stage_id
    assert history.from_stage is None
    assert history.to_stage == "Em Contato"


def test_legacy_text_writes_keep_canonical_ids_synchronized(legacy_database) -> None:
    connection, _schema, config = legacy_database
    seed_legacy_data(connection)
    command.upgrade(config, TENANT_HEAD)

    connection.execute(text("UPDATE deals SET stage = 'Ganho' WHERE id = 'deal-1'"))
    deal = connection.execute(
        text(
            "SELECT d.stage, d.stage_id, s.name, d.pipeline_id = s.pipeline_id AS same_pipeline "
            "FROM deals d JOIN deal_pipeline_stages s ON s.id = d.stage_id WHERE d.id = 'deal-1'"
        )
    ).one()
    connection.execute(
        text(
            "INSERT INTO deal_stage_history "
            "(workspace_id, deal_id, position, from_stage, to_stage, changed_at) "
            "VALUES ('default', 'deal-1', 1, 'Em Contato', 'Ganho', now())"
        )
    )
    history = connection.execute(
        text("SELECT from_stage_id, to_stage_id FROM deal_stage_history WHERE position = 1")
    ).one()

    assert deal.stage == "Ganho"
    assert deal.name == "Ganho"
    assert deal.same_pipeline is True
    assert history.from_stage_id is not None
    assert history.to_stage_id == deal.stage_id


def test_unknown_legacy_stage_rolls_back_without_publishing_head(legacy_database) -> None:
    connection, schema, config = legacy_database
    seed_legacy_data(connection)
    connection.execute(text("UPDATE deals SET stage = 'Etapa não mapeada' WHERE id = 'deal-1'"))
    connection.commit()

    with pytest.raises(DBAPIError, match="unknown legacy deal stage"):
        command.upgrade(config, TENANT_HEAD)

    connection.rollback()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == LEGACY_HEAD
    assert "deal_pipelines" not in inspect(connection).get_table_names(schema=schema)


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


def test_activity_upgrade_backfills_history_and_company_without_changing_sources(
    pipeline_database,
) -> None:
    connection, _schema, config = pipeline_database
    seed_activity_backfill_data(connection)
    before = {
        table_name: table_fingerprint(connection, table_name)
        for table_name in ("crm_users", "companies", "deals", "deal_stage_history")
    }

    command.upgrade(config, TENANT_HEAD)

    assert {
        table_name: table_fingerprint(connection, table_name)
        for table_name in before
    } == before
    rows = connection.execute(
        text(
            "SELECT category, event_type, actor_user_id, actor_name, summary, details, "
            "dedupe_key, occurred_at FROM crm_activity_events ORDER BY occurred_at, id"
        )
    ).all()
    company_event, movement_event = rows
    history = connection.execute(
        text(
            "SELECT id, from_stage_id, to_stage_id FROM deal_stage_history "
            "WHERE deal_id = 'activity-deal'"
        )
    ).one()

    assert company_event.category == "change"
    assert company_event.event_type == "company.created"
    assert company_event.actor_user_id is None
    assert company_event.actor_name == "Sistema (migração)"
    assert company_event.summary == "Empresa registrada"
    assert company_event.details == {"name": "Empresa Histórica", "source": "migration"}
    assert company_event.dedupe_key == "legacy-company-created:activity-company"
    assert company_event.occurred_at.isoformat() == "2026-01-01T03:00:00+00:00"
    assert movement_event.category == "movement"
    assert movement_event.event_type == "deal.stage_changed"
    assert movement_event.actor_user_id == "activity-user"
    assert movement_event.actor_name == "Ana Histórica"
    assert movement_event.summary == "Negócio criado na etapa Em Contato"
    assert movement_event.details == {
        "source": "user",
        "toStageId": str(history.to_stage_id),
        "toStageName": "Em Contato",
        "fromStageId": None,
        "fromStageName": None,
    }
    assert movement_event.dedupe_key == f"legacy-stage-history:{history.id}"
    assert movement_event.occurred_at.isoformat() == "2026-01-02T03:04:05+00:00"


def test_activity_schema_has_exact_constraints_indexes_and_forced_rls(pipeline_database) -> None:
    connection, schema, config = pipeline_database
    command.upgrade(config, TENANT_HEAD)

    constraints = dict(
        connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'crm_activity_events'::regclass"
            )
        ).all()
    )
    indexes = {
        row.indexname: row.indexdef
        for row in connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = :schema AND tablename = 'crm_activity_events'"
            ),
            {"schema": schema},
        )
    }
    rls = connection.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'crm_activity_events'::regclass"
        )
    ).one()

    assert "CHECK ((((deal_id IS NOT NULL) AND (company_id IS NULL)) OR " in constraints[
        "ck_crm_activity_events_exactly_one_subject"
    ]
    assert "category" in constraints["ck_crm_activity_events_valid_category"]
    assert constraints["uq_crm_activity_events_workspace_id_dedupe_key"].startswith(
        "UNIQUE (workspace_id, dedupe_key)"
    )
    assert "workspace_id, deal_id, occurred_at DESC, id DESC" in indexes[
        "ix_crm_activity_events_deal_timeline"
    ]
    assert "WHERE (deal_id IS NOT NULL)" in indexes["ix_crm_activity_events_deal_timeline"]
    assert "workspace_id, company_id, occurred_at DESC, id DESC" in indexes[
        "ix_crm_activity_events_company_timeline"
    ]
    assert "WHERE (company_id IS NOT NULL)" in indexes[
        "ix_crm_activity_events_company_timeline"
    ]
    assert tuple(rls) == (True, True)
    custom_definition_columns = {
        column["name"]
        for column in inspect(connection).get_columns(
            "custom_field_definitions", schema=schema
        )
    }
    assert "redact_in_history" in custom_definition_columns


def test_activity_rls_fails_closed_without_or_with_foreign_workspace(pipeline_database) -> None:
    connection, schema, config = pipeline_database
    seed_activity_backfill_data(connection)
    command.upgrade(config, TENANT_HEAD)
    connection.execute(text("INSERT INTO workspaces (id, version) VALUES ('other', 0)"))

    with runtime_role(connection, schema):
        assert connection.scalar(text("SELECT count(*) FROM crm_activity_events")) == 0
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
        assert connection.scalar(text("SELECT count(*) FROM crm_activity_events")) == 2
        with pytest.raises(DBAPIError) as exc_info:
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO crm_activity_events "
                        "(id, workspace_id, company_id, category, event_type, actor_name, "
                        "summary, details, dedupe_key, occurred_at) VALUES "
                        "(999, 'other', 'activity-company', 'observation', 'company.observation', "
                        "'Ana', 'Nota', '{}'::jsonb, 'cross-workspace', now())"
                    )
                )
        assert exc_info.value.orig.sqlstate == "42501"
        connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'other', true)"))
        assert connection.scalar(text("SELECT count(*) FROM crm_activity_events")) == 0


def test_activity_subject_and_dedupe_constraints_reject_invalid_rows(pipeline_database) -> None:
    connection, _schema, config = pipeline_database
    seed_activity_backfill_data(connection)
    command.upgrade(config, TENANT_HEAD)

    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO crm_activity_events "
                    "(workspace_id, category, event_type, actor_name, summary, details, "
                    "dedupe_key, occurred_at) VALUES "
                    "('default', 'observation', 'invalid.subject', 'Ana', 'Nota', '{}'::jsonb, "
                    "'invalid-subject', now())"
                )
            )
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO crm_activity_events "
                    "(workspace_id, deal_id, company_id, category, event_type, actor_name, "
                    "summary, details, dedupe_key, occurred_at) VALUES "
                    "('default', 'activity-deal', 'activity-company', 'observation', "
                    "'invalid.subject', 'Ana', 'Nota', '{}'::jsonb, 'two-subjects', now())"
                )
            )
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO crm_activity_events "
                    "(workspace_id, company_id, category, event_type, actor_name, summary, "
                    "details, dedupe_key, occurred_at) VALUES "
                    "('default', 'activity-company', 'observation', 'company.observation', "
                    "'Ana', 'Duplicada', '{}'::jsonb, "
                    "'legacy-company-created:activity-company', now())"
                )
            )


def test_activity_downgrade_removes_only_feature_schema(pipeline_database) -> None:
    connection, schema, config = pipeline_database
    seed_activity_backfill_data(connection)
    before = {
        table_name: table_fingerprint(connection, table_name)
        for table_name in ("companies", "deals", "deal_stage_history")
    }
    command.upgrade(config, TENANT_HEAD)

    command.downgrade(config, PIPELINE_HEAD)

    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PIPELINE_HEAD
    assert "crm_activity_events" not in inspect(connection).get_table_names(schema=schema)
    assert {
        table_name: table_fingerprint(connection, table_name)
        for table_name in before
    } == before
    assert "deal_pipelines" in inspect(connection).get_table_names(schema=schema)
