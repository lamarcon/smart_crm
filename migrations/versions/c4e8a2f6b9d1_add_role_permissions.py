"""configurable permissions per role, module and action

Revision ID: c4e8a2f6b9d1
Revises: f2b8d4a6c1e9
Create Date: 2026-11-17 10:00:00.000000

``role_permissions`` keeps the cells an administrator changed in the
permission matrix. A missing cell means the default the CRM always had, so
existing workspaces need no data.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a2f6b9d1"
down_revision: Union[str, Sequence[str], None] = "f2b8d4a6c1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "role_permissions",
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("module", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "role IN ('Gestor', 'Vendedor', 'Assistente', 'Faturamento')",
            name=op.f("ck_role_permissions_valid_role"),
        ),
        sa.CheckConstraint(
            "module IN ('leads', 'contacts', 'companies', 'deals', 'products')",
            name=op.f("ck_role_permissions_valid_module"),
        ),
        sa.CheckConstraint(
            "action IN ('read', 'create', 'update', 'delete', 'import', 'export')",
            name=op.f("ck_role_permissions_valid_action"),
        ),
        sa.CheckConstraint(
            "scope IN ('none', 'own', 'team', 'all')",
            name=op.f("ck_role_permissions_valid_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name=op.f("fk_role_permissions_workspace_id_workspaces"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "role", "module", "action", name=op.f("pk_role_permissions")),
    )
    op.execute(sa.text('ALTER TABLE "role_permissions" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY smartcrm_workspace_scope ON "role_permissions" FOR ALL '
            "USING (workspace_id = current_setting('smartcrm.workspace_id', true)) "
            "WITH CHECK (workspace_id = current_setting('smartcrm.workspace_id', true))"
        )
    )


def downgrade() -> None:
    op.execute(sa.text('DROP POLICY smartcrm_workspace_scope ON "role_permissions"'))
    op.execute(sa.text('ALTER TABLE "role_permissions" NO FORCE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "role_permissions" DISABLE ROW LEVEL SECURITY'))
    op.drop_table("role_permissions")
