from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.models import DealPipeline, DealPipelineAuditEvent, DealPipelineStage
from app.policies import PrincipalScope
from app.repositories.pipeline import DealPipelineAggregate
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
TENANT_HEAD = "c7f3a9d8e2b1"
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
    _assert_validation(
        _unit_request(_replace_stage(0, archived=True)),
        "pipeline_archive_not_supported",
    )
    _assert_validation(
        _unit_request(transfers={UNIT_STAGES[0].id: UNIT_STAGES[1].id}),
        "pipeline_transfer_not_supported",
    )
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


def test_update_creates_renames_recolors_reorders_and_audits_once(
    pipeline_database_url: str,
) -> None:
    service = DealPipelineService()
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
        assert len(audits) == 1
        assert audits[0].pipeline_version == result.pipeline_version
        assert audits[0].actor_user_id == ACTOR_ID
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
