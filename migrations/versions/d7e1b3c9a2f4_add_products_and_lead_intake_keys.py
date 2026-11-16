"""add products catalog, quote product link and lead intake keys

Revision ID: d7e1b3c9a2f4
Revises: c3d9a1f4b7e2
Create Date: 2026-11-16 12:00:00.000000

* ``products``: the catalog (name, SKU, price in BRL/USD/EUR, unit, active and
  a free key/value ``metadata`` list), used by deal quotes.
* ``quotes.product_id``: optional link from a quote line to its product.
* ``lead_intake_keys``: secret keys (stored as sha256 digests) that let an
  external system, such as the Instagram bot, create leads through the API.

Both new tables carry the tenant row-level security of the other tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d7e1b3c9a2f4"
down_revision: Union[str, Sequence[str], None] = "c3d9a1f4b7e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = ("products", "lead_intake_keys")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=128), server_default="", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("category", sa.String(length=255), server_default="", nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("currency", sa.CHAR(length=3), server_default="BRL", nullable=False),
        sa.Column("unit", sa.String(length=32), server_default="un", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("currency IN ('BRL', 'USD', 'EUR')", name=op.f("ck_products_valid_currency")),
        sa.CheckConstraint("price >= 0", name=op.f("ck_products_nonnegative_price")),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name=op.f("ck_products_name_present")),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'array'", name=op.f("ck_products_metadata_is_list")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name=op.f("fk_products_workspace_id_workspaces"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
    )
    op.create_index("ix_products_workspace_active", "products", ["workspace_id", "deleted_at"], unique=False)
    op.create_index("ix_products_workspace_sku", "products", ["workspace_id", "sku"], unique=False)

    op.add_column("quotes", sa.Column("product_id", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        op.f("fk_quotes_product_id_products"), "quotes", "products",
        ["product_id"], ["id"], ondelete="RESTRICT",
    )

    op.create_table(
        "lead_intake_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_digest", sa.CHAR(length=64), nullable=False),
        sa.Column("default_channel", sa.String(length=32), nullable=False),
        sa.Column("default_responsible_id", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=128), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("char_length(key_digest) = 64", name=op.f("ck_lead_intake_keys_digest_length")),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name=op.f("ck_lead_intake_keys_name_present")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name=op.f("fk_lead_intake_keys_workspace_id_workspaces"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["default_responsible_id"], ["crm_users.id"],
            name=op.f("fk_lead_intake_keys_default_responsible_id_crm_users"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["crm_users.id"],
            name=op.f("fk_lead_intake_keys_created_by_user_id_crm_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_intake_keys")),
        sa.UniqueConstraint("key_digest", name=op.f("uq_lead_intake_keys_key_digest")),
    )

    for table_name in NEW_TABLES:
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
    for table_name in NEW_TABLES:
        op.execute(sa.text(f'DROP POLICY smartcrm_workspace_scope ON "{table_name}"'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY'))
    op.drop_table("lead_intake_keys")
    op.drop_constraint(op.f("fk_quotes_product_id_products"), "quotes", type_="foreignkey")
    op.drop_column("quotes", "product_id")
    op.drop_index("ix_products_workspace_sku", table_name="products")
    op.drop_index("ix_products_workspace_active", table_name="products")
    op.drop_table("products")
