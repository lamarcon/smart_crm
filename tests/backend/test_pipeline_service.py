from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.models import (
    CrmActivityEvent,
    Deal,
    DealPipeline,
    DealPipelineAuditEvent,
    DealPipelineStage,
    DealStageHistory,
    Notification,
    Workspace,
)
from app.policies import PrincipalScope
from app.repositories.pipeline import DealPipelineAggregate
from app.repositories.pipeline import DealPipelineRepository
from app.schemas import DealPipelineStageUpdate, DealPipelineUpdateRequest
from app.services.pipeline import (
    DealPipelineAuthorizationError,
    DealPipelineService,
    DealPipelineValidationError,
    DealPipelineVersionConflict,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "f6b1d3a8c2e4"
WORKSPACE_ID = "default"
ACTOR_ID = "pipeline-service-admin"
PRINCIPAL = PrincipalScope(
    tenant_id=uuid.uuid4(),
    workspace_id=WORKSPACE_ID,
    user_id=ACTOR_ID,
    role="Administrador",
    team_id=None,
    auth_version=1,
)


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def pipeline_database_url() -> str:
    database_name = f"pipeline_service_{uuid.uuid4().hex}"
    admin_url = make_url(TEST_DATABASE_URL).set(database="postgres")
    tenant_url = make_url(TEST_DATABASE_URL).set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    tenant_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        tenant_engine = create_engine(tenant_url, poolclass=NullPool)
        with tenant_engine.begin() as connection:
            command.upgrade(_tenant_config(connection), TENANT_HEAD)
            connection.execute(
                text(
                    "INSERT INTO crm_users "
                    "(id, workspace_id, name, email, job_title, role, status, payload) "
                    "VALUES (:id, 'default', 'Pipeline Admin', 'service@example.test', "
                    "'Administrador', 'Administrador', 'Ativo', '{}'::jsonb)"
                ),
                {"id": ACTOR_ID},
            )
        yield tenant_url.render_as_string(hide_password=False)
    finally:
        if tenant_engine is not None:
            tenant_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


@contextmanager
def _session(database_url: str):
    engine = create_engine(database_url, poolclass=NullPool)
    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            session.execute(
                text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
                {"workspace_id": WORKSPACE_ID},
            )
            yield session
    engine.dispose()


def _stage(
    position: int,
    semantic_type: str,
    *,
    name: str | None = None,
) -> DealPipelineStage:
    return DealPipelineStage(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        pipeline_id=PIPELINE_ID,
        name=name or f"Stage {position}",
        semantic_type=semantic_type,
        color="#123ABC",
        position=position,
        system_key="initial" if position == 0 else None,
        archived_at=None,
    )


PIPELINE_ID = uuid.uuid4()
UNIT_STAGES = (_stage(0, "open"), _stage(1, "won"), _stage(2, "lost"))
UNIT_AGGREGATE = DealPipelineAggregate(
    pipeline=DealPipeline(
        id=PIPELINE_ID,
        workspace_id=WORKSPACE_ID,
        name="Negócios",
        version=1,
        is_default=True,
        default_stage_id=UNIT_STAGES[0].id,
    ),
    stages=UNIT_STAGES,
)


def _unit_request(
    stages: list[DealPipelineStageUpdate] | None = None,
    *,
    default_stage_id=None,  # noqa: ANN001
    transfers=None,  # noqa: ANN001
) -> DealPipelineUpdateRequest:
    values = stages or [
        DealPipelineStageUpdate(
            id=stage.id,
            name=stage.name,
            semanticType=stage.semantic_type,
            color=stage.color,
            position=stage.position,
        )
        for stage in UNIT_STAGES
    ]
    return DealPipelineUpdateRequest.model_construct(
        pipeline_version=1,
        workspace_version=0,
        default_stage_id=default_stage_id or UNIT_STAGES[0].id,
        stages=values,
        transfers=transfers or {},
    )


def _replace_stage(index: int, **changes) -> list[DealPipelineStageUpdate]:  # noqa: ANN003
    stages = list(_unit_request().stages)
    data = stages[index].model_dump()
    data.update(changes)
    stages[index] = DealPipelineStageUpdate.model_construct(**data)
    return stages


def _assert_validation(request: DealPipelineUpdateRequest, code: str) -> None:
    with pytest.raises(DealPipelineValidationError) as captured:
        DealPipelineService._validate_configuration(UNIT_AGGREGATE, request)
    assert captured.value.code == code
    assert captured.value.field


def test_configuration_validation_covers_every_prewrite_invariant() -> None:
    duplicate_ids = _replace_stage(1, id=UNIT_STAGES[0].id)
    _assert_validation(_unit_request(duplicate_ids), "pipeline_stage_duplicate_id")

    unknown_id = _replace_stage(1, id=uuid.uuid4())
    _assert_validation(_unit_request(unknown_id), "pipeline_stage_not_found")

    _assert_validation(
        _unit_request(list(_unit_request().stages[:-1])),
        "pipeline_stage_identity_changed",
    )
    archived_new = list(_unit_request().stages)
    archived_new.append(
        DealPipelineStageUpdate(
            name="Archived new",
            semanticType="open",
            color="#123456",
            position=3,
            archived=True,
        )
    )
    _assert_validation(_unit_request(archived_new), "pipeline_new_stage_archived")
    _assert_validation(
        _unit_request(_replace_stage(0, name="   ")),
        "pipeline_stage_name_invalid",
    )
    _assert_validation(
        _unit_request(_replace_stage(0, name="x" * 81)),
        "pipeline_stage_name_invalid",
    )
    _assert_validation(
        _unit_request(_replace_stage(1, name=UNIT_STAGES[0].name.swapcase())),
        "pipeline_stage_name_duplicate",
    )
    _assert_validation(
        _unit_request(_replace_stage(0, color="red")),
        "pipeline_stage_color_invalid",
    )
    _assert_validation(
        _unit_request(_replace_stage(1, position=0)),
        "pipeline_stage_position_duplicate",
    )
    _assert_validation(
        _unit_request(_replace_stage(2, position=4)),
        "pipeline_stage_positions_invalid",
    )
    _assert_validation(
        _unit_request(_replace_stage(0, semantic_type="won")),
        "pipeline_stage_semantic_immutable",
    )
    _assert_validation(
        _unit_request(default_stage_id=uuid.uuid4()),
        "pipeline_default_stage_invalid",
    )
    _assert_validation(
        _unit_request(default_stage_id=UNIT_STAGES[1].id),
        "pipeline_default_stage_not_open",
    )

    open_only = (_stage(0, "open"), _stage(1, "open"), _stage(2, "open"))
    aggregate = DealPipelineAggregate(
        pipeline=UNIT_AGGREGATE.pipeline,
        stages=open_only,
    )
    request = DealPipelineUpdateRequest.model_construct(
        pipeline_version=1,
        workspace_version=0,
        default_stage_id=open_only[0].id,
        stages=[
            DealPipelineStageUpdate(
                id=stage.id,
                name=stage.name,
                semanticType="open",
                color=stage.color,
                position=stage.position,
            )
            for stage in open_only
        ],
        transfers={},
    )
    with pytest.raises(DealPipelineValidationError) as captured:
        DealPipelineService._validate_configuration(aggregate, request)
    assert captured.value.code == "pipeline_semantic_minimum"

    too_many = list(_unit_request().stages)
    too_many.extend(
        DealPipelineStageUpdate(
            name=f"New {index}",
            semanticType="open",
            color="#123456",
            position=index,
        )
        for index in range(3, 51)
    )
    _assert_validation(_unit_request(too_many), "pipeline_stage_limit")


def _update_request(response, *, add_stage: bool = False) -> DealPipelineUpdateRequest:  # noqa: ANN001
    stages = [
        {
            "id": stage.id,
            "name": stage.name,
            "semanticType": stage.semantic_type,
            "color": stage.color,
            "position": stage.position,
        }
        for stage in response.stages
    ]
    if add_stage:
        stages.append(
            {
                "id": None,
                "name": "Descoberta",
                "semanticType": "open",
                "color": "#abcdef",
                "position": len(stages),
            }
        )
    return DealPipelineUpdateRequest.model_validate(
        {
            "pipelineVersion": response.pipeline_version,
            "workspaceVersion": response.workspace_version,
            "defaultStageId": response.default_stage_id,
            "stages": stages,
            "transfers": {},
        }
    )


def _archive_request(response, source_id, target_id=None):  # noqa: ANN001, ANN202
    request = _update_request(response)
    next_position = 0
    for stage in request.stages:
        if stage.id == source_id:
            stage.archived = True
        else:
            stage.position = next_position
            next_position += 1
    request.transfers = {source_id: target_id} if target_id is not None else {}
    return request


def _seed_deal(
    session: Session,
    stage,
    *,
    deal_id: str = "service-deal",
    deleted: bool = False,
    won_at: datetime | None = None,
    with_history: bool = False,
) -> None:
    record = {
        "id": deal_id,
        "title": deal_id,
        "pipelineId": str(stage.pipeline_id),
        "stageId": str(stage.id),
        "stage": stage.name,
        "stageHistory": [],
    }
    if won_at is not None:
        record["wonAt"] = won_at.isoformat().replace("+00:00", "Z")
    session.execute(
        text(
            "INSERT INTO deals "
            "(id, workspace_id, responsible_id, title, company_text, contact_text, amount, "
            "stage, pipeline_id, stage_id, won_at, payload, deleted_at) "
            "VALUES (:id, 'default', :actor, :id, '', '', 10, :stage, :pipeline_id, "
            ":stage_id, :won_at, CAST(:payload AS jsonb), :deleted_at)"
        ),
        {
            "id": deal_id,
            "actor": ACTOR_ID,
            "stage": stage.name,
            "pipeline_id": stage.pipeline_id,
            "stage_id": stage.id,
            "won_at": won_at,
            "payload": json.dumps({"position": 0, "record": record}),
            "deleted_at": datetime.now(timezone.utc) if deleted else None,
        },
    )
    if with_history:
        session.add(
            DealStageHistory(
                workspace_id=WORKSPACE_ID,
                deal_id=deal_id,
                position=0,
                from_stage=None,
                to_stage=stage.name,
                from_stage_id=None,
                to_stage_id=stage.id,
                changed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                changed_by_id=ACTOR_ID,
            )
        )
    session.flush()


def test_update_creates_renames_recolors_reorders_and_audits_once(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 17, 45, tzinfo=timezone.utc)
    service = DealPipelineService(clock=lambda: changed_at)
    with _session(pipeline_database_url) as session:
        before = service.load(session, PRINCIPAL)
        request = _update_request(before, add_stage=True)
        request.stages[0].name = "Primeiro contato"
        request.stages[0].color = "#AABBCC"
        request.stages[0].position = 1
        request.stages[1].position = 0
        request.default_stage_id = request.stages[1].id

        result = service.update(session, PRINCIPAL, request)
        audits = service.history(session, PRINCIPAL).items

        assert result.pipeline_version == before.pipeline_version + 1
        assert result.workspace_version == before.workspace_version
        assert len(result.stages) == len(before.stages) + 1
        assert [stage.position for stage in result.stages] == list(range(10))
        assert result.stages[1].name == "Primeiro contato"
        assert result.stages[1].color == "#AABBCC"
        assert result.stages[1].id == before.stages[0].id
        assert result.stages[1].semantic_type == before.stages[0].semantic_type
        assert result.stages[1].system_key == "initial"
        assert result.default_stage_id == before.stages[1].id
        assert sum(stage.initial for stage in result.stages) == 1
        assert result.stages[-1].color == "#ABCDEF"
        assert result.stages[-1].id is not None
        assert result.stages[-1].semantic_type == "open"
        assert result.stages[-1].active is True
        assert result.stages[-1].position == 9
        persisted_new_stage = session.get(DealPipelineStage, result.stages[-1].id)
        assert persisted_new_stage.semantic_type == "open"
        assert persisted_new_stage.archived_at is None
        assert len(audits) == 1
        assert audits[0].pipeline_id == before.id
        assert audits[0].pipeline_version == result.pipeline_version
        assert audits[0].actor_user_id == ACTOR_ID
        assert audits[0].created_at.utcoffset() == timedelta(0)
        assert audits[0].before_state["pipelineVersion"] == before.pipeline_version
        assert audits[0].after_state["pipelineVersion"] == result.pipeline_version
        assert {action["type"] for action in audits[0].actions} >= {
            "stage.created",
            "stage.renamed",
            "stage.recolored",
            "stage.reordered",
            "pipeline.initial_stage_changed",
        }
        assert audits[0].transfer_summary == []


def test_authorization_and_stale_version_cause_zero_writes(
    pipeline_database_url: str,
) -> None:
    service = DealPipelineService()
    non_admin = PrincipalScope(
        tenant_id=PRINCIPAL.tenant_id,
        workspace_id=WORKSPACE_ID,
        user_id="seller",
        role="Vendedor",
        team_id=None,
        auth_version=1,
    )
    with _session(pipeline_database_url) as session:
        before = service.load(session, PRINCIPAL)
        request = _update_request(before)
        with pytest.raises(DealPipelineAuthorizationError):
            service.update(session, non_admin, request)
        request.pipeline_version -= 1
        with pytest.raises(DealPipelineVersionConflict) as captured:
            service.update(session, PRINCIPAL, request)

        pipeline = session.scalar(select(DealPipeline))
        assert captured.value.code == "pipeline_version_conflict"
        assert captured.value.current_version == before.pipeline_version
        assert pipeline.version == before.pipeline_version
        assert session.scalar(select(func.count()).select_from(DealPipelineAuditEvent)) == 0


def test_concurrent_save_and_retry_have_one_winner_and_one_audit(
    pipeline_database_url: str,
) -> None:
    service = DealPipelineService()
    with _session(pipeline_database_url) as session:
        before = service.load(session, PRINCIPAL)
        request = _update_request(before, add_stage=True)

    def save_once() -> str:
        try:
            with _session(pipeline_database_url) as session:
                service.update(session, PRINCIPAL, request)
            return "saved"
        except DealPipelineVersionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: save_once(), range(2)))

    assert sorted(outcomes) == ["conflict", "saved"]
    with _session(pipeline_database_url) as session:
        current = service.load(session, PRINCIPAL)
        assert current.pipeline_version == before.pipeline_version + 1
        assert len(current.stages) == len(before.stages) + 1
        assert len(service.history(session, PRINCIPAL).items) == 1
        with pytest.raises(DealPipelineVersionConflict):
            service.update(session, PRINCIPAL, request)
        assert service.load(session, PRINCIPAL).pipeline_version == current.pipeline_version
        assert len(service.history(session, PRINCIPAL).items) == 1


def test_empty_stage_archives_without_destination_and_preserves_system_key(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
    service = DealPipelineService(clock=lambda: changed_at)
    with _session(pipeline_database_url) as session:
        before = service.load(session, PRINCIPAL)
        source = next(stage for stage in before.stages if stage.system_key == "billing")
        result = service.update(
            session,
            PRINCIPAL,
            _archive_request(before, source.id),
        )
        complete = service.load(session, PRINCIPAL, include_archived=True)
        archived = next(stage for stage in complete.stages if stage.id == source.id)
        event = service.history(session, PRINCIPAL).items[0]
        archive_action = next(
            action for action in event.actions if action["type"] == "stage.archived"
        )

        assert len(result.stages) == len(before.stages) - 1
        assert source.id not in {stage.id for stage in result.stages}
        assert [stage.position for stage in result.stages] == list(range(8))
        assert result.workspace_version == before.workspace_version
        assert result.transfer_counts[source.id] == 0
        assert archived.active is False
        assert archived.archived_at == changed_at
        assert archived.system_key == "billing"
        assert archive_action["stageId"] == str(source.id)
        assert archive_action["transferCount"] == 0
        assert event.transfer_summary == []


def test_occupied_stage_transfers_active_and_deleted_deals_and_increments_workspace(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 18, 30, tzinfo=timezone.utc)
    service = DealPipelineService(clock=lambda: changed_at)
    with _session(pipeline_database_url) as session:
        before = service.load(session, PRINCIPAL)
        source = next(stage for stage in before.stages if stage.name == "Orçamentos enviados")
        target = next(stage for stage in before.stages if stage.semantic_type == "won")
        source_model = session.get(DealPipelineStage, source.id)
        _seed_deal(session, source_model, deal_id="active")
        _seed_deal(session, source_model, deal_id="deleted", deleted=True)

        result = service.update(
            session,
            PRINCIPAL,
            _archive_request(before, source.id, target.id),
        )
        deals = session.scalars(select(Deal).order_by(Deal.id)).all()
        histories = session.scalars(select(DealStageHistory).order_by(DealStageHistory.deal_id)).all()
        archived_source = session.get(DealPipelineStage, source.id)
        event = service.history(session, PRINCIPAL).items[0]
        activity_events = session.scalars(
            select(CrmActivityEvent).order_by(CrmActivityEvent.deal_id)
        ).all()

        assert result.transfer_counts == {source.id: 2}
        assert result.workspace_version == before.workspace_version + 1
        assert all(deal.stage_id == target.id for deal in deals)
        assert all(deal.stage == target.name for deal in deals)
        assert all(deal.won_at == changed_at for deal in deals)
        assert deals[0].deleted_at is None and deals[1].deleted_at is not None
        assert all(deal.payload["record"]["stageId"] == str(target.id) for deal in deals)
        assert all(deal.payload["record"]["wonAt"] == "2026-09-29T18:30:00Z" for deal in deals)
        assert len(histories) == 2
        assert {history.from_stage_id for history in histories} == {source.id}
        assert {history.to_stage_id for history in histories} == {target.id}
        assert {history.from_stage for history in histories} == {source.name}
        assert {history.to_stage for history in histories} == {target.name}
        assert {history.changed_by_id for history in histories} == {ACTOR_ID}
        assert all(history.changed_at == changed_at for history in histories)
        assert all(stage.id != source.id for stage in result.stages)
        assert archived_source.archived_at == changed_at
        assert archived_source.system_key == source.system_key
        assert event.transfer_summary == [
            {
                "sourceStageId": str(source.id),
                "targetStageId": str(target.id),
                "count": 2,
            }
        ]
        assert "record" not in event.transfer_summary[0]
        assert [activity.deal_id for activity in activity_events] == ["active", "deleted"]
        assert {activity.category for activity in activity_events} == {"movement"}
        assert {activity.actor_user_id for activity in activity_events} == {ACTOR_ID}
        assert {activity.actor_name for activity in activity_events} == {"Pipeline Admin"}
        assert {
            (
                activity.details["fromStageId"],
                activity.details["fromStageName"],
                activity.details["toStageId"],
                activity.details["toStageName"],
                activity.details["source"],
            )
            for activity in activity_events
        } == {
            (
                str(source.id),
                source.name,
                str(target.id),
                target.name,
                "pipeline_transfer",
            )
        }

        retry_request = _archive_request(before, source.id, target.id)
        with pytest.raises(DealPipelineVersionConflict):
            service.update(session, PRINCIPAL, retry_request)
        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 2


def test_transfer_to_billing_runs_shared_automation_once_in_same_transaction(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 18, 40, tzinfo=timezone.utc)
    service = DealPipelineService(clock=lambda: changed_at)
    with _session(pipeline_database_url) as session:
        session.execute(
            text(
                "INSERT INTO teams (id, workspace_id, name) "
                "VALUES ('team-billing', 'default', 'Faturamento')"
            )
        )
        session.execute(
            text(
                "INSERT INTO crm_users "
                "(id, workspace_id, team_id, name, email, job_title, role, status, payload) "
                "VALUES ('u-billing', 'default', 'team-billing', 'Equipe de Faturamento', "
                "'billing@example.test', 'Faturamento', 'Faturamento', 'Ativo', '{}'::jsonb)"
            )
        )
        before = service.load(session, PRINCIPAL)
        source = next(stage for stage in before.stages if stage.name == "Orçamentos enviados")
        target = next(stage for stage in before.stages if stage.system_key == "billing")
        _seed_deal(session, session.get(DealPipelineStage, source.id), deal_id="billing-active")

        result = service.update(
            session,
            PRINCIPAL,
            _archive_request(before, source.id, target.id),
        )
        deal = session.get(Deal, "billing-active")
        activities = session.scalars(
            select(CrmActivityEvent).order_by(CrmActivityEvent.id)
        ).all()
        notifications = session.scalars(
            select(Notification).order_by(Notification.user_id)
        ).all()

        assert result.workspace_version == before.workspace_version + 1
        assert deal.stage_id == target.id
        assert deal.responsible_id == "u-billing"
        assert deal.team_id == "team-billing"
        assert deal.payload["record"]["responsibleId"] == "u-billing"
        assert [activity.category for activity in activities] == [
            "movement",
            "automation",
        ]
        assert activities[1].details["automationKey"] == "billing"
        assert activities[1].details["result"] == "success"
        assert {notification.user_id for notification in notifications} == {
            ACTOR_ID,
            "u-billing",
        }
        assert session.scalar(select(func.count()).select_from(DealPipelineAuditEvent)) == 1


class _FailingAutomationExecutor:
    def execute_for_transition(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("injected automation failure")


def test_transfer_automation_failure_rolls_back_every_side_effect(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 18, 42, tzinfo=timezone.utc)
    with _session(pipeline_database_url) as session:
        baseline = DealPipelineService().load(session, PRINCIPAL)
        source = next(stage for stage in baseline.stages if stage.name == "Orçamentos enviados")
        target = next(stage for stage in baseline.stages if stage.semantic_type == "won")
        _seed_deal(session, session.get(DealPipelineStage, source.id), deal_id="rollback")

    failing = DealPipelineService(
        automation_executor=_FailingAutomationExecutor(),
        clock=lambda: changed_at,
    )
    with pytest.raises(RuntimeError, match="injected automation failure"):
        with _session(pipeline_database_url) as session:
            failing.update(
                session,
                PRINCIPAL,
                _archive_request(baseline, source.id, target.id),
            )

    with _session(pipeline_database_url) as session:
        pipeline = session.scalar(select(DealPipeline))
        source_after = session.get(DealPipelineStage, source.id)
        deal = session.get(Deal, "rollback")
        workspace = session.get(Workspace, WORKSPACE_ID)

        assert pipeline.version == baseline.pipeline_version
        assert workspace.version == baseline.workspace_version
        assert source_after.archived_at is None
        assert deal.stage_id == source.id
        assert deal.stage == source.name
        assert deal.payload["record"]["stageHistory"] == []
        assert session.scalar(select(func.count()).select_from(DealStageHistory)) == 0
        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 0
        assert session.scalar(select(func.count()).select_from(Notification)) == 0
        assert session.scalar(select(func.count()).select_from(DealPipelineAuditEvent)) == 0


def test_occupied_billing_stage_transfer_keeps_key_only_on_archived_source(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 18, 45, tzinfo=timezone.utc)
    service = DealPipelineService(clock=lambda: changed_at)
    with _session(pipeline_database_url) as session:
        before = service.load(session, PRINCIPAL)
        source = next(stage for stage in before.stages if stage.system_key == "billing")
        target = next(
            stage
            for stage in before.stages
            if stage.semantic_type == "open" and stage.id != source.id
        )
        _seed_deal(session, session.get(DealPipelineStage, source.id), deal_id="billing")

        result = service.update(
            session,
            PRINCIPAL,
            _archive_request(before, source.id, target.id),
        )
        complete = service.load(session, PRINCIPAL, include_archived=True)
        archived = next(stage for stage in complete.stages if stage.id == source.id)
        active_target = next(stage for stage in result.stages if stage.id == target.id)
        deal = session.get(Deal, "billing")

        assert result.transfer_counts == {source.id: 1}
        assert deal.stage_id == target.id
        assert archived.active is False
        assert archived.archived_at == changed_at
        assert archived.system_key == "billing"
        assert active_target.system_key == target.system_key
        assert active_target.system_key != "billing"
        assert all(stage.system_key != "billing" for stage in result.stages)


@pytest.mark.parametrize(
    ("target_name", "renamed_target_name"),
    [
        ("Em Contato", "Retomada"),
        ("Analisar falha", "Encerrado sem ganho"),
    ],
)
def test_transfer_to_non_won_clears_won_state_and_rename_syncs_only_current_display(
    pipeline_database_url: str,
    target_name: str,
    renamed_target_name: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 19, 0, tzinfo=timezone.utc)
    service = DealPipelineService(clock=lambda: changed_at)
    won_at = datetime(2026, 9, 20, tzinfo=timezone.utc)
    with _session(pipeline_database_url) as session:
        before = service.load(session, PRINCIPAL)
        source = next(stage for stage in before.stages if stage.name == "Negociação Revisão")
        target = next(stage for stage in before.stages if stage.name == target_name)
        source_model = session.get(DealPipelineStage, source.id)
        _seed_deal(session, source_model, won_at=won_at, with_history=True)
        request = _archive_request(before, source.id, target.id)
        target_update = next(stage for stage in request.stages if stage.id == target.id)
        target_update.name = renamed_target_name

        result = service.update(session, PRINCIPAL, request)
        deal = session.get(Deal, "service-deal")
        histories = session.scalars(
            select(DealStageHistory).order_by(DealStageHistory.position)
        ).all()
        renamed_target = next(stage for stage in result.stages if stage.id == target.id)

        assert renamed_target.name == renamed_target_name
        assert deal.stage_id == target.id
        assert deal.stage == renamed_target_name
        assert deal.payload["record"]["stage"] == renamed_target_name
        assert deal.won_at is None
        assert "wonAt" not in deal.payload["record"]
        assert len(histories) == 2
        assert histories[0].to_stage == source.name
        assert histories[1].from_stage == source.name
        assert histories[1].to_stage == target.name


def test_invalid_archive_targets_and_last_semantic_stage_write_nothing(
    pipeline_database_url: str,
) -> None:
    service = DealPipelineService()
    with _session(pipeline_database_url) as session:
        before = service.load(session, PRINCIPAL)
        source = next(stage for stage in before.stages if stage.name == "Orçamento Proposta Preço")
        source_model = session.get(DealPipelineStage, source.id)
        _seed_deal(session, source_model)

        missing = _archive_request(before, source.id)
        with pytest.raises(DealPipelineValidationError) as captured:
            service.update(session, PRINCIPAL, missing)
        assert captured.value.code == "pipeline_archive_target_required"

        foreign = _archive_request(before, source.id, uuid.uuid4())
        with pytest.raises(DealPipelineValidationError) as captured:
            service.update(session, PRINCIPAL, foreign)
        assert captured.value.code == "pipeline_archive_target_invalid"

        unexpected_transfer = _update_request(before)
        unexpected_transfer.transfers = {
            source.id: next(stage.id for stage in before.stages if stage.id != source.id)
        }
        with pytest.raises(DealPipelineValidationError) as captured:
            service.update(session, PRINCIPAL, unexpected_transfer)
        assert captured.value.code == "pipeline_transfer_source_invalid"

        empty_source = next(stage for stage in before.stages if stage.name == "Faturando")
        valid_target = next(
            stage for stage in before.stages if stage.id not in {source.id, empty_source.id}
        )
        unnecessary = _archive_request(before, empty_source.id, valid_target.id)
        with pytest.raises(DealPipelineValidationError) as captured:
            service.update(session, PRINCIPAL, unnecessary)
        assert captured.value.code == "pipeline_archive_target_unnecessary"

        modified_archive = _archive_request(before, empty_source.id)
        next(
            stage for stage in modified_archive.stages if stage.id == empty_source.id
        ).name = "Changed while archiving"
        with pytest.raises(DealPipelineValidationError) as captured:
            service.update(session, PRINCIPAL, modified_archive)
        assert captured.value.code == "pipeline_archived_stage_modified"

        same_stage = _archive_request(before, source.id, source.id)
        with pytest.raises(DealPipelineValidationError) as captured:
            service.update(session, PRINCIPAL, same_stage)
        assert captured.value.code == "pipeline_archive_target_invalid"

        archived_target = _archive_request(before, source.id)
        other_open = next(
            stage
            for stage in archived_target.stages
            if stage.id != source.id
            and stage.id != archived_target.default_stage_id
            and stage.semantic_type == "open"
        )
        other_open.archived = True
        for position, stage in enumerate(
            item for item in archived_target.stages if not item.archived
        ):
            stage.position = position
        archived_target.transfers = {source.id: other_open.id}
        with pytest.raises(DealPipelineValidationError) as captured:
            service.update(session, PRINCIPAL, archived_target)
        assert captured.value.code == "pipeline_archive_target_invalid"

        only_won = next(stage for stage in before.stages if stage.semantic_type == "won")
        last_semantic = _archive_request(before, only_won.id)
        with pytest.raises(DealPipelineValidationError) as captured:
            service.update(session, PRINCIPAL, last_semantic)
        assert captured.value.code == "pipeline_semantic_minimum"

        pipeline = session.scalar(select(DealPipeline))
        deal = session.get(Deal, "service-deal")
        assert pipeline.version == before.pipeline_version
        assert deal.stage_id == source.id
        assert session.scalar(select(func.count()).select_from(DealStageHistory)) == 0
        assert session.scalar(select(func.count()).select_from(DealPipelineAuditEvent)) == 0


class _FailingAuditRepository(DealPipelineRepository):
    def append_audit(self, **kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("injected audit failure")


def test_stale_workspace_and_audit_failure_roll_back_transfer_and_archive(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)
    with _session(pipeline_database_url) as session:
        baseline = DealPipelineService().load(session, PRINCIPAL)
        source = next(stage for stage in baseline.stages if stage.name == "Pedido aprovado Consultar")
        target = next(stage for stage in baseline.stages if stage.semantic_type == "won")
        _seed_deal(session, session.get(DealPipelineStage, source.id))

    stale = _archive_request(baseline, source.id, target.id)
    stale.workspace_version += 1
    with _session(pipeline_database_url) as session:
        with pytest.raises(DealPipelineVersionConflict) as captured:
            DealPipelineService().update(session, PRINCIPAL, stale)
        assert captured.value.current_workspace_version == baseline.workspace_version

    request = _archive_request(baseline, source.id, target.id)
    failing = DealPipelineService(
        repository_factory=_FailingAuditRepository,
        clock=lambda: changed_at,
    )
    with pytest.raises(RuntimeError, match="injected audit failure"):
        with _session(pipeline_database_url) as session:
            failing.update(session, PRINCIPAL, request)

    with _session(pipeline_database_url) as session:
        pipeline = session.scalar(select(DealPipeline))
        source_after = session.get(DealPipelineStage, source.id)
        deal = session.get(Deal, "service-deal")
        workspace = session.get(Workspace, WORKSPACE_ID)

        assert pipeline.version == baseline.pipeline_version
        assert workspace.version == baseline.workspace_version
        assert source_after.archived_at is None
        assert deal.stage_id == source.id
        assert deal.stage == source.name
        assert deal.payload["record"]["stage"] == source.name
        assert deal.payload["record"]["stageHistory"] == []
        assert session.scalar(select(func.count()).select_from(DealStageHistory)) == 0
        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 0
        assert session.scalar(select(func.count()).select_from(Notification)) == 0
        assert session.scalar(select(func.count()).select_from(DealPipelineAuditEvent)) == 0
