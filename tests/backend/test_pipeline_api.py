from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.auth import AuthSettings, ResolvedPrincipal, unauthenticated_error
from app.main import create_app
from app.models import (
    Deal,
    DealPipeline,
    DealPipelineAuditEvent,
    DealPipelineStage,
    Workspace,
)
from app.policies import PrincipalScope
from app.repositories.pipeline import PipelineScopeError
from app.services.auth import SessionContext
from app.services.pipeline import DealPipelineService


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "c7f3a9d8e2b1"
ORIGIN = "https://sc2030.brbots.com"
WORKSPACE_ID = "default"
ACTOR_ID = "pipeline-api-admin"
TENANT_ID = uuid.uuid4()


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def pipeline_database_url() -> str:
    database_name = f"pipeline_api_{uuid.uuid4().hex}"
    admin_url = make_url(DATABASE_URL).set(database="postgres")
    tenant_url = make_url(DATABASE_URL).set(database=database_name)
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
                    "VALUES (:id, 'default', 'Pipeline Admin', 'api@example.test', "
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


def _context(role: str) -> SessionContext:
    return SessionContext(
        principal=PrincipalScope(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            user_id=ACTOR_ID,
            role=role,
            team_id=None,
            auth_version=1,
        ),
        tenant_slug="cliente-a",
        tenant_display_name="Cliente A",
        user_name="Pipeline Admin",
        email="api@example.test",
        token_digest="d" * 64,
    )


def _principal_dependency(database_url: str, role: str):
    async def dependency():
        engine = create_engine(database_url, poolclass=NullPool)
        session = Session(engine, expire_on_commit=False)
        try:
            with session.begin():
                session.execute(
                    text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
                    {"workspace_id": WORKSPACE_ID},
                )
                yield ResolvedPrincipal(
                    context=_context(role),
                    tenant_session=session,
                )
        finally:
            session.close()
            engine.dispose()

    return dependency


def _client(
    tmp_path: Path,
    database_url: str,
    *,
    role: str = "Administrador",
    pipeline_service=None,  # noqa: ANN001
) -> TestClient:
    (tmp_path / "index.html").write_text("<!doctype html><title>pipeline</title>", encoding="utf-8")
    app = create_app(
        static_dir=tmp_path,
        auth_settings=AuthSettings(expected_origin=ORIGIN),
        principal_dependency=_principal_dependency(database_url, role),
        pipeline_service=pipeline_service,
    )
    return TestClient(app, raise_server_exceptions=False)


def _update_body(response: dict) -> dict:
    return {
        "pipelineVersion": response["pipelineVersion"],
        "workspaceVersion": response["workspaceVersion"],
        "defaultStageId": response["defaultStageId"],
        "stages": [
            {
                "id": stage["id"],
                "name": stage["name"],
                "semanticType": stage["semanticType"],
                "color": stage["color"],
                "position": stage["position"],
                "archived": not stage["active"],
            }
            for stage in response["stages"]
        ],
        "transfers": {},
    }


def _database_snapshot(database_url: str) -> dict:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as session:
            session.execute(
                text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
                {"workspace_id": WORKSPACE_ID},
            )
            return {
                "pipelineVersion": session.scalar(select(DealPipeline.version)),
                "workspaceVersion": session.scalar(select(Workspace.version)),
                "auditCount": session.scalar(
                    select(func.count()).select_from(DealPipelineAuditEvent)
                ),
                "stages": [
                    tuple(row)
                    for row in session.execute(
                        select(
                            DealPipelineStage.id,
                            DealPipelineStage.name,
                            DealPipelineStage.position,
                            DealPipelineStage.archived_at,
                        ).order_by(DealPipelineStage.position, DealPipelineStage.id)
                    )
                ],
                "deals": [
                    tuple(row)
                    for row in session.execute(
                        select(Deal.id, Deal.stage_id, Deal.deleted_at).order_by(Deal.id)
                    )
                ],
            }
    finally:
        engine.dispose()


def _seed_deal(database_url: str, stage: dict, *, deal_id: str = "api-deal") -> None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(
                text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
                {"workspace_id": WORKSPACE_ID},
            )
            pipeline_id = session.scalar(
                select(DealPipelineStage.pipeline_id).where(
                    DealPipelineStage.id == uuid.UUID(stage["id"])
                )
            )
            record = {
                "id": deal_id,
                "title": deal_id,
                "pipelineId": str(pipeline_id),
                "stageId": stage["id"],
                "stage": stage["name"],
                "stageHistory": [],
            }
            session.execute(
                text(
                    "INSERT INTO deals "
                    "(id, workspace_id, responsible_id, title, company_text, contact_text, "
                    "amount, stage, pipeline_id, stage_id, payload) "
                    "VALUES (:id, 'default', :actor, :id, '', '', 10, :stage, "
                    ":pipeline_id, :stage_id, CAST(:payload AS jsonb))"
                ),
                {
                    "id": deal_id,
                    "actor": ACTOR_ID,
                    "stage": stage["name"],
                    "pipeline_id": pipeline_id,
                    "stage_id": uuid.UUID(stage["id"]),
                    "payload": json.dumps({"position": 0, "record": record}),
                },
            )
    finally:
        engine.dispose()


def _archive_body(
    response: dict,
    *source_ids: str,
    transfers: dict[str, str] | None = None,
) -> dict:
    body = _update_body(response)
    archived = set(source_ids)
    next_position = 0
    for stage in body["stages"]:
        stage["archived"] = stage["id"] in archived
        if not stage["archived"]:
            stage["position"] = next_position
            next_position += 1
    body["transfers"] = transfers or {}
    return body


def test_pipeline_routes_read_update_and_page_canonical_history(
    pipeline_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, pipeline_database_url)

    loaded = client.get("/api/deal-pipeline")
    assert loaded.status_code == 200
    assert loaded.headers["cache-control"] == "no-store"
    assert loaded.json()["pipelineVersion"] == 1
    assert len(loaded.json()["stages"]) == 9
    assert [stage["position"] for stage in loaded.json()["stages"]] == list(range(9))
    assert all(stage["active"] is True for stage in loaded.json()["stages"])

    body = _update_body(loaded.json())
    original_id = body["stages"][0]["id"]
    body["stages"][0]["name"] = "Contato inicial"
    updated = client.put(
        "/api/deal-pipeline",
        json=body,
        headers={"origin": ORIGIN},
    )
    assert updated.status_code == 200
    assert updated.headers["cache-control"] == "no-store"
    assert updated.json()["pipelineVersion"] == 2
    assert updated.json()["stages"][0]["id"] == original_id
    assert updated.json()["stages"][0]["name"] == "Contato inicial"

    complete = client.get("/api/deal-pipeline?include_archived=true")
    history = client.get("/api/deal-pipeline/history?limit=1")
    assert complete.status_code == 200
    assert len(complete.json()["stages"]) == 9
    assert history.status_code == 200
    assert history.headers["cache-control"] == "no-store"
    assert len(history.json()["items"]) == 1
    assert history.json()["items"][0]["actorUserId"] == ACTOR_ID
    assert history.json()["items"][0]["pipelineVersion"] == 2
    invalid_history = client.get("/api/deal-pipeline/history?limit=51")
    assert invalid_history.status_code == 422
    assert invalid_history.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "role",
    ["Gestor", "Vendedor", "Assistente", "Faturamento"],
)
def test_authenticated_roles_read_but_admin_operations_are_forbidden(
    pipeline_database_url: str,
    tmp_path: Path,
    role: str,
) -> None:
    client = _client(tmp_path, pipeline_database_url, role=role)
    loaded = client.get("/api/deal-pipeline")
    body = _update_body(loaded.json())

    assert loaded.status_code == 200
    assert len(loaded.json()["stages"]) == 9
    for response in (
        client.get("/api/deal-pipeline?include_archived=true"),
        client.get("/api/deal-pipeline/history"),
        client.put(
            "/api/deal-pipeline",
            json=body,
            headers={"origin": ORIGIN},
        ),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
        assert response.headers["cache-control"] == "no-store"


async def _unauthenticated(request: Request):
    raise unauthenticated_error(request)


def test_anonymous_pipeline_routes_return_stable_401(
    pipeline_database_url: str,
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_app(static_dir=tmp_path, principal_dependency=_unauthenticated)
    client = TestClient(app, raise_server_exceptions=False)

    for method, path in (
        ("get", "/api/deal-pipeline"),
        ("get", "/api/deal-pipeline/history"),
        ("put", "/api/deal-pipeline"),
    ):
        response = client.request(
            method.upper(),
            path,
            json={} if method == "put" else None,
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"
        assert response.headers["cache-control"] == "no-store"


def test_validation_conflict_and_forged_identifiers_fail_closed(
    pipeline_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, pipeline_database_url)
    loaded = client.get("/api/deal-pipeline").json()
    body = _update_body(loaded)

    invalid_origin = client.put("/api/deal-pipeline", json=body)
    assert invalid_origin.status_code == 403
    assert invalid_origin.json()["error"]["code"] == "invalid_origin"

    invalid_color = _update_body(loaded)
    invalid_color["stages"][0]["color"] = "secret-dsn"
    response = client.put(
        "/api/deal-pipeline", json=invalid_color, headers={"origin": ORIGIN}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["path"] == "body.stages.0.color"
    assert "secret-dsn" not in response.text

    foreign_stage = _update_body(loaded)
    foreign_stage["stages"][1]["id"] = str(uuid.uuid4())
    response = client.put(
        "/api/deal-pipeline", json=foreign_stage, headers={"origin": ORIGIN}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pipeline_stage_not_found"

    for forged_field in ("tenantId", "workspaceId", "pipelineId"):
        forged = {**body, forged_field: str(uuid.uuid4())}
        response = client.put(
            "/api/deal-pipeline", json=forged, headers={"origin": ORIGIN}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    body["stages"][0]["color"] = "#ABCDEF"
    first = client.put("/api/deal-pipeline", json=body, headers={"origin": ORIGIN})
    retry = client.put("/api/deal-pipeline", json=body, headers={"origin": ORIGIN})
    assert first.status_code == 200
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "pipeline_version_conflict"
    assert retry.json()["error"]["currentPipelineVersion"] == 2

    forged_route = client.get(f"/api/deal-pipeline/{uuid.uuid4()}")
    assert forged_route.status_code == 404
    engine = create_engine(pipeline_database_url, poolclass=NullPool)
    with Session(engine) as session:
        session.execute(
            text("SELECT set_config('smartcrm.workspace_id', 'default', false)")
        )
        assert session.scalar(select(DealPipeline.version)) == 2
        assert session.scalar(select(DealPipelineAuditEvent.id)) is not None
    engine.dispose()


@pytest.mark.parametrize("bad_name", ["   ", "x" * 81])
def test_invalid_name_boundaries_return_422_with_path_and_no_write(
    pipeline_database_url: str,
    tmp_path: Path,
    bad_name: str,
) -> None:
    client = _client(tmp_path, pipeline_database_url)
    loaded = client.get("/api/deal-pipeline").json()
    body = _update_body(loaded)
    body["stages"][0]["name"] = bad_name
    before = _database_snapshot(pipeline_database_url)

    response = client.put(
        "/api/deal-pipeline", json=body, headers={"origin": ORIGIN}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["path"] == "body.stages.0.name"
    assert _database_snapshot(pipeline_database_url) == before


def test_outer_whitespace_and_case_duplicate_returns_422_and_no_write(
    pipeline_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, pipeline_database_url)
    loaded = client.get("/api/deal-pipeline").json()
    body = _update_body(loaded)
    body["stages"][0]["name"] = "  Mesmo Nome  "
    body["stages"][1]["name"] = "mesmo nome"
    before = _database_snapshot(pipeline_database_url)

    response = client.put(
        "/api/deal-pipeline", json=body, headers={"origin": ORIGIN}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pipeline_stage_name_duplicate"
    assert response.json()["error"]["path"] == "stages[1].name"
    assert _database_snapshot(pipeline_database_url) == before


def test_fifty_first_active_stage_returns_422_and_no_write(
    pipeline_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, pipeline_database_url)
    loaded = client.get("/api/deal-pipeline").json()
    body = _update_body(loaded)
    for position in range(len(body["stages"]), 51):
        body["stages"].append(
            {
                "name": f"Etapa {position}",
                "semanticType": "open",
                "color": "#123ABC",
                "position": position,
                "archived": False,
            }
        )
    before = _database_snapshot(pipeline_database_url)

    response = client.put(
        "/api/deal-pipeline", json=body, headers={"origin": ORIGIN}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["path"] == "body"
    assert _database_snapshot(pipeline_database_url) == before


@pytest.mark.parametrize(
    ("case", "expected_code", "expected_path_kind"),
    [
        ("missing", "pipeline_archive_target_required", "transfer"),
        ("self", "validation_error", "body"),
        ("archived", "pipeline_archive_target_invalid", "transfer"),
        ("foreign", "pipeline_archive_target_invalid", "transfer"),
    ],
)
def test_invalid_archive_targets_return_422_with_stable_code_and_no_write(
    pipeline_database_url: str,
    tmp_path: Path,
    case: str,
    expected_code: str,
    expected_path_kind: str,
) -> None:
    client = _client(tmp_path, pipeline_database_url)
    loaded = client.get("/api/deal-pipeline").json()
    source = loaded["stages"][1]
    target = loaded["stages"][2]
    _seed_deal(pipeline_database_url, source)
    if case == "missing":
        body = _archive_body(loaded, source["id"])
    elif case == "self":
        body = _archive_body(
            loaded,
            source["id"],
            transfers={source["id"]: source["id"]},
        )
    elif case == "archived":
        body = _archive_body(
            loaded,
            source["id"],
            target["id"],
            transfers={source["id"]: target["id"]},
        )
    else:
        body = _archive_body(
            loaded,
            source["id"],
            transfers={source["id"]: str(uuid.uuid4())},
        )
    before = _database_snapshot(pipeline_database_url)

    response = client.put(
        "/api/deal-pipeline", json=body, headers={"origin": ORIGIN}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == expected_code
    expected_path = (
        "body"
        if expected_path_kind == "body"
        else f"transfers.{source['id']}"
    )
    assert response.json()["error"]["path"] == expected_path
    assert _database_snapshot(pipeline_database_url) == before


@pytest.mark.parametrize("semantic_type", ["open", "won", "lost"])
def test_archiving_last_semantic_stage_returns_422_and_no_write(
    pipeline_database_url: str,
    tmp_path: Path,
    semantic_type: str,
) -> None:
    client = _client(tmp_path, pipeline_database_url)
    loaded = client.get("/api/deal-pipeline").json()
    sources = [
        stage["id"]
        for stage in loaded["stages"]
        if stage["semanticType"] == semantic_type
    ]
    body = _archive_body(loaded, *sources)
    before = _database_snapshot(pipeline_database_url)

    response = client.put(
        "/api/deal-pipeline", json=body, headers={"origin": ORIGIN}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pipeline_semantic_minimum"
    assert response.json()["error"]["path"] == "stages"
    assert _database_snapshot(pipeline_database_url) == before


def test_archiving_current_default_without_replacement_returns_422_and_no_write(
    pipeline_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, pipeline_database_url)
    loaded = client.get("/api/deal-pipeline").json()
    body = _archive_body(loaded, loaded["defaultStageId"])
    before = _database_snapshot(pipeline_database_url)

    response = client.put(
        "/api/deal-pipeline", json=body, headers={"origin": ORIGIN}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pipeline_default_stage_invalid"
    assert response.json()["error"]["path"] == "defaultStageId"
    assert _database_snapshot(pipeline_database_url) == before


class _FailingPipelineService:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure

    def load(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        raise self.failure

    def update(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        raise self.failure


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (
            OperationalError("SELECT postgresql://secret@tenant", {}, RuntimeError("secret")),
            "database_unavailable",
        ),
        (PipelineScopeError("workspace=foreign secret-dsn"), "pipeline_unavailable"),
    ],
)
def test_pipeline_dependency_failures_return_redacted_stable_503(
    pipeline_database_url: str,
    tmp_path: Path,
    failure: Exception,
    code: str,
) -> None:
    client = _client(
        tmp_path,
        pipeline_database_url,
        pipeline_service=_FailingPipelineService(failure),
    )

    response = client.get("/api/deal-pipeline")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "no-store"
    assert "secret" not in response.text
    assert "foreign" not in response.text


def test_tenant_database_failure_during_put_returns_503_without_fallback_or_write(
    pipeline_database_url: str,
    tmp_path: Path,
) -> None:
    loaded = _client(tmp_path, pipeline_database_url).get("/api/deal-pipeline").json()
    body = _update_body(loaded)
    body["stages"][0]["name"] = "Mudança que não pode usar fallback"
    before = _database_snapshot(pipeline_database_url)
    failure = OperationalError(
        "UPDATE postgresql://secret@other-tenant",
        {},
        RuntimeError("foreign fallback secret"),
    )
    client = _client(
        tmp_path,
        pipeline_database_url,
        pipeline_service=_FailingPipelineService(failure),
    )

    response = client.put(
        "/api/deal-pipeline", json=body, headers={"origin": ORIGIN}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert response.headers["cache-control"] == "no-store"
    assert "secret" not in response.text
    assert "foreign" not in response.text
    assert "other-tenant" not in response.text
    assert _database_snapshot(pipeline_database_url) == before
