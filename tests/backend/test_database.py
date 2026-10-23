from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.database import Database, DatabaseSettings


TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)


def test_settings_read_database_url_without_exposing_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMART_CRM_DATABASE_URL", TEST_DATABASE_URL)

    settings = DatabaseSettings.from_env()

    assert settings.database_url == TEST_DATABASE_URL
    assert "smartcrm_local_dev" not in repr(settings)


def test_database_check_succeeds_against_postgres() -> None:
    database = Database(DatabaseSettings(database_url=TEST_DATABASE_URL))

    assert database.check_database() is True

    database.dispose()


def test_database_check_returns_false_when_postgres_is_unavailable() -> None:
    unavailable = Database(
        DatabaseSettings(
            database_url=(
                "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:1/"
                "smartcrm_test?connect_timeout=1"
            )
        )
    )

    assert unavailable.check_database() is False

    unavailable.dispose()


def test_session_scope_rolls_back_and_closes_on_exception(
    technical_probe_table: None,
) -> None:
    database = Database(DatabaseSettings(database_url=TEST_DATABASE_URL))
    probe_id = 2_000_000_000

    with pytest.raises(RuntimeError, match="force rollback"):
        with database.session_scope() as session:
            session.execute(
                text(
                    "INSERT INTO _smartcrm_test_probe (id) VALUES (:probe_id) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"probe_id": probe_id},
            )
            raise RuntimeError("force rollback")

    with database.session_scope() as session:
        stored = session.scalar(
            text("SELECT count(*) FROM _smartcrm_test_probe WHERE id = :probe_id"),
            {"probe_id": probe_id},
        )
        assert stored == 0

    assert database.open_session_count == 0
    database.dispose()
