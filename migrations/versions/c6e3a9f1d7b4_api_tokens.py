"""add personal API tokens

Revision ID: c6e3a9f1d7b4
Revises: b8d2f4a6c9e1
Create Date: 2026-11-25 18:00:00.000000

* ``api_tokens``: personal tokens for the REST API v1. Each token belongs to one
  user and acts with that user's current profile (role, team and permissions);
  ``access`` is ``read`` (GET only) or ``write``. Only a sha256 digest and the
  last four characters are stored. The table carries the tenant row-level
  security of the other tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c6e3a9f1d7b4"
down_revision: Union[str, Sequence[str], None] = "b8d2f4a6c9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("access", sa.String(length=8), nullable=False),
        sa.Column("token_digest", sa.CHAR(length=64), nullable=False),
        sa.Column("token_hint", sa.String(length=8), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(token_digest) = 64", name=op.f("ck_api_tokens_digest_length")),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name=op.f("ck_api_tokens_name_present")),
        sa.CheckConstraint("access IN ('read', 'write')", name=op.f("ck_api_tokens_valid_access")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name=op.f("fk_api_tokens_workspace_id_workspaces"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["crm_users.id"],
            name=op.f("fk_api_tokens_user_id_crm_users"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["crm_users.id"],
            name=op.f("fk_api_tokens_revoked_by_user_id_crm_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_api_tokens_token_digest")),
    )
    op.create_index("ix_api_tokens_workspace_user", "api_tokens", ["workspace_id", "user_id"], unique=False)
    op.execute(sa.text('ALTER TABLE "api_tokens" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "api_tokens" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY smartcrm_workspace_scope ON "api_tokens" FOR ALL '
            "USING (workspace_id = current_setting('smartcrm.workspace_id', true)) "
            "WITH CHECK (workspace_id = current_setting('smartcrm.workspace_id', true))"
        )
    )


def downgrade() -> None:
    op.execute(sa.text('DROP POLICY smartcrm_workspace_scope ON "api_tokens"'))
    op.execute(sa.text('ALTER TABLE "api_tokens" NO FORCE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "api_tokens" DISABLE ROW LEVEL SECURITY'))
    op.drop_index("ix_api_tokens_workspace_user", table_name="api_tokens")
    op.drop_table("api_tokens")
