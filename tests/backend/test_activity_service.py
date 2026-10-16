from __future__ import annotations

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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.models import CrmActivityEvent, Workspace
import app.services.activity as activity_module
from app.policies import PrincipalScope
from app.repositories.activity import ActivityRepository, NewActivityEvent
from app.schemas import ActivityQuery, ObservationCreateRequest
from app.services.activity import (
    ActivityAuthorizationError,
    ActivityNotFoundError,
    ActivityService,
    ActivityValidationError,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "e1c4a7b9d2f6"
TENANT_ID = uuid.UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
WORKSPACE_ID = "default"
COMPANY_ID = "activity-service-company"
DEAL_ID = "activity-service-deal"


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def activity_service_database_url() -> str:
    database_name = f"activity_service_{uuid.uuid4().hex}"
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


def _set_workspace(session: Session, workspace_id: str = WORKSPACE_ID) -> None:
    session.execute(
        text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
        {"workspace_id": workspace_id},
    )


def _seed(session: Session) -> None:
    users = (
        ("admin", "Admin", "Administrador", "team-b"),
        ("manager", "Manager", "Gestor", "team-a"),
        ("seller", "Seller", "Vendedor", "team-a"),
        ("assistant", "Assistant", "Assistente", "team-b"),
        ("billing", "Billing", "Faturamento", "team-b"),
        ("outsider", "Outsider", "Gestor", "team-b"),
    )
    session.execute(
        text("INSERT INTO teams (id, workspace_id, name) VALUES ('team-a', 'default', 'A'), ('team-b', 'default', 'B')")
    )
    for user_id, name, role, team_id in users:
        session.execute(
            text(
                "INSERT INTO crm_users "
                "(id, workspace_id, team_id, name, email, job_title, role, status, payload) "
                "VALUES (:id, 'default', :team, :name, :email, '', :role, 'Ativo', '{}'::jsonb)"
            ),
            {
                "id": user_id,
                "team": team_id,
                "name": name,
                "email": f"{user_id}@example.test",
                "role": role,
            },
        )
    session.execute(
        text(
            "INSERT INTO companies "
            "(id, workspace_id, owner_id, name, city, segment, phone, payload) "
            "VALUES (:id, 'default', 'seller', 'Service Company', '', '', '', '{}'::jsonb)"
        ),
        {"id": COMPANY_ID},
    )
    stage = session.execute(
        text(
            "SELECT p.id AS pipeline_id, s.id AS stage_id, s.name AS stage_name "
            "FROM deal_pipelines p JOIN deal_pipeline_stages s "
            "ON s.pipeline_id = p.id AND s.workspace_id = p.workspace_id "
            "WHERE p.workspace_id = 'default' AND p.is_default ORDER BY s.position LIMIT 1"
        )
    ).one()
    session.execute(
        text(
            "INSERT INTO deals "
            "(id, workspace_id, company_id, responsible_id, team_id, title, company_text, "
            "contact_text, amount, stage, pipeline_id, stage_id, payload) "
            "VALUES (:id, 'default', :company, 'seller', 'team-a', 'Service Deal', "
            "'Service Company', '', 100, :stage, :pipeline, :stage_id, '{}'::jsonb)"
        ),
        {
            "id": DEAL_ID,
            "company": COMPANY_ID,
            "stage": stage.stage_name,
            "pipeline": stage.pipeline_id,
            "stage_id": stage.stage_id,
        },
    )
    for position, user_id in enumerate(("assistant", "billing")):
        session.execute(
            text(
                "INSERT INTO deal_assistants (workspace_id, deal_id, user_id, position) "
                "VALUES ('default', :deal, :user, :position)"
            ),
            {"deal": DEAL_ID, "user": user_id, "position": position},
        )


@contextmanager
def service_scope(database_url: str):
    engine = create_engine(database_url, poolclass=NullPool)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        _set_workspace(session)
        _seed(session)
        yield ActivityService(clock=lambda: NOW), session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _principal(user_id: str, role: str, team_id: str | None) -> PrincipalScope:
    return PrincipalScope(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        user_id=user_id,
        role=role,
        team_id=team_id,
        auth_version=1,
    )


VISIBLE_DEAL_PRINCIPALS = (
    _principal("admin", "Administrador", "team-b"),
    _principal("manager", "Gestor", "team-a"),
    _principal("seller", "Vendedor", "team-a"),
    _principal("assistant", "Assistente", "team-b"),
    _principal("billing", "Faturamento", "team-b"),
)


def _request(text_value: str, key: uuid.UUID | None = None) -> ObservationCreateRequest:
    return ObservationCreateRequest(text=text_value, idempotencyKey=key or uuid.uuid4())


@pytest.mark.parametrize("principal", VISIBLE_DEAL_PRINCIPALS)
def test_deal_timeline_visibility_matches_each_supported_role(
    activity_service_database_url: str,
    principal: PrincipalScope,
) -> None:
    with service_scope(activity_service_database_url) as (service, session):
        ActivityRepository(session, WORKSPACE_ID).append(
            NewActivityEvent(
                deal_id=DEAL_ID,
                company_id=None,
                category="movement",
                event_type="deal.stage_changed",
                actor_user_id="seller",
                actor_name="Seller",
                summary="Etapa alterada",
                details={"fromStageId": None, "toStageId": "stage"},
                dedupe_key=f"visibility:{principal.user_id}",
                occurred_at=NOW,
            )
        )

        page = service.deal_timeline(
            session, principal, DEAL_ID, ActivityQuery(category="movement")
        )

        assert len(page.items) == 1
        assert page.items[0].event_type == "deal.stage_changed"
        assert page.items[0].actor.name == "Seller"
        assert page.items[0].occurred_at == NOW


def test_hidden_missing_and_foreign_deals_share_generic_not_found(
    activity_service_database_url: str,
) -> None:
    outsider = _principal("outsider", "Gestor", "team-b")
    with service_scope(activity_service_database_url) as (service, session):
        for deal_id in (DEAL_ID, "missing", "foreign"):
            with pytest.raises(ActivityNotFoundError, match="activity subject not found"):
                service.deal_timeline(session, outsider, deal_id, ActivityQuery())


@pytest.mark.parametrize("principal", VISIBLE_DEAL_PRINCIPALS)
def test_observation_derives_canonical_actor_and_preserves_plain_text(
    activity_service_database_url: str,
    principal: PrincipalScope,
) -> None:
    with service_scope(activity_service_database_url) as (service, session):
        response = service.add_deal_observation(
            session,
            principal,
            DEAL_ID,
            _request("  <script>alert('x')</script>  "),
        )

        persisted = session.scalar(
            select(CrmActivityEvent).where(CrmActivityEvent.id == response.id)
        )
        assert response.category == "observation"
        assert response.actor.id == principal.user_id
        assert response.actor.name == {
            "admin": "Admin",
            "manager": "Manager",
            "seller": "Seller",
            "assistant": "Assistant",
            "billing": "Billing",
        }[principal.user_id]
        assert response.occurred_at == NOW
        assert response.details == {"text": "<script>alert('x')</script>"}
        assert persisted.workspace_id == WORKSPACE_ID
        assert persisted.details == response.details


@pytest.mark.parametrize("text_value", ["", "   ", "x" * 4_001])
def test_observation_service_rejects_invalid_text_without_writing(
    activity_service_database_url: str,
    text_value: str,
) -> None:
    invalid = ObservationCreateRequest.model_construct(
        text=text_value, idempotency_key=uuid.uuid4()
    )
    with service_scope(activity_service_database_url) as (service, session):
        with pytest.raises(ActivityValidationError, match="observation text"):
            service.add_company_observation(
                session, VISIBLE_DEAL_PRINCIPALS[0], COMPANY_ID, invalid
            )

        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 0


def test_observation_retry_returns_original_without_version_or_duplicate_change(
    activity_service_database_url: str,
) -> None:
    request = _request("Primeira nota")
    admin = VISIBLE_DEAL_PRINCIPALS[0]
    with service_scope(activity_service_database_url) as (service, session):
        version_before = session.scalar(
            select(Workspace.version).where(Workspace.id == WORKSPACE_ID)
        )
        first = service.add_company_observation(session, admin, COMPANY_ID, request)
        repeated = service.add_company_observation(session, admin, COMPANY_ID, request)
        reloaded = service.company_timeline(
            session, admin, COMPANY_ID, ActivityQuery(category="observation")
        )

        assert repeated.id == first.id
        assert repeated.details == {"text": "Primeira nota"}
        assert [item.id for item in reloaded.items] == [first.id]
        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 1
        assert session.scalar(
            select(Workspace.version).where(Workspace.id == WORKSPACE_ID)
        ) == version_before


def test_correction_is_new_immutable_observation(
    activity_service_database_url: str,
) -> None:
    admin = VISIBLE_DEAL_PRINCIPALS[0]
    with service_scope(activity_service_database_url) as (service, session):
        original = service.add_company_observation(
            session, admin, COMPANY_ID, _request("Original")
        )
        correction = service.add_company_observation(
            session, admin, COMPANY_ID, _request("Correção")
        )
        page = service.company_timeline(
            session, admin, COMPANY_ID, ActivityQuery(category="observation")
        )

        assert [item.id for item in page.items] == [correction.id, original.id]
        assert [item.details["text"] for item in page.items] == ["Correção", "Original"]
        assert not hasattr(service, "update_observation")
        assert not hasattr(service, "delete_observation")


def test_visible_company_without_mutation_permission_is_forbidden(
    activity_service_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forged = _principal("admin", "Owner", "team-b")
    monkeypatch.setattr(activity_module, "can_read_record", lambda *_args: True)
    monkeypatch.setattr(activity_module, "can_mutate_record", lambda *_args: False)
    with service_scope(activity_service_database_url) as (service, session):
        with pytest.raises(ActivityAuthorizationError, match="activity mutation forbidden"):
            service.add_company_observation(
                session, forged, COMPANY_ID, _request("Negada")
            )

        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 0


def test_database_failure_propagates_for_closed_503_mapping() -> None:
    class UnavailableSession:
        def scalar(self, _statement):  # noqa: ANN001
            raise SQLAlchemyError("database unavailable")

    service = ActivityService()
    with pytest.raises(SQLAlchemyError, match="database unavailable"):
        service.deal_timeline(
            UnavailableSession(),
            VISIBLE_DEAL_PRINCIPALS[0],
            DEAL_ID,
            ActivityQuery(),
        )
