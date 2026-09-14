from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError

from app.control_database import (
    ControlConfigurationError,
    ControlDatabase,
    ControlDatabaseSettings,
    ControlRepository,
    InvalidTenantTransitionError,
    SecurityEventRedactionError,
)
from app.control_models import AuthSession, ControlBase, ControlTenant, LoginThrottle, SecurityEvent


TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def control_database():
    admin_engine = create_engine(TEST_DATABASE_URL)
    schema = f"control_repository_{uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=8,
        max_overflow=4,
    )
    ControlBase.metadata.create_all(engine)
    database = ControlDatabase(engine=engine)
    try:
        yield database
    finally:
        database.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def create_tenant(repository: ControlRepository, slug: str = "cliente-a") -> ControlTenant:
    return repository.create_tenant(
        tenant_id=uuid4(),
        slug=slug,
        display_name=f"Empresa {slug}",
        secret_ref=f"db-{slug}",
        expected_tenant_revision="tenant-head",
    )


def create_session(repository: ControlRepository, tenant: ControlTenant, token: str, *, expired: bool = False) -> AuthSession:
    return repository.create_session(
        token_digest=token,
        tenant_id=tenant.id,
        user_id="user-1",
        auth_version=3,
        created_at=NOW - timedelta(hours=13) if expired else NOW,
        last_seen_at=NOW - timedelta(hours=1) if expired else NOW,
        idle_expires_at=NOW - timedelta(minutes=1) if expired else NOW + timedelta(minutes=30),
        absolute_expires_at=NOW - timedelta(minutes=1) if expired else NOW + timedelta(hours=12),
        correlation_digest="a" * 64,
    )


def test_control_database_requires_explicit_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMART_CRM_CONTROL_DATABASE_URL", raising=False)

    with pytest.raises(ControlConfigurationError, match="SMART_CRM_CONTROL_DATABASE_URL"):
        ControlDatabaseSettings.from_env()


def test_control_settings_repr_redacts_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = "postgresql+psycopg://control:plain-secret@127.0.0.1/control"
    monkeypatch.setenv("SMART_CRM_CONTROL_DATABASE_URL", dsn)

    settings = ControlDatabaseSettings.from_env()

    assert settings.database_url == dsn
    assert "plain-secret" not in repr(settings)


def test_tenant_directory_enforces_unique_slug(control_database: ControlDatabase) -> None:
    with control_database.session_scope() as session:
        first = create_tenant(ControlRepository(session))
        first_id = first.id

    with pytest.raises(IntegrityError):
        with control_database.session_scope() as session:
            create_tenant(ControlRepository(session))

    with control_database.session_scope() as session:
        found = ControlRepository(session).find_tenant_by_slug("cliente-a")
        assert found is not None
        assert found.id == first_id


def test_tenant_transitions_follow_provisioning_state_machine(control_database: ControlDatabase) -> None:
    with control_database.session_scope() as session:
        tenant = create_tenant(ControlRepository(session))
        tenant_id = tenant.id

    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        active = repository.transition_tenant(tenant_id, "active", activated_at=NOW)
        assert active.status == "active"
        assert active.activated_at == NOW

    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        with pytest.raises(InvalidTenantTransitionError):
            repository.transition_tenant(tenant_id, "failed")


def test_active_session_load_rejects_expired_and_revoked_rows(control_database: ControlDatabase) -> None:
    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        tenant = create_tenant(repository)
        create_session(repository, tenant, "1" * 64)
        create_session(repository, tenant, "2" * 64, expired=True)

    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        assert repository.load_active_session("1" * 64, now=NOW) is not None
        assert repository.load_active_session("2" * 64, now=NOW) is None
        assert repository.revoke_session("1" * 64, reason="logout", revoked_at=NOW) is True

    with control_database.session_scope() as session:
        assert ControlRepository(session).load_active_session("1" * 64, now=NOW) is None


def test_revoke_user_sessions_affects_only_selected_tenant_user(control_database: ControlDatabase) -> None:
    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        tenant_a = create_tenant(repository)
        tenant_b = create_tenant(repository, "cliente-b")
        create_session(repository, tenant_a, "a" * 64)
        create_session(repository, tenant_a, "b" * 64)
        create_session(repository, tenant_b, "c" * 64)

    with control_database.session_scope() as session:
        count = ControlRepository(session).revoke_user_sessions(
            tenant_a.id, "user-1", reason="auth_changed", revoked_at=NOW
        )
        assert count == 2

    with control_database.session_scope() as session:
        remaining = ControlRepository(session).load_active_session("c" * 64, now=NOW)
        assert remaining is not None
        assert remaining.tenant_id == tenant_b.id


def test_cleanup_deletes_only_expired_sessions(control_database: ControlDatabase) -> None:
    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        tenant = create_tenant(repository)
        create_session(repository, tenant, "a" * 64)
        create_session(repository, tenant, "b" * 64, expired=True)

    with control_database.session_scope() as session:
        deleted = ControlRepository(session).cleanup_expired_sessions(now=NOW)
        assert deleted == 1

    with control_database.session_scope() as session:
        digests = set(session.scalars(select(AuthSession.token_digest)))
        assert digests == {"a" * 64}


def test_throttle_blocks_at_configured_limit(control_database: ControlDatabase) -> None:
    results = []
    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        for _ in range(6):
            results.append(
                repository.record_login_failure(
                    "account", "d" * 64, now=NOW, limit=5,
                    window=timedelta(minutes=15), block_for=timedelta(minutes=15),
                )
            )

    assert [result.blocked for result in results] == [False, False, False, False, True, True]
    assert results[-1].failure_count == 5
    assert results[-1].blocked_until == NOW + timedelta(minutes=15)


def test_concurrent_throttle_updates_are_serialized(control_database: ControlDatabase) -> None:
    workers = 6
    barrier = Barrier(workers)

    def fail_login() -> bool:
        barrier.wait()
        with control_database.session_scope() as session:
            result = ControlRepository(session).record_login_failure(
                "ip", "e" * 64, now=NOW, limit=5,
                window=timedelta(minutes=15), block_for=timedelta(minutes=15),
            )
            return result.blocked

    with ThreadPoolExecutor(max_workers=workers) as executor:
        blocked = list(executor.map(lambda _index: fail_login(), range(workers)))

    with control_database.session_scope() as session:
        throttle = session.get(LoginThrottle, {"bucket_type": "ip", "subject_digest": "e" * 64})
        assert throttle is not None
        assert throttle.failure_count == 5
        assert sum(blocked) == 2


def test_throttle_window_resets_after_expiry(control_database: ControlDatabase) -> None:
    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        repository.record_login_failure(
            "account", "f" * 64, now=NOW, limit=5,
            window=timedelta(minutes=15), block_for=timedelta(minutes=15),
        )

    later = NOW + timedelta(minutes=16)
    with control_database.session_scope() as session:
        result = ControlRepository(session).record_login_failure(
            "account", "f" * 64, now=later, limit=5,
            window=timedelta(minutes=15), block_for=timedelta(minutes=15),
        )
        assert result.failure_count == 1
        assert result.blocked is False


def test_security_event_accepts_only_redacted_codes(control_database: ControlDatabase) -> None:
    with control_database.session_scope() as session:
        repository = ControlRepository(session)
        tenant = create_tenant(repository)
        event = repository.append_security_event(
            event_type="login.failed",
            tenant_id=tenant.id,
            user_id="user-1",
            correlation_digest="a" * 64,
            outcome_code="invalid_credentials",
            occurred_at=NOW,
        )
        assert event.outcome_code == "invalid_credentials"

    with pytest.raises(SecurityEventRedactionError):
        with control_database.session_scope() as session:
            ControlRepository(session).append_security_event(
                event_type="login.failed",
                tenant_id=None,
                user_id=None,
                correlation_digest="b" * 64,
                outcome_code="password=plain-secret",
                occurred_at=NOW,
            )

    with control_database.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(SecurityEvent)) == 1


def test_session_scope_rolls_back_failed_control_transaction(control_database: ControlDatabase) -> None:
    with pytest.raises(RuntimeError, match="rollback"):
        with control_database.session_scope() as session:
            create_tenant(ControlRepository(session), "rollback-tenant")
            raise RuntimeError("rollback")

    with control_database.session_scope() as session:
        assert ControlRepository(session).find_tenant_by_slug("rollback-tenant") is None
