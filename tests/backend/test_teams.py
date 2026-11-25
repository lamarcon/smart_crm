"""Teams managed by the admin as part of the workspace snapshot."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.models import CrmUser, Lead, Team
from app.repositories.workspace import team_id_for_name
from app.schemas import WorkspaceState
from app.services.auth import PrincipalScope
from app.services.workspace import WorkspaceService
from tests.backend.test_deal_currency import save_as_admin
from tests.backend.test_workspace_service import TEST_PRINCIPAL, service, state_data  # noqa: F401


def stored_teams(database) -> dict[str, str]:  # noqa: ANN001
    with database.session_scope() as session:
        return {team.id: team.name for team in session.scalars(select(Team)).all()}


def test_teams_are_listed_sorted_and_include_empty_ones(service) -> None:  # noqa: F811
    workspace, database = service
    initial = state_data()
    initial["teams"] = ["Pós-venda"]
    workspace.bootstrap(WorkspaceState.model_validate(initial))
    # Teams named by users come in even when the list leaves them out.
    assert workspace.load().state.teams == ["Gestão", "Pós-venda", "Vendas"]

    def add(data: dict) -> None:
        data["teams"].append("  Expansão  ")

    result = save_as_admin(database, WorkspaceService(), add)
    assert result.state.teams == ["Expansão", "Gestão", "Pós-venda", "Vendas"]
    assert team_id_for_name("Expansão") in stored_teams(database)


def test_an_unused_team_left_out_of_the_list_is_removed(service) -> None:  # noqa: F811
    workspace, database = service
    initial = state_data()
    initial["teams"] = ["Pós-venda"]
    workspace.bootstrap(WorkspaceState.model_validate(initial))

    def remove(data: dict) -> None:
        data["teams"] = [name for name in data["teams"] if name not in ("Pós-venda", "Vendas")]

    result = save_as_admin(database, WorkspaceService(), remove)
    # "Vendas" is still Bia's team, so it stays.
    assert result.state.teams == ["Gestão", "Vendas"]
    assert set(stored_teams(database).values()) == {"Gestão", "Vendas"}


def test_a_snapshot_without_teams_keeps_the_stored_list(service) -> None:  # noqa: F811
    workspace, database = service
    initial = state_data()
    initial["teams"] = ["Pós-venda"]
    workspace.bootstrap(WorkspaceState.model_validate(initial))

    def older_client(data: dict) -> None:
        data.pop("teams")

    assert save_as_admin(database, WorkspaceService(), older_client).state.teams == ["Gestão", "Pós-venda", "Vendas"]


def test_renaming_a_team_moves_users_and_records(service) -> None:  # noqa: F811
    workspace, database = service
    initial = state_data()
    initial["leads"][0]["team"] = "Vendas"
    workspace.bootstrap(WorkspaceState.model_validate(initial))

    def rename(data: dict) -> None:
        data["teams"] = ["Gestão" if name == "Gestão" else "Vendas Sul" for name in data["teams"]]
        for collection in ("users", "leads", "deals"):
            for record in data[collection]:
                if record.get("team") == "Vendas":
                    record["team"] = "Vendas Sul"

    result = save_as_admin(database, WorkspaceService(), rename)
    assert result.state.teams == ["Gestão", "Vendas Sul"]
    assert {user["id"]: user["team"] for user in result.state.users} == {"u-1": "Gestão", "u-2": "Vendas Sul"}
    new_id = team_id_for_name("Vendas Sul")
    with database.session_scope() as session:
        assert session.scalar(select(CrmUser.team_id).where(CrmUser.id == "u-2")) == new_id
        assert session.scalar(select(Lead.team_id).where(Lead.id == "L-1")) == new_id
    assert team_id_for_name("Vendas") not in stored_teams(database)


def test_a_team_kept_only_by_deleted_records_can_be_removed(service) -> None:  # noqa: F811
    workspace, database = service
    initial = state_data()
    initial["teams"] = ["Antiga"]
    initial["leads"][0]["team"] = "Antiga"
    workspace.bootstrap(WorkspaceState.model_validate(initial))

    def delete_lead(data: dict) -> None:
        data["leads"] = []

    save_as_admin(database, WorkspaceService(), delete_lead)

    def drop_team(data: dict) -> None:
        data["teams"] = [name for name in data["teams"] if name != "Antiga"]

    assert save_as_admin(database, WorkspaceService(), drop_team).state.teams == ["Gestão", "Vendas"]
    with database.session_scope() as session:
        assert session.scalar(select(Lead.team_id).where(Lead.id == "L-1")) is None


def test_non_admins_see_the_list_but_cannot_change_it(service) -> None:  # noqa: F811
    workspace, database = service
    initial = state_data()
    initial["teams"] = ["Pós-venda"]
    workspace.bootstrap(WorkspaceState.model_validate(initial))
    assistant = PrincipalScope(
        tenant_id=TEST_PRINCIPAL.tenant_id,
        workspace_id="default",
        user_id="u-2",
        role="Assistente",
        team_id=team_id_for_name("Vendas"),
        auth_version=1,
    )
    core = WorkspaceService()
    with database.session_scope() as session:
        projected = core.load(session, assistant).state
        assert projected.teams == ["Gestão", "Pós-venda", "Vendas"]
        changed = projected.model_copy(update={"teams": ["Gestão", "Vendas", "Equipe pirata"]})
        core.save(session, assistant, 1, changed)
    assert workspace.load().state.teams == ["Gestão", "Pós-venda", "Vendas"]


@pytest.mark.parametrize("teams", [[""], ["   "], ["x" * 256], [3]])
def test_invalid_team_names_are_refused(teams) -> None:  # noqa: ANN001
    data = state_data()
    data["teams"] = teams
    with pytest.raises(ValidationError):
        WorkspaceState.model_validate(data)
