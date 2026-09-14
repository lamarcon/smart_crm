"""Server-side CRM authorization policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class Action(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MANAGE_USERS = "manage_users"
    MANAGE_FIELDS = "manage_fields"
    IMPORT_DATA = "import_data"
    RESET_WORKSPACE = "reset_workspace"
    RESTORE_DELETED = "restore_deleted"


CURRENT_ROLES = frozenset(
    {"Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento"}
)
BUSINESS_ACTIONS = frozenset({Action.READ, Action.CREATE, Action.UPDATE, Action.DELETE})
ADMIN_ACTIONS = frozenset(
    {
        Action.MANAGE_USERS,
        Action.MANAGE_FIELDS,
        Action.IMPORT_DATA,
        Action.RESET_WORKSPACE,
        Action.RESTORE_DELETED,
    }
)
TENANT_WIDE_MODULES = frozenset({"contacts", "companies"})
SCOPED_MODULES = frozenset({"leads", "deals"})


@dataclass(frozen=True)
class PrincipalScope:
    tenant_id: UUID
    workspace_id: str
    user_id: str
    role: str
    team_id: str | None
    auth_version: int


@dataclass(frozen=True)
class RecordScope:
    responsible_id: str | None
    assistant_ids: tuple[str, ...]
    team_id: str | None


def can_perform_action(principal: PrincipalScope, action: Action) -> bool:
    if principal.role not in CURRENT_ROLES or not isinstance(action, Action):
        return False
    if action in ADMIN_ACTIONS:
        return principal.role == "Administrador"
    return action in BUSINESS_ACTIONS


def _can_access_record(principal: PrincipalScope, module: str, record: RecordScope) -> bool:
    if principal.role not in CURRENT_ROLES:
        return False
    if module in TENANT_WIDE_MODULES:
        return True
    if module not in SCOPED_MODULES:
        return False
    if principal.role == "Administrador":
        return True
    if principal.role == "Gestor":
        return bool(principal.team_id) and record.team_id == principal.team_id
    return principal.user_id == record.responsible_id or principal.user_id in record.assistant_ids


def can_read_record(principal: PrincipalScope, module: str, record: RecordScope) -> bool:
    return can_perform_action(principal, Action.READ) and _can_access_record(
        principal, module, record
    )


def can_mutate_record(principal: PrincipalScope, module: str, record: RecordScope) -> bool:
    return can_perform_action(principal, Action.UPDATE) and _can_access_record(
        principal, module, record
    )
