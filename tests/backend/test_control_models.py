from __future__ import annotations

import os
from uuid import uuid4

from sqlalchemy import CheckConstraint, PrimaryKeyConstraint, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.schema import ForeignKeyConstraint

from app.control_models import ControlBase


TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)

EXPECTED_TABLES = {
    "control_tenants",
    "auth_sessions",
    "login_throttles",
    "security_events",
}


def test_control_metadata_contains_only_control_plane_tables() -> None:
    assert set(ControlBase.metadata.tables) == EXPECTED_TABLES


def test_tenant_directory_uses_uuid_and_unique_slug() -> None:
    table = ControlBase.metadata.tables["control_tenants"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert isinstance(table.c.id.type, UUID)
    assert ("slug",) in unique_columns


def test_tenant_states_are_closed_to_the_designed_values() -> None:
    table = ControlBase.metadata.tables["control_tenants"]
    checks = " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )

    assert all(state in checks for state in ("provisioning", "active", "inactive", "failed"))


def test_tenant_directory_keeps_only_an_opaque_secret_reference() -> None:
    columns = set(ControlBase.metadata.tables["control_tenants"].c.keys())

    assert "secret_ref" in columns
    assert columns.isdisjoint({"dsn", "database_url", "database_password", "connection_secret"})


def test_sessions_store_digest_and_linkage_without_raw_credentials() -> None:
    columns = set(ControlBase.metadata.tables["auth_sessions"].c.keys())

    assert {"token_digest", "tenant_id", "user_id", "auth_version"}.issubset(columns)
    assert columns.isdisjoint({"token", "raw_token", "password", "password_hash", "role"})


def test_session_indexes_cover_expiry_and_user_revocation() -> None:
    index_columns = {
        index.name: tuple(column.name for column in index.columns)
        for index in ControlBase.metadata.tables["auth_sessions"].indexes
    }

    assert index_columns["ix_auth_sessions_active_expiry"] == ("revoked_at", "idle_expires_at")
    assert index_columns["ix_auth_sessions_tenant_user"] == ("tenant_id", "user_id")


def test_throttle_identity_is_a_composite_primary_key() -> None:
    table = ControlBase.metadata.tables["login_throttles"]
    primary_key = next(
        constraint for constraint in table.constraints if isinstance(constraint, PrimaryKeyConstraint)
    )

    assert tuple(column.name for column in primary_key.columns) == ("bucket_type", "subject_digest")


def test_throttle_bucket_types_and_nonnegative_count_are_constrained() -> None:
    checks = " ".join(
        str(constraint.sqltext)
        for constraint in ControlBase.metadata.tables["login_throttles"].constraints
        if isinstance(constraint, CheckConstraint)
    )

    assert "account" in checks and "ip" in checks
    assert "failure_count >= 0" in checks


def test_security_events_are_redacted_by_construction() -> None:
    columns = set(ControlBase.metadata.tables["security_events"].c.keys())

    assert {"id", "event_type", "tenant_id", "user_id", "correlation_digest", "outcome_code"}.issubset(columns)
    assert columns.isdisjoint({"password", "password_hash", "token", "dsn", "payload", "snapshot"})


def test_all_control_constraints_are_named() -> None:
    relevant = (PrimaryKeyConstraint, ForeignKeyConstraint, UniqueConstraint, CheckConstraint)
    constraints = [
        constraint
        for table in ControlBase.metadata.sorted_tables
        for constraint in table.constraints
        if isinstance(constraint, relevant)
    ]

    assert constraints
    assert all(constraint.name for constraint in constraints)


def test_control_metadata_creates_on_postgresql_without_business_tables() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    schema = f"control_model_{uuid4().hex}"
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            scoped = connection.execution_options(schema_translate_map={None: schema})
            ControlBase.metadata.create_all(scoped)

        database_inspector = inspect(engine)
        assert set(database_inspector.get_table_names(schema=schema)) == EXPECTED_TABLES
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
