"""align CRM user statuses with the UI

Revision ID: 9f7a2c31d5e8
Revises: be40ea4d21ad
Create Date: 2026-08-28 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f7a2c31d5e8"
down_revision: Union[str, Sequence[str], None] = "be40ea4d21ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_crm_users_valid_status"), "crm_users", type_="check")
    op.create_check_constraint(
        op.f("ck_crm_users_valid_status"),
        "crm_users",
        "status IN ('Ativo', 'Pendente', 'Inativo', 'Cancelado', 'Convidado')",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE crm_users SET status = CASE "
            "WHEN status = 'Pendente' THEN 'Convidado' "
            "WHEN status = 'Cancelado' THEN 'Inativo' "
            "ELSE status END"
        )
    )
    op.drop_constraint(op.f("ck_crm_users_valid_status"), "crm_users", type_="check")
    op.create_check_constraint(
        op.f("ck_crm_users_valid_status"),
        "crm_users",
        "status IN ('Ativo', 'Convidado', 'Inativo')",
    )
