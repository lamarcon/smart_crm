"""SQLAlchemy models for the central multi-tenant control plane."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, MetaData, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class ControlBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ControlTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ControlTenant(ControlBase, ControlTimestampMixin):
    __tablename__ = "control_tenants"
    __table_args__ = (
        UniqueConstraint("slug"),
        CheckConstraint(
            "status IN ('provisioning', 'active', 'inactive', 'failed')",
            name="valid_status",
        ),
        CheckConstraint("profile_version >= 1", name="profile_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="provisioning", server_default="provisioning"
    )
    secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    expected_tenant_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    provisioning_checkpoint: Mapped[str | None] = mapped_column(String(128))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(ControlBase):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_active_expiry", "revoked_at", "idle_expires_at"),
        Index("ix_auth_sessions_tenant_user", "tenant_id", "user_id"),
        CheckConstraint("auth_version >= 0", name="auth_version_nonnegative"),
    )

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("control_tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(128))
    correlation_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class LoginThrottle(ControlBase):
    __tablename__ = "login_throttles"
    __table_args__ = (
        CheckConstraint("bucket_type IN ('account', 'ip')", name="valid_bucket_type"),
        CheckConstraint("failure_count >= 0", name="failure_count_nonnegative"),
        Index("ix_login_throttles_blocked_until", "blocked_until"),
    )

    bucket_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SecurityEvent(ControlBase):
    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_security_events_type_created", "event_type", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("control_tenants.id", ondelete="SET NULL"),
    )
    user_id: Mapped[str | None] = mapped_column(String(128))
    correlation_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_code: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
