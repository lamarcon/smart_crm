from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.models import AccountActionToken, CrmUser
from app.repositories.account_actions import AccountActionRepository


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "b4e2c9a7d6f1"
WORKSPACE_ID = "default"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def account_action_database_url() -> str:
    database_name = f"account_action_repository_{uuid.uuid4().hex}"
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


def _set_workspace(session: Session) -> None:
    session.execute(
        text("SELECT set_config('smartcrm.workspace_id', :workspace_id, true)"),
        {"workspace_id": WORKSPACE_ID},
    )


def _seed_user(session: Session, user_id: str) -> CrmUser:
    user = CrmUser(
        id=user_id,
        workspace_id=WORKSPACE_ID,
        name=user_id,
        email=f"{user_id}@example.test",
        normalized_email=f"{user_id}@example.test",
        auth_enabled=False,
        auth_version=0,
        job_title="",
        role="Vendedor",
        status="Pendente",
        payload={},
    )
    session.add(user)
    session.flush()
    return user


@contextmanager
def repository_scope(database_url: str, user_id: str):
    engine = create_engine(database_url, poolclass=NullPool)
    session = Session(bind=engine, expire_on_commit=False)
    try:
        with session.begin():
            _set_workspace(session)
            _seed_user(session, user_id)
            yield AccountActionRepository(session, WORKSPACE_ID), session
    finally:
        session.close()
        engine.dispose()


def test_issue_and_resend_invalidate_the_predecessor_under_the_same_user_purpose(
    account_action_database_url: str,
) -> None:
    user_id = f"action-user-{uuid.uuid4().hex}"
    with repository_scope(account_action_database_url, user_id) as (repository, session):
        first = repository.create_token(
            user_id=user_id,
            purpose="invitation",
            token_digest="a" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_by_user_id=user_id,
            now=NOW,
        )
        second = repository.create_token(
            user_id=user_id,
            purpose="invitation",
            token_digest="b" * 64,
            expires_at=NOW + timedelta(hours=2),
            created_by_user_id=user_id,
            now=NOW + timedelta(minutes=1),
        )

        tokens = session.scalars(
            select(AccountActionToken)
            .where(AccountActionToken.user_id == user_id)
            .order_by(AccountActionToken.created_at.asc())
        ).all()
        assert [token.id for token in tokens] == [first.id, second.id]
        assert (first.invalidated_at, first.invalidation_reason) == (
            NOW + timedelta(minutes=1),
            "replaced",
        )
        assert second.invalidated_at is None
        assert second.delivery_status == "pending"


def test_lookup_rejects_expiry_cross_purpose_and_replay(
    account_action_database_url: str,
) -> None:
    user_id = f"action-user-{uuid.uuid4().hex}"
    digest = "c" * 64
    expired_digest = "d" * 64
    with repository_scope(account_action_database_url, user_id) as (repository, _session):
        repository.create_token(
            user_id=user_id,
            purpose="invitation",
            token_digest=digest,
            expires_at=NOW + timedelta(hours=1),
            created_by_user_id=user_id,
            now=NOW,
        )
        repository.create_token(
            user_id=user_id,
            purpose="password_reset",
            token_digest=expired_digest,
            expires_at=NOW - timedelta(seconds=1),
            created_by_user_id=None,
            now=NOW,
        )

        assert repository.lock_valid_token("password_reset", digest, NOW) is None
        assert repository.lock_valid_token("password_reset", expired_digest, NOW) is None
        consumed = repository.consume_token("invitation", digest, NOW)
        assert consumed is not None and consumed.consumed_at == NOW
        assert repository.consume_token("invitation", digest, NOW) is None


def test_cancel_invalidates_only_live_tokens_for_the_selected_purpose(
    account_action_database_url: str,
) -> None:
    user_id = f"action-user-{uuid.uuid4().hex}"
    with repository_scope(account_action_database_url, user_id) as (repository, _session):
        invitation = repository.create_token(
            user_id=user_id,
            purpose="invitation",
            token_digest="e" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_by_user_id=user_id,
            now=NOW,
        )
        reset = repository.create_token(
            user_id=user_id,
            purpose="password_reset",
            token_digest="f" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_by_user_id=None,
            now=NOW,
        )

        assert repository.invalidate_active(
            user_id, "invitation", "cancelled", NOW
        ) == 1
        assert (invitation.invalidated_at, invitation.invalidation_reason) == (
            NOW,
            "cancelled",
        )
        assert reset.invalidated_at is None


def test_delivery_failure_preserves_failure_metadata_and_invalidates_the_token(
    account_action_database_url: str,
) -> None:
    user_id = f"action-user-{uuid.uuid4().hex}"
    with repository_scope(account_action_database_url, user_id) as (repository, _session):
        token = repository.create_token(
            user_id=user_id,
            purpose="invitation",
            token_digest="1" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_by_user_id=user_id,
            now=NOW,
        )

        repository.mark_delivery(
            token.id,
            status="failed",
            failure_code="recipient_rejected",
            now=NOW + timedelta(seconds=5),
        )

        assert token.delivery_status == "failed"
        assert token.delivery_attempted_at == NOW + timedelta(seconds=5)
        assert token.delivery_failure_code == "recipient_rejected"
        assert token.invalidated_at == NOW + timedelta(seconds=5)
        assert token.invalidation_reason == "delivery_failed"
        assert repository.lock_valid_token("invitation", "1" * 64, NOW) is None


def test_concurrent_consumption_has_exactly_one_winner(
    account_action_database_url: str,
) -> None:
    user_id = f"action-user-{uuid.uuid4().hex}"
    digest = "2" * 64
    with repository_scope(account_action_database_url, user_id) as (repository, _session):
        repository.create_token(
            user_id=user_id,
            purpose="password_reset",
            token_digest=digest,
            expires_at=NOW + timedelta(hours=1),
            created_by_user_id=None,
            now=NOW,
        )

    barrier = threading.Barrier(2)

    def consume() -> bool:
        engine = create_engine(account_action_database_url, poolclass=NullPool)
        session = Session(bind=engine, expire_on_commit=False)
        try:
            with session.begin():
                _set_workspace(session)
                repository = AccountActionRepository(session, WORKSPACE_ID)
                barrier.wait(timeout=5)
                return repository.consume_token(
                    "password_reset", digest, NOW
                ) is not None
        finally:
            session.close()
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: consume(), range(2)))

    assert sorted(outcomes) == [False, True]


def test_concurrent_issue_leaves_exactly_one_live_token(
    account_action_database_url: str,
) -> None:
    user_id = f"action-user-{uuid.uuid4().hex}"
    with repository_scope(account_action_database_url, user_id):
        pass

    barrier = threading.Barrier(2)

    def issue(digest: str) -> None:
        engine = create_engine(account_action_database_url, poolclass=NullPool)
        session = Session(bind=engine, expire_on_commit=False)
        try:
            with session.begin():
                _set_workspace(session)
                repository = AccountActionRepository(session, WORKSPACE_ID)
                barrier.wait(timeout=5)
                repository.create_token(
                    user_id=user_id,
                    purpose="invitation",
                    token_digest=digest,
                    expires_at=NOW + timedelta(hours=1),
                    created_by_user_id=user_id,
                    now=NOW,
                )
        finally:
            session.close()
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(issue, ("3" * 64, "4" * 64)))

    engine = create_engine(account_action_database_url, poolclass=NullPool)
    session = Session(bind=engine)
    try:
        with session.begin():
            _set_workspace(session)
            tokens = session.scalars(
                select(AccountActionToken).where(
                    AccountActionToken.user_id == user_id
                )
            ).all()
            live = [token for token in tokens if token.invalidated_at is None]
            replaced = [token for token in tokens if token.invalidation_reason == "replaced"]
            assert len(tokens) == 2
            assert len(live) == 1
            assert len(replaced) == 1
    finally:
        session.close()
        engine.dispose()
