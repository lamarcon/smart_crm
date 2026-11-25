"""pipelines as menu tabs and custom fields scoped to a pipeline

Revision ID: b8d2f4a6c9e1
Revises: f5b2d8e4a6c3
Create Date: 2026-11-25 10:00:00.000000

A pipeline can be shown as its own tab in the side menu (``menu_tab``) with an
icon (``menu_icon``); the default pipeline always stays under "Negócios".
A deal custom field can belong to one pipeline (``pipeline_id``): it then only
shows on the deals of that pipeline. Fields of other modules never carry one.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8d2f4a6c9e1"
down_revision: Union[str, Sequence[str], None] = "f5b2d8e4a6c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deal_pipelines",
        sa.Column("menu_tab", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("deal_pipelines", sa.Column("menu_icon", sa.String(length=8), nullable=True))
    op.create_check_constraint(
        op.f("ck_deal_pipelines_default_not_menu_tab"),
        "deal_pipelines",
        "NOT (is_default AND menu_tab)",
    )
    op.add_column(
        "custom_field_definitions",
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_custom_field_definitions_pipeline",
        "custom_field_definitions",
        "deal_pipelines",
        ["workspace_id", "pipeline_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_custom_field_definitions_pipeline_only_deals"),
        "custom_field_definitions",
        "pipeline_id IS NULL OR module = 'deals'",
    )


def downgrade() -> None:
    bind = op.get_bind()
    scoped = bind.execute(
        sa.text("SELECT count(*) FROM custom_field_definitions WHERE pipeline_id IS NOT NULL AND deleted_at IS NULL")
    ).scalar_one()
    products = bind.execute(
        sa.text("SELECT count(*) FROM custom_field_definitions WHERE module = 'products' AND deleted_at IS NULL")
    ).scalar_one()
    if scoped or products:
        raise RuntimeError(
            "downgrade refused: custom fields scoped to a pipeline or on products exist; "
            "the previous release cannot show them"
        )
    op.drop_constraint(op.f("ck_custom_field_definitions_pipeline_only_deals"), "custom_field_definitions", type_="check")
    op.drop_constraint("fk_custom_field_definitions_pipeline", "custom_field_definitions", type_="foreignkey")
    op.drop_column("custom_field_definitions", "pipeline_id")
    op.drop_constraint(op.f("ck_deal_pipelines_default_not_menu_tab"), "deal_pipelines", type_="check")
    op.drop_column("deal_pipelines", "menu_icon")
    op.drop_column("deal_pipelines", "menu_tab")
