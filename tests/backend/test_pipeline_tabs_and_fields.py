"""Pipelines shown as menu tabs, custom fields of one pipeline and of products."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas import WorkspaceReferenceError, WorkspaceState
from app.services.pipeline import DealPipelineService, DealPipelineValidationError
from app.services.workspace import WorkspaceService
from tests.backend.test_deal_currency import save_as_admin
from tests.backend.test_multi_pipeline_workspace import main_pipeline, second_pipeline
from tests.backend.test_products import catalog_state, product
from tests.backend.test_workspace_service import TEST_PRINCIPAL, service, state_data  # noqa: F401

NOW = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)


def change(database, pipeline: dict, **fields) -> dict:  # noqa: ANN001
    with database.session_scope() as session:
        changed = DealPipelineService(clock=lambda: NOW).change(
            session, TEST_PRINCIPAL, pipeline["id"], expected_version=pipeline["pipelineVersion"], **fields
        )
        return changed.model_dump(by_alias=True, mode="json")


def history(database, pipeline: dict) -> list[dict]:  # noqa: ANN001
    with database.session_scope() as session:
        page = DealPipelineService().history(session, TEST_PRINCIPAL, pipeline_id=pipeline["id"])
        return [item.model_dump(by_alias=True, mode="json") for item in page.items]


def test_a_pipeline_becomes_a_menu_tab_with_an_icon(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    after_sales = second_pipeline(database)
    assert (after_sales["menuTab"], after_sales["menuIcon"]) == (False, None)

    tab = change(database, after_sales, menu_tab=True, menu_icon="★")
    assert (tab["menuTab"], tab["menuIcon"], tab["pipelineVersion"]) == (True, "★", after_sales["pipelineVersion"] + 1)
    actions = history(database, tab)[0]["actions"]
    assert {"type": "pipeline.menu_tab", "to": True} in actions
    assert {"type": "pipeline.menu_icon", "from": None, "to": "★"} in actions

    # Sending the same values changes nothing.
    same = change(database, tab, menu_tab=True, menu_icon="★")
    assert same["pipelineVersion"] == tab["pipelineVersion"]

    back = change(database, tab, menu_tab=False)
    assert (back["menuTab"], back["menuIcon"]) == (False, "★")


def test_icons_come_from_the_fixed_list(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    after_sales = second_pipeline(database)
    with pytest.raises(DealPipelineValidationError) as error:
        change(database, after_sales, menu_icon="<b>")
    assert error.value.code == "invalid_menu_icon"


def test_the_main_pipeline_never_becomes_a_tab(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    main = main_pipeline(database)
    with pytest.raises(DealPipelineValidationError) as error:
        change(database, main, menu_tab=True)
    assert error.value.code == "default_pipeline_menu_tab"

    # A tab that becomes the main pipeline goes back under "Negócios".
    after_sales = change(database, second_pipeline(database), menu_tab=True, menu_icon="⚑")
    promoted = change(database, after_sales, is_default=True)
    assert (promoted["isDefault"], promoted["menuTab"]) == (True, False)


def scoped_field(pipeline_id: str | None, key: str = "user:install") -> dict:
    field = {"key": key, "label": "Data de instalação", "type": "date", "userCreated": True}
    if pipeline_id is not None:
        field["pipelineId"] = pipeline_id
    return field


def test_a_deal_field_can_belong_to_one_pipeline(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    after_sales = second_pipeline(database)
    core = WorkspaceService(clock=lambda: NOW)

    saved = save_as_admin(
        database, core, lambda data: data["customFieldSchemas"]["deals"].append(scoped_field(after_sales["id"]))
    )
    stored = {item["key"]: item for item in saved.state.custom_field_schemas["deals"]}
    assert stored["user:install"]["pipelineId"] == after_sales["id"]

    # Unscoping keeps the field for every pipeline.
    saved = save_as_admin(
        database, core, lambda data: data["customFieldSchemas"]["deals"][-1].pop("pipelineId")
    )
    assert "pipelineId" not in {item["key"]: item for item in saved.state.custom_field_schemas["deals"]}["user:install"]


def test_unknown_or_misplaced_pipeline_scopes_are_refused(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(state_data()))
    after_sales = second_pipeline(database)
    core = WorkspaceService(clock=lambda: NOW)
    with pytest.raises(WorkspaceReferenceError):
        save_as_admin(
            database,
            core,
            lambda data: data["customFieldSchemas"]["deals"].append(scoped_field("00000000-0000-4000-8000-000000000099")),
        )
    with pytest.raises(WorkspaceReferenceError):
        save_as_admin(
            database,
            core,
            lambda data: data["customFieldSchemas"].setdefault("contacts", []).append(scoped_field(after_sales["id"])),
        )
    with pytest.raises(WorkspaceReferenceError):
        save_as_admin(
            database, core, lambda data: data["customFieldSchemas"]["deals"].append(scoped_field("not-a-uuid"))
        )


def test_products_have_custom_fields(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(catalog_state(product())))
    core = WorkspaceService(clock=lambda: NOW)
    field = {"key": "user:warranty", "label": "Garantia", "type": "text", "userCreated": True}

    def mutate(data: dict) -> None:
        data["customFieldSchemas"].setdefault("products", []).append(field)
        data["products"][0]["customFields"] = [{**field, "value": "24 meses"}]
        data["products"][0]["visibleCustomFieldKeys"] = ["user:warranty"]

    saved = save_as_admin(database, core, mutate)
    assert [item["key"] for item in saved.state.custom_field_schemas["products"]] == ["user:warranty"]
    assert saved.counts.custom_fields == 1
    loaded = workspace.load().state
    assert loaded.products[0]["customFields"][0]["value"] == "24 meses"
    assert "products" in loaded.module_field_settings

    # A product value needs its definition.
    with pytest.raises(WorkspaceReferenceError):
        save_as_admin(
            database, core, lambda data: data["products"][0]["customFields"].append({"key": "user:ghost", "value": "x"})
        )
