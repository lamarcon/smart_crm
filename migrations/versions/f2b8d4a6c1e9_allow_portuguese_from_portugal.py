"""accept Portuguese from Portugal as a user language

Revision ID: f2b8d4a6c1e9
Revises: e9a4c2b7d1f3
Create Date: 2026-11-16 21:00:00.000000

Adds pt-PT to the languages ``crm_users.locale`` accepts. Downgrading moves
pt-PT users back to pt-BR before restoring the previous rule.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f2b8d4a6c1e9"
down_revision: Union[str, Sequence[str], None] = "e9a4c2b7d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_crm_users_valid_locale"), "crm_users", type_="check")
    op.create_check_constraint(
        op.f("ck_crm_users_valid_locale"),
        "crm_users",
        "locale IN ('pt-BR', 'pt-PT', 'en', 'es')",
    )


def downgrade() -> None:
    op.execute("UPDATE crm_users SET locale = 'pt-BR' WHERE locale = 'pt-PT'")
    op.drop_constraint(op.f("ck_crm_users_valid_locale"), "crm_users", type_="check")
    op.create_check_constraint(
        op.f("ck_crm_users_valid_locale"),
        "crm_users",
        "locale IN ('pt-BR', 'en', 'es')",
    )
