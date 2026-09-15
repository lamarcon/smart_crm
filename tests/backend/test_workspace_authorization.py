from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from app.policies import PrincipalScope
from app.repositories.workspace import team_id_for_name
from app.schemas import WorkspaceState
from app.services.workspace import (
    WorkspaceAuthorizationError,
    merge_authorized_state,
    project_workspace_state,
)


TEAM_ALPHA = team_id_for_name("Alpha")
TEAM_BETA = team_id_for_name("Beta")
TENANT_ID = uuid4()


def principal(role: str) -> PrincipalScope:
    identities = {
        "Administrador": ("u-admin", TEAM_ALPHA),
        "Gestor": ("u-manager", TEAM_ALPHA),
        "Vendedor": ("u-seller", TEAM_BETA),
        "Assistente": ("u-assistant", TEAM_BETA),
        "Faturamento": ("u-billing", TEAM_BETA),
    }
    user_id, team_id = identities.get(role, ("u-forged", TEAM_BETA))
    return PrincipalScope(
        tenant_id=TENANT_ID,
        workspace_id="default",
        user_id=user_id,
        role=role,
        team_id=team_id,
        auth_version=3,
    )


def canonical_data() -> dict:
    users = [
        {"id": "u-admin", "name": "Admin", "role": "Administrador", "team": "Alpha"},
        {"id": "u-manager", "name": "Manager", "role": "Gestor", "team": "Alpha"},
        {"id": "u-seller", "name": "Seller", "role": "Vendedor", "team": "Beta"},
        {"id": "u-assistant", "name": "Assistant", "role": "Assistente", "team": "Beta"},
        {"id": "u-billing", "name": "Billing", "role": "Faturamento", "team": "Beta"},
        {"id": "u-other", "name": "Other", "role": "Vendedor", "team": "Beta"},
    ]
    leads = [
        {"id": "L-team", "name": "Team", "team": "Alpha", "responsibleId": "u-other", "assistants": []},
        {"id": "L-seller", "name": "Seller", "team": "Beta", "responsibleId": "u-seller", "assistants": []},
        {"id": "L-seller-assist", "name": "Seller assist", "team": "Beta", "responsibleId": "u-other", "assistants": ["u-seller"]},
        {"id": "L-assistant", "name": "Assistant", "team": "Beta", "responsibleId": "u-other", "assistants": ["u-assistant"]},
        {"id": "L-billing", "name": "Billing", "team": "Beta", "responsibleId": "u-other", "assistants": ["u-billing"]},
        {"id": "L-hidden", "name": "Hidden", "team": "Beta", "responsibleId": "u-other", "assistants": []},
    ]
    deals = [
        {
            "id": lead["id"].replace("L-", "D-"),
            "title": lead["name"],
            "team": lead["team"],
            "responsibleId": lead["responsibleId"],
            "assistants": list(lead["assistants"]),
        }
        for lead in leads
    ]
    return {
        "currentUserId": "u-admin",
        "users": users,
        "leads": leads,
        "contacts": [{"id": "C-1", "name": "Contact"}],
        "companies": [{"id": "E-1", "name": "Company"}],
        "deals": deals,
        "notifications": [
            {"id": "N-seller", "userId": "u-seller", "text": "Mine"},
            {"id": "N-assistant", "userId": "u-assistant", "text": "Mine"},
            {"id": "N-billing", "userId": "u-billing", "text": "Mine"},
            {"id": "N-other", "userId": "u-other", "text": "Hidden"},
        ],
        "customFieldSchemas": {
            "leads": [{"key": "secret", "label": "Secret", "type": "text"}],
            "contacts": [], "companies": [], "deals": [],
        },
        "moduleFieldSettings": {
            module: {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []}
            for module in ("leads", "contacts", "companies", "deals")
        },
        "ui": {
            "savedFilters": [
                {"id": "SF-seller", "userId": "u-seller", "scope": "leads", "name": "Mine", "filter": {}, "updatedAt": "2026-09-15T00:00:00Z"},
                {"id": "SF-assistant", "userId": "u-assistant", "scope": "leads", "name": "Mine", "filter": {}, "updatedAt": "2026-09-15T00:00:00Z"},
                {"id": "SF-billing", "userId": "u-billing", "scope": "leads", "name": "Mine", "filter": {}, "updatedAt": "2026-09-15T00:00:00Z"},
                {"id": "SF-other", "userId": "u-other", "scope": "leads", "name": "Hidden", "filter": {}, "updatedAt": "2026-09-15T00:00:00Z"},
            ],
            "viewModesByUser": {
                "u-seller": {"leads": "list"},
                "u-assistant": {"leads": "kanban"},
                "u-billing": {"deals": "list"},
                "u-other": {"leads": "kanban"},
            },
            "dashboardScopeByUser": {
                "u-seller": "leads",
                "u-assistant": "deals",
                "u-billing": "all",
                "u-other": "all",
            },
        },
    }


def canonical_state() -> WorkspaceState:
    return WorkspaceState.model_validate(canonical_data())


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("Administrador", {"L-team", "L-seller", "L-seller-assist", "L-assistant", "L-billing", "L-hidden"}),
        ("Gestor", {"L-team"}),
        ("Vendedor", {"L-seller", "L-seller-assist"}),
        ("Assistente", {"L-assistant"}),
        ("Faturamento", {"L-billing"}),
    ],
)
def test_projection_filters_leads_and_deals_by_server_principal(
    role: str,
    expected: set[str],
) -> None:
    projected = project_workspace_state(canonical_state(), principal(role))

    assert {item["id"] for item in projected.leads} == expected
    assert {item["id"].replace("D-", "L-") for item in projected.deals} == expected
    assert projected.current_user_id is None


@pytest.mark.parametrize("role", ["Vendedor", "Assistente", "Faturamento"])
def test_projection_limits_notifications_and_ui_preferences_to_current_user(role: str) -> None:
    scope = principal(role)
    projected = project_workspace_state(canonical_state(), scope)
    ui = projected.ui

    assert {item["userId"] for item in projected.notifications} == {scope.user_id}
    assert {item["userId"] for item in ui["savedFilters"]} == {scope.user_id}
    assert set(ui["viewModesByUser"]) == {scope.user_id}
    assert set(ui["dashboardScopeByUser"]) == {scope.user_id}


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
def test_authorized_save_updates_visible_and_preserves_invisible_records(role: str) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    submitted.leads[0]["name"] = "Authorized update"

    merged = merge_authorized_state(canonical, submitted, scope)

    assert next(item for item in merged.leads if item["id"] == submitted.leads[0]["id"])["name"] == "Authorized update"
    assert next(item for item in merged.leads if item["id"] == "L-hidden")["name"] == "Hidden"


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
def test_authorized_delete_removes_visible_but_preserves_invisible_records(role: str) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    deleted_id = submitted.leads.pop(0)["id"]

    merged = merge_authorized_state(canonical, submitted, scope)

    assert deleted_id not in {item["id"] for item in merged.leads}
    assert "L-hidden" in {item["id"] for item in merged.leads}


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
def test_forged_invisible_record_update_is_rejected(role: str) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    forged = deepcopy(next(item for item in canonical.leads if item["id"] == "L-hidden"))
    forged["name"] = "Stolen"
    submitted.leads.append(forged)

    with pytest.raises(WorkspaceAuthorizationError, match="record is outside principal scope"):
        merge_authorized_state(canonical, submitted, scope)


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
def test_new_record_outside_principal_scope_is_rejected(role: str) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    submitted.leads.append(
        {"id": "L-forged", "name": "Forged", "team": "Other", "responsibleId": "u-other", "assistants": []}
    )

    with pytest.raises(WorkspaceAuthorizationError, match="record is outside principal scope"):
        merge_authorized_state(canonical, submitted, scope)


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
@pytest.mark.parametrize("privileged", ["users", "customFieldSchemas", "moduleFieldSettings"])
def test_non_admin_privileged_snapshot_changes_are_rejected(
    role: str,
    privileged: str,
) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    payload = submitted.model_dump(by_alias=True, exclude_none=True)
    if privileged == "users":
        payload["users"][0]["role"] = "Faturamento"
    elif privileged == "customFieldSchemas":
        payload[privileged]["leads"][0]["label"] = "Forged"
    else:
        payload[privileged]["leads"]["hiddenStandardFields"] = ["name"]

    with pytest.raises(WorkspaceAuthorizationError, match="administrative snapshot change"):
        merge_authorized_state(canonical, WorkspaceState.model_validate(payload), scope)


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
def test_forged_other_user_preferences_are_rejected(role: str) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    submitted.ui["viewModesByUser"]["u-other"] = {"leads": "list"}

    with pytest.raises(WorkspaceAuthorizationError, match="preference is outside principal scope"):
        merge_authorized_state(canonical, submitted, scope)


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
def test_forged_other_user_notification_is_rejected(role: str) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    submitted.notifications.append({"id": "N-forged", "userId": "u-other", "text": "Forged"})

    with pytest.raises(WorkspaceAuthorizationError, match="notification is outside principal scope"):
        merge_authorized_state(canonical, submitted, scope)


@pytest.mark.parametrize(
    "role",
    ["Administrador", "Gestor", "Vendedor", "Assistente", "Faturamento"],
)
def test_browser_current_user_never_changes_effective_identity(role: str) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    submitted.current_user_id = "u-admin" if scope.user_id != "u-admin" else "u-other"

    merged = merge_authorized_state(canonical, submitted, scope)

    assert merged.current_user_id is None


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
def test_contacts_and_companies_remain_tenant_wide_mutable(role: str) -> None:
    scope = principal(role)
    canonical = canonical_state()
    submitted = project_workspace_state(canonical, scope)
    submitted.contacts[0]["name"] = "Updated contact"
    submitted.companies[0]["name"] = "Updated company"

    merged = merge_authorized_state(canonical, submitted, scope)

    assert merged.contacts[0]["name"] == "Updated contact"
    assert merged.companies[0]["name"] == "Updated company"


def test_unknown_server_role_fails_closed_for_projection_and_merge() -> None:
    forged = principal("Owner")

    with pytest.raises(WorkspaceAuthorizationError, match="principal is not authorized"):
        project_workspace_state(canonical_state(), forged)
    with pytest.raises(WorkspaceAuthorizationError, match="principal is not authorized"):
        merge_authorized_state(canonical_state(), canonical_state(), forged)
