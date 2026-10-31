"""expand account action throttle buckets

Revision ID: d5f0a8c3e7b2
Revises: c01a5d8e4f20
Create Date: 2026-10-30 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5f0a8c3e7b2"
down_revision: Union[str, Sequence[str], None] = "c01a5d8e4f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_login_throttles_valid_bucket_type"),
        "login_throttles",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_login_throttles_valid_bucket_type"),
        "login_throttles",
        "bucket_type IN ("
        "'account', 'ip', 'invite_account', 'invite_ip', "
        "'reset_account', 'reset_ip'"
        ")",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM login_throttles WHERE bucket_type NOT IN ('account', 'ip')"
        )
    )
    op.drop_constraint(
        op.f("ck_login_throttles_valid_bucket_type"),
        "login_throttles",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_login_throttles_valid_bucket_type"),
        "login_throttles",
        "bucket_type IN ('account', 'ip')",
    )
