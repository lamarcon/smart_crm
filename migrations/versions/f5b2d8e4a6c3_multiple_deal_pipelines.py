"""several deal pipelines per company

Revision ID: f5b2d8e4a6c3
Revises: e1a7c3f9b2d4
Create Date: 2026-11-18 14:00:00.000000

Pipelines get an order (``position``) and can be archived (``archived_at``); the
default pipeline can never be archived. The stage-sync triggers used to find a
deal's stage by its name across the whole company, which breaks as soon as two
pipelines share a stage name ("Ganho"): they now keep the stage ids the
application sends and, for legacy rows that only carry a name, look inside the
deal's own pipeline (or the default one).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5b2d8e4a6c3"
down_revision: Union[str, Sequence[str], None] = "e1a7c3f9b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEAL_TRIGGER = (
    "CREATE OR REPLACE FUNCTION smartcrm_sync_deal_stage_ids() RETURNS trigger LANGUAGE plpgsql AS $$ "
    "DECLARE matched_pipeline uuid; matched_stage uuid; BEGIN "
    # Ids sent by the application win; the composite FK checks they belong together.
    "IF NEW.stage_id IS NOT NULL AND NEW.pipeline_id IS NOT NULL THEN RETURN NEW; END IF; "
    "SELECT s.pipeline_id, s.id INTO matched_pipeline, matched_stage "
    "FROM deal_pipeline_stages s JOIN deal_pipelines p "
    "ON p.workspace_id = s.workspace_id AND p.id = s.pipeline_id "
    "WHERE s.workspace_id = NEW.workspace_id AND s.name = NEW.stage AND s.archived_at IS NULL "
    "AND (NEW.pipeline_id IS NULL OR s.pipeline_id = NEW.pipeline_id) "
    "ORDER BY p.is_default DESC, p.position, s.position LIMIT 1; "
    "IF matched_stage IS NULL THEN RAISE EXCEPTION 'unknown or archived deal stage: %', NEW.stage; END IF; "
    "NEW.pipeline_id := matched_pipeline; NEW.stage_id := matched_stage; RETURN NEW; END $$"
)

_HISTORY_TRIGGER = (
    "CREATE OR REPLACE FUNCTION smartcrm_sync_deal_history_stage_ids() RETURNS trigger LANGUAGE plpgsql AS $$ "
    "DECLARE deal_pipeline uuid; BEGIN "
    "SELECT pipeline_id INTO deal_pipeline FROM deals "
    "WHERE workspace_id = NEW.workspace_id AND id = NEW.deal_id; "
    "IF NEW.to_stage_id IS NULL THEN "
    "SELECT s.id INTO NEW.to_stage_id FROM deal_pipeline_stages s JOIN deal_pipelines p "
    "ON p.workspace_id = s.workspace_id AND p.id = s.pipeline_id "
    "WHERE s.workspace_id = NEW.workspace_id AND s.name = NEW.to_stage "
    "ORDER BY (s.pipeline_id = deal_pipeline) DESC NULLS LAST, p.is_default DESC, s.position LIMIT 1; END IF; "
    "IF NEW.to_stage_id IS NULL THEN RAISE EXCEPTION 'unknown deal history destination: %', NEW.to_stage; END IF; "
    "IF NEW.from_stage IS NULL THEN NEW.from_stage_id := NULL; "
    "ELSIF NEW.from_stage_id IS NULL THEN "
    "SELECT s.id INTO NEW.from_stage_id FROM deal_pipeline_stages s JOIN deal_pipelines p "
    "ON p.workspace_id = s.workspace_id AND p.id = s.pipeline_id "
    "WHERE s.workspace_id = NEW.workspace_id AND s.name = NEW.from_stage "
    "ORDER BY (s.pipeline_id = deal_pipeline) DESC NULLS LAST, p.is_default DESC, s.position LIMIT 1; END IF; "
    "RETURN NEW; END $$"
)

_OLD_DEAL_TRIGGER = (
    "CREATE OR REPLACE FUNCTION smartcrm_sync_deal_stage_ids() RETURNS trigger LANGUAGE plpgsql AS $$ "
    "DECLARE matched_pipeline uuid; matched_stage uuid; BEGIN "
    "SELECT pipeline_id, id INTO matched_pipeline, matched_stage "
    "FROM deal_pipeline_stages WHERE workspace_id = NEW.workspace_id "
    "AND name = NEW.stage AND archived_at IS NULL; "
    "IF matched_stage IS NULL THEN RAISE EXCEPTION 'unknown or archived deal stage: %', NEW.stage; END IF; "
    "NEW.pipeline_id := matched_pipeline; NEW.stage_id := matched_stage; RETURN NEW; END $$"
)

_OLD_HISTORY_TRIGGER = (
    "CREATE OR REPLACE FUNCTION smartcrm_sync_deal_history_stage_ids() RETURNS trigger LANGUAGE plpgsql AS $$ "
    "BEGIN "
    "SELECT id INTO NEW.to_stage_id FROM deal_pipeline_stages "
    "WHERE workspace_id = NEW.workspace_id AND name = NEW.to_stage; "
    "IF NEW.to_stage_id IS NULL THEN RAISE EXCEPTION 'unknown deal history destination: %', NEW.to_stage; END IF; "
    "IF NEW.from_stage IS NULL THEN NEW.from_stage_id := NULL; ELSE "
    "SELECT id INTO NEW.from_stage_id FROM deal_pipeline_stages "
    "WHERE workspace_id = NEW.workspace_id AND name = NEW.from_stage; END IF; "
    "RETURN NEW; END $$"
)


def upgrade() -> None:
    op.add_column("deal_pipelines", sa.Column("position", sa.Integer(), server_default="0", nullable=False))
    op.add_column("deal_pipelines", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_deal_pipelines_default_not_archived"),
        "deal_pipelines",
        "NOT (is_default AND archived_at IS NOT NULL)",
    )
    # A new pipeline and its initial stage point at each other: check the pair at commit.
    op.drop_constraint("fk_deal_pipelines_default_stage", "deal_pipelines", type_="foreignkey")
    op.create_foreign_key(
        "fk_deal_pipelines_default_stage",
        "deal_pipelines",
        "deal_pipeline_stages",
        ["workspace_id", "default_stage_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.execute(sa.text(_DEAL_TRIGGER))
    op.execute(sa.text(_HISTORY_TRIGGER))


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT workspace_id FROM tenant_identity WHERE singleton_key = 'identity'")
    ).scalars().all()
    for workspace_id in [str(row) for row in rows if row] or ["default"]:
        connection.execute(sa.text("SELECT set_config('smartcrm.workspace_id', :w, true)"), {"w": workspace_id})
        extra = connection.scalar(
            sa.text(
                "SELECT count(*) FROM deals d JOIN deal_pipelines p "
                "ON p.workspace_id = d.workspace_id AND p.id = d.pipeline_id "
                "WHERE d.workspace_id = :w AND NOT p.is_default"
            ),
            {"w": workspace_id},
        )
        if extra:
            raise RuntimeError("deals live in more than one pipeline; move them to the default pipeline first")
    op.execute(sa.text(_OLD_HISTORY_TRIGGER))
    op.execute(sa.text(_OLD_DEAL_TRIGGER))
    op.drop_constraint("fk_deal_pipelines_default_stage", "deal_pipelines", type_="foreignkey")
    op.create_foreign_key(
        "fk_deal_pipelines_default_stage",
        "deal_pipelines",
        "deal_pipeline_stages",
        ["workspace_id", "default_stage_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(op.f("ck_deal_pipelines_default_not_archived"), "deal_pipelines", type_="check")
    op.drop_column("deal_pipelines", "archived_at")
    op.drop_column("deal_pipelines", "position")
