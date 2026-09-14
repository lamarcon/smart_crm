"""add tenant identity and authentication columns

Revision ID: a4c9d2e7f1b6
Revises: 9f7a2c31d5e8
Create Date: 2026-09-14 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a4c9d2e7f1b6"
down_revision: Union[str, Sequence[str], None] = "9f7a2c31d5e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHILD_TABLES = ("lead_assistants", "deal_assistants", "deal_stage_history", "quotes")
TENANT_TABLES = (
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
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF (SELECT count(*) FROM workspaces) <> 1 "
            "OR NOT EXISTS (SELECT 1 FROM workspaces WHERE id = 'default') "
            "THEN RAISE EXCEPTION 'tenant migration requires exactly one default workspace'; "
            "END IF; END $$"
        )
    )
    op.create_table(
        "tenant_identity",
        sa.Column("singleton_key", sa.String(length=16), nullable=False),
        sa.Column("control_tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("schema_contract", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "singleton_key = 'identity'",
            name=op.f("ck_tenant_identity_singleton_key_identity"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_tenant_identity_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("singleton_key", name=op.f("pk_tenant_identity")),
        sa.UniqueConstraint("control_tenant_id", name=op.f("uq_tenant_identity_control_tenant_id")),
    )
    op.add_column("crm_users", sa.Column("normalized_email", sa.String(length=320), nullable=True))
    op.add_column("crm_users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "crm_users",
        sa.Column("auth_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "crm_users",
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_crm_users_auth_version_nonnegative"),
        "crm_users",
        "auth_version >= 0",
    )
    op.create_unique_constraint(
        op.f("uq_crm_users_workspace_id_normalized_email"),
        "crm_users",
        ["workspace_id", "normalized_email"],
    )

    for table_name in CHILD_TABLES:
        op.add_column(table_name, sa.Column("workspace_id", sa.String(length=64), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table_name}_workspace_id_workspaces"),
            table_name,
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    backfills = {
        "lead_assistants": ("leads", "lead_id"),
        "deal_assistants": ("deals", "deal_id"),
        "deal_stage_history": ("deals", "deal_id"),
        "quotes": ("deals", "deal_id"),
    }
    for table_name, (parent_table, parent_key) in backfills.items():
        op.execute(
            sa.text(
                f'UPDATE "{table_name}" AS child '
                f'SET workspace_id = parent.workspace_id FROM "{parent_table}" AS parent '
                f'WHERE child."{parent_key}" = parent.id AND child.workspace_id IS NULL'
            )
        )
        op.execute(
            sa.text(
                f"DO $$ BEGIN IF EXISTS "
                f'(SELECT 1 FROM "{table_name}" WHERE workspace_id IS NULL) '
                f"THEN RAISE EXCEPTION 'workspace backfill failed for {table_name}'; "
                "END IF; END $$"
            )
        )
        op.alter_column(table_name, "workspace_id", existing_type=sa.String(length=64), nullable=False)

    for table_name in TENANT_TABLES:
        scope_column = "id" if table_name == "workspaces" else "workspace_id"
        predicate = (
            f"{scope_column} = "
            "current_setting('smartcrm.workspace_id', true)"
        )
        op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE POLICY smartcrm_workspace_scope ON "{table_name}" '
                f"FOR ALL USING ({predicate}) WITH CHECK ({predicate})"
            )
        )


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.execute(sa.text(f'DROP POLICY smartcrm_workspace_scope ON "{table_name}"'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY'))

    for table_name in reversed(CHILD_TABLES):
        op.drop_constraint(
            op.f(f"fk_{table_name}_workspace_id_workspaces"),
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "workspace_id")

    op.drop_constraint(
        op.f("uq_crm_users_workspace_id_normalized_email"),
        "crm_users",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_crm_users_auth_version_nonnegative"),
        "crm_users",
        type_="check",
    )
    op.drop_column("crm_users", "auth_version")
    op.drop_column("crm_users", "auth_enabled")
    op.drop_column("crm_users", "password_hash")
    op.drop_column("crm_users", "normalized_email")
    op.drop_table("tenant_identity")
