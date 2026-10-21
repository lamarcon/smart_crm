from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.models import CrmActivityEvent, Deal, DealPipelineStage, Notification
from app.policies import PrincipalScope
from app.services.deal_automation import DealAutomationExecutor, DealTransition


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "f6b1d3a8c2e4"
TENANT_ID = UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")
NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


def _principal(user_id: str = "actor") -> PrincipalScope:
    return PrincipalScope(
        tenant_id=TENANT_ID,
        workspace_id="default",
        user_id=user_id,
        role="Administrador" if user_id == "actor" else "Faturamento",
        team_id="sales" if user_id == "actor" else "billing",
        auth_version=1,
    )


def _seed(session: Session) -> None:
    session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
    session.execute(
        text(
            "INSERT INTO teams (id, workspace_id, name) VALUES "
            "('sales', 'default', 'Vendas'), ('billing', 'default', 'Faturamento')"
        )
    )
    for user_id, name, role, team_id in (
        ("actor", "Operador", "Administrador", "sales"),
        ("u-billing", "Equipe Faturamento", "Faturamento", "billing"),
    ):
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

    stages = {
        row.system_key or row.semantic_type: row
        for row in session.execute(
            text(
                "SELECT s.id, s.pipeline_id, s.name, s.semantic_type, s.system_key "
                "FROM deal_pipeline_stages s JOIN deal_pipelines p ON p.id = s.pipeline_id "
                "WHERE s.workspace_id = 'default' AND p.is_default AND s.archived_at IS NULL "
                "ORDER BY s.position"
            )
        )
    }
    open_stage = stages["open"]
    billing_stage = stages["billing"]
    for deal_id, stage in (
        ("success", billing_stage),
        ("missing-target", billing_stage),
        ("rollback", billing_stage),
        ("ordinary", open_stage),
    ):
        session.execute(
            text(
                "INSERT INTO deals "
                "(id, workspace_id, responsible_id, team_id, title, company_text, contact_text, "
                "amount, stage, pipeline_id, stage_id, payload) "
                "VALUES (:id, 'default', 'actor', 'sales', :id, '', '', 0, :stage, "
                ":pipeline, :stage_id, '{}'::jsonb)"
            ),
            {
                "id": deal_id,
                "stage": stage.name,
                "pipeline": stage.pipeline_id,
                "stage_id": stage.id,
            },
        )


@pytest.fixture(scope="module")
def deal_automation_database_url() -> str:
    database_name = f"deal_automation_{uuid4().hex}"
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
        with Session(tenant_engine) as session, session.begin():
            _seed(session)
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


def _transition(session: Session, deal_id: str) -> DealTransition:
    deal = session.get(Deal, deal_id)
    assert deal is not None
    return DealTransition(deal_id=deal.id, from_stage_id=None, to_stage_id=deal.stage_id)


def _executor() -> DealAutomationExecutor:
    return DealAutomationExecutor(clock=lambda: NOW)


def test_billing_success_is_safe_atomic_and_idempotent(
    deal_automation_database_url: str,
) -> None:
    engine = create_engine(deal_automation_database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            transition = _transition(session, "success")
            first = _executor().execute_for_transition(
                session, _principal(), transition, "workspace:42:success"
            )
            second = _executor().execute_for_transition(
                session, _principal(), transition, "workspace:42:success"
            )

            assert first is not None and second == first
            assert first.automation_key == "billing"
            assert first.automation_name == "Automação de Faturamento"
            assert first.result == "success"
            assert first.failure_code is None
            assert [action.type for action in first.actions] == [
                "assignment",
                "notification",
                "notification",
            ]

        with Session(engine) as session:
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            deal = session.get(Deal, "success")
            assert deal is not None
            assert (deal.responsible_id, deal.team_id) == ("u-billing", "billing")
            notifications = session.scalars(
                select(Notification).where(Notification.workspace_id == "default")
            ).all()
            assert {item.user_id for item in notifications} == {"actor", "u-billing"}
            assert len(notifications) == 2
            events = session.scalars(
                select(CrmActivityEvent).where(CrmActivityEvent.deal_id == "success")
            ).all()
            assert len(events) == 1
            assert events[0].details == first.details()
    finally:
        engine.dispose()


def test_non_billing_transition_is_a_no_op(deal_automation_database_url: str) -> None:
    engine = create_engine(deal_automation_database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            result = _executor().execute_for_transition(
                session,
                _principal(),
                _transition(session, "ordinary"),
                "workspace:42:ordinary",
            )
            assert result is None
            deal = session.get(Deal, "ordinary")
            assert deal is not None and deal.responsible_id == "actor"

        with Session(engine) as session:
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            assert session.scalar(
                select(CrmActivityEvent).where(CrmActivityEvent.deal_id == "ordinary")
            ) is None
    finally:
        engine.dispose()


def test_missing_billing_target_records_redacted_failure_without_reassignment(
    deal_automation_database_url: str,
) -> None:
    engine = create_engine(deal_automation_database_url, poolclass=NullPool)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            session.execute(
                text("UPDATE crm_users SET status = 'Inativo' WHERE id = 'u-billing'")
            )
            result = _executor().execute_for_transition(
                session,
                _principal(),
                _transition(session, "missing-target"),
                "workspace:42:missing-target",
            )
            assert result is not None
            assert result.result == "failure"
            assert result.failure_code == "billing_target_unavailable"
            assert result.actions == ()
            assert set(result.details()) == {
                "automationKey",
                "automationName",
                "result",
                "actions",
                "failureCode",
            }
            deal = session.get(Deal, "missing-target")
            assert deal is not None and deal.responsible_id == "actor"
            session.execute(text("UPDATE crm_users SET status = 'Ativo' WHERE id = 'u-billing'"))
    finally:
        engine.dispose()


def test_outer_transaction_rollback_removes_assignment_notifications_and_event(
    deal_automation_database_url: str,
) -> None:
    engine = create_engine(deal_automation_database_url, poolclass=NullPool)
    try:
        with pytest.raises(RuntimeError, match="injected rollback"):
            with Session(engine) as session, session.begin():
                session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
                result = _executor().execute_for_transition(
                    session,
                    _principal(),
                    _transition(session, "rollback"),
                    "workspace:42:rollback",
                )
                assert result is not None and result.result == "success"
                raise RuntimeError("injected rollback")

        with Session(engine) as session:
            session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
            deal = session.get(Deal, "rollback")
            assert deal is not None
            assert (deal.responsible_id, deal.team_id) == ("actor", "sales")
            assert session.scalar(
                select(CrmActivityEvent).where(CrmActivityEvent.deal_id == "rollback")
            ) is None
            assert session.scalar(
                select(Notification).where(
                    Notification.payload["dealId"].astext == "rollback"
                )
            ) is None
    finally:
        engine.dispose()
