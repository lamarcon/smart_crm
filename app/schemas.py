"""Pydantic workspace contract and cross-record validation."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MODULES = ("leads", "contacts", "companies", "deals")
EXPECTED_PUBLIC_HOST = "sc2030.brbots.com"
RESERVED_TENANT_SLUGS = frozenset({"api", "docs", "redoc", "static", "health", "openapi.json"})
TENANT_SLUG_PATTERN = re.compile(r"[a-z0-9-]{1,63}\Z")
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
LOGIN_FAILURE_MESSAGE = "Não foi possível entrar com os dados informados."


def normalize_tenant_identifier(identifier: str) -> str:
    value = identifier.strip()
    if "://" in value:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as error:
            raise ValueError("invalid tenant identifier") from error
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname is None
            or parsed.hostname.lower() != EXPECTED_PUBLIC_HOST
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or parsed.path.count("/") != 1
        ):
            raise ValueError("invalid tenant identifier")
        value = parsed.path[1:]

    slug = value.lower()
    if not TENANT_SLUG_PATTERN.fullmatch(slug) or slug in RESERVED_TENANT_SLUGS:
        raise ValueError("invalid tenant identifier")
    return slug


class AuthContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocateTenantRequest(AuthContractModel):
    identifier: str = Field(min_length=1, max_length=2048)

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return normalize_tenant_identifier(value)

    @property
    def slug(self) -> str:
        return self.identifier


class LocateTenantResponse(AuthContractModel):
    slug: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9-]+$")
    display_name: str = Field(min_length=1, max_length=255)


class LoginRequest(AuthContractModel):
    slug: str = Field(min_length=1, max_length=63)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        return normalize_tenant_identifier(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("invalid email")
        return normalized


class SessionResponse(AuthContractModel):
    tenant_id: UUID
    tenant_slug: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9-]+$")
    tenant_display_name: str = Field(min_length=1, max_length=255)
    user_id: str = Field(min_length=1, max_length=128)
    user_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=254)
    role: Literal["Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento"]


class AuthErrorResponse(AuthContractModel):
    error: str = "invalid_login"
    message: str = LOGIN_FAILURE_MESSAGE


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class PipelineContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DealStageReference(PipelineContractModel):
    pipeline_id: UUID = Field(alias="pipelineId")
    stage_id: UUID = Field(alias="stageId")
    stage: str = Field(min_length=1, max_length=80)


class DealPipelineStageUpdate(PipelineContractModel):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=80)
    semantic_type: Literal["open", "won", "lost"] = Field(alias="semanticType")
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    position: int = Field(ge=0)
    archived: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("color")
    @classmethod
    def normalize_color(cls, value: str) -> str:
        return value.upper()


class DealPipelineUpdateRequest(PipelineContractModel):
    pipeline_version: int = Field(alias="pipelineVersion", ge=1)
    workspace_version: int = Field(alias="workspaceVersion", ge=0)
    default_stage_id: UUID = Field(alias="defaultStageId")
    stages: list[DealPipelineStageUpdate] = Field(min_length=1)
    transfers: dict[UUID, UUID] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transfers(self) -> "DealPipelineUpdateRequest":
        if sum(not stage.archived for stage in self.stages) > 50:
            raise ValueError("pipeline cannot have more than 50 active stages")
        if any(source == target for source, target in self.transfers.items()):
            raise ValueError("archive transfer target must differ from source")
        return self


class DealPipelineStageResponse(PipelineContractModel):
    id: UUID
    name: str
    semantic_type: Literal["open", "won", "lost"] = Field(alias="semanticType")
    color: str
    position: int
    system_key: str | None = Field(default=None, alias="systemKey")
    active: bool
    initial: bool
    archived_at: datetime | None = Field(default=None, alias="archivedAt")


class DealPipelineResponse(PipelineContractModel):
    id: UUID
    name: str
    pipeline_version: int = Field(alias="pipelineVersion", ge=1)
    workspace_version: int = Field(alias="workspaceVersion", ge=0)
    default_stage_id: UUID = Field(alias="defaultStageId")
    stages: list[DealPipelineStageResponse]
    transfer_counts: dict[UUID, int] = Field(default_factory=dict, alias="transferCounts")


class DealPipelineAuditEventResponse(PipelineContractModel):
    id: int = Field(ge=1)
    pipeline_id: UUID = Field(alias="pipelineId")
    actor_user_id: str = Field(alias="actorUserId", min_length=1, max_length=128)
    pipeline_version: int = Field(alias="pipelineVersion", ge=1)
    action: str = Field(min_length=1, max_length=64)
    actions: list[dict[str, Any]]
    before_state: dict[str, Any] = Field(alias="beforeState")
    after_state: dict[str, Any] = Field(alias="afterState")
    transfer_summary: list[dict[str, Any]] = Field(alias="transferSummary")
    created_at: datetime = Field(alias="createdAt")


class DealPipelineAuditPage(PipelineContractModel):
    items: list[DealPipelineAuditEventResponse] = Field(max_length=50)
    next_before: int | None = Field(default=None, alias="nextBefore", ge=1)


class DealPipelineHistoryQuery(PipelineContractModel):
    before: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=50)


class WorkspaceState(ContractModel):
    current_user_id: str | None = Field(default=None, alias="currentUserId")
    users: list[dict[str, Any]] = Field(default_factory=list)
    leads: list[dict[str, Any]] = Field(default_factory=list)
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    companies: list[dict[str, Any]] = Field(default_factory=list)
    deals: list[dict[str, Any]] = Field(default_factory=list)
    notifications: list[dict[str, Any]] = Field(default_factory=list)
    custom_field_schemas: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict, alias="customFieldSchemas"
    )
    module_field_settings: dict[str, dict[str, Any]] = Field(
        default_factory=dict, alias="moduleFieldSettings"
    )
    ui: dict[str, Any] = Field(default_factory=dict)


class PersistedCounts(ContractModel):
    users: int
    leads: int
    contacts: int
    companies: int
    deals: int
    quotes: int
    notifications: int
    custom_fields: int = Field(alias="customFields")


class BootstrapRequest(ContractModel):
    state: WorkspaceState


class SaveRequest(ContractModel):
    version: int = Field(ge=0)
    state: WorkspaceState


class ResetRequest(SaveRequest):
    pass


class RestoreRequest(ContractModel):
    version: int = Field(ge=0)
    module: Literal["users", "leads", "contacts", "companies", "deals", "quotes", "notifications"]
    record_id: str = Field(alias="id", min_length=1)


class WorkspaceResponse(ContractModel):
    initialized: bool
    version: int
    state: WorkspaceState | None = None
    counts: PersistedCounts | None = None


class WorkspaceReferenceError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.message = message


def _require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise WorkspaceReferenceError(path, message)


def _unique_ids(items: list[dict[str, Any]], path: str) -> set[str]:
    found: set[str] = set()
    for index, item in enumerate(items):
        item_id = item.get("id")
        _require(isinstance(item_id, str) and bool(item_id), f"{path}[{index}].id", "ID obrigatório")
        _require(item_id not in found, f"{path}[{index}].id", "ID duplicado")
        found.add(item_id)
    return found


def _require_user(value: Any, users: set[str], path: str) -> None:
    if value not in (None, ""):
        _require(value in users, path, "Usuário referenciado não existe")


def validate_references(state: WorkspaceState) -> None:
    data = state.model_dump(by_alias=True, exclude_none=True)
    users = _unique_ids(data["users"], "users")
    ids = {module: _unique_ids(data[module], module) for module in MODULES}
    _unique_ids(data["notifications"], "notifications")

    current_user = data.get("currentUserId")
    if current_user:
        _require(current_user in users, "currentUserId", "Usuário atual não existe")

    for module in ("leads", "deals"):
        for index, record in enumerate(data[module]):
            _require_user(record.get("responsibleId"), users, f"{module}[{index}].responsibleId")
            for assistant_index, assistant_id in enumerate(record.get("assistants") or []):
                _require_user(
                    assistant_id,
                    users,
                    f"{module}[{index}].assistants[{assistant_index}]",
                )

    for index, company in enumerate(data["companies"]):
        _require_user(company.get("ownerId"), users, f"companies[{index}].ownerId")

    for index, contact in enumerate(data["contacts"]):
        company_id = contact.get("companyId")
        if company_id:
            _require(company_id in ids["companies"], f"contacts[{index}].companyId", "Empresa referenciada não existe")

    quote_ids: set[str] = set()
    for index, deal in enumerate(data["deals"]):
        for field, module in (("companyId", "companies"), ("contactId", "contacts")):
            linked_id = deal.get(field)
            if linked_id:
                _require(linked_id in ids[module], f"deals[{index}].{field}", "Registro referenciado não existe")
        _require_user(deal.get("stageChangedById"), users, f"deals[{index}].stageChangedById")
        for history_index, history in enumerate(deal.get("stageHistory") or []):
            _require_user(history.get("byId"), users, f"deals[{index}].stageHistory[{history_index}].byId")
        for quote_index, quote in enumerate(deal.get("quotes") or []):
            quote_id = quote.get("id")
            path = f"deals[{index}].quotes[{quote_index}].id"
            _require(isinstance(quote_id, str) and bool(quote_id), path, "ID obrigatório")
            _require(quote_id not in quote_ids, path, "ID duplicado")
            quote_ids.add(quote_id)

    for index, notification in enumerate(data["notifications"]):
        _require_user(notification.get("userId"), users, f"notifications[{index}].userId")

    definition_keys: dict[str, set[str]] = {}
    schemas = data.get("customFieldSchemas") or {}
    for module in MODULES:
        found: set[str] = set()
        for index, definition in enumerate(schemas.get(module) or []):
            key = definition.get("key")
            path = f"customFieldSchemas.{module}[{index}].key"
            _require(isinstance(key, str) and bool(key), path, "Chave obrigatória")
            _require(key not in found, path, "Chave duplicada")
            found.add(key)
        definition_keys[module] = found
        for record_index, record in enumerate(data[module]):
            for field_index, field in enumerate(record.get("customFields") or []):
                key = field.get("key")
                path = f"{module}[{record_index}].customFields[{field_index}].key"
                _require(key in found, path, "Definição de campo personalizado não existe")

    ui = data.get("ui") or {}
    for index, saved_filter in enumerate(ui.get("savedFilters") or []):
        _require_user(saved_filter.get("userId"), users, f"ui.savedFilters[{index}].userId")
    for mapping_name in ("viewModesByUser", "dashboardScopeByUser"):
        for user_id in (ui.get(mapping_name) or {}):
            _require(user_id in users, f"ui.{mapping_name}.{user_id}", "Usuário referenciado não existe")


def count_state(state: WorkspaceState) -> PersistedCounts:
    data = state.model_dump(by_alias=True, exclude_none=True)
    return PersistedCounts(
        users=len(data["users"]),
        leads=len(data["leads"]),
        contacts=len(data["contacts"]),
        companies=len(data["companies"]),
        deals=len(data["deals"]),
        quotes=sum(len(deal.get("quotes") or []) for deal in data["deals"]),
        notifications=len(data["notifications"]),
        customFields=sum(
            len((data.get("customFieldSchemas") or {}).get(module) or [])
            for module in MODULES
        ),
    )
