from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import (
    LOGIN_FAILURE_MESSAGE,
    AuthErrorResponse,
    ActivityActorResponse,
    ActivityEventResponse,
    ActivityPage,
    ActivityQuery,
    CompanyActivityQuery,
    CompanyDealMetricResponse,
    CompanyDealRow,
    CompanyDealSummaryResponse,
    DealPipelineAuditPage,
    DealPipelineHistoryQuery,
    DealPipelineStageResponse,
    DealPipelineUpdateRequest,
    LocateTenantRequest,
    LoginRequest,
    ObservationCreateRequest,
    SessionResponse,
    WorkspaceReferenceError,
    WorkspaceState,
    count_state,
    validate_references,
)


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
@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("Cliente-A", "cliente-a"),
        ("https://sc2030.brbots.com/CLIENTE-A", "cliente-a"),
    ],
)
def test_locator_normalizes_slug_or_expected_origin_url(identifier: str, expected: str) -> None:
    request = LocateTenantRequest(identifier=identifier)

    assert request.slug == expected


@pytest.mark.parametrize(
    "identifier",
    [
        "https://evil.example/cliente-a",
        "https://sc2030.brbots.com/cliente-a/extra",
        "api",
        "cliente_a",
        "x" * 64,
    ],
)
def test_locator_rejects_external_nested_reserved_or_invalid_identifiers(identifier: str) -> None:
    with pytest.raises(ValidationError):
        LocateTenantRequest(identifier=identifier)


def test_login_normalizes_tenant_and_email() -> None:
    request = LoginRequest(
        slug="Cliente-A",
        email="  USER@Example.Test ",
        password="correct horse battery staple",
    )

    assert request.slug == "cliente-a"
    assert request.email == "user@example.test"
    assert request.password == "correct horse battery staple"


@pytest.mark.parametrize("length", [8, 128])
def test_login_accepts_password_bounds_without_truncation(length: int) -> None:
    password = "x" * length

    assert LoginRequest(slug="cliente-a", email="a@example.test", password=password).password == password


@pytest.mark.parametrize(
    "values",
    [
        {"slug": "cliente-a", "email": "invalid", "password": "x" * 12},
        {"slug": "cliente-a", "email": "a@example.test", "password": "x" * 7},
        {"slug": "cliente-a", "email": "a@example.test", "password": "x" * 129},
    ],
)
def test_login_rejects_invalid_email_and_password_bounds(values: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(values)


@pytest.mark.parametrize("authority_field", ["tenant_id", "dsn", "role"])
def test_auth_requests_forbid_browser_authority_fields(authority_field: str) -> None:
    payload = {
        "slug": "cliente-a",
        "email": "a@example.test",
        "password": "correct horse battery staple",
        authority_field: "forged",
    }

    with pytest.raises(ValidationError):
        LoginRequest.model_validate(payload)


def test_session_response_exposes_identity_without_secret_fields() -> None:
    tenant_id = uuid4()
    response = SessionResponse(
        tenant_id=tenant_id,
        tenant_slug="cliente-a",
        tenant_display_name="Cliente A",
        user_id="u-1",
        user_name="Ana",
        email="ana@example.test",
        role="Administrador",
    )

    assert response.model_dump() == {
        "tenant_id": tenant_id,
        "tenant_slug": "cliente-a",
        "tenant_display_name": "Cliente A",
        "user_id": "u-1",
        "user_name": "Ana",
        "email": "ana@example.test",
        "role": "Administrador",
    }
    assert {"password_hash", "token", "dsn"}.isdisjoint(SessionResponse.model_fields)


def test_auth_failure_contract_uses_only_the_generic_public_message() -> None:
    failure = AuthErrorResponse()

    assert failure.model_dump() == {
        "error": "invalid_login",
        "message": LOGIN_FAILURE_MESSAGE,
    }
    assert failure.message == "Não foi possível entrar com os dados informados."


def valid_pipeline_update() -> dict:
    stage_id = uuid4()
    return {
        "pipelineVersion": 3,
        "workspaceVersion": 14,
        "defaultStageId": stage_id,
        "stages": [
            {
                "id": stage_id,
                "name": "  Em análise  ",
                "semanticType": "open",
                "color": "#4f46e5",
                "position": 0,
                "archived": False,
            }
        ],
        "transfers": {},
    }


def test_pipeline_update_round_trips_strict_camel_case_contract() -> None:
    parsed = DealPipelineUpdateRequest.model_validate(valid_pipeline_update())
    dumped = parsed.model_dump(by_alias=True)

    assert dumped["pipelineVersion"] == 3
    assert dumped["workspaceVersion"] == 14
    assert dumped["defaultStageId"] == dumped["stages"][0]["id"]
    assert dumped["stages"][0]["name"] == "Em análise"
    assert dumped["stages"][0]["semanticType"] == "open"
    assert dumped["stages"][0]["color"] == "#4F46E5"
    assert dumped["stages"][0]["position"] == 0
    assert dumped["transfers"] == {}


@pytest.mark.parametrize("name", ["", "   ", "x" * 81])
def test_pipeline_stage_rejects_empty_or_overlong_trimmed_names(name: str) -> None:
    payload = valid_pipeline_update()
    payload["stages"][0]["name"] = name

    with pytest.raises(ValidationError):
        DealPipelineUpdateRequest.model_validate(payload)


@pytest.mark.parametrize("color", ["4F46E5", "#FFFF", "#GGGGGG", "#1234567"])
def test_pipeline_stage_rejects_non_hex_colors(color: str) -> None:
    payload = valid_pipeline_update()
    payload["stages"][0]["color"] = color

    with pytest.raises(ValidationError):
        DealPipelineUpdateRequest.model_validate(payload)


@pytest.mark.parametrize("semantic_type", ["", "closed", "OPEN"])
def test_pipeline_stage_rejects_unknown_semantic_types(semantic_type: str) -> None:
    payload = valid_pipeline_update()
    payload["stages"][0]["semanticType"] = semantic_type

    with pytest.raises(ValidationError):
        DealPipelineUpdateRequest.model_validate(payload)


def test_pipeline_update_rejects_negative_position_and_versions() -> None:
    for path, value in (
        (("pipelineVersion",), 0),
        (("workspaceVersion",), -1),
        (("stages", 0, "position"), -1),
    ):
        payload = valid_pipeline_update()
        if len(path) == 1:
            payload[path[0]] = value
        else:
            payload[path[0]][path[1]][path[2]] = value
        with pytest.raises(ValidationError):
            DealPipelineUpdateRequest.model_validate(payload)


def test_pipeline_update_rejects_more_than_fifty_stages() -> None:
    payload = valid_pipeline_update()
    payload["stages"] = [
        {
            "id": uuid4(),
            "name": f"Etapa {index}",
            "semanticType": "open",
            "color": "#123456",
            "position": index,
            "archived": False,
        }
        for index in range(51)
    ]

    with pytest.raises(ValidationError):
        DealPipelineUpdateRequest.model_validate(payload)

    payload["stages"][50]["archived"] = True
    assert len(DealPipelineUpdateRequest.model_validate(payload).stages) == 51


def test_pipeline_update_rejects_self_transfer_and_extra_authority_fields() -> None:
    payload = valid_pipeline_update()
    stage_id = payload["defaultStageId"]
    payload["transfers"] = {stage_id: stage_id}
    with pytest.raises(ValidationError):
        DealPipelineUpdateRequest.model_validate(payload)

    payload = valid_pipeline_update()
    payload["workspaceId"] = "forged"
    with pytest.raises(ValidationError):
        DealPipelineUpdateRequest.model_validate(payload)


@pytest.mark.parametrize("values", [{"before": 0}, {"limit": 0}, {"limit": 51}])
def test_pipeline_history_query_enforces_cursor_and_page_bounds(values: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        DealPipelineHistoryQuery.model_validate(values)


def test_pipeline_response_exposes_immutable_stage_metadata_with_camel_case() -> None:
    stage_id = uuid4()
    response = DealPipelineStageResponse(
        id=stage_id,
        name="Faturando",
        semanticType="open",
        color="#112233",
        position=5,
        systemKey="billing",
        active=True,
        initial=False,
    )

    assert response.model_dump(by_alias=True)["systemKey"] == "billing"
    assert response.model_dump(by_alias=True)["semanticType"] == "open"
    assert response.model_dump(by_alias=True)["archivedAt"] is None
    assert DealPipelineHistoryQuery().limit == 50
    assert DealPipelineAuditPage(items=[]).model_dump(by_alias=True) == {
        "items": [],
        "nextBefore": None,
    }


@pytest.mark.parametrize("category", ["movement", "automation", "observation"])
def test_activity_query_accepts_only_deal_filter_categories(category: str) -> None:
    assert ActivityQuery(category=category).category == category


@pytest.mark.parametrize("category", ["", "change", "unknown", "MOVEMENT"])
def test_activity_query_rejects_non_deal_filter_categories(category: str) -> None:
    with pytest.raises(ValidationError):
        ActivityQuery(category=category)


@pytest.mark.parametrize("category", ["change", "observation"])
def test_company_activity_query_accepts_own_history_categories(category: str) -> None:
    assert CompanyActivityQuery(category=category).category == category


@pytest.mark.parametrize("text", ["x", " x ", "x" * 4_000])
def test_observation_contract_trims_and_accepts_text_bounds(text: str) -> None:
    key = uuid4()
    request = ObservationCreateRequest(text=text, idempotencyKey=key)

    assert request.text == text.strip()
    assert request.idempotency_key == key
    assert request.model_dump(by_alias=True) == {
        "text": text.strip(),
        "idempotencyKey": key,
    }


@pytest.mark.parametrize("text", ["", "   ", "x" * 4_001])
def test_observation_contract_rejects_invalid_text_bounds(text: str) -> None:
    with pytest.raises(ValidationError):
        ObservationCreateRequest(text=text, idempotencyKey=uuid4())


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "Nota", "idempotencyKey": "not-a-uuid"},
        {"text": "Nota"},
        {"text": "Nota", "idempotencyKey": uuid4(), "actorUserId": "forged"},
    ],
)
def test_observation_contract_requires_uuid_and_forbids_authority_fields(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ObservationCreateRequest.model_validate(payload)


@pytest.mark.parametrize(
    "values",
    [
        {"limit": 0},
        {"limit": 51},
        {"cursor": ""},
        {"cursor": "contains=padding"},
        {"cursor": "contains spaces"},
        {"cursor": "a" * 2_049},
    ],
)
def test_activity_query_rejects_page_bounds_and_malformed_cursors(values: dict) -> None:
    with pytest.raises(ValidationError):
        ActivityQuery.model_validate(values)


def test_activity_page_uses_camel_case_and_caps_items_at_fifty() -> None:
    occurred_at = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    event = ActivityEventResponse(
        id=1,
        category="movement",
        eventType="deal.stage_changed",
        actor=ActivityActorResponse(id="u-1", name="Ana", kind="user"),
        summary="Etapa alterada",
        details={"fromStageId": None, "toStageId": str(uuid4())},
        occurredAt=occurred_at,
    )
    page = ActivityPage(items=[event], nextCursor="v1_cursor-token")

    assert page.model_dump(by_alias=True) == {
        "items": [
            {
                "id": 1,
                "category": "movement",
                "eventType": "deal.stage_changed",
                "actor": {"id": "u-1", "name": "Ana", "kind": "user"},
                "summary": "Etapa alterada",
                "details": {"fromStageId": None, "toStageId": event.details["toStageId"]},
                "occurredAt": occurred_at,
            }
        ],
        "nextCursor": "v1_cursor-token",
    }
    assert ActivityQuery(cursor="v1_cursor-token").limit == 50
    with pytest.raises(ValidationError):
        ActivityPage(items=[event] * 51)


def test_company_deal_summary_serializes_exact_money_and_stage_semantics() -> None:
    stage_id = uuid4()
    row = CompanyDealRow(
        id="deal-1",
        title="Renovação",
        stageId=stage_id,
        stageName="Ganho",
        semanticType="won",
        responsibleId="u-1",
        responsibleName="Ana",
        amount=Decimal("1234.50"),
    )
    summary = CompanyDealSummaryResponse(
        totalCount=1,
        open=CompanyDealMetricResponse(count=0, amount=Decimal("0")),
        won=CompanyDealMetricResponse(count=1, amount=Decimal("1234.50")),
        lost=CompanyDealMetricResponse(count=0, amount=Decimal("0.00")),
        items=[row],
    )

    assert summary.model_dump(by_alias=True) == {
        "totalCount": 1,
        "open": {"count": 0, "amount": "0.00"},
        "won": {"count": 1, "amount": "1234.50"},
        "lost": {"count": 0, "amount": "0.00"},
        "items": [
            {
                "id": "deal-1",
                "title": "Renovação",
                "stageId": stage_id,
                "stageName": "Ganho",
                "semanticType": "won",
                "responsibleId": "u-1",
                "responsibleName": "Ana",
                "amount": "1234.50",
            }
        ],
    }


# --- T10: account-access contracts -------------------------------------------

from app.schemas import (  # noqa: E402
    ACCOUNT_ACTION_TOKEN_MAX_LENGTH,
    INVALID_ACTION_LINK_MESSAGE,
    PASSWORD_MISMATCH_MESSAGE,
    PASSWORD_RESET_REQUEST_MESSAGE,
    AccountActionTokenRequest,
    AccountActionViewResponse,
    AccountUserResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    InvitationAcceptRequest,
    InvitationCreateRequest,
    InvitationResponse,
    PasswordResetRequest,
    UserAccessResponse,
)
from app.security.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH  # noqa: E402

TOKEN = "dGVzdC10b2tlbi1maWN0aWNpby0xMjM0NTY3ODkwYWJj"


def _invitation(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "  Bia Souza ",
        "email": "  BIA@Example.Test ",
        "jobTitle": " Executiva de vendas ",
        "team": " Vendas ",
        "role": "Vendedor",
    }
    payload.update(changes)
    return payload


def test_invitation_request_normalizes_email_and_trims_profile_fields() -> None:
    request = InvitationCreateRequest.model_validate(_invitation())

    assert (request.name, request.email, request.job_title, request.team, request.role) == (
        "Bia Souza",
        "bia@example.test",
        "Executiva de vendas",
        "Vendas",
        "Vendedor",
    )


@pytest.mark.parametrize("team", [None, "", "   "])
def test_invitation_request_treats_blank_team_as_no_team(team: object) -> None:
    assert InvitationCreateRequest.model_validate(_invitation(team=team)).team is None


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"name": "n" * 256},
        {"email": "sem-arroba"},
        {"email": "a@b"},
        {"email": "x" * 250 + "@a.br"},
        {"jobTitle": ""},
        {"jobTitle": "c" * 256},
        {"team": "t" * 256},
        {"role": "Dono"},
        {"role": "administrador"},
    ],
)
def test_invitation_request_rejects_out_of_bounds_fields(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        InvitationCreateRequest.model_validate(_invitation(**changes))


def test_invitation_request_accepts_inclusive_text_bounds() -> None:
    request = InvitationCreateRequest.model_validate(
        _invitation(name="n" * 255, jobTitle="c" * 255, team="t" * 255)
    )

    assert (len(request.name), len(request.job_title), len(request.team)) == (255, 255, 255)


@pytest.mark.parametrize(
    "authority_field",
    ["status", "authEnabled", "passwordHash", "id", "workspaceId", "deliveryStatus", "token"],
)
def test_invitation_request_forbids_server_managed_fields(authority_field: str) -> None:
    with pytest.raises(ValidationError):
        InvitationCreateRequest.model_validate(_invitation(**{authority_field: "forjado"}))


def _password_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "slug": "Cliente-A",
        "token": TOKEN,
        "password": "senha123",
        "password_confirmation": "senha123",
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize("model", [InvitationAcceptRequest, PasswordResetRequest])
@pytest.mark.parametrize("length", [MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH])
def test_password_requests_accept_exact_inclusive_bounds(model, length: int) -> None:
    password = "p" * length

    request = model.model_validate(
        _password_payload(password=password, password_confirmation=password)
    )

    assert (MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH) == (8, 128)
    assert request.password == password
    assert request.slug == "cliente-a"


@pytest.mark.parametrize("model", [InvitationAcceptRequest, PasswordResetRequest])
@pytest.mark.parametrize("length", [MIN_PASSWORD_LENGTH - 1, MAX_PASSWORD_LENGTH + 1])
def test_password_requests_reject_lengths_outside_bounds(model, length: int) -> None:
    password = "p" * length

    with pytest.raises(ValidationError):
        model.model_validate(_password_payload(password=password, password_confirmation=password))


@pytest.mark.parametrize("model", [InvitationAcceptRequest, PasswordResetRequest])
def test_password_requests_require_identical_confirmation(model) -> None:
    with pytest.raises(ValidationError) as failure:
        model.model_validate(_password_payload(password_confirmation="senha124"))

    assert PASSWORD_MISMATCH_MESSAGE in str(failure.value)
    assert "senha123" not in str(failure.value)


@pytest.mark.parametrize("model", [InvitationAcceptRequest, PasswordResetRequest])
def test_password_requests_do_not_trim_or_truncate_passwords(model) -> None:
    password = "  " + "p" * (MAX_PASSWORD_LENGTH - 4) + "  "

    request = model.model_validate(
        _password_payload(password=password, password_confirmation=password)
    )

    assert request.password == password


@pytest.mark.parametrize(
    "model", [AccountActionTokenRequest, InvitationAcceptRequest, PasswordResetRequest]
)
@pytest.mark.parametrize(
    "changes",
    [
        {"token": ""},
        {"token": "t" * (ACCOUNT_ACTION_TOKEN_MAX_LENGTH + 1)},
        {"slug": "api"},
        {"slug": "https://evil.example/cliente-a"},
        {"tenant_id": str(uuid4())},
        {"dsn": "postgresql://fake"},
    ],
)
def test_token_requests_bound_token_and_reject_untrusted_tenant_fields(model, changes) -> None:
    payload = _password_payload(**changes)
    if model is AccountActionTokenRequest:
        payload.pop("password")
        payload.pop("password_confirmation")

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_token_request_accepts_maximum_token_length() -> None:
    token = "t" * ACCOUNT_ACTION_TOKEN_MAX_LENGTH

    assert AccountActionTokenRequest(slug="cliente-a", token=token).token == token


def test_forgot_password_request_normalizes_slug_and_email() -> None:
    request = ForgotPasswordRequest(slug=" Cliente-A ", email=" Ana@Example.Test ")

    assert (request.slug, request.email) == ("cliente-a", "ana@example.test")


@pytest.mark.parametrize(
    "values",
    [
        {"slug": "cliente-a", "email": "invalido"},
        {"slug": "cliente_a", "email": "ana@example.test"},
        {"slug": "cliente-a", "email": "ana@example.test", "token": TOKEN},
    ],
)
def test_forgot_password_request_rejects_invalid_or_extra_fields(values) -> None:
    with pytest.raises(ValidationError):
        ForgotPasswordRequest.model_validate(values)


def test_forgot_password_response_is_the_single_approved_message() -> None:
    assert ForgotPasswordResponse().model_dump() == {"message": PASSWORD_RESET_REQUEST_MESSAGE}
    assert PASSWORD_RESET_REQUEST_MESSAGE == "Se o e-mail existir, enviaremos as instruções."
    with pytest.raises(ValidationError):
        ForgotPasswordResponse(message="Conta não encontrada.")


def test_public_contract_messages_match_the_service_contract() -> None:
    from app.services import account_access

    assert account_access.INVALID_ACTION_LINK_MESSAGE == INVALID_ACTION_LINK_MESSAGE
    assert account_access.PASSWORD_RESET_REQUEST_MESSAGE == PASSWORD_RESET_REQUEST_MESSAGE
    assert account_access.MAX_RAW_TOKEN_LENGTH == ACCOUNT_ACTION_TOKEN_MAX_LENGTH


SECRET_FIELD_FRAGMENTS = ("token", "hash", "password", "dsn", "secret", "database", "available")


@pytest.mark.parametrize(
    "model",
    [
        AccountActionViewResponse,
        ForgotPasswordResponse,
        AccountUserResponse,
        InvitationResponse,
        UserAccessResponse,
    ],
)
def test_response_contracts_expose_no_secret_or_availability_fields(model) -> None:
    schema = model.model_json_schema(by_alias=True)
    names: set[str] = set()

    def collect(node: dict) -> None:
        names.update(node.get("properties", {}))
        for definition in node.get("$defs", {}).values():
            collect(definition)

    collect(schema)
    assert names
    assert not {
        name for name in names if any(part in name.lower() for part in SECRET_FIELD_FRAGMENTS)
    }


def test_action_view_contains_only_company_and_email() -> None:
    assert set(AccountActionViewResponse.model_fields) == {"company_name", "email"}
    with pytest.raises(ValidationError):
        AccountActionViewResponse(company_name="Cliente A", email="a@example.test", user_id="u-1")


def test_invitation_response_serializes_server_confirmed_state_in_camel_case() -> None:
    response = InvitationResponse(
        user=AccountUserResponse(
            id="user-1",
            name="Bia",
            email="bia@example.test",
            jobTitle="Vendas",
            team=None,
            role="Vendedor",
            status="Pendente",
            invitedAt=datetime(2026, 11, 4, 12, 0, tzinfo=UTC),
        ),
        deliveryStatus="failed",
        workspaceVersion=12,
    )

    assert response.model_dump(by_alias=True, mode="json") == {
        "user": {
            "id": "user-1",
            "name": "Bia",
            "email": "bia@example.test",
            "jobTitle": "Vendas",
            "team": None,
            "role": "Vendedor",
            "status": "Pendente",
            "invitedAt": "2026-11-04T12:00:00Z",
        },
        "deliveryStatus": "failed",
        "workspaceVersion": 12,
    }
    with pytest.raises(ValidationError):
        InvitationResponse(user=response.user, deliveryStatus="delivered")
    with pytest.raises(ValidationError):
        InvitationResponse(user=response.user, deliveryStatus="sent", workspaceVersion=0)
    uninitialized = InvitationResponse(user=response.user, deliveryStatus="sent")
    assert uninitialized.model_dump(by_alias=True)["workspaceVersion"] is None
    with pytest.raises(ValidationError):
        AccountUserResponse.model_validate(
            {**response.user.model_dump(by_alias=True), "passwordHash": "x"}
        )
