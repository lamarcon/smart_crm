"""Stored role permissions of a workspace (table ``role_permissions``).

Only cells that differ from nothing are required: a missing row means the
default of ``app.policies.DEFAULT_PERMISSIONS``. Queries are explicit SQL so a
tenant database still on an older schema (before the table existed) keeps
working with the defaults.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.policies import CONFIGURABLE_ROLES, MODULES, allowed_scopes, module_actions


def _table_exists(session: Session) -> bool:
    return session.scalar(text("SELECT to_regclass('role_permissions') IS NOT NULL")) is True


def read_role_permissions(session: Session, workspace_id: str, role: str) -> tuple[tuple[str, str, str], ...]:
    if role not in CONFIGURABLE_ROLES or not _table_exists(session):
        return ()
    rows = session.execute(
        text(
            "SELECT module, action, scope FROM role_permissions "
            "WHERE workspace_id = :workspace_id AND role = :role ORDER BY module, action"
        ),
        {"workspace_id": workspace_id, "role": role},
    ).all()
    return tuple((row.module, row.action, row.scope) for row in rows)


def read_all_role_permissions(session: Session, workspace_id: str) -> dict[str, tuple[tuple[str, str, str], ...]]:
    stored: dict[str, list[tuple[str, str, str]]] = {role: [] for role in CONFIGURABLE_ROLES}
    if _table_exists(session):
        rows = session.execute(
            text(
                "SELECT role, module, action, scope FROM role_permissions "
                "WHERE workspace_id = :workspace_id ORDER BY role, module, action"
            ),
            {"workspace_id": workspace_id},
        ).all()
        for row in rows:
            if row.role in stored:
                stored[row.role].append((row.module, row.action, row.scope))
    return {role: tuple(cells) for role, cells in stored.items()}


class InvalidPermissionError(ValueError):
    """A submitted cell names an unknown role, module or action, or a scope it does not accept."""


def validate_matrix(matrix: Mapping[str, Mapping[str, Mapping[str, str]]]) -> list[tuple[str, str, str, str]]:
    """Checks a full ``{role: {module: {action: scope}}}`` matrix and flattens it."""

    if set(matrix) != set(CONFIGURABLE_ROLES):
        raise InvalidPermissionError("roles")
    rows: list[tuple[str, str, str, str]] = []
    for role in CONFIGURABLE_ROLES:
        modules = matrix[role]
        if not isinstance(modules, Mapping) or set(modules) != set(MODULES):
            raise InvalidPermissionError(f"{role}: modules")
        for module in MODULES:
            actions = modules[module]
            if not isinstance(actions, Mapping) or set(actions) != set(module_actions(module)):
                raise InvalidPermissionError(f"{role}.{module}: actions")
            for action in module_actions(module):
                scope = actions[action]
                if scope not in allowed_scopes(module, action):
                    raise InvalidPermissionError(f"{role}.{module}.{action}")
                rows.append((role, module, action, scope))
    return rows


def replace_role_permissions(session: Session, workspace_id: str, rows: Iterable[tuple[str, str, str, str]]) -> None:
    session.execute(
        text("DELETE FROM role_permissions WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    payload = [
        {"workspace_id": workspace_id, "role": role, "module": module, "action": action, "scope": scope}
        for role, module, action, scope in rows
    ]
    if payload:
        session.execute(
            text(
                "INSERT INTO role_permissions (workspace_id, role, module, action, scope) "
                "VALUES (:workspace_id, :role, :module, :action, :scope)"
            ),
            payload,
        )


def owner_team_id(session: Session, workspace_id: str, owner_id: str | None) -> str | None:
    """The team of a company's responsible person (companies have no team of their own)."""

    if not owner_id:
        return None
    return session.scalar(
        text("SELECT team_id FROM crm_users WHERE workspace_id = :workspace_id AND id = :user_id"),
        {"workspace_id": workspace_id, "user_id": owner_id},
    )
