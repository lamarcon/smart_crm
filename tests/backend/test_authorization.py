from __future__ import annotations

from uuid import uuid4

import pytest

from app.policies import (
    Action,
    PrincipalScope,
    RecordScope,
    can_mutate_record,
    can_perform_action,
    can_read_record,
)


TENANT_ID = uuid4()


def principal(role: str, *, user_id: str = "u-current", team_id: str = "team-a") -> PrincipalScope:
    return PrincipalScope(
        tenant_id=TENANT_ID,
        workspace_id="default",
        user_id=user_id,
        role=role,
        team_id=team_id,
        auth_version=1,
    )


@pytest.mark.parametrize(
    "role",
    ["Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento"],
)
@pytest.mark.parametrize("module", ["contacts", "companies"])
def test_all_current_roles_read_and_mutate_tenant_wide_records(role: str, module: str) -> None:
    subject = principal(role)
    record = RecordScope(responsible_id="u-other", assistant_ids=(), team_id="team-b")

    assert can_read_record(subject, module, record) is True
    assert can_mutate_record(subject, module, record) is True


@pytest.mark.parametrize("module", ["leads", "deals"])
def test_administrator_reads_and_mutates_any_business_record(module: str) -> None:
    subject = principal("Administrador")
    record = RecordScope(responsible_id="u-other", assistant_ids=(), team_id="team-b")

    assert can_read_record(subject, module, record) is True
    assert can_mutate_record(subject, module, record) is True


@pytest.mark.parametrize("module", ["leads", "deals"])
def test_manager_scope_is_the_record_team(module: str) -> None:
    subject = principal("Gestor")

    assert can_read_record(
        subject,
        module,
        RecordScope(responsible_id="u-other", assistant_ids=(), team_id="team-a"),
    ) is True
    assert can_mutate_record(
        subject,
        module,
        RecordScope(responsible_id="u-current", assistant_ids=("u-current",), team_id="team-b"),
    ) is False


@pytest.mark.parametrize("role", ["Vendedor", "Assistente", "Faturamento"])
@pytest.mark.parametrize("module", ["leads", "deals"])
def test_individual_roles_use_responsible_or_assistant_scope(role: str, module: str) -> None:
    subject = principal(role)
    responsible = RecordScope(responsible_id="u-current", assistant_ids=(), team_id="team-b")
    assisted = RecordScope(responsible_id="u-other", assistant_ids=("u-current",), team_id="team-b")
    unrelated = RecordScope(responsible_id="u-other", assistant_ids=("u-third",), team_id="team-a")

    assert can_read_record(subject, module, responsible) is True
    assert can_mutate_record(subject, module, assisted) is True
    assert can_read_record(subject, module, unrelated) is False
    assert can_mutate_record(subject, module, unrelated) is False


@pytest.mark.parametrize(
    "action",
    [
        Action.MANAGE_USERS,
        Action.MANAGE_FIELDS,
        Action.IMPORT_DATA,
        Action.RESET_WORKSPACE,
        Action.RESTORE_DELETED,
        Action.MANAGE_PIPELINE,
    ],
)
def test_administrative_actions_are_admin_only(action: Action) -> None:
    assert can_perform_action(principal("Administrador"), action) is True
    assert can_perform_action(principal("Gestor"), action) is False
    assert can_perform_action(principal("Vendedor"), action) is False
    assert can_perform_action(principal("Assistente"), action) is False
    assert can_perform_action(principal("Faturamento"), action) is False


@pytest.mark.parametrize("action", [Action.READ, Action.CREATE, Action.UPDATE, Action.DELETE])
@pytest.mark.parametrize(
    "role",
    ["Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento"],
)
def test_current_roles_have_explicit_business_action_outcomes(role: str, action: Action) -> None:
    assert can_perform_action(principal(role), action) is True


@pytest.mark.parametrize("forged_role", ["admin", "ADMINISTRADOR", "Owner", "", "Gestor "])
def test_forged_or_unknown_roles_are_denied(forged_role: str) -> None:
    subject = principal(forged_role)
    record = RecordScope(responsible_id="u-current", assistant_ids=("u-current",), team_id="team-a")

    assert can_perform_action(subject, Action.READ) is False
    assert can_read_record(subject, "contacts", record) is False
    assert can_mutate_record(subject, "leads", record) is False


@pytest.mark.parametrize("module", ["users", "notifications", "unknown", "", "workspace"])
def test_unspecified_record_modules_fail_closed(module: str) -> None:
    subject = principal("Administrador")
    record = RecordScope(responsible_id="u-current", assistant_ids=(), team_id="team-a")

    assert can_read_record(subject, module, record) is False
    assert can_mutate_record(subject, module, record) is False
