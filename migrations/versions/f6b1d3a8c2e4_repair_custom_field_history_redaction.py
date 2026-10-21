"""repair custom field history redaction

Revision ID: f6b1d3a8c2e4
Revises: e1c4a7b9d2f6
Create Date: 2026-10-21 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6b1d3a8c2e4"
down_revision: Union[str, Sequence[str], None] = "e1c4a7b9d2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE custom_field_definitions "
            "ADD COLUMN IF NOT EXISTS redact_in_history "
            "boolean NOT NULL DEFAULT false"
        )
    )


def downgrade() -> None:
    # Revision e1c4a7b9d2f6 owns this column. Returning to that revision must
    # preserve its schema, so the repair revision has no downgrade DDL.
    pass
