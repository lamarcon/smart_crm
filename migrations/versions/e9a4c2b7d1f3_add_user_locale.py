"""add the interface language of each user

Revision ID: e9a4c2b7d1f3
Revises: d7e1b3c9a2f4
Create Date: 2026-11-16 18:00:00.000000

``crm_users.locale`` keeps the language each person chose for the interface and
for the e-mails sent to them (pt-BR, en or es). Existing users stay pt-BR.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9a4c2b7d1f3"
down_revision: Union[str, Sequence[str], None] = "d7e1b3c9a2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "crm_users",
        sa.Column("locale", sa.String(length=8), server_default="pt-BR", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_crm_users_valid_locale"),
        "crm_users",
        "locale IN ('pt-BR', 'en', 'es')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_crm_users_valid_locale"), "crm_users", type_="check")
    op.drop_column("crm_users", "locale")
