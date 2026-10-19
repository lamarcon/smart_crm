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
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.auth import AuthSettings, ResolvedPrincipal, unauthenticated_error
from app.main import create_app
from app.policies import PrincipalScope
from app.services.auth import SessionContext


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "e1c4a7b9d2f6"
ORIGIN = "https://sc2030.brbots.com"
WORKSPACE_ID = "default"
TENANT_ID = uuid.UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")
COMPANY_ID = "company-api"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


def _set_workspace(connection, workspace_id: str) -> None:  # noqa: ANN001
    connection.execute(
        text("SELECT set_config('smartcrm.workspace_id', :workspace_id, false)"),
        {"workspace_id": workspace_id},
    )


def _seed_company_api(connection) -> None:  # noqa: ANN001
    _set_workspace(connection, WORKSPACE_ID)
    connection.execute(
        text(
            "INSERT INTO teams (id, workspace_id, name) VALUES "
            "('team-a', 'default', 'A'), ('team-b', 'default', 'B')"
        )
    )
    for user_id, name, team_id in (
        ("seller", "Seller", "team-a"),
        ("manager-a", "Manager A", "team-a"),
        ("other", "Other", "team-b"),
    ):
        connection.execute(
            text(
                "INSERT INTO crm_users "
                "(id, workspace_id, team_id, name, email, job_title, role, status, payload) "
                "VALUES (:id, 'default', :team, :name, :email, '', 'Vendedor', "
                "'Ativo', '{}'::jsonb)"
            ),
            {
                "id": user_id,
                "team": team_id,
                "name": name,
                "email": f"{user_id}@example.test",
            },
        )
    for company_id, name, deleted_at in (
        (COMPANY_ID, "Company API", None),
        ("empty-company", "Empty", None),
        ("deleted-company", "Deleted", "2026-01-01T00:00:00+00:00"),
    ):
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, workspace_id, owner_id, name, city, segment, phone, payload, deleted_at) "
                "VALUES (:id, 'default', 'seller', :name, '', '', '', '{}'::jsonb, :deleted_at)"
            ),
            {"id": company_id, "name": name, "deleted_at": deleted_at},
        )

    stages = {
        row.semantic_type: row
        for row in connection.execute(
            text(
                "SELECT p.id AS pipeline_id, s.id AS stage_id, s.name, s.semantic_type "
                "FROM deal_pipelines p JOIN deal_pipeline_stages s "
                "ON s.pipeline_id = p.id AND s.workspace_id = p.workspace_id "
                "WHERE p.workspace_id = 'default' AND p.is_default "
                "ORDER BY s.position"
            )
        )
    }
    deals = (
        ("deal-open", "seller", "team-a", "10.10", "open", None),
        ("deal-won-assisted", "other", "team-b", "20.20", "won", "seller"),
        ("deal-lost-team", "other", "team-a", "30.30", "lost", None),
        ("deal-hidden", "other", "team-b", "40.40", "open", None),
        ("deal-deleted", "seller", "team-a", "50.50", "won", None),
    )
    for position, (deal_id, responsible, team_id, amount, semantic, assistant) in enumerate(deals):
        stage = stages[semantic]
        connection.execute(
            text(
                "INSERT INTO deals "
                "(id, workspace_id, company_id, responsible_id, team_id, title, company_text, "
                "contact_text, amount, stage, pipeline_id, stage_id, payload, created_at, deleted_at) "
                "VALUES (:id, 'default', :company, :responsible, :team, :title, 'Company API', '', "
                ":amount, :stage, :pipeline, :stage_id, CAST(:payload AS jsonb), "
                "TIMESTAMPTZ '2026-01-01 00:00:00+00' + (:position * INTERVAL '1 minute'), "
                ":deleted_at)"
            ),
            {
                "id": deal_id,
                "company": COMPANY_ID,
                "responsible": responsible,
                "team": team_id,
                "title": deal_id,
                "amount": amount,
                "stage": stage.name,
                "pipeline": stage.pipeline_id,
                "stage_id": stage.stage_id,
                "payload": json.dumps({"position": position, "record": {"id": deal_id}}),
                "position": position,
                "deleted_at": (
                    "2026-02-01T00:00:00+00:00" if deal_id == "deal-deleted" else None
                ),
            },
        )
        if assistant:
            connection.execute(
                text(
                    "INSERT INTO deal_assistants (workspace_id, deal_id, user_id, position) "
                    "VALUES ('default', :deal, :user, 0)"
                ),
                {"deal": deal_id, "user": assistant},
            )

    for offset, category in enumerate(("change", "observation")):
        connection.execute(
            text(
                "INSERT INTO crm_activity_events "
                "(workspace_id, company_id, category, event_type, actor_user_id, actor_name, "
                "summary, details, dedupe_key, occurred_at) "
                "VALUES ('default', :company, :category, :event_type, 'seller', 'Seller', "
                ":summary, '{}'::jsonb, :dedupe, :occurred_at)"
            ),
            {
                "company": COMPANY_ID,
                "category": category,
                "event_type": f"company.seed_{category}",
                "summary": f"Seed {category}",
                "dedupe": f"company-api-seed:{category}",
                "occurred_at": NOW + timedelta(minutes=offset),
            },
        )
    connection.execute(
        text(
            "INSERT INTO crm_activity_events "
            "(workspace_id, deal_id, category, event_type, actor_user_id, actor_name, "
            "summary, details, dedupe_key, occurred_at) "
            "VALUES ('default', 'deal-open', 'movement', 'deal.stage_changed', 'seller', "
            "'Seller', 'Must stay out of Company history', '{}'::jsonb, "
            "'company-api-linked-deal', :occurred_at)"
        ),
        {"occurred_at": NOW + timedelta(minutes=2)},
    )
    _set_workspace(connection, "foreign")
    connection.execute(text("INSERT INTO workspaces (id, version) VALUES ('foreign', 0)"))
    connection.execute(
        text(
            "INSERT INTO companies "
            "(id, workspace_id, name, city, segment, phone, payload) "
            "VALUES ('foreign-company', 'foreign', 'Foreign', '', '', '', '{}'::jsonb)"
        )
    )
    _set_workspace(connection, WORKSPACE_ID)


@pytest.fixture(scope="module")
def company_api_database_url() -> str:
    database_name = f"company_api_{uuid.uuid4().hex}"
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
            _seed_company_api(connection)
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
    company_deal_service=None,  # noqa: ANN001
    unauthenticated: bool = False,
) -> TestClient:
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>company</title>", encoding="utf-8"
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
        company_deal_service=company_deal_service,
    )
    return TestClient(app, raise_server_exceptions=False)


def test_company_timeline_pages_filters_and_excludes_linked_deal_events(
    company_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, company_api_database_url)
    response = client.get(f"/api/companies/{COMPANY_ID}/activities?limit=1")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert [item["category"] for item in body["items"]] == ["observation"]
    assert body["nextCursor"]
    assert COMPANY_ID not in body["nextCursor"]

    second = client.get(
        f"/api/companies/{COMPANY_ID}/activities",
        params={"limit": 1, "cursor": body["nextCursor"]},
    )
    assert [item["category"] for item in second.json()["items"]] == ["change"]
    assert "Must stay out" not in response.text + second.text

    filtered = client.get(
        f"/api/companies/{COMPANY_ID}/activities",
        params={"category": "change"},
    )
    assert [item["category"] for item in filtered.json()["items"]] == ["change"]
    client.close()


def test_company_observation_requires_origin_is_idempotent_and_rejects_forgery(
    company_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, company_api_database_url)
    key = uuid.uuid4()
    body = {"text": "  Nota da empresa  ", "idempotencyKey": str(key)}
    forbidden = client.post(f"/api/companies/{COMPANY_ID}/observations", json=body)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "invalid_origin"

    first = client.post(
        f"/api/companies/{COMPANY_ID}/observations",
        json=body,
        headers={"origin": ORIGIN},
    )
    retry = client.post(
        f"/api/companies/{COMPANY_ID}/observations",
        json=body,
        headers={"origin": ORIGIN},
    )
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert first.json()["details"] == {"text": "Nota da empresa"}
    assert first.json()["actor"] == {"id": "seller", "name": "Seller", "kind": "user"}

    forged = client.post(
        f"/api/companies/{COMPANY_ID}/observations",
        json={
            **body,
            "actorUserId": "other",
            "workspaceId": "foreign",
            "tenantId": str(uuid.uuid4()),
            "occurredAt": "1999-01-01T00:00:00Z",
        },
        headers={"origin": ORIGIN},
    )
    assert forged.status_code == 422
    assert forged.json()["error"]["code"] == "validation_error"
    client.close()


@pytest.mark.parametrize(
    ("user_id", "role", "team_id", "expected_ids"),
    (
        ("seller", "Administrador", None, ["deal-hidden", "deal-lost-team", "deal-won-assisted", "deal-open"]),
        ("manager-a", "Gestor", "team-a", ["deal-lost-team", "deal-open"]),
        ("seller", "Vendedor", "team-a", ["deal-won-assisted", "deal-open"]),
        ("seller", "Assistente", "team-a", ["deal-won-assisted", "deal-open"]),
        ("seller", "Faturamento", "team-a", ["deal-won-assisted", "deal-open"]),
    ),
)
def test_company_deals_api_returns_exact_visible_active_rows_for_all_roles(
    company_api_database_url: str,
    tmp_path: Path,
    user_id: str,
    role: str,
    team_id: str | None,
    expected_ids: list[str],
) -> None:
    client = _client(
        tmp_path,
        company_api_database_url,
        user_id=user_id,
        role=role,
        team_id=team_id,
    )
    response = client.get(f"/api/companies/{COMPANY_ID}/deals")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert [item["id"] for item in body["items"]] == expected_ids
    assert body["totalCount"] == len(expected_ids)
    assert sum(body[key]["count"] for key in ("open", "won", "lost")) == len(expected_ids)
    assert "deal-deleted" not in response.text
    client.close()


def test_company_deals_api_returns_exact_admin_totals_empty_state_and_semantic_rename(
    company_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, company_api_database_url, role="Administrador", team_id=None)
    full = client.get(f"/api/companies/{COMPANY_ID}/deals")
    assert full.json() | {"items": []} == {
        "totalCount": 4,
        "open": {"count": 2, "amount": "50.50"},
        "won": {"count": 1, "amount": "20.20"},
        "lost": {"count": 1, "amount": "30.30"},
        "items": [],
    }
    empty = client.get("/api/companies/empty-company/deals")
    assert empty.status_code == 200
    assert empty.json() == {
        "totalCount": 0,
        "open": {"count": 0, "amount": "0.00"},
        "won": {"count": 0, "amount": "0.00"},
        "lost": {"count": 0, "amount": "0.00"},
        "items": [],
    }

    engine = create_engine(company_api_database_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            _set_workspace(connection, WORKSPACE_ID)
            connection.execute(
                text(
                    "UPDATE deal_pipeline_stages SET name = 'Ganho renomeado' "
                    "WHERE workspace_id = 'default' AND semantic_type = 'won'"
                )
            )
        renamed = client.get(f"/api/companies/{COMPANY_ID}/deals")
        won = next(item for item in renamed.json()["items"] if item["id"] == "deal-won-assisted")
        assert won["stageName"] == "Ganho renomeado"
        assert renamed.json()["won"] == {"count": 1, "amount": "20.20"}
    finally:
        engine.dispose()
    client.close()


def test_company_routes_hide_missing_deleted_and_unauthorized_subjects(
    company_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, company_api_database_url)
    for suffix in ("activities", "deals"):
        missing = client.get(f"/api/companies/missing/{suffix}")
        deleted = client.get(f"/api/companies/deleted-company/{suffix}")
        foreign = client.get(f"/api/companies/foreign-company/{suffix}")
        assert missing.status_code == deleted.status_code == foreign.status_code == 404
        assert missing.json() == deleted.json() == foreign.json()

    forbidden = _client(tmp_path, company_api_database_url, role="Owner")
    response = forbidden.get(f"/api/companies/{COMPANY_ID}/activities")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    client.close()
    forbidden.close()


@pytest.mark.parametrize(
    "suffix",
    ("?category=movement", "?limit=0", "?limit=51", "?cursor=invalid%2Bcursor"),
)
def test_company_timeline_rejects_invalid_queries(
    company_api_database_url: str,
    tmp_path: Path,
    suffix: str,
) -> None:
    client = _client(tmp_path, company_api_database_url)
    response = client.get(f"/api/companies/{COMPANY_ID}/activities{suffix}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.headers["cache-control"] == "no-store"
    client.close()


class _FailingCompanyDealService:
    def summary(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        raise OperationalError("SELECT postgresql://secret@foreign", {}, RuntimeError("secret"))


def test_company_dependency_failure_is_redacted_closed_and_no_store(
    company_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        company_api_database_url,
        company_deal_service=_FailingCompanyDealService(),
    )
    response = client.get(f"/api/companies/{COMPANY_ID}/deals")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert response.headers["cache-control"] == "no-store"
    assert "secret" not in response.text
    assert "foreign" not in response.text
    client.close()


def test_company_routes_require_authentication(
    company_api_database_url: str,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, company_api_database_url, unauthenticated=True)
    for suffix in ("activities", "deals"):
        response = client.get(f"/api/companies/{COMPANY_ID}/{suffix}")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"
        assert response.headers["cache-control"] == "no-store"
    client.close()
