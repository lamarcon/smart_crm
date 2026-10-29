from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/"
    "smartcrm_test?connect_timeout=3",
)
PREVIOUS_HEAD = "f6b1d3a8c2e4"
REPAIR_HEAD = "a8d4e6f2b1c9"
TENANT_ID = uuid.UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")


def _config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def repair_database():  # noqa: ANN201
    engine = create_engine(TEST_DATABASE_URL)
    schema = f"deployment_repair_{uuid.uuid4().hex}"
    with engine.begin() as setup:
        setup.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    connection.execute(text("SET lock_timeout TO '5s'"))
    connection.execute(text("SET statement_timeout TO '30s'"))
    try:
        yield connection, _config(connection)
    finally:
        connection.close()
        with engine.begin() as cleanup:
            cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _prepare_affected_tenant(connection, config: Config) -> None:  # noqa: ANN001
    command.upgrade(config, PREVIOUS_HEAD)
    connection.commit()
    connection.execute(
        text(
            "INSERT INTO tenant_identity "
            "(singleton_key, control_tenant_id, workspace_id, schema_contract) "
            "VALUES ('identity', :tenant_id, 'default', 'tenant-v1')"
        ),
        {"tenant_id": TENANT_ID},
    )
    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
    connection.execute(
        text(
            "INSERT INTO crm_users "
            "(id, workspace_id, name, email, normalized_email, password_hash, "
            "auth_enabled, auth_version, job_title, role, status, payload) "
            "VALUES ('admin-1', 'default', 'Luiz Felipe', 'lfmarcon@brbots.com', "
            "'lfmarcon@brbots.com', '$argon2id$preserve', true, 8, '', "
            "'Administrador', 'Ativo', '{}'::jsonb)"
        )
    )
    connection.commit()
    connection.execute(text("SELECT set_config('smartcrm.workspace_id', '', false)"))
    connection.commit()


def _tenant_state(connection) -> dict:  # noqa: ANN001
    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
    pipeline = connection.execute(
        text(
            "SELECT name, default_stage_id, version, is_default "
            "FROM deal_pipelines WHERE workspace_id='default'"
        )
    ).mappings().one()
    stages = connection.execute(
        text(
            "SELECT name, semantic_type, color, position, system_key "
            "FROM deal_pipeline_stages WHERE workspace_id='default' "
            "AND archived_at IS NULL ORDER BY position"
        )
    ).mappings().all()
    user = connection.execute(
        text(
            "SELECT payload, password_hash, auth_version, role, status "
            "FROM crm_users WHERE id='admin-1'"
        )
    ).mappings().one()
    return {"pipeline": dict(pipeline), "stages": [dict(row) for row in stages], "user": dict(user)}


def test_repair_seeds_pipeline_and_canonical_user_payload_under_force_rls(
    repair_database,
) -> None:  # noqa: ANN001
    connection, config = repair_database
    _prepare_affected_tenant(connection, config)
    forced_tables = connection.scalar(
        text(
            "SELECT count(*) FROM pg_class "
            "WHERE relname IN ('crm_users', 'deal_pipelines', 'deal_pipeline_stages') "
            "AND relnamespace = current_schema()::regnamespace "
            "AND relforcerowsecurity"
        )
    )
    assert forced_tables == 3

    command.upgrade(config, REPAIR_HEAD)

    state = _tenant_state(connection)
    assert state["pipeline"] == {
        "name": "Negócios",
        "default_stage_id": uuid.UUID("1403531f-6ba4-054d-d048-ffcfe8aba536"),
        "version": 1,
        "is_default": True,
    }
    assert len(state["stages"]) == 9
    assert [stage["position"] for stage in state["stages"]] == list(range(9))
    assert [stage["system_key"] for stage in state["stages"]].count("initial") == 1
    assert state["user"]["payload"] == {
        "position": 0,
        "record": {
            "id": "admin-1",
            "name": "Luiz Felipe",
            "email": "lfmarcon@brbots.com",
            "jobTitle": "",
            "role": "Administrador",
            "status": "Ativo",
            "avatar": "LF",
        },
    }
    assert state["user"]["password_hash"] == "$argon2id$preserve"
    assert state["user"]["auth_version"] == 8
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REPAIR_HEAD


def test_repair_retry_preserves_custom_pipeline_and_extra_payload_fields(
    repair_database,
) -> None:  # noqa: ANN001
    connection, config = repair_database
    _prepare_affected_tenant(connection, config)
    command.upgrade(config, REPAIR_HEAD)
    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
    connection.execute(
        text("UPDATE deal_pipelines SET name='Funil BRBots', version=7 WHERE workspace_id='default'")
    )
    connection.execute(
        text(
            "UPDATE deal_pipeline_stages SET name='Primeiro contato', color='#123456' "
            "WHERE workspace_id='default' AND system_key='initial'"
        )
    )
    connection.execute(
        text(
            "UPDATE crm_users SET payload = "
            "jsonb_set(payload || '{\"extraTop\": true}'::jsonb, "
            "'{record}', (payload->'record') || '{\"team\": \"Gestão\"}'::jsonb) "
            "WHERE id='admin-1'"
        )
    )
    connection.commit()

    command.downgrade(config, PREVIOUS_HEAD)
    command.upgrade(config, REPAIR_HEAD)

    state = _tenant_state(connection)
    assert state["pipeline"]["name"] == "Funil BRBots"
    assert state["pipeline"]["version"] == 7
    assert state["stages"][0]["name"] == "Primeiro contato"
    assert state["stages"][0]["color"] == "#123456"
    assert len(state["stages"]) == 9
    assert state["user"]["payload"]["extraTop"] is True
    assert state["user"]["payload"]["record"]["team"] == "Gestão"
    assert state["user"]["payload"]["record"]["name"] == "Luiz Felipe"
    assert state["user"]["password_hash"] == "$argon2id$preserve"
    assert state["user"]["auth_version"] == 8


def test_repair_without_tenant_identity_fails_before_workspace_write(
    repair_database,
) -> None:  # noqa: ANN001
    connection, config = repair_database
    command.upgrade(config, PREVIOUS_HEAD)
    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
    connection.execute(
        text(
            "INSERT INTO crm_users "
            "(id, workspace_id, name, email, normalized_email, password_hash, "
            "auth_enabled, auth_version, job_title, role, status, payload) "
            "VALUES ('orphan-admin', 'default', 'Tenant sem identidade', "
            "'orphan@example.test', 'orphan@example.test', '$argon2id$preserve', "
            "true, 1, '', 'Administrador', 'Ativo', '{}'::jsonb)"
        )
    )
    counts_before = (
        connection.scalar(text("SELECT count(*) FROM deal_pipelines")),
        connection.scalar(text("SELECT count(*) FROM deal_pipeline_stages")),
    )
    connection.commit()

    with pytest.raises(RuntimeError, match="tenant identity is required"):
        command.upgrade(config, REPAIR_HEAD)
    connection.rollback()

    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
    counts_after = (
        connection.scalar(text("SELECT count(*) FROM deal_pipelines")),
        connection.scalar(text("SELECT count(*) FROM deal_pipeline_stages")),
    )
    assert counts_after == counts_before


def test_fresh_unactivated_database_reaches_head_without_repair(
    repair_database,
) -> None:  # noqa: ANN001
    connection, config = repair_database

    command.upgrade(config, REPAIR_HEAD)

    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REPAIR_HEAD
    assert connection.scalar(text("SELECT count(*) FROM tenant_identity")) == 0
