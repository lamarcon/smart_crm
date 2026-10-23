from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text


TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)


@pytest.fixture
def technical_probe_table() -> None:
    """Provide the migration-preservation probe without relying on prior test runs."""

    engine = create_engine(TEST_DATABASE_URL)
    probe_id = 1
    with engine.begin() as connection:
        table_existed = bool(
            connection.scalar(text("SELECT to_regclass('_smartcrm_test_probe') IS NOT NULL"))
        )
        if not table_existed:
            connection.execute(
                text("CREATE TABLE _smartcrm_test_probe (id integer PRIMARY KEY)")
            )
        row_existed = bool(
            connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM _smartcrm_test_probe WHERE id = :id)"),
                {"id": probe_id},
            )
        )
        if not row_existed:
            connection.execute(
                text("INSERT INTO _smartcrm_test_probe (id) VALUES (:id)"),
                {"id": probe_id},
            )

    try:
        yield
    finally:
        with engine.begin() as connection:
            if not table_existed:
                connection.execute(text("DROP TABLE IF EXISTS _smartcrm_test_probe"))
            elif not row_existed:
                connection.execute(
                    text("DELETE FROM _smartcrm_test_probe WHERE id = :id"),
                    {"id": probe_id},
                )
        engine.dispose()
