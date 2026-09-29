"""add customizable deal pipeline

Revision ID: c7f3a9d8e2b1
Revises: a4c9d2e7f1b6
Create Date: 2026-09-28 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c7f3a9d8e2b1"
down_revision: Union[str, Sequence[str], None] = "a4c9d2e7f1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PIPELINE_TABLES = (
    "deal_pipelines",
    "deal_pipeline_stages",
    "deal_pipeline_audit_events",
)
LEGACY_STAGES = (
    (0, "Em Contato", "open", "#2E90FA", "initial"),
    (1, "Orçamento Proposta Preço", "open", "#2E90FA", None),
    (2, "Orçamentos enviados", "open", "#2E90FA", None),
    (3, "Negociação Revisão", "open", "#7F56D9", None),
    (4, "Pedido aprovado Consultar", "open", "#DC6803", None),
    (5, "Faturando", "open", "#DC6803", "billing"),
    (6, "Ganho", "won", "#039855", None),
    (7, "Orçamento Não Aprovado", "lost", "#D92D20", None),
    (8, "Analisar falha", "lost", "#D92D20", None),
)


def _stage_values_sql() -> str:
    rows = []
    for position, name, semantic_type, color, system_key in LEGACY_STAGES:
        key = "NULL" if system_key is None else f"'{system_key}'"
        rows.append(f"({position}, '{name}', '{semantic_type}', '{color}', {key})")
    return ", ".join(rows)


def upgrade() -> None:
    approved_names = ", ".join(f"'{name}'" for _, name, _, _, _ in LEGACY_STAGES)
    op.execute(
        sa.text(
            "DO $$ DECLARE unknown_stage text; BEGIN "
            "SELECT stage INTO unknown_stage FROM deals "
            f"WHERE stage NOT IN ({approved_names}) LIMIT 1; "
            "IF unknown_stage IS NOT NULL THEN "
            "RAISE EXCEPTION 'unknown legacy deal stage: %', unknown_stage; END IF; "
            "SELECT legacy_stage INTO unknown_stage FROM ("
            "SELECT from_stage AS legacy_stage FROM deal_stage_history WHERE from_stage IS NOT NULL "
            "UNION ALL SELECT to_stage FROM deal_stage_history"
            ") history "
            f"WHERE legacy_stage NOT IN ({approved_names}) LIMIT 1; "
            "IF unknown_stage IS NOT NULL THEN "
            "RAISE EXCEPTION 'unknown legacy deal history stage: %', unknown_stage; END IF; "
            "END $$"
        )
    )

    op.create_table(
        "deal_pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("default_stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_deal_pipelines_version_positive")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name=op.f("fk_deal_pipelines_workspace_id_workspaces"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_pipelines")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_deal_pipelines_workspace_id_id")),
    )
    op.create_index(
        "uq_deal_pipelines_workspace_default",
        "deal_pipelines",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "deal_pipeline_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("semantic_type", sa.String(length=16), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("system_key", sa.String(length=32), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("name = btrim(name) AND name <> ''", name=op.f("ck_deal_pipeline_stages_trimmed_name")),
        sa.CheckConstraint("semantic_type IN ('open', 'won', 'lost')", name=op.f("ck_deal_pipeline_stages_valid_semantic_type")),
        sa.CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name=op.f("ck_deal_pipeline_stages_valid_color")),
        sa.CheckConstraint("position >= 0", name=op.f("ck_deal_pipeline_stages_position_nonnegative")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "pipeline_id"],
            ["deal_pipelines.workspace_id", "deal_pipelines.id"],
            name=op.f("fk_deal_pipeline_stages_workspace_id_pipeline_id_deal_pipelines"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_pipeline_stages")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_deal_pipeline_stages_workspace_id_id")),
        sa.UniqueConstraint("workspace_id", "pipeline_id", "id", name=op.f("uq_deal_pipeline_stages_workspace_id_pipeline_id_id")),
    )
    op.create_index(
        "uq_deal_pipeline_stages_active_name",
        "deal_pipeline_stages",
        ["workspace_id", "pipeline_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "uq_deal_pipeline_stages_active_position",
        "deal_pipeline_stages",
        ["workspace_id", "pipeline_id", "position"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "uq_deal_pipeline_stages_system_key",
        "deal_pipeline_stages",
        ["workspace_id", "system_key"],
        unique=True,
        postgresql_where=sa.text("system_key IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_deal_pipelines_default_stage",
        "deal_pipelines",
        "deal_pipeline_stages",
        ["workspace_id", "default_stage_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "deal_pipeline_audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", sa.String(length=128), nullable=False),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=False),
        sa.Column("after_state", postgresql.JSONB(), nullable=False),
        sa.Column("transfer_summary", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("pipeline_version >= 1", name=op.f("ck_deal_pipeline_audit_events_pipeline_version_positive")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "pipeline_id"],
            ["deal_pipelines.workspace_id", "deal_pipelines.id"],
            name=op.f("fk_deal_pipeline_audit_events_workspace_id_pipeline_id_deal_pipelines"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["crm_users.id"],
            name=op.f("fk_deal_pipeline_audit_events_actor_user_id_crm_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_pipeline_audit_events")),
    )
    op.create_index(
        "ix_deal_pipeline_audit_workspace_cursor",
        "deal_pipeline_audit_events",
        ["workspace_id", "id"],
        unique=False,
    )

    op.execute(
        sa.text(
            "INSERT INTO deal_pipelines (id, workspace_id, name, version, is_default) "
            "SELECT md5('smartcrm:pipeline:' || id)::uuid, id, 'Negócios', 1, true FROM workspaces"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO deal_pipeline_stages "
            "(id, workspace_id, pipeline_id, name, semantic_type, color, position, system_key) "
            "SELECT md5('smartcrm:stage:' || w.id || ':' || seed.name)::uuid, w.id, "
            "md5('smartcrm:pipeline:' || w.id)::uuid, seed.name, seed.semantic_type, "
            "seed.color, seed.position, seed.system_key FROM workspaces w CROSS JOIN "
            f"(VALUES {_stage_values_sql()}) AS seed(position, name, semantic_type, color, system_key)"
        )
    )
    op.execute(
        sa.text(
            "DO $$ DECLARE invalid_workspace text; BEGIN "
            "SELECT w.id INTO invalid_workspace FROM workspaces w "
            "LEFT JOIN deal_pipelines p ON p.workspace_id = w.id AND p.is_default "
            "LEFT JOIN deal_pipeline_stages s ON s.workspace_id = w.id AND s.pipeline_id = p.id "
            "GROUP BY w.id HAVING count(DISTINCT p.id) <> 1 OR count(s.id) <> 9 LIMIT 1; "
            "IF invalid_workspace IS NOT NULL THEN "
            "RAISE EXCEPTION 'invalid pipeline seed count for workspace: %', invalid_workspace; "
            "END IF; END $$"
        )
    )
    op.execute(
        sa.text(
            "UPDATE deal_pipelines p SET default_stage_id = s.id "
            "FROM deal_pipeline_stages s WHERE s.workspace_id = p.workspace_id "
            "AND s.pipeline_id = p.id AND s.system_key = 'initial'"
        )
    )
    op.alter_column("deal_pipelines", "default_stage_id", nullable=False)

    op.add_column("deals", sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("deals", sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("deal_stage_history", sa.Column("from_stage_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("deal_stage_history", sa.Column("to_stage_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        sa.text(
            "UPDATE deals d SET pipeline_id = p.id, stage_id = s.id "
            "FROM deal_pipelines p JOIN deal_pipeline_stages s "
            "ON s.workspace_id = p.workspace_id AND s.pipeline_id = p.id "
            "WHERE d.workspace_id = p.workspace_id AND p.is_default AND d.stage = s.name"
        )
    )
    op.execute(
        sa.text(
            "UPDATE deal_stage_history h SET "
            "from_stage_id = CASE WHEN h.from_stage IS NULL THEN NULL ELSE ("
            "SELECT source.id FROM deal_pipeline_stages source "
            "WHERE source.workspace_id = h.workspace_id AND source.name = h.from_stage) END, "
            "to_stage_id = (SELECT target.id FROM deal_pipeline_stages target "
            "WHERE target.workspace_id = h.workspace_id AND target.name = h.to_stage)"
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM deals WHERE pipeline_id IS NULL OR stage_id IS NULL) "
            "THEN RAISE EXCEPTION 'deal pipeline backfill failed'; END IF; "
            "IF EXISTS (SELECT 1 FROM deal_stage_history WHERE to_stage_id IS NULL "
            "OR (from_stage IS NOT NULL AND from_stage_id IS NULL)) "
            "THEN RAISE EXCEPTION 'deal history stage backfill failed'; END IF; "
            "IF (SELECT count(*) FROM deals) <> ("
            "SELECT count(*) FROM deals d JOIN deal_pipeline_stages s "
            "ON s.workspace_id = d.workspace_id AND s.pipeline_id = d.pipeline_id AND s.id = d.stage_id) "
            "THEN RAISE EXCEPTION 'deal pipeline relationship count mismatch'; END IF; "
            "IF (SELECT count(*) FROM deal_stage_history) <> ("
            "SELECT count(*) FROM deal_stage_history h JOIN deal_pipeline_stages s "
            "ON s.workspace_id = h.workspace_id AND s.id = h.to_stage_id) "
            "THEN RAISE EXCEPTION 'deal history relationship count mismatch'; END IF; "
            "END $$"
        )
    )
    op.alter_column("deals", "pipeline_id", nullable=False)
    op.alter_column("deals", "stage_id", nullable=False)
    op.alter_column("deal_stage_history", "to_stage_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_deals_workspace_id_pipeline_id_stage_id_deal_pipeline_stages"),
        "deals", "deal_pipeline_stages",
        ["workspace_id", "pipeline_id", "stage_id"],
        ["workspace_id", "pipeline_id", "id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_deal_stage_history_workspace_id_from_stage_id_deal_pipeline_stages"),
        "deal_stage_history", "deal_pipeline_stages",
        ["workspace_id", "from_stage_id"], ["workspace_id", "id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_deal_stage_history_workspace_id_to_stage_id_deal_pipeline_stages"),
        "deal_stage_history", "deal_pipeline_stages",
        ["workspace_id", "to_stage_id"], ["workspace_id", "id"], ondelete="RESTRICT",
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION smartcrm_sync_deal_stage_ids() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "DECLARE matched_pipeline uuid; matched_stage uuid; BEGIN "
            "SELECT pipeline_id, id INTO matched_pipeline, matched_stage "
            "FROM deal_pipeline_stages WHERE workspace_id = NEW.workspace_id "
            "AND name = NEW.stage AND archived_at IS NULL; "
            "IF matched_stage IS NULL THEN RAISE EXCEPTION 'unknown or archived deal stage: %', NEW.stage; END IF; "
            "NEW.pipeline_id := matched_pipeline; NEW.stage_id := matched_stage; RETURN NEW; END $$"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER smartcrm_sync_deal_stage_ids BEFORE INSERT OR UPDATE OF workspace_id, stage "
            "ON deals FOR EACH ROW EXECUTE FUNCTION smartcrm_sync_deal_stage_ids()"
        )
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION smartcrm_sync_deal_history_stage_ids() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN "
            "SELECT id INTO NEW.to_stage_id FROM deal_pipeline_stages "
            "WHERE workspace_id = NEW.workspace_id AND name = NEW.to_stage; "
            "IF NEW.to_stage_id IS NULL THEN RAISE EXCEPTION 'unknown deal history destination: %', NEW.to_stage; END IF; "
            "IF NEW.from_stage IS NULL THEN NEW.from_stage_id := NULL; ELSE "
            "SELECT id INTO NEW.from_stage_id FROM deal_pipeline_stages "
            "WHERE workspace_id = NEW.workspace_id AND name = NEW.from_stage; END IF; "
            "RETURN NEW; END $$"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER smartcrm_sync_deal_history_stage_ids BEFORE INSERT OR UPDATE OF workspace_id, from_stage, to_stage "
            "ON deal_stage_history FOR EACH ROW EXECUTE FUNCTION smartcrm_sync_deal_history_stage_ids()"
        )
    )

    for table_name in PIPELINE_TABLES:
        op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE POLICY smartcrm_workspace_scope ON "{table_name}" FOR ALL '
                "USING (workspace_id = current_setting('smartcrm.workspace_id', true)) "
                "WITH CHECK (workspace_id = current_setting('smartcrm.workspace_id', true))"
            )
        )


def downgrade() -> None:
    for table_name in reversed(PIPELINE_TABLES):
        op.execute(sa.text(f'DROP POLICY smartcrm_workspace_scope ON "{table_name}"'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY'))

    op.execute(sa.text("DROP TRIGGER smartcrm_sync_deal_history_stage_ids ON deal_stage_history"))
    op.execute(sa.text("DROP FUNCTION smartcrm_sync_deal_history_stage_ids()"))
    op.execute(sa.text("DROP TRIGGER smartcrm_sync_deal_stage_ids ON deals"))
    op.execute(sa.text("DROP FUNCTION smartcrm_sync_deal_stage_ids()"))
    op.drop_constraint(
        op.f("fk_deal_stage_history_workspace_id_to_stage_id_deal_pipeline_stages"),
        "deal_stage_history", type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_deal_stage_history_workspace_id_from_stage_id_deal_pipeline_stages"),
        "deal_stage_history", type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_deals_workspace_id_pipeline_id_stage_id_deal_pipeline_stages"),
        "deals", type_="foreignkey",
    )
    op.drop_column("deal_stage_history", "to_stage_id")
    op.drop_column("deal_stage_history", "from_stage_id")
    op.drop_column("deals", "stage_id")
    op.drop_column("deals", "pipeline_id")
    op.drop_table("deal_pipeline_audit_events")
    op.drop_constraint("fk_deal_pipelines_default_stage", "deal_pipelines", type_="foreignkey")
    op.drop_table("deal_pipeline_stages")
    op.drop_table("deal_pipelines")
