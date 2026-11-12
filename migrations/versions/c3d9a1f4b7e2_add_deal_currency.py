"""add deal currency and frozen exchange rate

Revision ID: c3d9a1f4b7e2
Revises: b4e2c9a7d6f1
Create Date: 2026-11-12 12:00:00.000000

Deals may be priced in BRL, USD or EUR. ``fx_rate``/``fx_rate_date`` keep the
PTAX rate frozen when a foreign-currency deal is won. Existing deals stay BRL.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d9a1f4b7e2"
down_revision: Union[str, Sequence[str], None] = "b4e2c9a7d6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column("currency", sa.CHAR(length=3), server_default="BRL", nullable=False),
    )
    op.add_column("deals", sa.Column("fx_rate", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("deals", sa.Column("fx_rate_date", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_deals_valid_currency"),
        "deals",
        "currency IN ('BRL', 'USD', 'EUR')",
    )
    op.create_check_constraint(
        op.f("ck_deals_positive_fx_rate"),
        "deals",
        "fx_rate IS NULL OR fx_rate > 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_deals_positive_fx_rate"), "deals", type_="check")
    op.drop_constraint(op.f("ck_deals_valid_currency"), "deals", type_="check")
    op.drop_column("deals", "fx_rate_date")
    op.drop_column("deals", "fx_rate")
    op.drop_column("deals", "currency")
