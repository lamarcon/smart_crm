"""quote items with an additional value, and the item price permission

Revision ID: e1a7c3f9b2d4
Revises: c4e8a2f6b9d1
Create Date: 2026-11-18 10:00:00.000000

A deal's value becomes the sum of its quote items plus an "additional value"
with a reason. Existing deals are converted once so their value never doubles:

- a deal without quotes keeps its typed value as the additional value;
- a deal with quotes gets an additional value of zero and a value equal to the
  sum of its quotes (now its items).

``role_permissions`` also accepts the new "price" action (change the price of
an item or give a discount). Downgrading keeps the converted values and only
drops stored "price" cells.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1a7c3f9b2d4"
down_revision: Union[str, Sequence[str], None] = "c4e8a2f6b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tenant_workspaces(connection) -> list[str]:  # noqa: ANN001
    """The tenant's workspace (tables are under FORCE RLS, so each statement runs
    inside it); a database without an identity yet uses the default workspace."""

    rows = connection.execute(
        sa.text("SELECT workspace_id FROM tenant_identity WHERE singleton_key = 'identity'")
    ).scalars().all()
    return [str(row) for row in rows if row] or ["default"]


def _in_workspace(connection, workspace_id: str) -> None:  # noqa: ANN001
    connection.execute(sa.text("SELECT set_config('smartcrm.workspace_id', :w, true)"), {"w": workspace_id})


def _convert_deals(connection, workspace_id: str) -> None:  # noqa: ANN001
    connection.execute(
        sa.text(
            """
            WITH item_sums AS (
                SELECT deal_id, SUM(total) AS items
                FROM quotes
                WHERE workspace_id = :w AND deleted_at IS NULL
                GROUP BY deal_id
            ), converted AS (
                SELECT d.id,
                       CASE WHEN s.items IS NULL THEN d.amount ELSE 0 END AS additional,
                       COALESCE(s.items, 0) + CASE WHEN s.items IS NULL THEN d.amount ELSE 0 END AS total
                FROM deals d
                LEFT JOIN item_sums s ON s.deal_id = d.id
                WHERE d.workspace_id = :w
                  AND NOT (COALESCE(d.payload -> 'record', '{}'::jsonb) ? 'additionalAmount')
            )
            UPDATE deals d
            SET amount = c.total,
                payload = jsonb_set(
                    COALESCE(d.payload, '{}'::jsonb),
                    '{record}',
                    COALESCE(d.payload -> 'record', '{}'::jsonb)
                        || jsonb_build_object(
                            'additionalAmount', c.additional,
                            'additionalReason', COALESCE(d.payload -> 'record' ->> 'additionalReason', ''),
                            'amount', c.total
                        )
                )
            FROM converted c
            WHERE d.id = c.id AND d.workspace_id = :w
            """
        ),
        {"w": workspace_id},
    )


def upgrade() -> None:
    op.drop_constraint(op.f("ck_role_permissions_valid_action"), "role_permissions", type_="check")
    op.create_check_constraint(
        op.f("ck_role_permissions_valid_action"),
        "role_permissions",
        "action IN ('read', 'create', 'update', 'delete', 'import', 'export', 'price')",
    )
    connection = op.get_bind()
    for workspace_id in _tenant_workspaces(connection):
        _in_workspace(connection, workspace_id)
        _convert_deals(connection, workspace_id)


def downgrade() -> None:
    connection = op.get_bind()
    for workspace_id in _tenant_workspaces(connection):
        _in_workspace(connection, workspace_id)
        connection.execute(
            sa.text("DELETE FROM role_permissions WHERE workspace_id = :w AND action = 'price'"), {"w": workspace_id}
        )
    op.drop_constraint(op.f("ck_role_permissions_valid_action"), "role_permissions", type_="check")
    op.create_check_constraint(
        op.f("ck_role_permissions_valid_action"),
        "role_permissions",
        "action IN ('read', 'create', 'update', 'delete', 'import', 'export')",
    )
