from __future__ import annotations

import inspect
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.models import Deal, DealPipelineAuditEvent, DealPipelineStage, DealStageHistory
from app.repositories.pipeline import (
    DealPipelineRepository,
    PipelineScopeError,
    PipelineStageNotFoundError,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "c7f3a9d8e2b1"
WORKSPACE_ID = "default"
ACTOR_ID = "pipeline-admin"


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def pipeline_database_url() -> str:
    database_name = f"pipeline_repository_{uuid.uuid4().hex}"
    admin_url = make_url(TEST_DATABASE_URL).set(database="postgres")
    tenant_url = make_url(TEST_DATABASE_URL).set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    tenant_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        tenant_engine = create_engine(tenant_url, poolclass=NullPool)
        with tenant_engine.connect() as connection:
            command.upgrade(_tenant_config(connection), TENANT_HEAD)
            connection.commit()
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
def repository_scope(database_url: str):
    engine = create_engine(database_url, poolclass=NullPool)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        session.execute(
            text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
            {"workspace_id": WORKSPACE_ID},
        )
        session.execute(
            text(
                "INSERT INTO crm_users "
                "(id, workspace_id, name, email, job_title, role, status, payload) "
                "VALUES (:id, 'default', 'Pipeline Admin', 'pipeline@example.test', "
                "'Administrador', 'Administrador', 'Ativo', '{}'::jsonb)"
            ),
            {"id": ACTOR_ID},
        )
        yield DealPipelineRepository(session, WORKSPACE_ID), session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _stages(repository: DealPipelineRepository) -> dict[str, DealPipelineStage]:
    return {stage.name: stage for stage in repository.load_default(include_archived=True).stages}


def _seed_deal(
    session: Session,
    *,
    deal_id: str,
    stage: DealPipelineStage,
    deleted: bool = False,
) -> None:
    payload = {
        "position": 0,
        "record": {
            "id": deal_id,
            "title": deal_id,
            "stage": stage.name,
            "stageHistory": [],
        },
    }
    session.execute(
        text(
            "INSERT INTO deals "
            "(id, workspace_id, responsible_id, title, company_text, contact_text, amount, "
            "stage, pipeline_id, stage_id, payload, deleted_at) "
            "VALUES (:id, 'default', :actor, :id, '', '', 10, :stage, :pipeline_id, "
            ":stage_id, CAST(:payload AS jsonb), :deleted_at)"
        ),
        {
            "id": deal_id,
            "actor": ACTOR_ID,
            "stage": stage.name,
            "pipeline_id": stage.pipeline_id,
            "stage_id": stage.id,
            "payload": json.dumps(payload),
            "deleted_at": datetime.now(timezone.utc) if deleted else None,
        },
    )


def test_repository_rejects_missing_and_mismatched_workspace_context(
    pipeline_database_url: str,
) -> None:
    engine = create_engine(pipeline_database_url, poolclass=NullPool)
    session = Session(bind=engine)
    try:
        session.execute(text("RESET smartcrm.workspace_id"))
        with pytest.raises(PipelineScopeError, match="workspace context unavailable"):
            DealPipelineRepository(session, WORKSPACE_ID)
        session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
        with pytest.raises(PipelineScopeError, match="workspace context mismatch"):
            DealPipelineRepository(session, "foreign-workspace")
    finally:
        session.close()
        engine.dispose()


def test_load_default_is_canonical_and_archived_filter_is_explicit(
    pipeline_database_url: str,
) -> None:
    with repository_scope(pipeline_database_url) as (repository, session):
        aggregate = repository.load_default(include_archived=True)
        archived = aggregate.stages[3]
        archived.archived_at = datetime.now(timezone.utc)
        session.flush()

        active = repository.load_default()
        complete = repository.load_default(include_archived=True)

        assert len(active.stages) == 8
        assert len(complete.stages) == 9
        assert archived.id not in {stage.id for stage in active.stages}
        assert [stage.position for stage in complete.stages] == list(range(9))
        assert active.pipeline.workspace_id == WORKSPACE_ID
        assert all(stage.workspace_id == WORKSPACE_ID for stage in complete.stages)


def test_stage_lookup_and_counts_fail_closed_for_foreign_ids_and_include_deleted(
    pipeline_database_url: str,
) -> None:
    with repository_scope(pipeline_database_url) as (repository, session):
        stages = _stages(repository)
        source = stages["Em Contato"]
        _seed_deal(session, deal_id="active", stage=source)
        _seed_deal(session, deal_id="deleted", stage=source, deleted=True)
        session.flush()

        counts = repository.count_deals_by_stage([source.id, stages["Ganho"].id])

        assert counts[source.id] == 2
        assert counts[stages["Ganho"].id] == 0
        with pytest.raises(PipelineStageNotFoundError):
            repository.load_stage(uuid.uuid4())
        with pytest.raises(PipelineStageNotFoundError):
            repository.load_stage(source.id, pipeline_id=uuid.uuid4())


def test_transfer_updates_active_and_deleted_deals_payload_and_history(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 15, 30, tzinfo=timezone.utc)
    with repository_scope(pipeline_database_url) as (repository, session):
        stages = _stages(repository)
        source = stages["Em Contato"]
        target = stages["Ganho"]
        _seed_deal(session, deal_id="active", stage=source)
        _seed_deal(session, deal_id="deleted", stage=source, deleted=True)
        session.flush()

        transferred = repository.transfer_deals(source.id, target, ACTOR_ID, changed_at)
        session.expire_all()
        deals = session.scalars(
            select(Deal).where(Deal.workspace_id == WORKSPACE_ID).order_by(Deal.id)
        ).all()
        histories = session.scalars(
            select(DealStageHistory)
            .where(DealStageHistory.workspace_id == WORKSPACE_ID)
            .order_by(DealStageHistory.deal_id)
        ).all()

        assert len(transferred) == 2
        assert [result.deal_id for result in transferred] == ["active", "deleted"]
        assert {result.from_stage_id for result in transferred} == {source.id}
        assert {result.to_stage_id for result in transferred} == {target.id}
        assert [result.deleted for result in transferred] == [False, True]
        assert {deal.stage_id for deal in deals} == {target.id}
        assert {deal.stage for deal in deals} == {"Ganho"}
        assert all(deal.won_at == changed_at for deal in deals)
        assert deals[0].deleted_at is None and deals[1].deleted_at is not None
        assert all(deal.payload["record"]["stageId"] == str(target.id) for deal in deals)
        assert all(deal.payload["record"]["stage"] == "Ganho" for deal in deals)
        assert all(deal.payload["record"]["wonAt"] == "2026-09-29T15:30:00Z" for deal in deals)
        assert all(len(deal.payload["record"]["stageHistory"]) == 1 for deal in deals)
        assert len(histories) == 2
        assert {history.from_stage_id for history in histories} == {source.id}
        assert {history.to_stage_id for history in histories} == {target.id}
        assert all(history.changed_by_id == ACTOR_ID for history in histories)


def test_transfer_to_non_won_clears_relational_and_packed_won_at(
    pipeline_database_url: str,
) -> None:
    first_at = datetime(2026, 9, 29, 15, 30, tzinfo=timezone.utc)
    second_at = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)
    with repository_scope(pipeline_database_url) as (repository, session):
        stages = _stages(repository)
        source = stages["Em Contato"]
        won = stages["Ganho"]
        lost = stages["Analisar falha"]
        _seed_deal(session, deal_id="deal", stage=source)
        session.flush()
        repository.transfer_deals(source.id, won, ACTOR_ID, first_at)
        repository.transfer_deals(won.id, lost, ACTOR_ID, second_at)
        session.expire_all()
        deal = session.get(Deal, "deal")

        assert deal.stage_id == lost.id
        assert deal.won_at is None
        assert "wonAt" not in deal.payload["record"]
        assert len(deal.payload["record"]["stageHistory"]) == 2
        assert session.scalar(select(func.count()).select_from(DealStageHistory)) == 2


def test_transfer_failure_rolls_back_all_deal_and_history_writes(
    pipeline_database_url: str,
) -> None:
    changed_at = datetime(2026, 9, 29, 15, 30, tzinfo=timezone.utc)
    with repository_scope(pipeline_database_url) as (repository, session):
        stages = _stages(repository)
        source = stages["Em Contato"]
        target = stages["Ganho"]
        _seed_deal(session, deal_id="deal", stage=source)
        session.flush()

        with pytest.raises(IntegrityError):
            with session.begin_nested():
                repository.transfer_deals(source.id, target, "missing-actor", changed_at)
        session.expire_all()
        deal = session.get(Deal, "deal")

        assert deal.stage_id == source.id
        assert deal.stage == source.name
        assert deal.payload["record"]["stage"] == source.name
        assert deal.payload["record"]["stageHistory"] == []
        assert session.scalar(select(func.count()).select_from(DealStageHistory)) == 0


def test_audit_is_append_only_paginated_and_rejects_commercial_payloads(
    pipeline_database_url: str,
) -> None:
    with repository_scope(pipeline_database_url) as (repository, session):
        pipeline = repository.load_default().pipeline
        first = repository.append_audit(
            pipeline_id=pipeline.id,
            actor_user_id=ACTOR_ID,
            pipeline_version=2,
            action="pipeline.updated",
            actions=[{"type": "stage.renamed", "stageId": str(pipeline.default_stage_id)}],
            before_state={"pipelineVersion": 1, "stages": []},
            after_state={"pipelineVersion": 2, "stages": []},
            transfer_summary=[],
        )
        second = repository.append_audit(
            pipeline_id=pipeline.id,
            actor_user_id=ACTOR_ID,
            pipeline_version=3,
            action="pipeline.updated",
            actions=[{"type": "stage.recolored"}],
            before_state={"pipelineVersion": 2, "stages": []},
            after_state={"pipelineVersion": 3, "stages": []},
            transfer_summary=[{"sourceStageId": "a", "targetStageId": "b", "count": 0}],
        )

        page = repository.list_audit(pipeline.id, limit=1)
        previous = repository.list_audit(pipeline.id, before_id=second.id, limit=50)

        assert [event.id for event in page] == [second.id]
        assert [event.id for event in previous] == [first.id]
        assert first.workspace_id == WORKSPACE_ID
        assert first.actions[0]["type"] == "stage.renamed"
        assert "deals" not in first.before_state
        with pytest.raises(ValueError, match="commercial payloads"):
            repository.append_audit(
                pipeline_id=pipeline.id,
                actor_user_id=ACTOR_ID,
                pipeline_version=4,
                action="pipeline.updated",
                actions=[],
                before_state={"deals": [{"id": "secret"}]},
                after_state={"stages": []},
                transfer_summary=[],
            )
        assert session.scalar(select(func.count()).select_from(DealPipelineAuditEvent)) == 2


def test_repository_exposes_no_audit_update_or_delete_operation() -> None:
    source = inspect.getsource(DealPipelineRepository)

    assert "update_audit" not in source
    assert "delete_audit" not in source
