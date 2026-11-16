"""Lead tracking is recorded by the intake API only: workspace saves keep it intact."""

from __future__ import annotations

from app.schemas import WorkspaceState
from tests.backend.test_workspace_service import service, state_data  # noqa: F401

TRACKING = {"channel": "Instagram", "tool": "bot-instagram", "externalId": "ig-123", "receivedAt": "2026-11-16T12:00:00+00:00"}


def tracked_state() -> dict:
    data = state_data()
    data["leads"][0]["source"] = "Instagram"
    data["leads"][0]["tracking"] = dict(TRACKING)
    return data


def saved_leads(workspace, mutate):  # noqa: ANN001, ANN201
    loaded = workspace.load()
    data = loaded.state.model_dump(by_alias=True, exclude_none=True)
    mutate(data)
    return {lead["id"]: lead for lead in workspace.save(loaded.version, WorkspaceState.model_validate(data)).state.leads}


def test_tracking_survives_ordinary_saves(service) -> None:  # noqa: F811
    workspace, _database = service
    workspace.bootstrap(WorkspaceState.model_validate(tracked_state()))
    leads = saved_leads(workspace, lambda data: data["leads"][0].update(phone="(11) 99999-0000"))
    assert leads["L-1"]["tracking"] == TRACKING
    assert leads["L-1"]["phone"] == "(11) 99999-0000"


def test_a_save_cannot_forge_or_erase_tracking(service) -> None:  # noqa: F811
    workspace, _database = service
    workspace.bootstrap(WorkspaceState.model_validate(tracked_state()))

    def forge(data: dict) -> None:
        data["leads"][0]["tracking"] = {"channel": "Google Ads", "campaign": "falsa"}
        data["leads"].append({**data["leads"][0], "id": "L-2", "tracking": {"channel": "Site"}})

    leads = saved_leads(workspace, forge)
    assert leads["L-1"]["tracking"] == TRACKING
    assert "tracking" not in leads["L-2"]

    leads = saved_leads(workspace, lambda data: data["leads"][0].pop("tracking"))
    assert leads["L-1"]["tracking"] == TRACKING
