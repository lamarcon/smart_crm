"""Normalized PostgreSQL model for the Smart CRM workspace."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("version >= 0", name="version_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Team(Base, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class CrmUser(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "crm_users"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email"),
        CheckConstraint(
            "status IN ('Ativo', 'Pendente', 'Inativo', 'Cancelado', 'Convidado')",
            name="valid_status",
        ),
        Index("ix_crm_users_workspace_active", "workspace_id", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    job_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Ativo")
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Lead(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_workspace_active", "workspace_id", "deleted_at"),
        Index("ix_leads_workspace_responsible", "workspace_id", "responsible_id"),
        Index("ix_leads_workspace_stage", "workspace_id", "stage"),
        Index("ix_leads_workspace_bitrix", "workspace_id", "bitrix_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    responsible_id: Mapped[str | None] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    segment: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    discard_reason: Mapped[str | None] = mapped_column(Text)
    bitrix_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Company(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_workspace_active", "workspace_id", "deleted_at"),
        Index("ix_companies_workspace_owner", "workspace_id", "owner_id"),
        Index("ix_companies_workspace_bitrix", "workspace_id", "bitrix_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    segment: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    bitrix_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Contact(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_workspace_active", "workspace_id", "deleted_at"),
        Index("ix_contacts_workspace_company", "workspace_id", "company_id"),
        Index("ix_contacts_workspace_bitrix", "workspace_id", "bitrix_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_text: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    bitrix_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Deal(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "deals"
    __table_args__ = (
        Index("ix_deals_workspace_active", "workspace_id", "deleted_at"),
        Index("ix_deals_workspace_stage", "workspace_id", "stage"),
        Index("ix_deals_workspace_responsible", "workspace_id", "responsible_id"),
        Index("ix_deals_workspace_created", "workspace_id", "created_at"),
        Index("ix_deals_workspace_bitrix", "workspace_id", "bitrix_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"))
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="RESTRICT"))
    responsible_id: Mapped[str | None] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company_text: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact_text: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    stage_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage_changed_by_id: Mapped[str | None] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"))
    won_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bitrix_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class LeadAssistant(Base):
    __tablename__ = "lead_assistants"
    __table_args__ = (UniqueConstraint("lead_id", "user_id"),)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="RESTRICT"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class DealAssistant(Base):
    __tablename__ = "deal_assistants"
    __table_args__ = (UniqueConstraint("deal_id", "user_id"),)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class DealStageHistory(Base):
    __tablename__ = "deal_stage_history"
    __table_args__ = (UniqueConstraint("deal_id", "position"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    from_stage: Mapped[str | None] = mapped_column(String(128))
    to_stage: Mapped[str] = mapped_column(String(128), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by_id: Mapped[str | None] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"))


class Quote(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "quotes"
    __table_args__ = (Index("ix_quotes_deal_active", "deal_id", "deleted_at"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    discount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(64), nullable=False, default="Rascunho")
    pdf_name: Mapped[str | None] = mapped_column(String(512))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Notification(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_active", "user_id", "deleted_at"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    displayed_time: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class CustomFieldDefinition(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "custom_field_definitions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "module", "key"),
        UniqueConstraint("workspace_id", "module", "source_name", "source_occurrence"),
        Index("ix_custom_definitions_module_active", "workspace_id", "module", "deleted_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(64), nullable=False)
    options: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    source_name: Mapped[str | None] = mapped_column(String(255))
    source_occurrence: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    user_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"
    __table_args__ = (
        UniqueConstraint("workspace_id", "module", "record_id", "field_key", "position"),
        Index("ix_custom_values_record", "workspace_id", "module", "record_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    definition_id: Mapped[int] = mapped_column(ForeignKey("custom_field_definitions.id", ondelete="RESTRICT"), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    field_key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RecordVisibleCustomField(Base):
    __tablename__ = "record_visible_custom_fields"
    __table_args__ = (UniqueConstraint("workspace_id", "module", "record_id", "field_key"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    field_key: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ExternalSourceField(Base):
    __tablename__ = "external_source_fields"
    __table_args__ = (
        UniqueConstraint("workspace_id", "module", "record_id", "source", "position"),
        Index("ix_external_fields_record", "workspace_id", "module", "record_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    occurrence: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)


class ModuleFieldSetting(Base):
    __tablename__ = "module_field_settings"
    __table_args__ = (UniqueConstraint("workspace_id", "module"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    hidden_standard_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    hidden_custom_field_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class SavedFilter(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "saved_filters"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "scope", "name"),
        Index("ix_saved_filters_user_active", "user_id", "deleted_at"),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filter: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class UserModulePreference(Base):
    __tablename__ = "user_module_preferences"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "module"),
        CheckConstraint("view_mode IN ('list', 'kanban')", name="valid_view_mode"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    view_mode: Mapped[str] = mapped_column(String(16), nullable=False)


class UserDashboardPreference(Base):
    __tablename__ = "user_dashboard_preferences"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id"),
        CheckConstraint("scope IN ('all', 'leads', 'deals')", name="valid_scope"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("crm_users.id", ondelete="RESTRICT"), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
