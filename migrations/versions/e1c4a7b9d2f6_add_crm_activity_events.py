"""add crm activity events

Revision ID: e1c4a7b9d2f6
Revises: c7f3a9d8e2b1
Create Date: 2026-10-15 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e1c4a7b9d2f6"
down_revision: Union[str, Sequence[str], None] = "c7f3a9d8e2b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "custom_field_definitions",
        sa.Column(
            "redact_in_history",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "crm_activity_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("deal_id", sa.String(length=128), nullable=True),
        sa.Column("company_id", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("actor_user_id", sa.String(length=128), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(deal_id IS NOT NULL AND company_id IS NULL) OR "
            "(deal_id IS NULL AND company_id IS NOT NULL)",
            name=op.f("ck_crm_activity_events_exactly_one_subject"),
        ),
        sa.CheckConstraint(
            "category IN ('movement', 'automation', 'observation', 'change')",
            name=op.f("ck_crm_activity_events_valid_category"),
        ),
        sa.CheckConstraint(
            "length(btrim(event_type)) > 0",
            name=op.f("ck_crm_activity_events_event_type_nonempty"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_crm_activity_events_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"],
            ["deals.id"],
            name=op.f("fk_crm_activity_events_deal_id_deals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_crm_activity_events_company_id_companies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["crm_users.id"],
            name=op.f("fk_crm_activity_events_actor_user_id_crm_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crm_activity_events")),
        sa.UniqueConstraint(
            "workspace_id",
            "dedupe_key",
            name=op.f("uq_crm_activity_events_workspace_id_dedupe_key"),
        ),
    )
    op.create_index(
        "ix_crm_activity_events_deal_timeline",
        "crm_activity_events",
        ["workspace_id", "deal_id", sa.text("occurred_at DESC"), sa.text("id DESC")],
        unique=False,
        postgresql_where=sa.text("deal_id IS NOT NULL"),
    )
    op.create_index(
        "ix_crm_activity_events_company_timeline",
        "crm_activity_events",
        ["workspace_id", "company_id", sa.text("occurred_at DESC"), sa.text("id DESC")],
        unique=False,
        postgresql_where=sa.text("company_id IS NOT NULL"),
    )

    op.execute(
        sa.text(
            "INSERT INTO crm_activity_events "
            "(workspace_id, deal_id, category, event_type, actor_user_id, actor_name, "
            "summary, details, dedupe_key, occurred_at) "
            "SELECT h.workspace_id, h.deal_id, 'movement', 'deal.stage_changed', "
            "h.changed_by_id, coalesce(u.name, 'Sistema (migração)'), "
            "CASE WHEN h.from_stage IS NULL THEN 'Negócio criado na etapa ' || h.to_stage "
            "ELSE 'Etapa alterada de ' || h.from_stage || ' para ' || h.to_stage END, "
            "jsonb_build_object("
            "'fromStageId', h.from_stage_id, 'fromStageName', h.from_stage, "
            "'toStageId', h.to_stage_id, 'toStageName', h.to_stage, 'source', 'user'), "
            "'legacy-stage-history:' || h.id::text, h.changed_at "
            "FROM deal_stage_history h LEFT JOIN crm_users u ON u.id = h.changed_by_id "
            "ON CONFLICT (workspace_id, dedupe_key) DO NOTHING"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO crm_activity_events "
            "(workspace_id, company_id, category, event_type, actor_name, summary, "
            "details, dedupe_key, occurred_at) "
            "SELECT c.workspace_id, c.id, 'change', 'company.created', "
            "'Sistema (migração)', 'Empresa registrada', "
            "jsonb_build_object('name', c.name, 'source', 'migration'), "
            "'legacy-company-created:' || c.id, c.created_at FROM companies c "
            "ON CONFLICT (workspace_id, dedupe_key) DO NOTHING"
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF (SELECT count(*) FROM deal_stage_history) <> ("
            "SELECT count(*) FROM crm_activity_events "
            "WHERE dedupe_key LIKE 'legacy-stage-history:%') "
            "THEN RAISE EXCEPTION 'deal activity backfill count mismatch'; END IF; "
            "IF (SELECT count(*) FROM companies) <> ("
            "SELECT count(*) FROM crm_activity_events "
            "WHERE dedupe_key LIKE 'legacy-company-created:%') "
            "THEN RAISE EXCEPTION 'company activity backfill count mismatch'; END IF; "
            "END $$"
        )
    )

    op.execute(sa.text('ALTER TABLE "crm_activity_events" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "crm_activity_events" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY smartcrm_workspace_scope ON "crm_activity_events" FOR ALL '
            "USING (workspace_id = current_setting('smartcrm.workspace_id', true)) "
            "WITH CHECK (workspace_id = current_setting('smartcrm.workspace_id', true))"
        )
    )


def downgrade() -> None:
    op.execute(sa.text('DROP POLICY smartcrm_workspace_scope ON "crm_activity_events"'))
    op.execute(sa.text('ALTER TABLE "crm_activity_events" NO FORCE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "crm_activity_events" DISABLE ROW LEVEL SECURITY'))
    op.drop_table("crm_activity_events")
    op.drop_column("custom_field_definitions", "redact_in_history")
