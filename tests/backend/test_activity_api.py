from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
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
from app.models import CrmActivityEvent, DealPipelineStage
from app.policies import PrincipalScope
from app.repositories.activity import ActivityScopeError
from app.services.auth import SessionContext
from app.services.activity import ActivityValidationError


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "e1c4a7b9d2f6"
ORIGIN = "https://sc2030.brbots.com"
WORKSPACE_ID = "default"
TENANT_ID = uuid.UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")
DEAL_ID = "activity-api-deal"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def activity_api_database_url() -> str:
    database_name = f"activity_api_{uuid.uuid4().hex}"
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
                    "INSERT INTO teams (id, workspace_id, name) VALUES "
                    "('team-a', 'default', 'A'), ('team-b', 'default', 'B')"
                )
            )
            for user_id, name, role, team_id in (
                ("seller", "Seller", "Vendedor", "team-a"),
                ("manager-b", "Manager B", "Gestor", "team-b"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO crm_users "
                        "(id, workspace_id, team_id, name, email, job_title, role, status, payload) "
                        "VALUES (:id, 'default', :team, :name, :email, '', :role, "
                        "'Ativo', '{}'::jsonb)"
                    ),
                    {
                        "id": user_id,
                        "team": team_id,
                        "name": name,
                        "email": f"{user_id}@example.test",
                        "role": role,
                    },
                )
            stage = connection.execute(
                text(
                    "SELECT pipeline_id, id, name FROM deal_pipeline_stages "
                    "WHERE workspace_id = 'default' AND archived_at IS NULL "
                    "ORDER BY position LIMIT 1"
                )
            ).one()
            connection.execute(
                text(
                    "INSERT INTO deals "
                    "(id, workspace_id, responsible_id, team_id, title, company_text, "
                    "contact_text, amount, stage, pipeline_id, stage_id, payload) "
                    "VALUES (:id, 'default', 'seller', 'team-a', 'API Deal', '', '', 100, "
                    ":stage, :pipeline, :stage_id, CAST(:payload AS jsonb))"
                ),
                {
                    "id": DEAL_ID,
                    "stage": stage.name,
                    "pipeline": stage.pipeline_id,
                    "stage_id": stage.id,
                    "payload": json.dumps({"position": 0, "record": {"id": DEAL_ID}}),
                },
            )
            for offset, category in enumerate(("movement", "automation", "observation")):
                connection.execute(
                    text(
                        "INSERT INTO crm_activity_events "
                        "(workspace_id, deal_id, category, event_type, actor_user_id, "
                        "actor_name, summary, details, dedupe_key, occurred_at) "
                        "VALUES ('default', :deal, :category, :event_type, 'seller', "
                        "'Seller', :summary, '{}'::jsonb, :dedupe, :occurred_at)"
                    ),
                    {
                        "deal": DEAL_ID,
                        "category": category,
                        "event_type": f"deal.seed_{category}",
                        "summary": f"Seed {category}",
                        "dedupe": f"activity-api-seed:{category}",
                        "occurred_at": NOW + timedelta(minutes=offset),
                    },
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


def _context(user_id: str, role: str, team_id: str | None) -> SessionContext:
    return SessionContext(
        principal=PrincipalScope(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            user_id=user_id,
            role=role,
            team_id=team_id,
            auth_version=1,
        ),
        tenant_slug="brbots",
        tenant_display_name="BRBots",
        user_name=user_id,
        email=f"{user_id}@example.test",
        token_digest="d" * 64,
    )


def _principal_dependency(
    database_url: str,
    *,
    user_id: str = "seller",
    role: str = "Vendedor",
    team_id: str | None = "team-a",
):
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
                    context=_context(user_id, role, team_id),
                    tenant_session=session,
                )
        finally:
            session.close()
            engine.dispose()

    return dependency


async def _unauthenticated(request: Request) -> None:
    raise unauthenticated_error(request)


def _client(
    tmp_path: Path,
    database_url: str,
    *,
    user_id: str = "seller",
    role: str = "Vendedor",
    team_id: str | None = "team-a",
    activity_service=None,  # noqa: ANN001
    unauthenticated: bool = False,
) -> TestClient:
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>activity</title>", encoding="utf-8"
    )
    dependency = (
        _unauthenticated
        if unauthenticated
        else _principal_dependency(
            database_url,
            user_id=user_id,
            role=role,
            team_id=team_id,
        )
    )
    app = create_app(
        static_dir=tmp_path,
        auth_settings=AuthSettings(expected_origin=ORIGIN),
        principal_dependency=dependency,
        activity_service=activity_service,
    )
    return TestClient(app, raise_server_exceptions=False)


def _event_count(database_url: str, dedupe_key: str) -> int:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as session:
            session.execute(
                text("SELECT set_config('smartcrm.workspace_id', 'default', true)")
            )
            return int(
                session.scalar(
                    select(func.count()).select_from(CrmActivityEvent).where(
                        CrmActivityEvent.dedupe_key == dedupe_key
                    )
                )
                or 0
            )
    finally:
        engine.dispose()


def test_deal_timeline_filters_and_pages_with_opaque_cursor(
    activity_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, activity_api_database_url)

    first = client.get(f"/api/deals/{DEAL_ID}/activities?limit=2")
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    first_body = first.json()
    assert [item["category"] for item in first_body["items"]] == [
        "observation",
        "automation",
    ]
    assert first_body["nextCursor"]
    assert DEAL_ID not in first_body["nextCursor"]

    second = client.get(
        f"/api/deals/{DEAL_ID}/activities",
        params={"limit": 2, "cursor": first_body["nextCursor"]},
    )
    assert second.status_code == 200
    assert [item["category"] for item in second.json()["items"]] == ["movement"]
    assert second.json()["nextCursor"] is None

    filtered = client.get(
        f"/api/deals/{DEAL_ID}/activities",
        params={"category": "automation"},
    )
    assert filtered.status_code == 200
    assert [item["category"] for item in filtered.json()["items"]] == ["automation"]
    client.close()


def test_observation_requires_origin_is_idempotent_and_owns_metadata(
    activity_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, activity_api_database_url)
    key = uuid.uuid4()
    body = {"text": "  Retornar ao cliente  ", "idempotencyKey": str(key)}

    forbidden = client.post(f"/api/deals/{DEAL_ID}/observations", json=body)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "invalid_origin"
    assert forbidden.headers["cache-control"] == "no-store"

    first = client.post(
        f"/api/deals/{DEAL_ID}/observations",
        json=body,
        headers={"origin": ORIGIN},
    )
    retry = client.post(
        f"/api/deals/{DEAL_ID}/observations",
        json=body,
        headers={"origin": ORIGIN},
    )
    assert first.status_code == retry.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json() == retry.json()
    assert first.json()["actor"] == {"id": "seller", "name": "Seller", "kind": "user"}
    assert first.json()["details"] == {"text": "Retornar ao cliente"}
    assert _event_count(activity_api_database_url, f"observation:{key}") == 1

    forged = client.post(
        f"/api/deals/{DEAL_ID}/observations",
        json={
            **body,
            "actorUserId": "manager-b",
            "workspaceId": "foreign",
            "tenantId": str(uuid.uuid4()),
            "occurredAt": "1999-01-01T00:00:00Z",
        },
        headers={"origin": ORIGIN},
    )
    assert forged.status_code == 422
    assert forged.json()["error"]["code"] == "validation_error"
    client.close()


def test_deal_activity_routes_hide_missing_and_forbidden_subjects(
    activity_api_database_url: str,
    tmp_path: Path,
) -> None:
    outsider = _client(
        tmp_path,
        activity_api_database_url,
        user_id="manager-b",
        role="Gestor",
        team_id="team-b",
    )
    hidden = outsider.get(f"/api/deals/{DEAL_ID}/activities")
    missing = outsider.get("/api/deals/missing/activities")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()
    assert DEAL_ID not in hidden.text

    ghost = _client(
        tmp_path,
        activity_api_database_url,
        user_id="ghost",
        role="Administrador",
        team_id=None,
    )
    forbidden = ghost.post(
        f"/api/deals/{DEAL_ID}/observations",
        json={"text": "Teste", "idempotencyKey": str(uuid.uuid4())},
        headers={"origin": ORIGIN},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"
    outsider.close()
    ghost.close()


@pytest.mark.parametrize(
    "suffix",
    (
        "?category=change",
        "?limit=0",
        "?limit=51",
        "?cursor=invalid%2Bcursor",
    ),
)
def test_deal_timeline_rejects_invalid_queries_with_stable_422(
    activity_api_database_url: str,
    tmp_path: Path,
    suffix: str,
) -> None:
    client = _client(tmp_path, activity_api_database_url)
    response = client.get(f"/api/deals/{DEAL_ID}/activities{suffix}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.headers["cache-control"] == "no-store"
    client.close()


class _FailingActivityService:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure

    def deal_timeline(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        raise self.failure

    def add_deal_observation(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        raise self.failure


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    (
        (ActivityValidationError("unsafe secret"), 422, "validation_error"),
        (ActivityScopeError("workspace=foreign secret"), 503, "activity_unavailable"),
        (
            OperationalError("SELECT postgresql://secret@tenant", {}, RuntimeError("secret")),
            503,
            "database_unavailable",
        ),
    ),
)
def test_activity_failures_are_stable_redacted_and_no_store(
    activity_api_database_url: str,
    tmp_path: Path,
    failure: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    client = _client(
        tmp_path,
        activity_api_database_url,
        activity_service=_FailingActivityService(failure),
    )
    response = client.get(f"/api/deals/{DEAL_ID}/activities")
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert response.headers["cache-control"] == "no-store"
    assert "secret" not in response.text
    assert "foreign" not in response.text
    assert "tenant" not in response.text
    client.close()


def test_deal_activity_requires_authentication(
    activity_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        activity_api_database_url,
        unauthenticated=True,
    )
    response = client.get(f"/api/deals/{DEAL_ID}/activities")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["cache-control"] == "no-store"
    client.close()
