"""Deals in several pipelines: each deal's stage belongs to its own pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas import WorkspaceState
from app.services.pipeline import DealPipelineService
from app.services.workspace import WorkspaceService, WorkspaceStageConflict
from tests.backend.test_deal_currency import deal, save_as_admin
from tests.backend.test_workspace_service import TEST_PRINCIPAL, service, state_data  # noqa: F401

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)


def second_pipeline(database) -> dict:  # noqa: ANN001
    with database.session_scope() as session:
        created = DealPipelineService(clock=lambda: NOW).create(session, TEST_PRINCIPAL, "Pós-venda")
        return created.model_dump(by_alias=True, mode="json")


def main_pipeline(database) -> dict:  # noqa: ANN001
    with database.session_scope() as session:
        return DealPipelineService().load(session, TEST_PRINCIPAL).model_dump(by_alias=True, mode="json")


def stage(pipeline: dict, semantic: str) -> dict:
    return next(item for item in pipeline["stages"] if item["semanticType"] == semantic)


def test_a_deal_moves_to_another_pipeline_and_the_move_is_in_its_history(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    after_sales = second_pipeline(database)
    core = WorkspaceService(clock=lambda: NOW)
    target = stage(after_sales, "open")

    moved = save_as_admin(
        database, core, lambda data: data["deals"][0].update(pipelineId=after_sales["id"], stageId=target["id"])
    )
    record = deal(moved, "N-1")
    assert (record["pipelineId"], record["stageId"], record["stage"]) == (after_sales["id"], target["id"], "Em andamento")
    assert record["stageHistory"][-1]["toStageId"] == target["id"]
    assert record["stageHistory"][-1]["to"] == "Em andamento"

    # Back to the main pipeline, at a stage that shares a name with the other one.
    main = main_pipeline(database)
    won = stage(main, "won")
    back = save_as_admin(database, core, lambda data: data["deals"][0].update(pipelineId=main["id"], stageId=won["id"]))
    assert (deal(back, "N-1")["pipelineId"], deal(back, "N-1")["stageId"]) == (main["id"], won["id"])


def test_a_stage_of_another_pipeline_is_refused(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    after_sales = second_pipeline(database)
    main = main_pipeline(database)
    core = WorkspaceService(clock=lambda: NOW)
    with pytest.raises(WorkspaceStageConflict):
        save_as_admin(
            database, core, lambda data: data["deals"][0].update(pipelineId=main["id"], stageId=stage(after_sales, "won")["id"])
        )


def test_new_deals_start_at_the_initial_stage_of_their_own_pipeline(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    after_sales = second_pipeline(database)
    core = WorkspaceService(clock=lambda: NOW)

    def add(stage_info: dict, deal_id: str):  # noqa: ANN202
        def mutate(data: dict) -> None:
            new = dict(data["deals"][0])
            new.update(id=deal_id, title=deal_id, pipelineId=after_sales["id"], stageId=stage_info["id"], quotes=[], stageHistory=[])
            data["deals"].append(new)
        return mutate

    created = save_as_admin(database, core, add(stage(after_sales, "open"), "N-new"))
    assert deal(created, "N-new")["pipelineId"] == after_sales["id"]
    with pytest.raises(WorkspaceStageConflict):
        save_as_admin(database, core, add(stage(after_sales, "won"), "N-late"))


def test_archived_pipelines_cannot_receive_deals(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    after_sales = second_pipeline(database)
    with database.session_scope() as session:
        DealPipelineService(clock=lambda: NOW).change(
            session, TEST_PRINCIPAL, after_sales["id"], expected_version=after_sales["pipelineVersion"], archived=True
        )
    core = WorkspaceService(clock=lambda: NOW)
    with pytest.raises(WorkspaceStageConflict):
        save_as_admin(
            database, core, lambda data: data["deals"][0].update(pipelineId=after_sales["id"], stageId=stage(after_sales, "open")["id"])
        )
