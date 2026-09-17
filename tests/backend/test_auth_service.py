from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.control_database import ThrottleResult
from app.schemas import LOGIN_FAILURE_MESSAGE
from app.security.passwords import digest_session_token, hash_password
from app.services.auth import (
    AuthenticationError,
    AuthService,
    SessionContext,
    TenantUserIdentity,
)
from app.tenant_database import TenantUnavailableError


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


class FakeControlDatabase:
    def __init__(self, repository) -> None:  # noqa: ANN001
        self.repository = repository

    @contextmanager
    def session_scope(self):  # noqa: ANN201
        yield self.repository


class FakeControlRepository:
    def __init__(self) -> None:
        self.tenants: dict[str, SimpleNamespace] = {}
        self.sessions: dict[str, SimpleNamespace] = {}
        self.throttles: dict[tuple[str, str], SimpleNamespace] = {}
        self.events: list[dict] = []
        self.created_sessions: list[dict] = []
        self.revocations: list[tuple] = []
        self.failure_limits: list[tuple[str, int]] = []
        self.session = self

    def find_tenant_by_slug(self, slug: str):  # noqa: ANN201
        return self.tenants.get(slug)

    def get_tenant(self, tenant_id: UUID):  # noqa: ANN201
        return next((tenant for tenant in self.tenants.values() if tenant.id == tenant_id), None)

    def get(self, _model, key):  # noqa: ANN001, ANN201
        return self.throttles.get((key["bucket_type"], key["subject_digest"]))

    def record_login_failure(self, bucket_type: str, subject_digest: str, *, now, limit, window, block_for):  # noqa: ANN001, ANN201
        self.failure_limits.append((bucket_type, limit))
        key = (bucket_type, subject_digest)
        row = self.throttles.get(key)
        if row is None or row.window_started_at + window <= now:
            row = SimpleNamespace(failure_count=0, window_started_at=now, blocked_until=None)
            self.throttles[key] = row
        if row.blocked_until is None or row.blocked_until <= now:
            row.failure_count = min(row.failure_count + 1, limit)
            if row.failure_count >= limit:
                row.blocked_until = now + block_for
        return ThrottleResult(row.failure_count, bool(row.blocked_until and row.blocked_until > now), row.blocked_until)

    def clear_login_throttle(self, bucket_type: str, subject_digest: str) -> bool:
        return self.throttles.pop((bucket_type, subject_digest), None) is not None

    def create_session(self, **values):  # noqa: ANN003, ANN201
        row = SimpleNamespace(**values, revoked_at=None)
        self.sessions[values["token_digest"]] = row
        self.created_sessions.append(values)
        return row

    def load_active_session(self, token_digest: str, *, now):  # noqa: ANN001, ANN201
        row = self.sessions.get(token_digest)
        if row is None or row.revoked_at is not None:
            return None
        if row.idle_expires_at <= now or row.absolute_expires_at <= now:
            return None
        return row

    def touch_session(self, token_digest: str, *, now, idle_expires_at):  # noqa: ANN001, ANN201
        row = self.sessions[token_digest]
        row.last_seen_at = now
        row.idle_expires_at = idle_expires_at
        return True

    def revoke_session(self, token_digest: str, *, reason: str, revoked_at):  # noqa: ANN001, ANN201
        row = self.sessions.get(token_digest)
        if row is None:
            return False
        row.revoked_at = revoked_at
        self.revocations.append((token_digest, reason))
        return True

    def revoke_user_sessions(self, tenant_id: UUID, user_id: str, *, reason: str, revoked_at):  # noqa: ANN001, ANN201
        count = 0
        for digest, row in self.sessions.items():
            if row.tenant_id == tenant_id and row.user_id == user_id and row.revoked_at is None:
                row.revoked_at = revoked_at
                self.revocations.append((digest, reason))
                count += 1
        return count

    def append_security_event(self, **values):  # noqa: ANN003, ANN201
        self.events.append(values)
        return SimpleNamespace(**values)


class FakeRouter:
    def __init__(self) -> None:
        self.databases: dict[UUID, dict[str, TenantUserIdentity]] = {}
        self.calls: list[UUID] = []
        self.unavailable: set[UUID] = set()

    @contextmanager
    def tenant_session_scope(self, tenant_id: UUID):  # noqa: ANN201
        self.calls.append(tenant_id)
        if tenant_id in self.unavailable:
            raise TenantUnavailableError("tenant database unavailable")
        yield SimpleNamespace(users=self.databases[tenant_id])


def load_by_email(session, email: str):  # noqa: ANN001, ANN201
    return session.users.get(email)


def load_by_id(session, user_id: str):  # noqa: ANN001, ANN201
    return next((user for user in session.users.values() if user.user_id == user_id), None)


@pytest.fixture
def auth_setup():  # noqa: ANN201
    repository = FakeControlRepository()
    router = FakeRouter()
    tenant_a = SimpleNamespace(id=uuid4(), slug="cliente-a", display_name="Cliente A", status="active")
    tenant_b = SimpleNamespace(id=uuid4(), slug="cliente-b", display_name="Cliente B", status="active")
    repository.tenants = {tenant_a.slug: tenant_a, tenant_b.slug: tenant_b}
    router.databases = {
        tenant_a.id: {
            "same@example.test": TenantUserIdentity(
                user_id="user-a", workspace_id="default", name="Ana", email="same@example.test",
                password_hash=hash_password("tenant a secure password"), auth_enabled=True,
                auth_version=2, role="Administrador", team_id="team-a", status="Ativo",
            )
        },
        tenant_b.id: {
            "same@example.test": TenantUserIdentity(
                user_id="user-b", workspace_id="default", name="Bia", email="same@example.test",
                password_hash=hash_password("tenant b secure password"), auth_enabled=True,
                auth_version=4, role="Gestor", team_id="team-b", status="Ativo",
            )
        },
    }
    service = AuthService(
        FakeControlDatabase(repository),
        router,
        repository_factory=lambda value: value,
        user_by_email_loader=load_by_email,
        user_by_id_loader=load_by_id,
    )
    return service, repository, router, tenant_a, tenant_b


def login(service: AuthService, slug: str = "cliente-a", password: str = "tenant a secure password"):  # noqa: ANN201
    return service.login(slug, "same@example.test", password, "192.0.2.10", now=NOW)


def test_locate_returns_only_active_tenant(auth_setup) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, tenant_b = auth_setup
    tenant_b.status = "inactive"

    assert service.locate_tenant("cliente-a").display_name == "Cliente A"
    assert service.locate_tenant("cliente-b") is None
    assert service.locate_tenant("missing") is None


def test_same_email_authenticates_only_against_slug_selected_database(auth_setup) -> None:  # noqa: ANN001
    service, _repository, router, tenant_a, tenant_b = auth_setup

    result_a = login(service)
    result_b = login(service, "cliente-b", "tenant b secure password")

    assert result_a.context.principal.tenant_id == tenant_a.id
    assert result_a.context.principal.user_id == "user-a"
    assert result_b.context.principal.tenant_id == tenant_b.id
    assert result_b.context.principal.user_id == "user-b"
    assert router.calls == [tenant_a.id, tenant_b.id]


def test_password_from_other_tenant_never_authenticates(auth_setup) -> None:  # noqa: ANN001
    service, repository, router, tenant_a, _tenant_b = auth_setup

    with pytest.raises(AuthenticationError, match=LOGIN_FAILURE_MESSAGE):
        login(service, "cliente-a", "tenant b secure password")

    assert router.calls == [tenant_a.id]
    assert repository.created_sessions == []


@pytest.mark.parametrize("slug", ["missing", "cliente-inexistente"])
def test_unknown_tenant_uses_dummy_verification(auth_setup, monkeypatch: pytest.MonkeyPatch, slug: str) -> None:  # noqa: ANN001
    service, repository, router, _tenant_a, _tenant_b = auth_setup
    calls: list[tuple[str | None, str]] = []
    monkeypatch.setattr("app.services.auth.verify_or_dummy", lambda encoded, password: calls.append((encoded, password)) or False)

    with pytest.raises(AuthenticationError, match=LOGIN_FAILURE_MESSAGE):
        login(service, slug)

    assert calls == [(None, "tenant a secure password")]
    assert router.calls == []
    assert repository.created_sessions == []


def test_tenant_outage_is_publicly_identical_and_has_no_fallback(auth_setup, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    service, repository, router, tenant_a, tenant_b = auth_setup
    router.unavailable.add(tenant_a.id)
    calls: list[str | None] = []
    monkeypatch.setattr("app.services.auth.verify_or_dummy", lambda encoded, _password: calls.append(encoded) or False)

    with pytest.raises(AuthenticationError, match=LOGIN_FAILURE_MESSAGE):
        login(service)

    assert router.calls == [tenant_a.id]
    assert tenant_b.id not in router.calls
    assert calls == [None]
    assert repository.created_sessions == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("auth_enabled", False), ("status", "Inativo"), ("password_hash", None)],
)
def test_disabled_user_states_share_generic_failure(auth_setup, field: str, value) -> None:  # noqa: ANN001
    service, repository, _router, tenant_a, _tenant_b = auth_setup
    user = next(iter(service._router.databases[tenant_a.id].values()))
    service._router.databases[tenant_a.id][user.email] = TenantUserIdentity(
        **{**user.__dict__, field: value}
    )

    with pytest.raises(AuthenticationError, match=LOGIN_FAILURE_MESSAGE):
        login(service)

    assert repository.created_sessions == []


def test_success_stores_digest_and_linkage_without_password_or_role(auth_setup) -> None:  # noqa: ANN001
    service, repository, _router, tenant_a, _tenant_b = auth_setup

    result = login(service)
    stored = repository.created_sessions[0]

    assert stored["token_digest"] == digest_session_token(result.token)
    assert stored["tenant_id"] == tenant_a.id
    assert stored["user_id"] == "user-a"
    assert stored["auth_version"] == 2
    assert result.token not in repr(stored)
    assert {"password", "password_hash", "role"}.isdisjoint(stored)


def test_success_sets_exact_idle_and_absolute_expiry(auth_setup) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, _tenant_b = auth_setup

    login(service)
    stored = repository.created_sessions[0]

    assert stored["created_at"] == NOW
    assert stored["last_seen_at"] == NOW
    assert stored["idle_expires_at"] == NOW + timedelta(minutes=30)
    assert stored["absolute_expires_at"] == NOW + timedelta(hours=12)


def test_failed_login_records_account_and_ip_limits_and_redacted_event(auth_setup, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, _tenant_b = auth_setup
    monkeypatch.setattr("app.services.auth.verify_or_dummy", lambda _encoded, _password: False)

    with pytest.raises(AuthenticationError):
        login(service, password="wrong password value")

    assert repository.failure_limits == [("account", 5), ("ip", 30)]
    assert repository.events[-1]["event_type"] == "login.failed"
    assert repository.events[-1]["outcome_code"] == "invalid_credentials"
    assert "wrong password value" not in repr(repository.events[-1])


def test_account_bucket_blocks_fifth_failure_with_generic_message(auth_setup, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, _tenant_b = auth_setup
    monkeypatch.setattr("app.services.auth.verify_or_dummy", lambda _encoded, _password: False)

    for _ in range(5):
        with pytest.raises(AuthenticationError, match=LOGIN_FAILURE_MESSAGE):
            login(service, password="wrong password value")

    account = next(row for (kind, _digest), row in repository.throttles.items() if kind == "account")
    assert account.failure_count == 5
    assert account.blocked_until == NOW + timedelta(minutes=15)


def test_concurrent_failures_cannot_advance_account_bucket_past_limit(auth_setup, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, _tenant_b = auth_setup
    monkeypatch.setattr("app.services.auth.verify_or_dummy", lambda _encoded, _password: False)
    workers = 6
    barrier = Barrier(workers)

    def attempt(_index: int) -> str:
        barrier.wait()
        with pytest.raises(AuthenticationError) as error:
            login(service, password="wrong password value")
        return str(error.value)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        messages = list(executor.map(attempt, range(workers)))

    account = next(row for (kind, _digest), row in repository.throttles.items() if kind == "account")
    assert messages == [LOGIN_FAILURE_MESSAGE] * workers
    assert account.failure_count == 5
    assert account.blocked_until == NOW + timedelta(minutes=15)


def test_success_clears_only_account_throttle(auth_setup) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, _tenant_b = auth_setup
    account_digest, ip_digest = service.login_subject_digests("cliente-a", "same@example.test", "192.0.2.10")
    repository.throttles[("account", account_digest)] = SimpleNamespace(
        failure_count=1, window_started_at=NOW, blocked_until=None
    )
    repository.throttles[("ip", ip_digest)] = SimpleNamespace(
        failure_count=1, window_started_at=NOW, blocked_until=None
    )

    login(service)

    assert ("account", account_digest) not in repository.throttles
    assert ("ip", ip_digest) in repository.throttles


def test_current_session_refreshes_idle_ttl_without_exceeding_absolute(auth_setup) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, _tenant_b = auth_setup
    result = login(service)
    row = repository.sessions[digest_session_token(result.token)]
    row.absolute_expires_at = NOW + timedelta(minutes=10)

    context = service.current_session(result.token, now=NOW + timedelta(minutes=1))

    assert isinstance(context, SessionContext)
    assert row.last_seen_at == NOW + timedelta(minutes=1)
    assert row.idle_expires_at == NOW + timedelta(minutes=10)


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_expired_or_revoked_session_is_rejected(auth_setup, state: str) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, _tenant_b = auth_setup
    result = login(service)
    row = repository.sessions[digest_session_token(result.token)]
    if state == "expired":
        row.idle_expires_at = NOW
    else:
        row.revoked_at = NOW

    with pytest.raises(AuthenticationError, match="Sessão inválida"):
        service.current_session(result.token, now=NOW)


def test_auth_version_change_revokes_all_user_sessions(auth_setup) -> None:  # noqa: ANN001
    service, repository, router, tenant_a, _tenant_b = auth_setup
    result = login(service)
    user = router.databases[tenant_a.id]["same@example.test"]
    router.databases[tenant_a.id][user.email] = TenantUserIdentity(
        **{**user.__dict__, "auth_version": user.auth_version + 1}
    )

    with pytest.raises(AuthenticationError, match="Sessão inválida"):
        service.current_session(result.token, now=NOW)

    assert repository.revocations == [(digest_session_token(result.token), "auth_changed")]



def test_explicit_access_change_revokes_all_prior_user_sessions(auth_setup) -> None:  # noqa: ANN001
    service, repository, _router, tenant_a, _tenant_b = auth_setup
    first = login(service)
    second = login(service)

    count = service.revoke_user_sessions(
        tenant_a.id,
        "user-a",
        now=NOW,
        reason="auth_changed",
    )

    assert count == 2
    assert repository.sessions[digest_session_token(first.token)].revoked_at == NOW
    assert repository.sessions[digest_session_token(second.token)].revoked_at == NOW

def test_logout_revokes_only_digest_and_never_records_raw_token(auth_setup) -> None:  # noqa: ANN001
    service, repository, _router, _tenant_a, _tenant_b = auth_setup
    result = login(service)

    assert service.logout(result.token, now=NOW) is True
    assert repository.revocations[-1] == (digest_session_token(result.token), "logout")
    assert result.token not in repr(repository.revocations)
