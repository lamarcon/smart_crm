from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql.sqltypes import DateTime, Numeric

from app.models import Base, CrmActivityEvent


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
    "deal_pipelines",
    "deal_pipeline_stages",
    "deal_pipeline_audit_events",
    "crm_activity_events",
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


def test_pipeline_tables_express_stable_tenant_scoped_identity() -> None:
    pipeline = Base.metadata.tables["deal_pipelines"]
    stage = Base.metadata.tables["deal_pipeline_stages"]
    audit = Base.metadata.tables["deal_pipeline_audit_events"]

    assert isinstance(pipeline.c.id.type, UUID)
    assert pipeline.c.workspace_id.nullable is False
    assert isinstance(stage.c.id.type, UUID)
    assert stage.c.workspace_id.nullable is False
    assert stage.c.pipeline_id.nullable is False
    assert audit.c.workspace_id.nullable is False
    assert audit.c.pipeline_id.nullable is False
    assert audit.c.actor_user_id.nullable is False


def test_pipeline_stage_constraints_preserve_semantics_and_active_uniqueness() -> None:
    table = Base.metadata.tables["deal_pipeline_stages"]
    checks = " ".join(
        str(item.sqltext) for item in table.constraints if isinstance(item, CheckConstraint)
    )
    indexes = {index.name: index for index in table.indexes}

    assert "semantic_type IN ('open', 'won', 'lost')" in checks
    assert "^#[0-9A-Fa-f]{6}$" in checks
    assert "position >= 0" in checks
    assert indexes["uq_deal_pipeline_stages_active_name"].unique is True
    assert indexes["uq_deal_pipeline_stages_active_position"].unique is True
    assert indexes["uq_deal_pipeline_stages_system_key"].unique is True


def test_deals_and_history_reference_stable_stage_ids_without_removing_names() -> None:
    deal = Base.metadata.tables["deals"]
    history = Base.metadata.tables["deal_stage_history"]

    assert isinstance(deal.c.pipeline_id.type, UUID)
    assert isinstance(deal.c.stage_id.type, UUID)
    assert deal.c.pipeline_id.nullable is False
    assert deal.c.stage_id.nullable is False
    assert deal.c.stage.nullable is False
    assert isinstance(history.c.from_stage_id.type, UUID)
    assert history.c.from_stage_id.nullable is True
    assert isinstance(history.c.to_stage_id.type, UUID)
    assert history.c.to_stage_id.nullable is False
    assert history.c.from_stage.nullable is True
    assert history.c.to_stage.nullable is False


def test_activity_events_define_typed_append_only_payload() -> None:
    table = Base.metadata.tables["crm_activity_events"]

    assert isinstance(table.c.id.type, BigInteger)
    assert table.c.workspace_id.nullable is False
    assert table.c.deal_id.nullable is True
    assert table.c.company_id.nullable is True
    assert table.c.actor_user_id.nullable is True
    assert table.c.actor_name.nullable is False
    assert isinstance(table.c.details.type, JSONB)
    assert table.c.details.nullable is False
    assert isinstance(table.c.occurred_at.type, DateTime)
    assert table.c.occurred_at.type.timezone is True
    assert "deleted_at" not in table.c
    assert "updated_at" not in table.c
    assert not hasattr(CrmActivityEvent, "update")
    assert not hasattr(CrmActivityEvent, "delete")


def test_activity_events_enforce_subject_category_type_and_dedupe_constraints() -> None:
    table = Base.metadata.tables["crm_activity_events"]
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    foreign_targets = {
        element.target_fullname
        for constraint in table.foreign_key_constraints
        for element in constraint.elements
    }

    subject_check = checks["ck_crm_activity_events_exactly_one_subject"]
    assert "deal_id IS NOT NULL AND company_id IS NULL" in subject_check
    assert "deal_id IS NULL AND company_id IS NOT NULL" in subject_check
    assert "category IN ('movement', 'automation', 'observation', 'change')" in checks[
        "ck_crm_activity_events_valid_category"
    ]
    assert "length(btrim(event_type)) > 0" in checks[
        "ck_crm_activity_events_event_type_nonempty"
    ]
    assert ("workspace_id", "dedupe_key") in unique_columns
    assert {
        "workspaces.id",
        "deals.id",
        "companies.id",
        "crm_users.id",
    }.issubset(foreign_targets)


def test_activity_events_have_descending_partial_subject_indexes() -> None:
    table = Base.metadata.tables["crm_activity_events"]
    indexes = {index.name: index for index in table.indexes}

    deal_index = indexes["ix_crm_activity_events_deal_timeline"]
    company_index = indexes["ix_crm_activity_events_company_timeline"]

    assert [str(expression) for expression in deal_index.expressions] == [
        "crm_activity_events.workspace_id",
        "crm_activity_events.deal_id",
        "crm_activity_events.occurred_at DESC",
        "crm_activity_events.id DESC",
    ]
    assert str(deal_index.dialect_options["postgresql"]["where"]) == "deal_id IS NOT NULL"
    assert [str(expression) for expression in company_index.expressions] == [
        "crm_activity_events.workspace_id",
        "crm_activity_events.company_id",
        "crm_activity_events.occurred_at DESC",
        "crm_activity_events.id DESC",
    ]
    assert str(company_index.dialect_options["postgresql"]["where"]) == "company_id IS NOT NULL"
