from __future__ import annotations

import os
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Contact,
    CrmUser,
    CustomFieldValue,
    DealAssistant,
    ExternalSourceField,
    Lead,
    LeadAssistant,
    Notification,
    Quote,
    SavedFilter,
)
from app.repositories.workspace import WorkspaceRepository
from app.schemas import WorkspaceState, validate_references


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)


def sample_state() -> dict:
    return {
        "users": [
            {"id": "u-1", "name": "Ana", "email": "ana@test", "jobTitle": "Admin", "role": "Administrador", "team": "Gestão", "status": "Ativo", "invitedAt": None},
            {"id": "u-2", "name": "Bia", "email": "bia@test", "jobTitle": "Assistente", "role": "Assistente", "team": "Vendas", "status": "Ativo", "invitedAt": None},
        ],
        "leads": [{"id": "L-2", "name": "Segundo", "company": "Empresa", "stage": "Em contato", "responsibleId": "u-1", "assistants": ["u-2"], "customFields": [{"key": "empty", "value": ""}, {"key": "flag", "value": False}, {"key": "multi", "value": []}], "visibleCustomFieldKeys": ["empty"], "bitrixFields": [{"name": "Telefone", "occurrence": 1, "position": 0, "value": ""}, {"name": "Telefone", "occurrence": 2, "position": 1, "value": "1199"}]}, {"id": "L-1", "name": "Primeiro", "company": "Empresa", "stage": "Em contato", "responsibleId": "u-1", "assistants": []}],
        "companies": [{"id": "E-1", "name": "Empresa", "city": "SP", "segment": "Lab", "phone": "", "ownerId": "u-1"}],
        "contacts": [{"id": "C-1", "name": "Contato", "company": "Empresa", "companyId": "E-1", "email": "", "phone": "", "role": "Comprador"}],
        "deals": [{"id": "N-1", "title": "Negócio", "company": "Empresa", "companyId": "E-1", "contact": "Contato", "contactId": "C-1", "amount": 10.25, "stage": "Em Contato", "responsibleId": "u-1", "stageChangedById": "u-1", "assistants": ["u-2"], "stageHistory": [{"from": "Novo", "to": "Em Contato", "at": "2026-08-26T12:00:00Z", "byId": "u-1"}], "quotes": [{"id": "Q-1", "description": "Item", "quantity": 1, "unitPrice": 10.25, "discount": 0, "total": 10.25, "state": "Enviado", "pdf": "q.pdf"}]}],
        "notifications": [{"id": "NT-1", "userId": "u-2", "text": "Aviso", "detail": "Detalhe", "time": "Agora", "read": False}],
        "customFieldSchemas": {"leads": [{"key": "empty", "label": "Vazio", "type": "text", "position": 0}, {"key": "flag", "label": "Flag", "type": "boolean", "position": 1}, {"key": "multi", "label": "Multi", "type": "multiselect", "position": 2}], "contacts": [], "companies": [], "deals": []},
        "moduleFieldSettings": {"leads": {"hiddenStandardFields": ["email"], "hiddenCustomFieldKeys": ["empty"]}, "contacts": {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []}, "companies": {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []}, "deals": {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []}},
        "ui": {"savedFilters": [{"id": "SF-1", "userId": "u-1", "scope": "deals", "name": "Meu", "filter": {"stage": ["Em Contato"]}, "updatedAt": "2026-08-26T12:00:00Z"}], "viewModesByUser": {"u-1": {"leads": "list", "deals": "kanban"}}, "dashboardScopeByUser": {"u-1": "deals"}},
    }


@pytest.fixture
def repository():
    engine = create_engine(DATABASE_URL)
    schema = f"repository_{uuid.uuid4().hex}"
    with engine.begin() as setup:
        setup.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    connection.commit()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        session.execute(
            text("SELECT set_config('smartcrm.workspace_id', 'default', true)")
        )
        yield WorkspaceRepository(session, "default"), session
    finally:
        session.close()
        connection.close()
        with engine.begin() as cleanup:
            cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def persist(repository: WorkspaceRepository, state: dict) -> None:
    parsed = WorkspaceState.model_validate(state)
    validate_references(parsed)
    repository.reconcile(parsed)
    repository.session.commit()


def without_pipeline_metadata(state: dict) -> dict:
    comparable = deepcopy(state)
    for deal in comparable.get("deals", []):
        deal.pop("pipelineId", None)
        if deal.get("currency") == "BRL":
            deal.pop("currency")  # server default for deals saved without a currency
        deal.pop("stageId", None)
        for history in deal.get("stageHistory") or []:
            history.pop("fromStageId", None)
            history.pop("toStageId", None)
    return comparable


def test_insert_and_read_are_deep_equal_for_durable_state(repository) -> None:
    repo, _session = repository
    original = sample_state()
    persist(repo, original)
    loaded = repo.read_active().model_dump(by_alias=True, exclude_none=True)
    assert without_pipeline_metadata(loaded) == original


def test_every_ui_user_status_round_trips_through_postgres(repository) -> None:
    repo, _session = repository
    original = sample_state()
    original["users"].extend(
        [
            {"id": "u-3", "name": "Carla", "email": "carla@test", "jobTitle": "Vendas", "role": "Vendedor", "team": "Vendas", "status": "Inativo", "invitedAt": None},
            {"id": "u-4", "name": "Dora", "email": "dora@test", "jobTitle": "Vendas", "role": "Vendedor", "team": "Vendas", "status": "Cancelado", "invitedAt": None},
        ]
    )
    original["users"][1]["status"] = "Pendente"

    persist(repo, original)

    loaded_statuses = {
        user["id"]: user["status"]
        for user in repo.read_active().model_dump(by_alias=True, exclude_none=True)["users"]
    }
    assert loaded_statuses == {
        "u-1": "Ativo",
        "u-2": "Pendente",
        "u-3": "Inativo",
        "u-4": "Cancelado",
    }


@pytest.mark.parametrize(
    ("user_id", "field", "value"),
    [
        ("u-1", "role", "Vendedor"),
        ("u-2", "role", "Administrador"),
        ("u-2", "status", "Inativo"),
    ],
)
def test_access_change_increments_auth_version_once_and_queues_revocation(
    repository,
    user_id: str,
    field: str,
    value: str,
) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    session.info.clear()
    changed = deepcopy(original)
    target = next(user for user in changed["users"] if user["id"] == user_id)
    target[field] = value

    repo.reconcile(WorkspaceState.model_validate(changed))
    session.flush()

    row = session.scalar(
        select(CrmUser).where(
            CrmUser.workspace_id == "default",
            CrmUser.id == user_id,
        )
    )
    assert row.auth_version == 1
    assert session.info["auth_changed_user_ids"] == {user_id}


def test_non_access_user_change_does_not_increment_or_queue_revocation(repository) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    session.info.clear()
    changed = deepcopy(original)
    changed["users"][0]["name"] = "Ana atualizada"

    repo.reconcile(WorkspaceState.model_validate(changed))
    session.flush()

    row = session.scalar(
        select(CrmUser).where(
            CrmUser.workspace_id == "default",
            CrmUser.id == "u-1",
        )
    )
    assert row.auth_version == 0
    assert "auth_changed_user_ids" not in session.info


def test_access_change_auth_version_rolls_back_with_tenant_transaction(repository) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    session.info.clear()
    changed = deepcopy(original)
    changed["users"][0]["status"] = "Inativo"

    repo.reconcile(WorkspaceState.model_validate(changed))
    session.flush()
    assert session.scalar(select(CrmUser.auth_version).where(CrmUser.id == "u-1")) == 1
    session.rollback()
    session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))

    assert session.scalar(select(CrmUser.auth_version).where(CrmUser.id == "u-1")) == 0


def test_every_table_family_receives_rows(repository) -> None:
    repo, session = repository
    persist(repo, sample_state())
    assert session.scalar(select(func.count()).select_from(LeadAssistant)) == 1
    assert session.scalar(select(func.count()).select_from(DealAssistant)) == 1
    assert session.scalar(select(func.count()).select_from(Quote)) == 1
    assert session.scalar(select(func.count()).select_from(Notification)) == 1
    assert session.scalar(select(func.count()).select_from(SavedFilter)) == 1


def test_order_and_duplicate_bitrix_headers_round_trip(repository) -> None:
    repo, _session = repository
    original = sample_state()
    persist(repo, original)
    loaded = repo.read_active().model_dump(by_alias=True, exclude_none=True)
    assert [lead["id"] for lead in loaded["leads"]] == ["L-2", "L-1"]
    assert loaded["leads"][0]["bitrixFields"] == original["leads"][0]["bitrixFields"]


def test_empty_false_and_list_custom_values_are_lossless(repository) -> None:
    repo, session = repository
    persist(repo, sample_state())
    values = session.scalars(select(CustomFieldValue).order_by(CustomFieldValue.position)).all()
    assert [item.value for item in values] == ["", False, []]


def test_absent_active_record_is_soft_deleted(repository) -> None:
    repo, session = repository
    state = sample_state()
    persist(repo, state)
    state["leads"] = state["leads"][1:]
    persist(repo, state)
    assert session.get(Lead, "L-2").deleted_at is not None
    assert [lead["id"] for lead in repo.read_active().leads] == ["L-1"]


def test_present_record_is_reactivated(repository) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    reduced = deepcopy(original)
    reduced["leads"] = reduced["leads"][1:]
    persist(repo, reduced)
    persist(repo, original)
    assert session.get(Lead, "L-2").deleted_at is None


def test_soft_deleted_parent_keeps_child_rows(repository) -> None:
    repo, session = repository
    state = sample_state()
    persist(repo, state)
    before = session.scalar(select(func.count()).select_from(ExternalSourceField))
    state["leads"] = state["leads"][1:]
    persist(repo, state)
    assert session.scalar(select(func.count()).select_from(LeadAssistant)) == 1
    assert session.scalar(select(func.count()).select_from(ExternalSourceField)) == before == 2


def test_company_and_contact_links_are_deterministic(repository) -> None:
    repo, session = repository
    persist(repo, sample_state())
    contact = session.get(Contact, "C-1")
    company = session.get(Company, "E-1")
    assert (contact.company_id, contact.company_text) == (company.id, "Empresa")


def test_forced_intermediate_failure_rolls_back_every_table(repository) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    changed = deepcopy(original)
    changed["companies"][0]["name"] = "Alterada"
    with pytest.raises(RuntimeError, match="forced repository failure"):
        repo.reconcile(WorkspaceState.model_validate(changed), fail_after="companies")
        session.commit()
    session.rollback()
    assert repo.read_active().companies[0]["name"] == "Empresa"


def test_hidden_fields_and_preferences_round_trip(repository) -> None:
    repo, _session = repository
    original = sample_state()
    persist(repo, original)
    loaded = repo.read_active().model_dump(by_alias=True, exclude_none=True)
    assert loaded["moduleFieldSettings"] == original["moduleFieldSettings"]
    assert loaded["ui"] == original["ui"]


def test_combined_workflow_state_rehydrates_in_new_repository_session(repository) -> None:
    repo, _session = repository
    original = sample_state()
    original["users"].append(
        {"id": "u-3", "name": "Convidada", "email": "convidada@test", "jobTitle": "Vendas", "role": "Vendedor", "team": "Vendas", "status": "Pendente", "invitedAt": "2026-08-26T12:30:00Z"}
    )
    original["leads"][0]["name"] = "Lead criado e editado"
    original["leads"][0]["stage"] = "Lead convertido"
    original["deals"][0]["stageHistory"].extend(
        [
            {"from": "Em Contato", "to": "Negociação Revisão", "at": "2026-08-26T12:31:00Z", "byId": "u-1"},
            {"from": "Negociação Revisão", "to": "Em Contato", "at": "2026-08-26T12:32:00Z", "byId": "u-1"},
        ]
    )
    original["notifications"].append(
        {"id": "NT-2", "userId": "u-1", "text": "Automação executada", "detail": "N-1", "time": "Agora", "read": False}
    )
    deal_field = {"key": "workflow:contract", "label": "Contrato", "type": "text", "position": 0}
    original["customFieldSchemas"]["deals"] = [deal_field]
    original["deals"][0]["customFields"] = [{**deal_field, "value": "CTR-900"}]
    original["deals"][0]["visibleCustomFieldKeys"] = [deal_field["key"]]

    persist(repo, original)

    fresh_session = Session(bind=repo.session.get_bind(), expire_on_commit=False)
    try:
        fresh_session.execute(
            text("SELECT set_config('smartcrm.workspace_id', 'default', true)")
        )
        rehydrated = WorkspaceRepository(fresh_session, "default").read_active().model_dump(by_alias=True, exclude_none=True)
    finally:
        fresh_session.close()
    assert without_pipeline_metadata(rehydrated) == original


# --- T9: server-managed account fields ---------------------------------------

from datetime import datetime, timezone  # noqa: E402

from app.repositories.workspace import team_id_for_name  # noqa: E402

SERVER_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2VydmVy$c2VydmVyLW1hbmFnZWQ"
INVITED_AT = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _row(session: Session, user_id: str) -> CrmUser:
    session.expire_all()
    return session.scalar(
        select(CrmUser).where(CrmUser.workspace_id == "default", CrmUser.id == user_id)
    )


def _set_columns(session: Session, user_id: str, **values: object) -> None:
    row = _row(session, user_id)
    for name, value in values.items():
        setattr(row, name, value)
    session.commit()
    session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))


def _add_server_invitee(session: Session, user_id: str, *, status: str = "Pendente") -> None:
    session.add(
        CrmUser(
            id=user_id,
            workspace_id="default",
            name="Convidada Real",
            email=f"{user_id}@test",
            normalized_email=f"{user_id}@test",
            password_hash=None,
            auth_enabled=False,
            auth_version=0,
            job_title="Comercial",
            team_id=None,
            role="Vendedor",
            status=status,
            invited_at=INVITED_AT,
            payload={},
        )
    )
    session.commit()
    session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))


def _users(repo: WorkspaceRepository) -> dict[str, dict]:
    return {
        user["id"]: user
        for user in repo.read_active().model_dump(by_alias=True, exclude_none=True)["users"]
    }


def test_workspace_update_preserves_credentials_access_flags_version_and_identity(
    repository,
) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    _set_columns(
        session,
        "u-1",
        password_hash=SERVER_HASH,
        auth_enabled=True,
        auth_version=3,
        normalized_email="ana@test",
    )
    session.info.clear()
    crafted = deepcopy(original)
    crafted["users"][0].update(
        {
            "name": "Ana Editada",
            "jobTitle": "Diretora",
            "email": "atacante@test",
            "passwordHash": "texto-plano",
            "password_hash": "texto-plano",
            "authEnabled": False,
            "auth_enabled": False,
            "authVersion": 0,
            "auth_version": 0,
            "normalizedEmail": "atacante@test",
            "normalized_email": "atacante@test",
        }
    )

    repo.reconcile(WorkspaceState.model_validate(crafted))
    session.commit()
    session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))

    row = _row(session, "u-1")
    assert (row.password_hash, row.auth_enabled, row.auth_version) == (SERVER_HASH, True, 3)
    assert (row.email, row.normalized_email) == ("ana@test", "ana@test")
    assert (row.name, row.job_title) == ("Ana Editada", "Diretora")
    assert "auth_changed_user_ids" not in session.info
    assert "texto-plano" not in repr(row.payload)
    assert "atacante@test" not in repr(row.payload)
    loaded = _users(repo)["u-1"]
    assert not {
        "passwordHash",
        "password_hash",
        "authEnabled",
        "auth_enabled",
        "authVersion",
        "auth_version",
        "normalizedEmail",
        "normalized_email",
    } & set(loaded)
    assert (loaded["email"], loaded["name"], loaded["jobTitle"]) == (
        "ana@test",
        "Ana Editada",
        "Diretora",
    )


def test_legacy_roster_user_without_server_identity_keeps_editable_email(repository) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    changed = deepcopy(original)
    changed["users"][1]["email"] = "bia.nova@test"

    persist(repo, changed)

    row = _row(session, "u-2")
    assert (row.email, row.normalized_email, row.auth_enabled) == ("bia.nova@test", None, False)


@pytest.mark.parametrize(
    ("current", "submitted"),
    [
        ("Pendente", "Ativo"),
        ("Pendente", "Inativo"),
        ("Cancelado", "Ativo"),
        ("Cancelado", "Pendente"),
        ("Inativo", "Ativo"),
        ("Ativo", "Pendente"),
        ("Ativo", "Cancelado"),
        ("Ativo", "Convidado"),
    ],
)
def test_crafted_snapshot_cannot_change_protected_account_status(
    repository,
    current: str,
    submitted: str,
) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    _set_columns(session, "u-2", status=current, auth_version=2)
    session.info.clear()
    crafted = deepcopy(original)
    crafted["users"][1]["status"] = submitted

    repo.reconcile(WorkspaceState.model_validate(crafted))
    session.commit()
    session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))

    row = _row(session, "u-2")
    assert (row.status, row.auth_version, row.auth_enabled) == (current, 2, False)
    assert "auth_changed_user_ids" not in session.info
    assert _users(repo)["u-2"]["status"] == current


def test_server_created_invitee_is_read_from_columns_and_survives_a_stale_admin_snapshot(
    repository,
) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    _add_server_invitee(session, "u-real")

    loaded = repo.read_active().model_dump(by_alias=True, exclude_none=True)
    validate_references(WorkspaceState.model_validate(loaded))
    invitee = next(user for user in loaded["users"] if user["id"] == "u-real")
    assert invitee == {
        "id": "u-real",
        "name": "Convidada Real",
        "email": "u-real@test",
        "jobTitle": "Comercial",
        "role": "Vendedor",
        "status": "Pendente",
        "invitedAt": "2026-10-31T12:00:00Z",
    }
    assert [user["id"] for user in loaded["users"]][-1] == "u-real"

    stale = deepcopy(original)
    stale["users"][0]["name"] = "Ana sem saber do convite"
    persist(repo, stale)

    row = _row(session, "u-real")
    assert (row.deleted_at, row.status, row.payload) == (None, "Pendente", {})
    assert _users(repo)["u-real"]["status"] == "Pendente"
    assert _row(session, "u-1").name == "Ana sem saber do convite"


def test_columns_win_over_a_stale_payload_after_server_reinvitation(repository) -> None:
    repo, session = repository
    original = sample_state()
    original["users"].append(
        {"id": "u-3", "name": "Carla", "email": "carla@test", "jobTitle": "Vendas", "role": "Vendedor", "team": "Vendas", "status": "Cancelado", "invitedAt": None}
    )
    persist(repo, original)
    _set_columns(
        session,
        "u-3",
        name="Carla Reconvidada",
        role="Faturamento",
        team_id=team_id_for_name("Gestão"),
        status="Pendente",
        invited_at=INVITED_AT,
        normalized_email="carla@test",
    )

    loaded = _users(repo)["u-3"]

    assert {key: loaded[key] for key in ("name", "role", "team", "status", "invitedAt")} == {
        "name": "Carla Reconvidada",
        "role": "Faturamento",
        "team": "Gestão",
        "status": "Pendente",
        "invitedAt": "2026-10-31T12:00:00Z",
    }
    crafted = deepcopy(original)
    crafted["users"][-1]["invitedAt"] = "2020-01-01T00:00:00Z"
    persist(repo, crafted)
    assert (_row(session, "u-3").invited_at, _row(session, "u-3").status) == (
        INVITED_AT,
        "Pendente",
    )


def test_pending_invitee_cannot_be_made_assignable_by_a_crafted_snapshot(repository) -> None:
    repo, session = repository
    original = sample_state()
    persist(repo, original)
    _add_server_invitee(session, "u-real")
    crafted = repo.read_active().model_dump(by_alias=True, exclude_none=True)
    target = next(user for user in crafted["users"] if user["id"] == "u-real")
    target["status"] = "Ativo"
    target["authEnabled"] = True

    persist(repo, crafted)

    loaded = _users(repo)
    assert loaded["u-real"]["status"] == "Pendente"
    row = _row(session, "u-real")
    assert (row.status, row.auth_enabled, row.password_hash) == ("Pendente", False, None)
    assignable = {user_id for user_id, user in loaded.items() if user["status"] == "Ativo"}
    assert "u-real" not in assignable


def test_deal_currency_and_frozen_rate_round_trip(repository) -> None:
    repo, session = repository
    state = sample_state()
    state["deals"][0].update(currency="usd", amount=1000, fxRate="5.5606", fxRateDate="2026-11-11")
    persist(repo, state)
    deal = repo.read_active().deals[0]
    assert (deal["currency"], deal["fxRate"], deal["fxRateDate"]) == ("USD", "5.5606", "2026-11-11")
    row = session.execute(text("SELECT currency, fx_rate, fx_rate_date FROM deals WHERE id = 'N-1'")).one()
    assert (row.currency, str(row.fx_rate), row.fx_rate_date.isoformat()) == ("USD", "5.560600", "2026-11-11")

    state["deals"][0].update(currency="EUR")
    state["deals"][0].pop("fxRate")
    state["deals"][0].pop("fxRateDate")
    persist(repo, state)
    deal = repo.read_active().deals[0]
    assert deal["currency"] == "EUR"
    assert "fxRate" not in deal and "fxRateDate" not in deal


def test_deals_without_currency_are_real(repository) -> None:
    repo, _session = repository
    persist(repo, sample_state())
    assert repo.read_active().deals[0]["currency"] == "BRL"


@pytest.mark.parametrize("bad", [{"currency": "GBP"}, {"currency": "USD", "fxRate": "0", "fxRateDate": "2026-11-11"}])
def test_database_refuses_unknown_currency_or_zero_rate(repository, bad) -> None:  # noqa: ANN001
    from sqlalchemy.exc import IntegrityError

    repo, session = repository
    state = sample_state()
    state["deals"][0].update(bad)
    with pytest.raises(IntegrityError):
        persist(repo, state)
    session.rollback()


def test_the_frozen_rate_columns_are_the_source_of_truth_on_read(repository) -> None:
    repo, session = repository
    state = sample_state()
    state["deals"][0].update(currency="USD", fxRate="5.5606", fxRateDate="2026-11-11")
    persist(repo, state)
    # Server-side writes (e.g. pipeline transfers) update the columns directly.
    session.execute(text("UPDATE deals SET fx_rate = 5.61, fx_rate_date = '2026-11-12' WHERE id = 'N-1'"))
    deal = repo.read_active().deals[0]
    assert (deal["fxRate"], deal["fxRateDate"]) == ("5.61", "2026-11-12")
    session.execute(text("UPDATE deals SET fx_rate = NULL, fx_rate_date = NULL WHERE id = 'N-1'"))
    deal = repo.read_active().deals[0]
    assert "fxRate" not in deal and "fxRateDate" not in deal
