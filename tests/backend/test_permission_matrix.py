"""Permission matrix: defaults reproduce the fixed rules; stored rows change them."""

from __future__ import annotations

import itertools
from uuid import uuid4

import pytest

from app.policies import (
    DEFAULT_PERMISSIONS,
    MODULE_ACTIONS,
    MODULES,
    PrincipalScope,
    RecordScope,
    allowed,
    allowed_scopes,
    can_manage_products,
    can_mutate_record,
    can_read_record,
    effective_permissions,
    permission_scope,
    permissions_payload,
    record_allowed,
)

ROLES = ("Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento")
USERS = ("u-current", "u-other", None)
TEAMS = ("team-a", "team-b", None)


def principal(role: str, *, team_id: str | None = "team-a", permissions=None) -> PrincipalScope:  # noqa: ANN001
    return PrincipalScope(
        tenant_id=uuid4(),
        workspace_id="default",
        user_id="u-current",
        role=role,
        team_id=team_id,
        auth_version=1,
        permissions=permissions,
    )


def _legacy_access(subject: PrincipalScope, module: str, record: RecordScope) -> bool:
    """The rule app/policies.py had before the matrix (kept here as the reference)."""

    if module in {"contacts", "companies"}:
        return True
    if module not in {"leads", "deals"}:
        return False
    if subject.role == "Administrador":
        return True
    if subject.role == "Gestor":
        return bool(subject.team_id) and record.team_id == subject.team_id
    return subject.user_id == record.responsible_id or subject.user_id in record.assistant_ids


def _records():  # noqa: ANN202
    for responsible, team, assisted in itertools.product(USERS, TEAMS, (False, True)):
        yield RecordScope(
            responsible_id=responsible,
            assistant_ids=("u-current",) if assisted else ("u-third",),
            team_id=team,
        )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("team_id", ["team-a", None])
@pytest.mark.parametrize("module", ["leads", "deals", "contacts", "companies"])
def test_default_matrix_reproduces_the_previous_fixed_rules(role: str, team_id, module: str) -> None:  # noqa: ANN001
    subject = principal(role, team_id=team_id)
    for record in _records():
        expected = _legacy_access(subject, module, record)
        assert can_read_record(subject, module, record) is expected, (role, module, record)
        assert can_mutate_record(subject, module, record) is expected, (role, module, record)
        # Deleting used to follow the same rule as editing.
        assert record_allowed(subject, module, "delete", record) is expected, (role, module, record)


@pytest.mark.parametrize("role", ROLES)
def test_default_product_and_flag_permissions_match_previous_behaviour(role: str) -> None:
    subject = principal(role)
    assert can_manage_products(subject) is (role in {"Administrador", "Gestor"})
    assert allowed(subject, "products", "read") is True
    for module in MODULES:
        manages = module != "products" or role in {"Administrador", "Gestor"}
        assert allowed(subject, module, "create") is manages
        assert allowed(subject, module, "delete") is manages
        # Import was Administrador-only; export is new and starts with the Administrador only.
        assert allowed(subject, module, "import") is (role == "Administrador")
        assert allowed(subject, module, "export") is (role == "Administrador")


def test_every_default_cell_is_a_valid_choice() -> None:
    for role, matrix in DEFAULT_PERMISSIONS.items():
        assert set(matrix) == {(module, action) for module in MODULES for action in MODULE_ACTIONS}, role
        for (module, action), scope in matrix.items():
            assert scope in allowed_scopes(module, action), (role, module, action)


def test_allowed_scopes_depend_on_module_and_action() -> None:
    assert allowed_scopes("deals", "read") == ("none", "own", "team", "all")
    assert allowed_scopes("companies", "delete") == ("none", "own", "team", "all")
    assert allowed_scopes("contacts", "read") == ("none", "all")
    assert allowed_scopes("products", "update") == ("none", "all")
    assert allowed_scopes("deals", "create") == ("none", "all")
    assert allowed_scopes("deals", "export") == ("none", "all")
    assert allowed_scopes("quotes", "read") == ()
    assert allowed_scopes("deals", "approve") == ()


def test_stored_rows_override_defaults_and_invalid_rows_are_ignored() -> None:
    stored = (
        ("leads", "read", "team"),
        ("leads", "delete", "none"),
        ("deals", "export", "all"),
        ("contacts", "read", "own"),  # not a valid scope for contacts
        ("quotes", "read", "all"),  # unknown module
    )
    matrix = effective_permissions("Vendedor", stored)
    assert matrix[("leads", "read")] == "team"
    assert matrix[("leads", "delete")] == "none"
    assert matrix[("deals", "export")] == "all"
    assert matrix[("contacts", "read")] == "all"
    assert ("quotes", "read") not in matrix


def test_the_administrator_cannot_be_restricted() -> None:
    subject = principal("Administrador", permissions=(("deals", "read", "none"), ("leads", "delete", "none")))
    assert permission_scope(subject, "deals", "read") == "all"
    assert allowed(subject, "leads", "delete") is True


def test_unknown_roles_modules_and_actions_get_nothing() -> None:
    assert permission_scope(principal("Visitante"), "deals", "read") == "none"
    assert permission_scope(principal("Gestor"), "quotes", "read") == "none"
    assert permission_scope(principal("Gestor"), "deals", "approve") == "none"
    assert can_read_record(principal("Visitante"), "contacts", RecordScope(None, (), None)) is False


def test_stored_scopes_drive_record_decisions() -> None:
    subject = principal(
        "Vendedor",
        permissions=(("deals", "read", "team"), ("deals", "update", "own"), ("deals", "delete", "none")),
    )
    teammate = RecordScope(responsible_id="u-other", assistant_ids=(), team_id="team-a")
    mine = RecordScope(responsible_id="u-current", assistant_ids=(), team_id="team-b")
    assert can_read_record(subject, "deals", teammate) is True
    assert can_mutate_record(subject, "deals", teammate) is False
    assert can_mutate_record(subject, "deals", mine) is True
    assert record_allowed(subject, "deals", "delete", mine) is False
    without_team = principal("Vendedor", team_id=None, permissions=(("deals", "read", "team"),))
    assert can_read_record(without_team, "deals", RecordScope("u-other", (), None)) is False


def test_permissions_payload_lists_every_module_and_action() -> None:
    payload = permissions_payload(effective_permissions("Faturamento"))
    assert list(payload) == list(MODULES)
    assert payload["leads"] == {"read": "own", "create": "all", "update": "own", "delete": "own", "import": "none", "export": "none"}
    assert payload["products"]["update"] == "none"


def test_deal_sql_filter_follows_the_read_scope_only() -> None:
    from sqlalchemy.dialects import postgresql

    from app.policies import deal_visibility_predicate

    def sql(subject: PrincipalScope) -> str:
        return str(deal_visibility_predicate(subject).compile(dialect=postgresql.dialect()))

    wide_read = principal("Vendedor", permissions=(("deals", "read", "all"), ("deals", "update", "none")))
    assert "responsible_id" not in sql(wide_read) and "team_id" not in sql(wide_read)
    team_read = principal("Vendedor", permissions=(("deals", "read", "team"), ("deals", "update", "all")))
    assert "team_id" in sql(team_read)
    no_read = principal("Vendedor", permissions=(("deals", "read", "none"), ("deals", "update", "all")))
    assert "false" in sql(no_read).lower()
