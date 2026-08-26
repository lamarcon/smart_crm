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
        yield WorkspaceRepository(session), session
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


def test_insert_and_read_are_deep_equal_for_durable_state(repository) -> None:
    repo, _session = repository
    original = sample_state()
    persist(repo, original)
    assert repo.read_active().model_dump(by_alias=True, exclude_none=True) == original


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
