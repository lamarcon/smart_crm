from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text

from app.database import Database, DatabaseSettings
from app.models import (
    Company,
    CrmActivityEvent,
    Deal,
    DealPipelineStage,
    DealStageHistory,
    Notification,
)
from app.policies import PrincipalScope
from app.repositories.activity import ActivityRepository
from app.repositories.workspace import WorkspaceRepository, team_id_for_name
from app.schemas import DealPipelineUpdateRequest, WorkspaceReferenceError, WorkspaceState
from app.services.pipeline import DealPipelineService
from app.services.deal_automation import DealAutomationExecutor
from app.services.workspace import (
    WorkspaceAlreadyInitialized,
    WorkspaceAuthorizationError,
    WorkspaceConflict,
    WorkspaceNotInitialized,
    WorkspaceRecordNotFound,
    WorkspaceRestoreConflict,
    WorkspaceService,
    WorkspaceStageConflict,
)


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("SMART_CRM_TEST_DATABASE_URL", "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test")
TEST_PRINCIPAL = PrincipalScope(
    tenant_id=uuid.uuid4(),
    workspace_id="default",
    user_id="u-1",
    role="Administrador",
    team_id=None,
    auth_version=1,
)


class BoundWorkspaceService:
    def __init__(self, service: WorkspaceService, database: Database) -> None:
        self.service = service
        self.database = database

    def _call(self, method: str, *args):  # noqa: ANN002, ANN202
        with self.database.session_scope() as session:
            return getattr(self.service, method)(session, TEST_PRINCIPAL, *args)

    def load(self):  # noqa: ANN201
        return self._call("load")

    def bootstrap(self, value):  # noqa: ANN001, ANN201
        return self._call("bootstrap", value)

    def save(self, version, value):  # noqa: ANN001, ANN201
        return self._call("save", version, value)

    def reset(self, version, value):  # noqa: ANN001, ANN201
        return self._call("reset", version, value)

    def list_deleted(self, module):  # noqa: ANN001, ANN201
        return self._call("list_deleted", module)

    def restore(self, version, module, record_id):  # noqa: ANN001, ANN201
        return self._call("restore", version, module, record_id)


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


def without_pipeline_metadata(state_value: dict) -> dict:
    comparable = deepcopy(state_value)
    for deal in comparable.get("deals", []):
        deal.pop("pipelineId", None)
        deal.pop("stageId", None)
        if deal.get("stageHistory") == []:
            deal.pop("stageHistory")
        for history in deal.get("stageHistory") or []:
            history.pop("fromStageId", None)
            history.pop("toStageId", None)
    return comparable


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
    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "options": f"-csearch_path={schema} -csmartcrm.workspace_id=default"
        },
        pool_pre_ping=True,
    )
    database = Database(DatabaseSettings(database_url=DATABASE_URL), engine=engine)
    try:
        yield BoundWorkspaceService(WorkspaceService(), database), database
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
    loaded = result.state.model_dump(by_alias=True, exclude_none=True)
    assert without_pipeline_metadata(loaded) == state_data()


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
    actual = loaded.state.model_dump(by_alias=True, exclude_none=True)
    submitted = expected.model_dump(by_alias=True, exclude_none=True)
    assert without_pipeline_metadata(actual) == submitted


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

    failing = BoundWorkspaceService(WorkspaceService(FailingRepository), database)
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


def test_non_admin_privileged_save_returns_no_partial_write(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())
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
        projected.users[0]["role"] = "Faturamento"
        with pytest.raises(WorkspaceAuthorizationError, match="administrative snapshot change"):
            core.save(session, assistant, 1, projected)

    loaded = workspace.load()
    assert loaded.version == 1
    assert loaded.state.users[0]["role"] == "Administrador"


def test_non_admin_physical_save_preserves_invisible_canonical_row(service) -> None:
    workspace, database = service
    initial = state_data()
    initial["leads"].append(
        {
            "id": "L-hidden",
            "name": "Invisible canonical",
            "company": "Empresa",
            "stage": "Em contato",
            "responsibleId": "u-1",
            "assistants": [],
        }
    )
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
        assert [item["id"] for item in projected.leads] == ["L-1"]
        projected.leads[0]["name"] = "Authorized"
        result = core.save(session, assistant, 1, projected)
        assert result.version == 2

    loaded = workspace.load()
    assert {item["id"]: item["name"] for item in loaded.state.leads} == {
        "L-1": "Authorized",
        "L-hidden": "Invisible canonical",
    }


def test_non_admin_stale_version_fails_before_merge_and_keeps_database(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())
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
        projected.leads[0]["name"] = "Must not persist"
        with pytest.raises(WorkspaceConflict) as error:
            core.save(session, assistant, 0, projected)
        assert error.value.current_version == 1

    loaded = workspace.load()
    assert loaded.version == 1
    assert loaded.state.leads[0]["name"] == "Lead"


def test_workspace_load_and_save_use_canonical_stage_identity_and_name(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    loaded = workspace.load()
    deal = loaded.state.deals[0]
    original_pipeline_id = deal["pipelineId"]
    original_stage_id = deal["stageId"]
    deal["stage"] = "forged display"
    deal["stageHistory"] = [
        {"from": "forged", "to": "forged", "at": "2000-01-01T00:00:00Z"}
    ]

    result = workspace.save(loaded.version, loaded.state)

    assert result.state.deals[0]["pipelineId"] == original_pipeline_id
    assert result.state.deals[0]["stageId"] == original_stage_id
    assert result.state.deals[0]["stage"] == "Em Contato"
    assert result.state.deals[0]["stageHistory"] == []


def test_workspace_stage_move_builds_immutable_server_history_and_semantics(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())
    loaded = workspace.load()
    original_stage_id = loaded.state.deals[0]["stageId"]
    with database.session_scope() as session:
        won = session.scalar(
            select(DealPipelineStage).where(
                DealPipelineStage.workspace_id == "default",
                DealPipelineStage.semantic_type == "won",
            )
        )
    deal = loaded.state.deals[0]
    deal["stageId"] = str(won.id)
    deal["stage"] = "forged won label"
    deal["stageHistory"] = [{"to": "forged"}]

    moved = workspace.save(loaded.version, loaded.state)
    canonical = moved.state.deals[0]
    assert canonical["stageId"] == str(won.id)
    assert canonical["stage"] == won.name
    assert canonical["wonAt"]
    assert len(canonical["stageHistory"]) == 1
    assert canonical["stageHistory"][0]["fromStageId"] == original_stage_id
    assert canonical["stageHistory"][0]["toStageId"] == str(won.id)
    assert canonical["stageHistory"][0]["byId"] == TEST_PRINCIPAL.user_id
    assert canonical["stageHistory"][0]["to"] == won.name

    canonical["stageHistory"] = []
    canonical["stageChangedById"] = "forged-user"
    preserved = workspace.save(moved.version, moved.state)
    assert len(preserved.state.deals[0]["stageHistory"]) == 1
    assert preserved.state.deals[0]["stageChangedById"] == TEST_PRINCIPAL.user_id
    with database.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(DealStageHistory)) == 1


def test_workspace_stage_move_dual_writes_activity_retries_and_undoes(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())
    loaded = workspace.load()
    original = deepcopy(loaded.state.deals[0])
    with database.session_scope() as session:
        won = session.scalar(
            select(DealPipelineStage).where(
                DealPipelineStage.workspace_id == "default",
                DealPipelineStage.semantic_type == "won",
            )
        )
    moved_input = deepcopy(loaded.state)
    moved_input.deals[0].update(
        {
            "stageId": str(won.id),
            "stage": "forged",
            "stageHistory": [{"to": "forged", "byId": "forged"}],
            "activity": {"eventType": "forged"},
            "actorName": "forged",
            "occurredAt": "1999-01-01T00:00:00Z",
            "workspaceId": "foreign",
        }
    )

    moved = workspace.save(loaded.version, moved_input)
    with pytest.raises(WorkspaceConflict):
        workspace.save(loaded.version, moved_input)

    with database.session_scope() as session:
        histories = session.scalars(select(DealStageHistory)).all()
        events = session.scalars(
            select(CrmActivityEvent)
            .where(CrmActivityEvent.deal_id == "N-1")
            .order_by(CrmActivityEvent.id)
        ).all()
        persisted = session.get(Deal, "N-1")
        assert len(histories) == 1
        assert len(events) == 1
        assert events[0].event_type == "deal.stage_changed"
        assert events[0].actor_user_id == "u-1"
        assert events[0].actor_name == "Ana"
        assert events[0].details == {
            "fromStageId": original["stageId"],
            "fromStageName": "Em Contato",
            "toStageId": str(won.id),
            "toStageName": won.name,
            "source": "user",
        }
        persisted_record = persisted.payload["record"]
        assert not {
            "activity",
            "actorName",
            "occurredAt",
            "workspaceId",
        }.intersection(persisted_record)

    undo = deepcopy(moved.state)
    undo.deals[0]["stageId"] = original["stageId"]
    undone = workspace.save(moved.version, undo)
    assert undone.state.deals[0]["stageId"] == original["stageId"]
    with database.session_scope() as session:
        histories = session.scalars(
            select(DealStageHistory).order_by(DealStageHistory.position)
        ).all()
        events = session.scalars(
            select(CrmActivityEvent)
            .where(CrmActivityEvent.deal_id == "N-1")
            .order_by(CrmActivityEvent.id)
        ).all()
        assert len(histories) == len(events) == 2
        assert events[-1].details["fromStageId"] == str(won.id)
        assert events[-1].details["toStageId"] == original["stageId"]


def test_workspace_company_creation_change_redaction_and_no_op(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())
    loaded = workspace.load()
    changed = deepcopy(loaded.state)
    changed.companies[0].update(
        {
            "name": "Empresa Renomeada",
            "city": "RJ",
            "activityHistory": [{"secret": "do-not-store"}],
            "actorId": "forged",
            "tenantId": "foreign",
            "eventType": "company.forged",
        }
    )
    changed.companies.append(
        {
            "id": "E-2",
            "name": "Empresa Nova",
            "city": "POA",
            "segment": "Tech",
            "phone": "",
            "ownerId": "u-1",
            "details": {"password": "forged"},
        }
    )

    saved = workspace.save(loaded.version, changed)
    no_op = workspace.save(saved.version, saved.state)
    assert no_op.version == saved.version + 1

    with database.session_scope() as session:
        events = session.scalars(
            select(CrmActivityEvent)
            .where(CrmActivityEvent.company_id.is_not(None))
            .order_by(CrmActivityEvent.id)
        ).all()
        assert [(event.company_id, event.event_type) for event in events] == [
            ("E-1", "company.updated"),
            ("E-2", "company.created"),
        ]
        updated_changes = events[0].details["changes"]
        assert [change["field"] for change in updated_changes] == ["name", "city"]
        assert updated_changes[0]["before"] == "Empresa"
        assert updated_changes[0]["after"] == "Empresa Renomeada"
        assert events[0].actor_name == events[1].actor_name == "Ana"
        assert all(
            set(change) == {"field", "label", "before", "after"}
            for event in events
            for change in event.details["changes"]
        )
        first = session.get(Company, "E-1")
        second = session.get(Company, "E-2")
        assert not {
            "activityHistory",
            "actorId",
            "tenantId",
            "eventType",
        }.intersection(first.payload["record"])
        assert "details" not in second.payload["record"]


def test_workspace_billing_transition_commits_server_effects_once(service) -> None:
    workspace, database = service
    initial = state_data()
    initial["users"].append(
        {
            "id": "u-billing",
            "name": "Equipe Faturamento",
            "email": "billing@test",
            "jobTitle": "Analista",
            "role": "Faturamento",
            "team": "Faturamento",
            "status": "Ativo",
            "invitedAt": None,
        }
    )
    workspace.bootstrap(WorkspaceState.model_validate(initial))
    loaded = workspace.load()
    with database.session_scope() as session:
        billing = session.scalar(
            select(DealPipelineStage).where(
                DealPipelineStage.workspace_id == "default",
                DealPipelineStage.system_key == "billing",
            )
        )
    loaded.state.deals[0]["stageId"] = str(billing.id)

    saved = workspace.save(loaded.version, loaded.state)
    with pytest.raises(WorkspaceConflict):
        workspace.save(loaded.version, loaded.state)

    canonical = saved.state.deals[0]
    assert canonical["stageId"] == str(billing.id)
    assert canonical["responsibleId"] == "u-billing"
    assert canonical["team"] == "Faturamento"
    assert sum(
        item.get("text") == "Responsabilidade alterada automaticamente."
        for item in saved.state.notifications
    ) == 1
    assert sum(
        item.get("text") == "Automação de Faturamento executada."
        for item in saved.state.notifications
    ) == 1

    with database.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(DealStageHistory)) == 1
        events = session.scalars(
            select(CrmActivityEvent)
            .where(CrmActivityEvent.deal_id == "N-1")
            .order_by(CrmActivityEvent.id)
        ).all()
        assert [event.category for event in events] == ["movement", "automation"]
        assert events[-1].details["result"] == "success"
        assert session.scalar(select(func.count()).select_from(Notification)) == 3


def test_activity_failure_rolls_back_workspace_version_rows_and_events(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())

    class FailingActivityRepository(ActivityRepository):
        def append_many(self, events):  # noqa: ANN001, ANN201
            super().append_many(events)
            raise RuntimeError("forced activity failure")

    failing = BoundWorkspaceService(
        WorkspaceService(activity_repository_factory=FailingActivityRepository),
        database,
    )
    changed = workspace.load().state
    changed.companies[0]["name"] = "Must roll back"
    with pytest.raises(RuntimeError, match="forced activity failure"):
        failing.save(1, changed)

    loaded = workspace.load()
    assert loaded.version == 1
    assert loaded.state.companies[0]["name"] == "Empresa"
    with database.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 0


def test_automation_failure_rolls_back_transition_history_and_notifications(service) -> None:
    workspace, database = service
    initial = state_data()
    initial["users"].append(
        {
            "id": "u-billing",
            "name": "Equipe Faturamento",
            "email": "billing@test",
            "jobTitle": "Analista",
            "role": "Faturamento",
            "team": "Faturamento",
            "status": "Ativo",
            "invitedAt": None,
        }
    )
    workspace.bootstrap(WorkspaceState.model_validate(initial))

    class FailingAutomationExecutor(DealAutomationExecutor):
        def execute_for_transition(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            super().execute_for_transition(*args, **kwargs)
            raise RuntimeError("forced automation failure")

    failing = BoundWorkspaceService(
        WorkspaceService(automation_executor=FailingAutomationExecutor()),
        database,
    )
    loaded = workspace.load()
    original_stage_id = loaded.state.deals[0]["stageId"]
    with database.session_scope() as session:
        billing = session.scalar(
            select(DealPipelineStage).where(
                DealPipelineStage.workspace_id == "default",
                DealPipelineStage.system_key == "billing",
            )
        )
    loaded.state.deals[0]["stageId"] = str(billing.id)
    with pytest.raises(RuntimeError, match="forced automation failure"):
        failing.save(loaded.version, loaded.state)

    canonical = workspace.load()
    assert canonical.version == loaded.version
    assert canonical.state.deals[0]["stageId"] == original_stage_id
    assert len(canonical.state.notifications) == 1
    with database.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(DealStageHistory)) == 0
        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 0


def test_new_deal_requires_active_initial_stage_and_invalid_stage_rolls_back(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())
    loaded = workspace.load()
    existing = deepcopy(loaded.state.deals[0])
    existing["id"] = "N-2"
    existing["title"] = "Novo canônico"
    existing["quotes"] = []
    existing["stageHistory"] = [{"to": "forged"}]
    loaded.state.deals.append(existing)

    created = workspace.save(loaded.version, loaded.state)
    new_deal = next(item for item in created.state.deals if item["id"] == "N-2")
    assert new_deal["stageId"] == created.state.deals[0]["stageId"]
    assert new_deal["pipelineId"] == created.state.deals[0]["pipelineId"]
    assert new_deal["stage"] == "Em Contato"
    assert new_deal["stageHistory"] == []

    forged = deepcopy(created.state)
    forged.deals[0]["stageId"] = str(uuid.uuid4())
    with pytest.raises(WorkspaceStageConflict) as error:
        workspace.save(created.version, forged)
    assert error.value.current_version == created.version
    assert workspace.load().version == created.version

    with database.session_scope() as session:
        stage = session.scalar(
            select(DealPipelineStage).where(
                DealPipelineStage.workspace_id == "default",
                DealPipelineStage.name == "Analisar falha",
            )
        )
        stage.archived_at = datetime.now(timezone.utc)
        archived_stage_id = stage.id
    archived = workspace.load().state
    archived.deals[0]["stageId"] = str(archived_stage_id)
    with pytest.raises(WorkspaceStageConflict):
        workspace.save(created.version, archived)
    assert workspace.load().version == created.version


def test_deleted_and_restored_deal_keeps_canonical_stage_and_history(service) -> None:
    workspace, _database = service
    workspace.bootstrap(state())
    loaded = workspace.load()
    canonical = deepcopy(loaded.state.deals[0])
    loaded.state.deals = []

    deleted = workspace.save(loaded.version, loaded.state)
    deleted_record = workspace.list_deleted("deals")[0]
    assert deleted_record["pipelineId"] == canonical["pipelineId"]
    assert deleted_record["stageId"] == canonical["stageId"]
    assert deleted_record["stage"] == canonical["stage"]

    restored = workspace.restore(deleted.version, "deals", canonical["id"])
    assert restored.state.deals[0]["pipelineId"] == canonical["pipelineId"]
    assert restored.state.deals[0]["stageId"] == canonical["stageId"]
    assert restored.state.deals[0]["stageHistory"] == canonical["stageHistory"]


def test_pipeline_transfer_invalidates_stale_workspace_snapshot(service) -> None:
    workspace, database = service
    workspace.bootstrap(state())
    stale = workspace.load()
    pipeline_service = DealPipelineService()
    with database.session_scope() as session:
        pipeline = pipeline_service.load(session, TEST_PRINCIPAL)
        source = next(stage for stage in pipeline.stages if stage.name == "Em Contato")
        target = next(stage for stage in pipeline.stages if stage.semantic_type == "won")
        stages = []
        position = 0
        for stage in pipeline.stages:
            archived = stage.id == source.id
            stages.append(
                {
                    "id": stage.id,
                    "name": stage.name,
                    "semanticType": stage.semantic_type,
                    "color": stage.color,
                    "position": stage.position if archived else position,
                    "archived": archived,
                }
            )
            if not archived:
                position += 1
        request = DealPipelineUpdateRequest.model_validate(
            {
                "pipelineVersion": pipeline.pipeline_version,
                "workspaceVersion": pipeline.workspace_version,
                "defaultStageId": next(
                    stage.id
                    for stage in pipeline.stages
                    if stage.semantic_type == "open" and stage.id != source.id
                ),
                "stages": stages,
                "transfers": {str(source.id): str(target.id)},
            }
        )
        pipeline_service.update(session, TEST_PRINCIPAL, request)

    with pytest.raises(WorkspaceConflict) as error:
        workspace.save(stale.version, stale.state)
    assert error.value.current_version == stale.version + 1
    current = workspace.load()
    assert current.version == stale.version + 1
    assert current.state.deals[0]["stageId"] == str(target.id)
    assert current.state.deals[0]["stage"] == target.name
    assert len(current.state.deals[0]["stageHistory"]) == 1
