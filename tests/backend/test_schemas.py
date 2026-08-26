from __future__ import annotations

from copy import deepcopy

import pytest

from app.schemas import WorkspaceReferenceError, WorkspaceState, count_state, validate_references


def valid_state() -> dict:
    return {
        "currentUserId": "u-1",
        "users": [
            {
                "id": "u-1",
                "name": "Ana",
                "email": "ana@example.test",
                "role": "Administrador",
                "team": "Gestão",
                "status": "Ativo",
            },
            {
                "id": "u-2",
                "name": "Bia",
                "email": "bia@example.test",
                "role": "Assistente",
                "team": "Vendas",
                "status": "Ativo",
            },
        ],
        "leads": [
            {
                "id": "L-1",
                "name": "Lead",
                "responsibleId": "u-1",
                "assistants": ["u-2"],
                "customFields": [
                    {"key": "empty", "value": ""},
                    {"key": "enabled", "value": False},
                    {"key": "choices", "value": []},
                ],
                "visibleCustomFieldKeys": ["empty"],
                "bitrixFields": [
                    {"name": "Telefone", "occurrence": 1, "position": 0, "value": ""},
                    {"name": "Telefone", "occurrence": 2, "position": 1, "value": "1199"},
                ],
            }
        ],
        "contacts": [{"id": "C-1", "name": "Contato", "companyId": "E-1"}],
        "companies": [{"id": "E-1", "name": "Empresa", "ownerId": "u-1"}],
        "deals": [
            {
                "id": "N-1",
                "title": "Negócio",
                "companyId": "E-1",
                "contactId": "C-1",
                "responsibleId": "u-1",
                "stageChangedById": "u-1",
                "assistants": ["u-2"],
                "stageHistory": [{"from": "A", "to": "B", "byId": "u-1"}],
                "quotes": [{"id": "Q-1", "description": "Item", "total": 10}],
            }
        ],
        "notifications": [{"id": "NT-1", "userId": "u-2", "text": "Aviso"}],
        "customFieldSchemas": {
            "leads": [
                {"key": "empty", "label": "Vazio", "type": "text", "position": 0},
                {"key": "enabled", "label": "Ativo", "type": "boolean", "position": 1},
                {"key": "choices", "label": "Opções", "type": "multiselect", "position": 2},
            ],
            "contacts": [],
            "companies": [],
            "deals": [],
        },
        "moduleFieldSettings": {
            "leads": {"hiddenStandardFields": ["email"], "hiddenCustomFieldKeys": ["empty"]},
            "contacts": {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []},
            "companies": {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []},
            "deals": {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []},
        },
        "ui": {
            "savedFilters": [{"id": "SF-1", "userId": "u-1", "scope": "deals", "name": "Meu", "filter": {}}],
            "viewModesByUser": {"u-1": {"leads": "list", "deals": "kanban"}},
            "dashboardScopeByUser": {"u-1": "all"},
        },
    }


def assert_invalid(state: dict, expected_path: str) -> None:
    parsed = WorkspaceState.model_validate(state)
    with pytest.raises(WorkspaceReferenceError) as error:
        validate_references(parsed)
    assert error.value.path == expected_path


def test_contract_round_trips_empty_false_lists_and_duplicate_bitrix_headers() -> None:
    original = valid_state()

    parsed = WorkspaceState.model_validate(original)
    validate_references(parsed)
    dumped = parsed.model_dump(by_alias=True, exclude_none=True)

    values = dumped["leads"][0]["customFields"]
    assert [field["value"] for field in values] == ["", False, []]
    assert dumped["leads"][0]["bitrixFields"] == original["leads"][0]["bitrixFields"]
    assert dumped["moduleFieldSettings"] == original["moduleFieldSettings"]


def test_counts_include_quotes_notifications_and_custom_definitions_exactly() -> None:
    counts = count_state(WorkspaceState.model_validate(valid_state()))

    assert counts.model_dump(by_alias=True) == {
        "users": 2,
        "leads": 1,
        "contacts": 1,
        "companies": 1,
        "deals": 1,
        "quotes": 1,
        "notifications": 1,
        "customFields": 3,
    }


def test_duplicate_module_id_reports_stable_path() -> None:
    state = valid_state()
    state["leads"].append(deepcopy(state["leads"][0]))
    assert_invalid(state, "leads[1].id")


def test_unknown_current_user_reports_stable_path() -> None:
    state = valid_state()
    state["currentUserId"] = "missing"
    assert_invalid(state, "currentUserId")


def test_unknown_responsible_reports_stable_path() -> None:
    state = valid_state()
    state["deals"][0]["responsibleId"] = "missing"
    assert_invalid(state, "deals[0].responsibleId")


def test_unknown_assistant_reports_stable_path() -> None:
    state = valid_state()
    state["leads"][0]["assistants"] = ["missing"]
    assert_invalid(state, "leads[0].assistants[0]")


def test_unknown_company_link_reports_stable_path() -> None:
    state = valid_state()
    state["contacts"][0]["companyId"] = "missing"
    assert_invalid(state, "contacts[0].companyId")


def test_unknown_custom_field_definition_reports_stable_path() -> None:
    state = valid_state()
    state["leads"][0]["customFields"].append({"key": "missing", "value": "x"})
    assert_invalid(state, "leads[0].customFields[3].key")


def test_unknown_saved_filter_user_reports_stable_path() -> None:
    state = valid_state()
    state["ui"]["savedFilters"][0]["userId"] = "missing"
    assert_invalid(state, "ui.savedFilters[0].userId")

@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda state: state["companies"][0].update(ownerId="missing"), "companies[0].ownerId"),
        (lambda state: state["deals"][0].update(stageChangedById="missing"), "deals[0].stageChangedById"),
        (lambda state: state["deals"][0]["stageHistory"][0].update(byId="missing"), "deals[0].stageHistory[0].byId"),
        (lambda state: state["notifications"][0].update(userId="missing"), "notifications[0].userId"),
        (lambda state: state["ui"]["viewModesByUser"].update(missing={}), "ui.viewModesByUser.missing"),
    ],
)
def test_all_user_reference_branches_report_stable_paths(mutate, path: str) -> None:  # noqa: ANN001
    state = valid_state()
    mutate(state)
    assert_invalid(state, path)


def test_empty_record_id_reports_stable_path() -> None:
    state = valid_state()
    state["contacts"][0]["id"] = ""
    assert_invalid(state, "contacts[0].id")


@pytest.mark.parametrize(
    ("quotes", "path"),
    [
        ([{"id": "", "total": 1}], "deals[0].quotes[0].id"),
        (
            [{"id": "Q-1", "total": 1}, {"id": "Q-1", "total": 2}],
            "deals[0].quotes[1].id",
        ),
    ],
)
def test_quote_id_validation_reports_stable_path(quotes: list[dict], path: str) -> None:
    state = valid_state()
    state["deals"][0]["quotes"] = quotes
    assert_invalid(state, path)


@pytest.mark.parametrize(
    ("definitions", "path"),
    [
        ([{"key": "", "label": "Inválido", "type": "text"}], "customFieldSchemas.leads[0].key"),
        (
            [
                {"key": "same", "label": "A", "type": "text"},
                {"key": "same", "label": "B", "type": "text"},
            ],
            "customFieldSchemas.leads[1].key",
        ),
    ],
)
def test_custom_definition_validation_reports_stable_path(definitions: list[dict], path: str) -> None:
    state = valid_state()
    state["customFieldSchemas"]["leads"] = definitions
    state["leads"][0]["customFields"] = []
    assert_invalid(state, path)