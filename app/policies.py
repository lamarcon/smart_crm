"""Server-side CRM authorization policy.

Business access is a permission matrix: for each role, module and action a
scope says which records the action reaches. Each workspace may store its own
matrix (table ``role_permissions``); anything not stored falls back to
``DEFAULT_PERMISSIONS``, which reproduces the rules the CRM always had. The
Administrador always has every permission and cannot be restricted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping
from uuid import UUID

from sqlalchemy import and_, exists, false, or_, select
from sqlalchemy.sql.elements import ColumnElement


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
    MANAGE_PIPELINE = "manage_pipeline"


ADMIN_ROLE = "Administrador"
CURRENT_ROLES = frozenset(
    {"Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento"}
)
CONFIGURABLE_ROLES = ("Gestor", "Vendedor", "Assistente", "Faturamento")
BUSINESS_ACTIONS = frozenset({Action.READ, Action.CREATE, Action.UPDATE, Action.DELETE})
ADMIN_ACTIONS = frozenset(
    {
        Action.MANAGE_USERS,
        Action.MANAGE_FIELDS,
        Action.IMPORT_DATA,
        Action.RESET_WORKSPACE,
        Action.RESTORE_DELETED,
        Action.MANAGE_PIPELINE,
    }
)

# --- Permission matrix -----------------------------------------------------------------

MODULES = ("leads", "contacts", "companies", "deals", "products")
# Actions that reach records with a scope, and actions that are simply allowed or not.
SCOPED_ACTIONS = ("read", "update", "delete")
FLAG_ACTIONS = ("create", "import", "export", "price")
MODULE_ACTIONS = ("read", "create", "update", "delete", "import", "export")
# Actions only some modules have: "price" lets a role change the price of a deal's
# quote items or give them a discount.
EXTRA_ACTIONS: dict[str, tuple[str, ...]] = {"deals": ("price",)}
SCOPE_NONE, SCOPE_OWN, SCOPE_TEAM, SCOPE_ALL = "none", "own", "team", "all"
SCOPES = (SCOPE_NONE, SCOPE_OWN, SCOPE_TEAM, SCOPE_ALL)
# Modules whose records have a responsible person and a team.
OWNED_MODULES = frozenset({"leads", "deals", "companies"})

PermissionKey = tuple[str, str]  # (module, action)


def module_actions(module: str) -> tuple[str, ...]:
    return MODULE_ACTIONS + EXTRA_ACTIONS.get(module, ())


def allowed_scopes(module: str, action: str) -> tuple[str, ...]:
    """Scopes an administrator may choose for one module and action."""

    if module not in MODULES or action not in module_actions(module):
        return ()
    if action in FLAG_ACTIONS or module not in OWNED_MODULES:
        return (SCOPE_NONE, SCOPE_ALL)
    return SCOPES


def _matrix(rows: Mapping[str, Mapping[str, str]]) -> dict[PermissionKey, str]:
    return {(module, action): scope for module, actions in rows.items() for action, scope in actions.items()}


_ALL = {action: SCOPE_ALL for action in MODULE_ACTIONS}
_ALL_DEALS = {**_ALL, "price": SCOPE_ALL}
_OPEN_RECORDS = {"read": SCOPE_ALL, "create": SCOPE_ALL, "update": SCOPE_ALL, "delete": SCOPE_ALL, "import": SCOPE_NONE, "export": SCOPE_NONE}
_PRODUCTS_READ_ONLY = {"read": SCOPE_ALL, "create": SCOPE_NONE, "update": SCOPE_NONE, "delete": SCOPE_NONE, "import": SCOPE_NONE, "export": SCOPE_NONE}


def _scoped(scope: str) -> dict[str, str]:
    return {"read": scope, "create": SCOPE_ALL, "update": scope, "delete": scope, "import": SCOPE_NONE, "export": SCOPE_NONE}


_INDIVIDUAL = _matrix(
    {
        "leads": _scoped(SCOPE_OWN),
        "deals": {**_scoped(SCOPE_OWN), "price": SCOPE_NONE},
        "contacts": _OPEN_RECORDS,
        "companies": _OPEN_RECORDS,
        "products": _PRODUCTS_READ_ONLY,
    }
)

# The rules the CRM had before permissions became configurable.
DEFAULT_PERMISSIONS: dict[str, dict[PermissionKey, str]] = {
    "Administrador": _matrix({module: _ALL_DEALS if module == "deals" else _ALL for module in MODULES}),
    "Gestor": _matrix(
        {
            "leads": _scoped(SCOPE_TEAM),
            "deals": {**_scoped(SCOPE_TEAM), "price": SCOPE_ALL},
            "contacts": _OPEN_RECORDS,
            "companies": _OPEN_RECORDS,
            "products": {**_OPEN_RECORDS},
        }
    ),
    "Vendedor": dict(_INDIVIDUAL),
    "Assistente": dict(_INDIVIDUAL),
    "Faturamento": dict(_INDIVIDUAL),
}


def effective_permissions(
    role: str, stored: Iterable[tuple[str, str, str]] = ()
) -> dict[PermissionKey, str]:
    """The role's matrix: the defaults overlaid with valid stored rows."""

    if role not in CURRENT_ROLES:
        return {(module, action): SCOPE_NONE for module in MODULES for action in module_actions(module)}
    matrix = dict(DEFAULT_PERMISSIONS[role])
    if role == ADMIN_ROLE:
        return matrix
    for module, action, scope in stored:
        if scope in allowed_scopes(module, action):
            matrix[(module, action)] = scope
    return matrix


def permissions_payload(matrix: Mapping[PermissionKey, str]) -> dict[str, dict[str, str]]:
    """``{module: {action: scope}}`` for JSON answers."""

    return {
        module: {action: matrix.get((module, action), SCOPE_NONE) for action in module_actions(module)}
        for module in MODULES
    }


@dataclass(frozen=True)
class PrincipalScope:
    tenant_id: UUID
    workspace_id: str
    user_id: str
    role: str
    team_id: str | None
    auth_version: int
    # ((module, action, scope), ...) stored for the role; None means the defaults.
    permissions: tuple[tuple[str, str, str], ...] | None = None


@dataclass(frozen=True)
class RecordScope:
    responsible_id: str | None
    assistant_ids: tuple[str, ...]
    team_id: str | None


def permission_scope(principal: PrincipalScope, module: str, action: str) -> str:
    if principal.role not in CURRENT_ROLES or module not in MODULES or action not in module_actions(module):
        return SCOPE_NONE
    if principal.role == ADMIN_ROLE:
        return SCOPE_ALL
    matrix = effective_permissions(principal.role, principal.permissions or ())
    return matrix.get((module, action), SCOPE_NONE)


def allowed(principal: PrincipalScope, module: str, action: str) -> bool:
    """Whether the role may perform the action on at least some records."""

    return permission_scope(principal, module, action) != SCOPE_NONE


def scope_covers(principal: PrincipalScope, scope: str, record: RecordScope) -> bool:
    if scope == SCOPE_ALL:
        return True
    if scope == SCOPE_TEAM:
        return bool(principal.team_id) and record.team_id == principal.team_id
    if scope == SCOPE_OWN:
        return principal.user_id == record.responsible_id or principal.user_id in record.assistant_ids
    return False


def record_allowed(
    principal: PrincipalScope, module: str, action: str, record: RecordScope
) -> bool:
    return scope_covers(principal, permission_scope(principal, module, action), record)


def can_perform_action(principal: PrincipalScope, action: Action) -> bool:
    if principal.role not in CURRENT_ROLES or not isinstance(action, Action):
        return False
    if action in ADMIN_ACTIONS:
        return principal.role == ADMIN_ROLE
    return action in BUSINESS_ACTIONS


def can_manage_products(principal: PrincipalScope) -> bool:
    """Whether the role may change the product catalog."""

    return can_perform_action(principal, Action.UPDATE) and allowed(principal, "products", "update")


def can_read_record(principal: PrincipalScope, module: str, record: RecordScope) -> bool:
    return can_perform_action(principal, Action.READ) and record_allowed(
        principal, module, "read", record
    )


def can_mutate_record(principal: PrincipalScope, module: str, record: RecordScope) -> bool:
    return can_perform_action(principal, Action.UPDATE) and record_allowed(
        principal, module, "update", record
    )


def deal_visibility_predicate(principal: PrincipalScope) -> ColumnElement[bool]:
    """Return the SQL equivalent of the Deal read policy for one bound principal."""

    if not isinstance(principal, PrincipalScope):
        raise TypeError("principal scope is required")

    # Local import keeps the policy dataclasses independent from ORM model import order.
    from app.models import Deal, DealAssistant

    workspace_scope = Deal.workspace_id == principal.workspace_id
    scope = permission_scope(principal, "deals", "read")
    if scope == SCOPE_ALL:
        return workspace_scope
    if scope == SCOPE_TEAM:
        if not principal.team_id:
            return and_(workspace_scope, false())
        return and_(workspace_scope, Deal.team_id == principal.team_id)
    if scope != SCOPE_OWN:
        return and_(workspace_scope, false())

    assisted = exists(
        select(1).where(
            DealAssistant.workspace_id == Deal.workspace_id,
            DealAssistant.deal_id == Deal.id,
            DealAssistant.user_id == principal.user_id,
        )
    )
    return and_(
        workspace_scope,
        or_(Deal.responsible_id == principal.user_id, assisted),
    )
