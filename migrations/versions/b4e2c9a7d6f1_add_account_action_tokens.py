"""add account action tokens

Revision ID: b4e2c9a7d6f1
Revises: a8d4e6f2b1c9
Create Date: 2026-10-30 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b4e2c9a7d6f1"
down_revision: Union[str, Sequence[str], None] = "a8d4e6f2b1c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_action_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_digest", sa.CHAR(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "delivery_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("delivery_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_failure_code", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('invitation', 'password_reset')",
            name=op.f("ck_account_action_tokens_valid_purpose"),
        ),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed')",
            name=op.f("ck_account_action_tokens_valid_delivery_status"),
        ),
        sa.CheckConstraint(
            "char_length(token_digest) = 64",
            name=op.f("ck_account_action_tokens_digest_length"),
        ),
        sa.CheckConstraint(
            "NOT (consumed_at IS NOT NULL AND invalidated_at IS NOT NULL)",
            name=op.f("ck_account_action_tokens_single_terminal_state"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_account_action_tokens_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["crm_users.id"],
            name=op.f("fk_account_action_tokens_user_id_crm_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["crm_users.id"],
            name=op.f("fk_account_action_tokens_created_by_user_id_crm_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_action_tokens")),
        sa.UniqueConstraint(
            "token_digest",
            name=op.f("uq_account_action_tokens_token_digest"),
        ),
    )
    op.create_index(
        "ix_account_action_tokens_user_purpose_created",
        "account_action_tokens",
        ["workspace_id", "user_id", "purpose", sa.text("created_at DESC")],
        unique=False,
    )
    op.execute(sa.text('ALTER TABLE "account_action_tokens" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "account_action_tokens" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY smartcrm_workspace_scope ON "account_action_tokens" FOR ALL '
            "USING (workspace_id = current_setting('smartcrm.workspace_id', true)) "
            "WITH CHECK (workspace_id = current_setting('smartcrm.workspace_id', true))"
        )
    )


def downgrade() -> None:
    op.execute(sa.text('DROP POLICY smartcrm_workspace_scope ON "account_action_tokens"'))
    op.execute(sa.text('ALTER TABLE "account_action_tokens" NO FORCE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "account_action_tokens" DISABLE ROW LEVEL SECURITY'))
    op.drop_table("account_action_tokens")
