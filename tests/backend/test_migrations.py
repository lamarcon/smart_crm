from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.models import Base


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)


def alembic_config(connection=None) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


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
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "be40ea4d21ad"


def test_repeated_upgrade_is_idempotent(isolated_migration) -> None:
    connection, _schema, config = isolated_migration
    command.upgrade(config, "head")

    command.upgrade(config, "head")

    assert connection.scalar(text("SELECT count(*) FROM workspaces")) == 1
    assert connection.scalar(text("SELECT version FROM workspaces WHERE id='default'")) == 0


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


def test_upgrade_current_database_preserves_existing_probe() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        before = connection.scalar(text("SELECT count(*) FROM _smartcrm_test_probe"))

    command.upgrade(alembic_config(), "head")

    with engine.connect() as connection:
        after = connection.scalar(text("SELECT count(*) FROM _smartcrm_test_probe"))
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert after == before == 1
    assert head == "be40ea4d21ad"
    engine.dispose()
