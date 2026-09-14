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


def upgrade() -> None:
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


def downgrade() -> None:
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
