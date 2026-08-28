from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.database import Database, DatabaseSettings
from app.repositories.workspace import WorkspaceRepository
from app.schemas import WorkspaceReferenceError, WorkspaceState
from app.services.workspace import (
    WorkspaceAlreadyInitialized,
    WorkspaceConflict,
    WorkspaceNotInitialized,
    WorkspaceRecordNotFound,
    WorkspaceRestoreConflict,
    WorkspaceService,
)


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("SMART_CRM_TEST_DATABASE_URL", "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test")


def state_data() -> dict:
    return {
        "users": [{"id": "u-1", "name": "Ana", "email": "ana@test", "jobTitle": "Admin", "role": "Administrador", "team": "Gestão", "status": "Ativo", "invitedAt": None}, {"id": "u-2", "name": "Bia", "email": "bia@test", "jobTitle": "Assistente", "role": "Assistente", "team": "Vendas", "status": "Ativo", "invitedAt": None}],
        "leads": [{"id": "L-1", "name": "Lead", "company": "Empresa", "stage": "Em contato", "responsibleId": "u-1", "assistants": ["u-2"]}],
        "companies": [{"id": "E-1", "name": "Empresa", "city": "SP", "segment": "Lab", "phone": "", "ownerId": "u-1"}],
        "contacts": [{"id": "C-1", "name": "Contato", "company": "Empresa", "companyId": "E-1", "email": "", "phone": "", "role": "Comprador"}],
        "deals": [{"id": "N-1", "title": "Negócio", "company": "Empresa", "companyId": "E-1", "contact": "Contato", "contactId": "C-1", "amount": 10, "stage": "Em Contato", "responsibleId": "u-1", "stageChangedById": "u-1", "assistants": ["u-2"], "quotes": [{"id": "Q-1", "description": "Item", "quantity": 1, "unitPrice": 10, "discount": 0, "total": 10, "state": "Enviado"}]}],
        "notifications": [{"id": "NT-1", "userId": "u-2", "text": "Aviso", "detail": "", "time": "Agora", "read": False}],
        "customFieldSchemas": {"leads": [], "contacts": [], "companies": [], "deals": []},
        "moduleFieldSettings": {module: {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []} for module in ("leads", "contacts", "companies", "deals")},
        "ui": {"savedFilters": [], "viewModesByUser": {"u-1": {"leads": "list", "deals": "kanban"}}, "dashboardScopeByUser": {"u-1": "all"}},
    }


def state() -> WorkspaceState:
    return WorkspaceState.model_validate(state_data())


@pytest.fixture
def service():
    root_engine = create_engine(DATABASE_URL)
    schema = f"service_{uuid.uuid4().hex}"
    with root_engine.begin() as setup:
        setup.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection = root_engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    connection.commit()
    connection.close()
    engine = create_engine(DATABASE_URL, connect_args={"options": f"-csearch_path={schema}"}, pool_pre_ping=True)
    database = Database(DatabaseSettings(database_url=DATABASE_URL), engine=engine)
    try:
        yield WorkspaceService(database), database
    finally:
        database.dispose()
        with root_engine.begin() as cleanup:
            cleanup.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root_engine.dispose()


def test_load_reports_uninitialized_workspace_at_version_zero(service) -> None:
    workspace, _database = service
    loaded = workspace.load()
    assert (loaded.initialized, loaded.version, loaded.state) == (False, 0, None)


def test_bootstrap_initializes_version_one_with_exact_counts(service) -> None:
    workspace, _database = service
    result = workspace.bootstrap(state())
    assert result.version == 1
    assert result.counts.model_dump(by_alias=True) == {"users": 2, "leads": 1, "contacts": 1, "companies": 1, "deals": 1, "quotes": 1, "notifications": 1, "customFields": 0}
    assert result.state.model_dump(by_alias=True, exclude_none=True) == state_data()


def test_repeated_bootstrap_returns_typed_conflict_without_changes(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    with pytest.raises(WorkspaceAlreadyInitialized) as error:
        workspace.bootstrap(state())
    assert error.value.current_version == 1
    assert workspace.load().version == 1


def test_concurrent_bootstrap_accepts_exactly_one_winner(service) -> None:
    workspace, _database = service

    def attempt() -> str:
        try:
            workspace.bootstrap(state())
            return "created"
        except WorkspaceAlreadyInitialized:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: attempt(), range(2)))
    assert outcomes == ["conflict", "created"]
    assert workspace.load().version == 1


def test_save_with_current_version_increments_exactly_once(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    changed = state_data()
    changed["leads"][0]["name"] = "Alterado"
    result = workspace.save(1, WorkspaceState.model_validate(changed))
    assert (result.version, result.state.leads[0]["name"]) == (2, "Alterado")


def test_simultaneous_saves_have_one_complete_winner_and_one_conflict(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    candidates = []
    for suffix in ("A", "B"):
        candidate = state_data()
        candidate["leads"][0]["name"] = f"Lead candidato {suffix}"
        candidate["companies"][0]["name"] = f"Empresa candidata {suffix}"
        candidate["contacts"][0]["company"] = candidate["companies"][0]["name"]
        candidate["deals"][0]["company"] = candidate["companies"][0]["name"]
        candidates.append(WorkspaceState.model_validate(candidate))
    start = Barrier(2)

    def attempt(candidate: WorkspaceState) -> tuple[str, int, str]:
        start.wait()
        try:
            result = workspace.save(1, candidate)
            return "saved", result.version, result.state.leads[0]["name"]
        except WorkspaceConflict as error:
            return "conflict", error.current_version, ""

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, candidates))

    assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "saved"]
    assert [outcome[1] for outcome in outcomes] == [2, 2]
    winning_name = next(outcome[2] for outcome in outcomes if outcome[0] == "saved")
    loaded = workspace.load()
    expected = candidates[0] if winning_name.endswith("A") else candidates[1]
    assert loaded.version == 2
    assert loaded.state.model_dump(by_alias=True, exclude_none=True) == expected.model_dump(by_alias=True, exclude_none=True)


def test_stale_save_returns_current_version_and_keeps_database_unchanged(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    workspace.save(1, state())
    changed = state_data()
    changed["leads"][0]["name"] = "Não salvar"
    with pytest.raises(WorkspaceConflict) as error:
        workspace.save(1, WorkspaceState.model_validate(changed))
    assert error.value.current_version == 2
    assert workspace.load().state.leads[0]["name"] == "Lead"


def test_reset_replaces_state_and_increments_once(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    replacement = state_data()
    replacement["notifications"] = []
    result = workspace.reset(1, WorkspaceState.model_validate(replacement))
    assert result.version == 2
    assert result.state.notifications == []


def test_list_deleted_returns_record_after_omission(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    changed = state_data()
    changed["leads"] = []
    workspace.save(1, WorkspaceState.model_validate(changed))
    assert workspace.list_deleted("leads") == [state_data()["leads"][0]]


def test_restore_recovers_links_and_increments_once(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    changed = state_data()
    changed["leads"] = []
    workspace.save(1, WorkspaceState.model_validate(changed))
    result = workspace.restore(2, "leads", "L-1")
    assert result.version == 3
    assert (result.state.leads[0]["id"], result.state.leads[0]["assistants"]) == ("L-1", ["u-2"])


def test_restore_with_stale_version_does_not_reactivate(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    changed = state_data()
    changed["leads"] = []
    workspace.save(1, WorkspaceState.model_validate(changed))
    with pytest.raises(WorkspaceConflict) as error:
        workspace.restore(1, "leads", "L-1")
    assert error.value.current_version == 2
    assert workspace.list_deleted("leads")[0]["id"] == "L-1"


def test_restore_missing_record_returns_typed_not_found(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    with pytest.raises(WorkspaceRecordNotFound):
        workspace.restore(1, "leads", "missing")
    assert workspace.load().version == 1


def test_save_before_bootstrap_returns_not_initialized(service) -> None:
    workspace, _database = service
    with pytest.raises(WorkspaceNotInitialized):
        workspace.save(0, state())
    assert workspace.load().version == 0


def test_invalid_reference_rejects_bootstrap_without_partial_rows(service) -> None:
    workspace, _database = service
    invalid = state_data()
    invalid["leads"][0]["responsibleId"] = "missing"
    with pytest.raises(WorkspaceReferenceError) as error:
        workspace.bootstrap(WorkspaceState.model_validate(invalid))
    assert error.value.path == "leads[0].responsibleId"
    assert workspace.load().initialized is False


def test_repository_exception_rolls_back_save_and_version(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())

    class FailingRepository(WorkspaceRepository):
        def reconcile(self, value, **kwargs) -> None:  # noqa: ANN001
            super().reconcile(value, **kwargs)
            raise RuntimeError("forced service failure")

    failing = WorkspaceService(database, FailingRepository)
    changed = state_data()
    changed["companies"][0]["name"] = "Não salvar"
    with pytest.raises(RuntimeError, match="forced service failure"):
        failing.save(1, WorkspaceState.model_validate(changed))
    loaded = workspace.load()
    assert (loaded.version, loaded.state.companies[0]["name"]) == (1, "Empresa")


def test_restore_detects_active_user_email_conflict() -> None:
    class FakeRepository:
        def list_deleted(self, module: str) -> list[dict]:
            return [{"id": "u-old", "email": "same@test"}]

        def read_active(self):
            return WorkspaceState.model_validate({"users": [{"id": "u-new", "email": "SAME@test"}]})

    with pytest.raises(WorkspaceRestoreConflict):
        WorkspaceService._check_restore_uniqueness(FakeRepository(), "users", "u-old")
