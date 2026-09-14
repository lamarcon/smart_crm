"""create central control plane

Revision ID: c01a5d8e4f20
Revises:
Create Date: 2026-09-14 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c01a5d8e4f20"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "control_tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="provisioning", nullable=False),
        sa.Column("secret_ref", sa.String(length=255), nullable=False),
        sa.Column("profile_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expected_tenant_revision", sa.String(length=64), nullable=False),
        sa.Column("provisioning_checkpoint", sa.String(length=128), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("profile_version >= 1", name=op.f("ck_control_tenants_profile_version_positive")),
        sa.CheckConstraint(
            "status IN ('provisioning', 'active', 'inactive', 'failed')",
            name=op.f("ck_control_tenants_valid_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_control_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_control_tenants_slug")),
    )
    op.create_table(
        "login_throttles",
        sa.Column("bucket_type", sa.String(length=16), nullable=False),
        sa.Column("subject_digest", sa.String(length=64), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("bucket_type IN ('account', 'ip')", name=op.f("ck_login_throttles_valid_bucket_type")),
        sa.CheckConstraint("failure_count >= 0", name=op.f("ck_login_throttles_failure_count_nonnegative")),
        sa.PrimaryKeyConstraint("bucket_type", "subject_digest", name=op.f("pk_login_throttles")),
    )
    op.create_index("ix_login_throttles_blocked_until", "login_throttles", ["blocked_until"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=128), nullable=True),
        sa.Column("correlation_digest", sa.String(length=64), nullable=False),
        sa.CheckConstraint("auth_version >= 0", name=op.f("ck_auth_sessions_auth_version_nonnegative")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["control_tenants.id"],
            name=op.f("fk_auth_sessions_tenant_id_control_tenants"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_digest", name=op.f("pk_auth_sessions")),
    )
    op.create_index("ix_auth_sessions_active_expiry", "auth_sessions", ["revoked_at", "idle_expires_at"], unique=False)
    op.create_index("ix_auth_sessions_tenant_user", "auth_sessions", ["tenant_id", "user_id"], unique=False)
    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("correlation_digest", sa.String(length=64), nullable=False),
        sa.Column("outcome_code", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["control_tenants.id"],
            name=op.f("fk_security_events_tenant_id_control_tenants"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
    )
    op.create_index("ix_security_events_tenant_created", "security_events", ["tenant_id", "created_at"], unique=False)
    op.create_index("ix_security_events_type_created", "security_events", ["event_type", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_security_events_type_created", table_name="security_events")
    op.drop_index("ix_security_events_tenant_created", table_name="security_events")
    op.drop_table("security_events")
    op.drop_index("ix_auth_sessions_tenant_user", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_active_expiry", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_login_throttles_blocked_until", table_name="login_throttles")
    op.drop_table("login_throttles")
    op.drop_table("control_tenants")
