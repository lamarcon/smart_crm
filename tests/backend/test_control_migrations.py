from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.control_models import ControlBase


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
CONTROL_HEAD = "c01a5d8e4f20"


def control_config(connection=None) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic-control.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


@pytest.fixture
def isolated_control_migration():
    engine = create_engine(TEST_DATABASE_URL)
    schema = f"control_migration_{uuid.uuid4().hex}"
    with engine.begin() as setup:
        setup.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    try:
        yield connection, schema, control_config(connection)
    finally:
        connection.close()
        with engine.begin() as cleanup:
            cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_control_upgrade_reaches_its_own_head(isolated_control_migration) -> None:
    connection, schema, config = isolated_control_migration

    command.upgrade(config, "head")

    assert set(inspect(connection).get_table_names(schema=schema)) == {
        *ControlBase.metadata.tables,
        "alembic_control_version",
    }
    assert connection.scalar(text("SELECT version_num FROM alembic_control_version")) == CONTROL_HEAD


def test_control_migration_creates_named_constraints(isolated_control_migration) -> None:
    connection, schema, config = isolated_control_migration
    command.upgrade(config, "head")
    database_inspector = inspect(connection)

    tenant_checks = database_inspector.get_check_constraints("control_tenants", schema=schema)
    tenant_uniques = database_inspector.get_unique_constraints("control_tenants", schema=schema)

    assert {item["name"] for item in tenant_checks} == {
        "ck_control_tenants_profile_version_positive",
        "ck_control_tenants_valid_status",
    }
    assert {item["name"] for item in tenant_uniques} == {"uq_control_tenants_slug"}


def test_control_upgrade_is_idempotent(isolated_control_migration) -> None:
    connection, _schema, config = isolated_control_migration

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    assert connection.scalar(text("SELECT count(*) FROM alembic_control_version")) == 1


def test_control_downgrade_removes_only_control_lineage(isolated_control_migration) -> None:
    connection, schema, config = isolated_control_migration
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    # Alembic intentionally keeps its empty bookkeeping table at base.
    assert set(inspect(connection).get_table_names(schema=schema)) == {"alembic_control_version"}


def test_control_and_business_lineages_are_separate(isolated_control_migration) -> None:
    connection, schema, control = isolated_control_migration
    business = Config(str(ROOT / "alembic.ini"))

    command.upgrade(control, "head")

    assert Path(control.get_main_option("script_location")).name == "migrations_control"
    assert Path(business.get_main_option("script_location")).name == "migrations"
    assert set(ControlBase.metadata.tables).isdisjoint({"workspaces", "crm_users", "leads", "deals"})
    assert {"workspaces", "crm_users", "leads", "deals"}.isdisjoint(
        inspect(connection).get_table_names(schema=schema)
    )
