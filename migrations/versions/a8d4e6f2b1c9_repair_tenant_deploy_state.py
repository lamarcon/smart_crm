"""repair tenant deployment state

Revision ID: a8d4e6f2b1c9
Revises: f6b1d3a8c2e4
Create Date: 2026-10-29 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8d4e6f2b1c9"
down_revision: Union[str, Sequence[str], None] = "f6b1d3a8c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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


def _workspace_id(connection) -> str | None:  # noqa: ANN001
    rows = connection.execute(
        sa.text(
            "SELECT workspace_id FROM tenant_identity "
            "WHERE singleton_key = 'identity'"
        )
    ).scalars().all()
    if not rows:
        connection.execute(
            sa.text("SELECT set_config('smartcrm.workspace_id', 'default', true)")
        )
        existing_users = connection.scalar(sa.text("SELECT count(*) FROM crm_users"))
        if existing_users:
            raise RuntimeError("tenant identity is required for deployment repair")
        return None
    if len(rows) != 1 or not rows[0]:
        raise RuntimeError("tenant identity is required for deployment repair")
    workspace_id = str(rows[0])
    connection.execute(
        sa.text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
        {"workspace_id": workspace_id},
    )
    visible = connection.scalar(
        sa.text("SELECT count(*) FROM workspaces WHERE id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    if visible != 1:
        raise RuntimeError("tenant identity workspace is unavailable")
    return workspace_id


def _seed_pipeline(connection, workspace_id: str) -> None:  # noqa: ANN001
    pipelines = connection.execute(
        sa.text(
            "SELECT id, is_default, default_stage_id FROM deal_pipelines "
            "WHERE workspace_id = :workspace_id ORDER BY id"
        ),
        {"workspace_id": workspace_id},
    ).mappings().all()
    if pipelines:
        default_pipelines = [item for item in pipelines if item["is_default"]]
        if len(default_pipelines) != 1 or default_pipelines[0]["default_stage_id"] is None:
            raise RuntimeError("tenant pipeline state is inconsistent")
        default_stage_exists = connection.scalar(
            sa.text(
                "SELECT count(*) FROM deal_pipeline_stages "
                "WHERE workspace_id = :workspace_id AND pipeline_id = :pipeline_id "
                "AND id = :stage_id AND archived_at IS NULL"
            ),
            {
                "workspace_id": workspace_id,
                "pipeline_id": default_pipelines[0]["id"],
                "stage_id": default_pipelines[0]["default_stage_id"],
            },
        )
        if default_stage_exists != 1:
            raise RuntimeError("tenant default pipeline stage is inconsistent")
        return

    op.alter_column("deal_pipelines", "default_stage_id", nullable=True)
    pipeline_id = connection.scalar(
        sa.text("SELECT md5('smartcrm:pipeline:' || :workspace_id)::uuid"),
        {"workspace_id": workspace_id},
    )
    connection.execute(
        sa.text(
            "INSERT INTO deal_pipelines "
            "(id, workspace_id, name, version, is_default) "
            "VALUES (:pipeline_id, :workspace_id, 'Negócios', 1, true)"
        ),
        {"pipeline_id": pipeline_id, "workspace_id": workspace_id},
    )
    for position, name, semantic_type, color, system_key in LEGACY_STAGES:
        stage_id = connection.scalar(
            sa.text(
                "SELECT md5('smartcrm:stage:' || :workspace_id || ':' || :name)::uuid"
            ),
            {"workspace_id": workspace_id, "name": name},
        )
        connection.execute(
            sa.text(
                "INSERT INTO deal_pipeline_stages "
                "(id, workspace_id, pipeline_id, name, semantic_type, color, "
                "position, system_key) VALUES "
                "(:id, :workspace_id, :pipeline_id, :name, :semantic_type, "
                ":color, :position, :system_key)"
            ),
            {
                "id": stage_id,
                "workspace_id": workspace_id,
                "pipeline_id": pipeline_id,
                "name": name,
                "semantic_type": semantic_type,
                "color": color,
                "position": position,
                "system_key": system_key,
            },
        )
    connection.execute(
        sa.text(
            "UPDATE deal_pipelines AS pipeline SET default_stage_id = stage.id "
            "FROM deal_pipeline_stages AS stage "
            "WHERE pipeline.id = :pipeline_id "
            "AND stage.workspace_id = pipeline.workspace_id "
            "AND stage.pipeline_id = pipeline.id AND stage.system_key = 'initial'"
        ),
        {"pipeline_id": pipeline_id},
    )
    stage_count = connection.scalar(
        sa.text(
            "SELECT count(*) FROM deal_pipeline_stages "
            "WHERE workspace_id = :workspace_id AND pipeline_id = :pipeline_id "
            "AND archived_at IS NULL"
        ),
        {"workspace_id": workspace_id, "pipeline_id": pipeline_id},
    )
    default_stage_id = connection.scalar(
        sa.text("SELECT default_stage_id FROM deal_pipelines WHERE id = :pipeline_id"),
        {"pipeline_id": pipeline_id},
    )
    if stage_count != len(LEGACY_STAGES) or default_stage_id is None:
        raise RuntimeError("tenant pipeline repair failed")
    op.alter_column("deal_pipelines", "default_stage_id", nullable=False)


def _repair_user_payloads(connection, workspace_id: str) -> None:  # noqa: ANN001
    connection.execute(
        sa.text(
            "UPDATE crm_users SET payload = "
            "(CASE WHEN jsonb_typeof(payload) = 'object' THEN payload ELSE '{}'::jsonb END) "
            "|| jsonb_build_object("
            "'position', CASE WHEN jsonb_typeof(payload->'position') = 'number' "
            "THEN payload->'position' ELSE '0'::jsonb END, "
            "'record', (CASE WHEN jsonb_typeof(payload->'record') = 'object' "
            "THEN payload->'record' ELSE '{}'::jsonb END) || jsonb_build_object("
            "'id', id, 'name', name, 'email', email, 'jobTitle', job_title, "
            "'role', role, 'status', status, 'avatar', "
            "upper(left(btrim(name), 1) || CASE WHEN strpos(btrim(name), ' ') > 0 "
            "THEN left(regexp_replace(btrim(name), '^.* ', ''), 1) ELSE '' END))) "
            "WHERE workspace_id = :workspace_id"
        ),
        {"workspace_id": workspace_id},
    )


def upgrade() -> None:
    connection = op.get_bind()
    workspace_id = _workspace_id(connection)
    if workspace_id is None:
        return
    _seed_pipeline(connection, workspace_id)
    _repair_user_payloads(connection, workspace_id)


def downgrade() -> None:
    # This repair only restores required data. Downgrade keeps tenant business data intact.
    pass
