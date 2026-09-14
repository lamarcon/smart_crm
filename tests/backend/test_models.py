from sqlalchemy import CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql.sqltypes import DateTime, Numeric

from app.models import Base


EXPECTED_TABLES = {
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
    "tenant_identity",
}


def test_metadata_contains_every_normalized_table() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_primary_foreign_unique_and_check_constraints_are_named() -> None:
    constraint_types = (
        PrimaryKeyConstraint,
        ForeignKeyConstraint,
        UniqueConstraint,
        CheckConstraint,
    )
    constraints = [
        constraint
        for table in Base.metadata.sorted_tables
        for constraint in table.constraints
        if isinstance(constraint, constraint_types)
    ]

    assert constraints
    assert all(constraint.name for constraint in constraints)


def test_deletable_records_have_soft_delete_column() -> None:
    deletable = {
        "crm_users",
        "leads",
        "contacts",
        "companies",
        "deals",
        "quotes",
        "notifications",
        "custom_field_definitions",
        "saved_filters",
    }

    assert {name for name in deletable if "deleted_at" in Base.metadata.tables[name].c} == deletable


def test_money_and_times_use_lossless_database_types() -> None:
    amount_type = Base.metadata.tables["deals"].c.amount.type
    quote_total_type = Base.metadata.tables["quotes"].c.total.type
    created_type = Base.metadata.tables["deals"].c.created_at.type

    assert isinstance(amount_type, Numeric) and (amount_type.precision, amount_type.scale) == (18, 2)
    assert isinstance(quote_total_type, Numeric) and (quote_total_type.precision, quote_total_type.scale) == (18, 2)
    assert isinstance(created_type, DateTime) and created_type.timezone is True


def test_custom_values_are_jsonb_and_required_query_indexes_exist() -> None:
    custom_value_type = Base.metadata.tables["custom_field_values"].c.value.type
    external_value_type = Base.metadata.tables["external_source_fields"].c.value.type
    index_names = {
        index.name
        for table in Base.metadata.sorted_tables
        for index in table.indexes
    }

    assert isinstance(custom_value_type, JSONB)
    assert isinstance(external_value_type, JSONB)
    assert {
        "ix_leads_workspace_active",
        "ix_deals_workspace_stage",
        "ix_deals_workspace_responsible",
        "ix_custom_values_record",
        "ix_external_fields_record",
    }.issubset(index_names)


def test_user_status_constraint_accepts_every_ui_status() -> None:
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in Base.metadata.tables["crm_users"].constraints
        if isinstance(constraint, CheckConstraint)
    }
    status_constraint = constraints["ck_crm_users_valid_status"]
    assert all(
        f"'{status}'" in status_constraint
        for status in ("Ativo", "Pendente", "Inativo", "Cancelado")
    )


def test_tenant_identity_binds_control_uuid_to_workspace() -> None:
    table = Base.metadata.tables["tenant_identity"]
    checks = " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )

    assert isinstance(table.c.control_tenant_id.type, UUID)
    assert table.c.control_tenant_id.nullable is False
    assert table.c.workspace_id.nullable is False
    assert "singleton_key = 'identity'" in checks


def test_legacy_users_start_without_enabled_credentials() -> None:
    table = Base.metadata.tables["crm_users"]

    assert table.c.normalized_email.nullable is True
    assert table.c.password_hash.nullable is True
    assert table.c.auth_enabled.default.arg is False
    assert table.c.auth_version.default.arg == 0


def test_normalized_email_is_unique_inside_workspace() -> None:
    table = Base.metadata.tables["crm_users"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("workspace_id", "normalized_email") in unique_columns


def test_all_direct_child_tables_carry_required_workspace_scope() -> None:
    child_tables = {
        "lead_assistants",
        "deal_assistants",
        "deal_stage_history",
        "quotes",
    }

    assert {
        name
        for name in child_tables
        if "workspace_id" in Base.metadata.tables[name].c
        and Base.metadata.tables[name].c.workspace_id.nullable is False
    } == child_tables


def test_auth_version_is_nonnegative() -> None:
    checks = " ".join(
        str(item.sqltext) for item in Base.metadata.tables["crm_users"].constraints
        if isinstance(item, CheckConstraint)
    )
    assert "auth_version >= 0" in checks
