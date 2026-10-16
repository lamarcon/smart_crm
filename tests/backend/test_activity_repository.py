from __future__ import annotations

import inspect
import os
import re
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

from app.models import CrmActivityEvent
from app.repositories.activity import (
    ActivityRepository,
    ActivityScopeError,
    NewActivityEvent,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "e1c4a7b9d2f6"
WORKSPACE_ID = "default"
ACTOR_ID = "activity-admin"
DEAL_ID = "activity-deal"
COMPANY_ID = "activity-company"
OCCURRED_AT = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    # Load the INI once, then suppress Alembic's process-wide fileConfig call.
    # Repository tests run before API logging tests and must not replace pytest's
    # capture handlers or disable the application logger.
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def activity_database_url() -> str:
    database_name = f"activity_repository_{uuid.uuid4().hex}"
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


def _set_workspace(session: Session, workspace_id: str) -> None:
    session.execute(
        text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
        {"workspace_id": workspace_id},
    )


def _seed_default_subjects(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO crm_users "
            "(id, workspace_id, name, email, job_title, role, status, payload) "
            "VALUES (:id, 'default', 'Activity Admin', 'activity@example.test', '', "
            "'Administrador', 'Ativo', '{}'::jsonb)"
        ),
        {"id": ACTOR_ID},
    )
    session.execute(
        text(
            "INSERT INTO companies "
            "(id, workspace_id, owner_id, name, city, segment, phone, payload) "
            "VALUES (:id, 'default', :actor, 'Activity Company', '', '', '', '{}'::jsonb)"
        ),
        {"id": COMPANY_ID, "actor": ACTOR_ID},
    )
    pipeline = session.execute(
        text(
            "SELECT p.id AS pipeline_id, s.id AS stage_id, s.name AS stage_name "
            "FROM deal_pipelines p JOIN deal_pipeline_stages s "
            "ON s.pipeline_id = p.id AND s.workspace_id = p.workspace_id "
            "WHERE p.workspace_id = 'default' AND p.is_default "
            "ORDER BY s.position LIMIT 1"
        )
    ).one()
    session.execute(
        text(
            "INSERT INTO deals "
            "(id, workspace_id, company_id, responsible_id, title, company_text, "
            "contact_text, amount, stage, pipeline_id, stage_id, payload) "
            "VALUES (:id, 'default', :company, :actor, 'Activity Deal', "
            "'Activity Company', '', 10, :stage_name, :pipeline_id, :stage_id, '{}'::jsonb)"
        ),
        {
            "id": DEAL_ID,
            "company": COMPANY_ID,
            "actor": ACTOR_ID,
            "stage_name": pipeline.stage_name,
            "pipeline_id": pipeline.pipeline_id,
            "stage_id": pipeline.stage_id,
        },
    )


@contextmanager
def repository_scope(database_url: str):
    engine = create_engine(database_url, poolclass=NullPool)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        _set_workspace(session, WORKSPACE_ID)
        _seed_default_subjects(session)
        yield ActivityRepository(session, WORKSPACE_ID), session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _deal_event(
    key: str,
    *,
    category: str = "movement",
    occurred_at: datetime = OCCURRED_AT,
    summary: str | None = None,
) -> NewActivityEvent:
    return NewActivityEvent(
        deal_id=DEAL_ID,
        company_id=None,
        category=category,
        event_type=f"deal.{category}",
        actor_user_id=ACTOR_ID,
        actor_name="Activity Admin",
        summary=summary or key,
        details={"key": key},
        dedupe_key=key,
        occurred_at=occurred_at,
    )


def _company_event(key: str) -> NewActivityEvent:
    return NewActivityEvent(
        deal_id=None,
        company_id=COMPANY_ID,
        category="change",
        event_type="company.updated",
        actor_user_id=ACTOR_ID,
        actor_name="Activity Admin",
        summary=key,
        details={"key": key},
        dedupe_key=key,
        occurred_at=OCCURRED_AT,
    )


def test_repository_rejects_missing_and_mismatched_workspace_context(
    activity_database_url: str,
) -> None:
    engine = create_engine(activity_database_url, poolclass=NullPool)
    session = Session(bind=engine)
    try:
        session.execute(text("RESET smartcrm.workspace_id"))
        with pytest.raises(ActivityScopeError, match="workspace context unavailable"):
            ActivityRepository(session, WORKSPACE_ID)
        session.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', false)"))
        with pytest.raises(ActivityScopeError, match="workspace context mismatch"):
            ActivityRepository(session, "foreign-workspace")
    finally:
        session.close()
        engine.dispose()


def test_append_is_typed_idempotent_and_supports_batches(activity_database_url: str) -> None:
    assert "workspace_id" not in inspect.signature(NewActivityEvent).parameters
    with repository_scope(activity_database_url) as (repository, session):
        first = repository.append(_deal_event("deal:one"))
        repeated = repository.append(_deal_event("deal:one", summary="must not replace"))
        company, second = repository.append_many(
            (_company_event("company:one"), _deal_event("deal:two", category="observation"))
        )

        assert repeated.id == first.id
        assert repeated.summary == "deal:one"
        assert repository.find_by_dedupe_key("deal:one").id == first.id
        assert company.company_id == COMPANY_ID and company.deal_id is None
        assert second.deal_id == DEAL_ID and second.company_id is None
        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 3


def test_deal_paging_is_stable_for_51_plus_equal_timestamps_and_categories(
    activity_database_url: str,
) -> None:
    with repository_scope(activity_database_url) as (repository, _session):
        events = tuple(
            _deal_event(
                f"deal:{index:02d}",
                category="observation" if index % 10 == 0 else "movement",
            )
            for index in range(53)
        )
        inserted = repository.append_many(events)

        first = repository.list_for_deal(DEAL_ID, category=None, cursor=None, limit=50)
        second = repository.list_for_deal(
            DEAL_ID, category=None, cursor=first.next_cursor, limit=50
        )
        movements = repository.list_for_deal(
            DEAL_ID, category="movement", cursor=None, limit=50
        )

        expected = sorted((event.id for event in inserted), reverse=True)
        returned = [event.id for event in (*first.items, *second.items)]
        assert returned == expected
        assert len(first.items) == 50 and len(second.items) == 3
        assert set(event.id for event in first.items).isdisjoint(
            event.id for event in second.items
        )
        assert first.next_cursor is not None
        assert re.fullmatch(r"[A-Za-z0-9_-]+", first.next_cursor)
        assert "2026" not in first.next_cursor and DEAL_ID not in first.next_cursor
        assert second.next_cursor is None
        assert len(movements.items) == 47
        assert all(event.category == "movement" for event in movements.items)


def test_company_timeline_does_not_include_linked_deal_events(activity_database_url: str) -> None:
    with repository_scope(activity_database_url) as (repository, _session):
        company = repository.append(_company_event("company:own"))
        repository.append(_deal_event("deal:linked"))

        page = repository.list_for_company(
            COMPANY_ID, category=None, cursor=None, limit=50
        )

        assert [event.id for event in page.items] == [company.id]
        assert page.next_cursor is None


def test_repository_and_rls_hide_foreign_or_missing_workspace_scope(
    activity_database_url: str,
) -> None:
    with repository_scope(activity_database_url) as (repository, session):
        own = repository.append(_company_event("company:own"))
        _set_workspace(session, "foreign")
        session.execute(text("INSERT INTO workspaces (id, version) VALUES ('foreign', 0)"))
        session.execute(
            text(
                "INSERT INTO companies "
                "(id, workspace_id, name, city, segment, phone, payload) "
                "VALUES ('foreign-company', 'foreign', 'Foreign', '', '', '', '{}'::jsonb)"
            )
        )
        session.execute(
            text(
                "INSERT INTO crm_activity_events "
                "(workspace_id, company_id, category, event_type, actor_name, summary, "
                "details, dedupe_key, occurred_at) VALUES "
                "('foreign', 'foreign-company', 'change', 'company.created', 'System', "
                "'Foreign', '{}'::jsonb, 'foreign:event', :occurred_at)"
            ),
            {"occurred_at": OCCURRED_AT},
        )
        _set_workspace(session, WORKSPACE_ID)

        assert repository.list_for_company(
            "foreign-company", category=None, cursor=None, limit=50
        ).items == ()
        assert [event.id for event in repository.list_for_company(
            COMPANY_ID, category=None, cursor=None, limit=50
        ).items] == [own.id]

def test_transaction_rollback_removes_appended_events(activity_database_url: str) -> None:
    with repository_scope(activity_database_url) as (repository, session):
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                repository.append(_deal_event("deal:rollback"))
                session.execute(
                    text(
                        "INSERT INTO crm_activity_events "
                        "(workspace_id, deal_id, category, event_type, actor_user_id, "
                        "actor_name, summary, details, dedupe_key, occurred_at) VALUES "
                        "('default', :deal_id, 'movement', 'deal.invalid', 'missing-user', "
                        "'Invalid', 'Invalid', '{}'::jsonb, 'invalid-fk', :occurred_at)"
                    ),
                    {"deal_id": DEAL_ID, "occurred_at": OCCURRED_AT},
                )

        assert repository.find_by_dedupe_key("deal:rollback") is None
        assert session.scalar(select(func.count()).select_from(CrmActivityEvent)) == 0


def test_repository_exposes_no_event_update_or_delete_operation() -> None:
    source = inspect.getsource(ActivityRepository)

    assert "update_event" not in source
    assert "delete_event" not in source
    assert not hasattr(ActivityRepository, "update")
    assert not hasattr(ActivityRepository, "delete")
