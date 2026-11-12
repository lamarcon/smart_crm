from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.mail import InMemoryMailSender, MailDeliveryError
from app.models import AccountActionToken, CrmUser
from app.policies import PrincipalScope
from app.services.account_access import (
    INVALID_ACTION_LINK_MESSAGE,
    AccountAccessAuthorizationError,
    AccountAccessService,
    AccountActionLinkInvalidError,
    AccountAlreadyActiveError,
    AccountPasswordPolicyError,
    AccountRequiresReactivationError,
    InvitationCommand,
    PublicActionView,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv(
    "SMART_CRM_TEST_DATABASE_URL",
    "postgresql+psycopg://smartcrm:smartcrm_local_dev@127.0.0.1:5432/smartcrm_test",
)
TENANT_HEAD = "c3d9a1f4b7e2"
WORKSPACE_ID = "default"
TENANT_ID = uuid.UUID("0704e2f5-38f2-440d-9ef2-1d9e91a77508")
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _tenant_config(connection) -> Config:  # noqa: ANN001
    config = Config(str(ROOT / "alembic.ini"))
    config.file_config
    config.config_file_name = None
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="module")
def account_access_database_url() -> str:
    yield from _migrated_tenant_database("account_access_service")


@pytest.fixture(scope="module")
def other_tenant_database_url() -> str:
    yield from _migrated_tenant_database("account_access_other_tenant")


def _migrated_tenant_database(prefix: str):  # noqa: ANN202
    database_name = f"{prefix}_{uuid.uuid4().hex}"
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


class TenantRouter:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.calls = 0
        self._lock = threading.Lock()

    @contextmanager
    def tenant_session_scope(self, tenant_id: uuid.UUID):
        assert tenant_id == TENANT_ID
        with self._lock:
            self.calls += 1
        engine = create_engine(self.database_url, poolclass=NullPool)
        session = Session(bind=engine, expire_on_commit=False)
        try:
            with session.begin():
                _set_workspace(session)
                yield session
        finally:
            session.close()
            engine.dispose()


class ControlDatabaseStub:
    @contextmanager
    def session_scope(self):
        yield object()


class ControlRepositoryStub:
    def __init__(self, _session: object) -> None:
        pass

    def get_tenant(self, tenant_id: uuid.UUID):  # noqa: ANN201
        if tenant_id != TENANT_ID:
            return None
        return SimpleNamespace(
            id=TENANT_ID,
            slug="brbots",
            display_name="BRBots",
            status="active",
        )

    def find_tenant_by_slug(self, slug: str):  # noqa: ANN201
        if slug != "brbots":
            return None
        return self.get_tenant(TENANT_ID)

    def create_session(self, **_values) -> None:  # noqa: ANN003
        raise AssertionError("account access must never create an authenticated session")

    def admit_account_action_request(self, subjects, *, now) -> bool:  # noqa: ANN001
        # Limits are exercised against the real ControlRepository in the T8/T11 tests.
        return True


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, **values):  # noqa: ANN003, ANN201
        self.events.append(values)
        return uuid.uuid4()


class FailingMailSender:
    def __init__(self, code: str = "smtp_recipient_refused") -> None:
        self.code = code
        self.attempts = 0

    def send(self, _message) -> None:  # noqa: ANN001
        self.attempts += 1
        raise MailDeliveryError(self.code)


class CommitCheckingMailSender(InMemoryMailSender):
    def __init__(self, database_url: str, expected_email: str) -> None:
        super().__init__()
        self.database_url = database_url
        self.expected_email = expected_email

    def send(self, message) -> None:  # noqa: ANN001
        engine = create_engine(self.database_url, poolclass=NullPool)
        try:
            with Session(bind=engine) as session, session.begin():
                _set_workspace(session)
                user = session.scalar(
                    select(CrmUser).where(CrmUser.normalized_email == self.expected_email)
                )
                live_tokens = session.scalar(
                    select(func.count())
                    .select_from(AccountActionToken)
                    .where(
                        AccountActionToken.user_id == user.id,
                        AccountActionToken.invalidated_at.is_(None),
                        AccountActionToken.consumed_at.is_(None),
                    )
                )
                assert user.status == "Pendente"
                assert user.auth_enabled is False
                assert live_tokens == 1
        finally:
            engine.dispose()
        super().send(message)


def _principal(actor_id: str, *, role: str = "Administrador") -> PrincipalScope:
    return PrincipalScope(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        user_id=actor_id,
        role=role,
        team_id=None,
        auth_version=1,
    )


def _command(email: str, *, role: str = "Vendedor") -> InvitationCommand:
    return InvitationCommand(
        name="Funcionário Convidado",
        email=email,
        job_title="Comercial",
        team_id=None,
        role=role,
    )


def _seed_user(
    database_url: str,
    *,
    user_id: str,
    email: str,
    role: str,
    status: str,
    auth_enabled: bool,
    password_hash: str | None = None,
) -> None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(bind=engine, expire_on_commit=False) as session, session.begin():
            _set_workspace(session)
            session.add(
                CrmUser(
                    id=user_id,
                    workspace_id=WORKSPACE_ID,
                    name=user_id,
                    email=email,
                    normalized_email=email.lower(),
                    password_hash=password_hash,
                    auth_enabled=auth_enabled,
                    auth_version=1 if auth_enabled else 0,
                    job_title="",
                    role=role,
                    status=status,
                    payload={},
                )
            )
    finally:
        engine.dispose()


def _read_user(database_url: str, email: str) -> CrmUser | None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(bind=engine, expire_on_commit=False) as session, session.begin():
            _set_workspace(session)
            return session.scalar(
                select(CrmUser).where(CrmUser.normalized_email == email.lower())
            )
    finally:
        engine.dispose()


def _read_tokens(database_url: str, user_id: str) -> list[AccountActionToken]:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(bind=engine, expire_on_commit=False) as session, session.begin():
            _set_workspace(session)
            return list(
                session.scalars(
                    select(AccountActionToken)
                    .where(AccountActionToken.user_id == user_id)
                    .order_by(AccountActionToken.created_at.asc())
                ).all()
            )
    finally:
        engine.dispose()


def _service(
    database_url: str,
    mail_sender,
    *,
    audit: RecordingAudit | None = None,
) -> tuple[AccountAccessService, TenantRouter, RecordingAudit]:
    router = TenantRouter(database_url)
    recorder = audit or RecordingAudit()
    return (
        AccountAccessService(
            ControlDatabaseStub(),
            router,
            mail_sender,
            public_origin="https://crm.example.test",
            control_repository_factory=ControlRepositoryStub,
            security_audit=recorder,
            clock=lambda: NOW,
        ),
        router,
        recorder,
    )


def test_invite_creates_one_pending_disabled_user_and_sends_after_commit(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    email = f"new-{uuid.uuid4().hex}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
        password_hash="$argon2id$existing",
    )
    mail = CommitCheckingMailSender(account_access_database_url, email)
    service, _router, audit = _service(account_access_database_url, mail)

    result = service.invite(
        TENANT_ID,
        _principal(actor_id),
        _command(email, role="Administrador"),
        "203.0.113.10",
    )

    user = _read_user(account_access_database_url, email)
    tokens = _read_tokens(account_access_database_url, result.user_id)
    raw_token = mail.messages[0].action_link.split("#token=", 1)[1]
    assert (result.status, result.delivery_status) == ("Pendente", "sent")
    assert (user.id, user.role, user.status) == (
        result.user_id,
        "Administrador",
        "Pendente",
    )
    assert (user.auth_enabled, user.password_hash, user.auth_version) == (False, None, 0)
    assert (tokens[0].delivery_status, tokens[0].expires_at) == (
        "sent",
        NOW + timedelta(hours=48),
    )
    assert tokens[0].token_digest != raw_token
    assert mail.messages[0].subject == "Você foi convidado para o Smart CRM da BRBots"
    assert mail.messages[0].action_link.startswith(
        "https://crm.example.test/brbots/accept-invite#token="
    )
    assert [event["event_type"] for event in audit.events] == [
        "invitation.created",
        "invitation.sent",
    ]
    assert raw_token not in repr(audit.events)


def test_pending_resend_reuses_user_and_replaces_every_previous_invitation(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    email = f"pending-{uuid.uuid4().hex}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    mail = InMemoryMailSender()
    service, _router, audit = _service(account_access_database_url, mail)
    first = service.invite(
        TENANT_ID, _principal(actor_id), _command(email), "203.0.113.11"
    )

    second = service.resend_invitation(
        TENANT_ID, _principal(actor_id), first.user_id, "203.0.113.11"
    )

    tokens = _read_tokens(account_access_database_url, first.user_id)
    assert second.user_id == first.user_id
    assert len(mail.messages) == 2
    assert len(tokens) == 2
    assert (tokens[0].invalidation_reason, tokens[1].delivery_status) == (
        "replaced",
        "sent",
    )
    assert sum(token.invalidated_at is None for token in tokens) == 1
    assert "invitation.resent" in [event["event_type"] for event in audit.events]


def test_delivery_failure_keeps_pending_and_invalidates_undelivered_token(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    email = f"failed-{uuid.uuid4().hex}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    mail = FailingMailSender()
    service, _router, audit = _service(account_access_database_url, mail)

    result = service.invite(
        TENANT_ID, _principal(actor_id), _command(email), "203.0.113.12"
    )

    user = _read_user(account_access_database_url, email)
    token = _read_tokens(account_access_database_url, result.user_id)[0]
    assert (result.delivery_status, user.status, user.auth_enabled) == (
        "failed",
        "Pendente",
        False,
    )
    assert (
        token.delivery_status,
        token.delivery_failure_code,
        token.invalidation_reason,
    ) == ("failed", "smtp_recipient_refused", "delivery_failed")
    assert audit.events[-1]["event_type"] == "invitation.delivery_failed"
    assert audit.events[-1]["outcome_code"] == "smtp_recipient_refused"


def test_cancel_marks_pending_user_cancelled_and_invalidates_all_live_invitations(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    email = f"cancel-{uuid.uuid4().hex}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    mail = InMemoryMailSender()
    service, _router, audit = _service(account_access_database_url, mail)
    invited = service.invite(
        TENANT_ID, _principal(actor_id), _command(email), "203.0.113.13"
    )

    result = service.cancel_invitation(TENANT_ID, _principal(actor_id), invited.user_id)

    user = _read_user(account_access_database_url, email)
    tokens = _read_tokens(account_access_database_url, invited.user_id)
    assert (result.status, user.status, user.auth_enabled) == (
        "Cancelado",
        "Cancelado",
        False,
    )
    assert all(token.invalidated_at is not None for token in tokens)
    assert tokens[-1].invalidation_reason == "cancelled"
    assert audit.events[-1]["event_type"] == "invitation.cancelled"


def test_active_email_is_rejected_without_user_or_mail_change(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    target_id = f"active-{uuid.uuid4().hex}"
    email = f"{target_id}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    _seed_user(
        account_access_database_url,
        user_id=target_id,
        email=email,
        role="Vendedor",
        status="Ativo",
        auth_enabled=True,
        password_hash="$argon2id$unchanged",
    )
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)

    with pytest.raises(AccountAlreadyActiveError):
        service.invite(
            TENANT_ID, _principal(actor_id), _command(email), "203.0.113.14"
        )

    user = _read_user(account_access_database_url, email)
    assert (user.id, user.status, user.password_hash) == (
        target_id,
        "Ativo",
        "$argon2id$unchanged",
    )
    assert mail.messages == []


def test_cancelled_email_reuses_account_and_starts_a_new_pending_invitation(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    target_id = f"cancelled-{uuid.uuid4().hex}"
    email = f"{target_id}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    _seed_user(
        account_access_database_url,
        user_id=target_id,
        email=email,
        role="Assistente",
        status="Cancelado",
        auth_enabled=False,
        password_hash="$argon2id$old",
    )
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)

    result = service.invite(
        TENANT_ID,
        _principal(actor_id),
        _command(email, role="Gestor"),
        "203.0.113.15",
    )

    user = _read_user(account_access_database_url, email)
    assert result.user_id == target_id
    assert (user.status, user.role, user.auth_enabled, user.password_hash) == (
        "Pendente",
        "Gestor",
        False,
        None,
    )
    assert len(mail.messages) == 1


def test_inactive_email_requires_reactivation_without_new_account_or_mail(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    target_id = f"inactive-{uuid.uuid4().hex}"
    email = f"{target_id}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    _seed_user(
        account_access_database_url,
        user_id=target_id,
        email=email,
        role="Vendedor",
        status="Inativo",
        auth_enabled=False,
        password_hash="$argon2id$inactive",
    )
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)

    with pytest.raises(AccountRequiresReactivationError):
        service.invite(
            TENANT_ID, _principal(actor_id), _command(email), "203.0.113.16"
        )

    user = _read_user(account_access_database_url, email)
    assert (user.id, user.status, user.password_hash) == (
        target_id,
        "Inativo",
        "$argon2id$inactive",
    )
    assert mail.messages == []


def test_non_admin_create_resend_and_cancel_have_zero_tenant_or_smtp_side_effect(
    account_access_database_url: str,
) -> None:
    actor_id = f"seller-{uuid.uuid4().hex}"
    target_id = f"pending-target-{uuid.uuid4().hex}"
    target_email = f"{target_id}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Vendedor",
        status="Ativo",
        auth_enabled=True,
    )
    _seed_user(
        account_access_database_url,
        user_id=target_id,
        email=target_email,
        role="Vendedor",
        status="Pendente",
        auth_enabled=False,
    )
    mail = InMemoryMailSender()
    service, router, audit = _service(account_access_database_url, mail)
    actor = _principal(actor_id, role="Vendedor")

    with pytest.raises(AccountAccessAuthorizationError):
        service.invite(
            TENANT_ID,
            actor,
            _command(f"blocked-{uuid.uuid4().hex}@example.test"),
            "203.0.113.17",
        )
    with pytest.raises(AccountAccessAuthorizationError):
        service.resend_invitation(TENANT_ID, actor, target_id, "203.0.113.17")
    with pytest.raises(AccountAccessAuthorizationError):
        service.cancel_invitation(TENANT_ID, actor, target_id)

    user = _read_user(account_access_database_url, target_email)
    assert router.calls == 0
    assert (user.status, user.auth_enabled) == ("Pendente", False)
    assert mail.messages == []
    assert audit.events == []


def test_concurrent_invites_persist_one_user_and_at_most_one_live_token(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    email = f"concurrent-{uuid.uuid4().hex}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)
    barrier = threading.Barrier(2)

    def invite() -> str:
        barrier.wait(timeout=5)
        return service.invite(
            TENANT_ID, _principal(actor_id), _command(email), "203.0.113.18"
        ).user_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        user_ids = list(executor.map(lambda _index: invite(), range(2)))

    user = _read_user(account_access_database_url, email)
    tokens = _read_tokens(account_access_database_url, user.id)
    assert user_ids == [user.id, user.id]
    assert len(tokens) == 2
    assert sum(
        token.invalidated_at is None and token.consumed_at is None for token in tokens
    ) == 1



def test_resent_invitation_email_carries_one_fresh_link_bound_to_the_live_token(
    account_access_database_url: str,
) -> None:
    actor_id = f"admin-{uuid.uuid4().hex}"
    email = f"resend-link-{uuid.uuid4().hex}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)
    invited = service.invite(
        TENANT_ID, _principal(actor_id), _command(email), "203.0.113.19"
    )

    service.resend_invitation(
        TENANT_ID, _principal(actor_id), invited.user_id, "203.0.113.19"
    )

    first, second = mail.messages
    first_token = first.action_link.split("#token=", 1)[1]
    second_token = second.action_link.split("#token=", 1)[1]
    tokens = _read_tokens(account_access_database_url, invited.user_id)
    live = [token for token in tokens if token.invalidated_at is None]
    assert second.subject == "Você foi convidado para o Smart CRM da BRBots"
    assert second.action_link.startswith(
        "https://crm.example.test/brbots/accept-invite#token="
    )
    assert second_token and second_token != first_token
    assert second.action_link.count("#token=") == 1
    assert len(live) == 1
    assert live[0].token_digest == AccountAccessService._token_digest(
        "invitation", second_token
    )
    assert tokens[0].token_digest == AccountAccessService._token_digest(
        "invitation", first_token
    )
    assert tokens[0].invalidation_reason == "replaced"


class LoginControlRepositoryStub:
    def __init__(self, _session: object) -> None:
        self.session = SimpleNamespace(get=lambda *_args, **_kwargs: None)

    def find_tenant_by_slug(self, slug: str):  # noqa: ANN201
        if slug != "brbots":
            return None
        return ControlRepositoryStub(None).get_tenant(TENANT_ID)

    def record_login_failure(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def append_security_event(self, **_values):  # noqa: ANN003, ANN201
        return SimpleNamespace(id=uuid.uuid4())

    def clear_login_throttle(self, *_args) -> None:  # noqa: ANN002
        raise AssertionError("login must not succeed")

    def create_session(self, **_values) -> None:  # noqa: ANN003
        raise AssertionError("login must not create a session")


def _force_password_hash(database_url: str, user_id: str, password_hash: str) -> None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(bind=engine) as session, session.begin():
            _set_workspace(session)
            session.get(CrmUser, user_id).password_hash = password_hash
    finally:
        engine.dispose()


def test_pending_and_cancelled_invitees_cannot_log_in_even_with_a_valid_hash(
    account_access_database_url: str,
) -> None:
    from app.security.passwords import hash_password
    from app.services.auth import AuthenticationError, AuthService

    actor_id = f"admin-{uuid.uuid4().hex}"
    email = f"login-blocked-{uuid.uuid4().hex}@example.test"
    password = "senha-correta-123"
    _seed_user(
        account_access_database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    service, _router, _audit = _service(account_access_database_url, InMemoryMailSender())
    auth = AuthService(
        ControlDatabaseStub(),
        TenantRouter(account_access_database_url),
        repository_factory=LoginControlRepositoryStub,
        security_audit=RecordingAudit(),
    )
    invited = service.invite(
        TENANT_ID, _principal(actor_id), _command(email), "203.0.113.20"
    )
    _force_password_hash(account_access_database_url, invited.user_id, hash_password(password))

    with pytest.raises(AuthenticationError):
        auth.login("brbots", email, password, "203.0.113.20", now=NOW)

    service.cancel_invitation(TENANT_ID, _principal(actor_id), invited.user_id)
    _force_password_hash(account_access_database_url, invited.user_id, hash_password(password))

    with pytest.raises(AuthenticationError):
        auth.login("brbots", email, password, "203.0.113.20", now=NOW)

    user = _read_user(account_access_database_url, email)
    assert (user.status, user.auth_enabled) == ("Cancelado", False)


# --- T7: invitation inspection and acceptance -------------------------------

OTHER_TENANT_ID = uuid.UUID("5a0f3c2e-9d41-4b7a-8c6e-2f1d0b9a7c53")
INVITEE_PASSWORD = "senha-do-convidado-2026"


def _seed_admin(database_url: str) -> str:
    actor_id = f"admin-{uuid.uuid4().hex}"
    _seed_user(
        database_url,
        user_id=actor_id,
        email=f"{actor_id}@example.test",
        role="Administrador",
        status="Ativo",
        auth_enabled=True,
    )
    return actor_id


def _link_token(message) -> str:  # noqa: ANN001
    return message.action_link.split("#token=", 1)[1]


def _invite(
    service: AccountAccessService,
    mail: InMemoryMailSender,
    actor_id: str,
    email: str,
) -> tuple[str, str]:
    result = service.invite(TENANT_ID, _principal(actor_id), _command(email), "203.0.113.30")
    return result.user_id, _link_token(mail.messages[-1])


def _account_state(database_url: str, email: str) -> tuple[object, ...]:
    user = _read_user(database_url, email)
    return (user.status, user.auth_enabled, user.auth_version, user.password_hash)


def _live_tokens(database_url: str, user_id: str) -> list[AccountActionToken]:
    return [
        token
        for token in _read_tokens(database_url, user_id)
        if token.invalidated_at is None and token.consumed_at is None
    ]


def _assert_public_link_failure(action) -> None:  # noqa: ANN001
    with pytest.raises(AccountActionLinkInvalidError) as failure:
        action()
    assert str(failure.value) == INVALID_ACTION_LINK_MESSAGE


def test_inspect_valid_invitation_exposes_only_company_and_email_without_consuming(
    account_access_database_url: str,
) -> None:
    import dataclasses

    actor_id = _seed_admin(account_access_database_url)
    email = f"inspect-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    service, _router, audit = _service(account_access_database_url, mail)
    user_id, raw_token = _invite(service, mail, actor_id, email)
    events_before = len(audit.events)

    first = service.inspect_action("brbots", "invitation", raw_token)
    second = service.inspect_action("brbots", "invitation", raw_token)

    assert first == second == PublicActionView(company_name="BRBots", email=email)
    assert {field.name for field in dataclasses.fields(PublicActionView)} == {
        "company_name",
        "email",
    }
    assert _account_state(account_access_database_url, email) == (
        "Pendente",
        False,
        0,
        None,
    )
    assert len(_live_tokens(account_access_database_url, user_id)) == 1
    assert len(audit.events) == events_before


def test_accept_stores_argon2id_activates_consumes_and_increments_auth_version_once(
    account_access_database_url: str,
) -> None:
    from app.security.passwords import verify_password

    actor_id = _seed_admin(account_access_database_url)
    email = f"accept-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    service, _router, audit = _service(account_access_database_url, mail)
    user_id, raw_token = _invite(service, mail, actor_id, email)

    service.accept_invitation(
        "brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.31"
    )

    user = _read_user(account_access_database_url, email)
    token = _read_tokens(account_access_database_url, user_id)[-1]
    assert (user.status, user.auth_enabled, user.auth_version) == ("Ativo", True, 1)
    assert user.password_hash.startswith("$argon2id$")
    assert INVITEE_PASSWORD not in user.password_hash
    assert verify_password(user.password_hash, INVITEE_PASSWORD)
    assert (token.consumed_at, token.invalidated_at) == (NOW, None)
    assert audit.events[-1]["event_type"] == "invitation.accepted"
    assert audit.events[-1]["outcome_code"] == "accepted"
    assert audit.events[-1]["user_id"] == user_id
    assert audit.events[-1]["tenant_id"] == TENANT_ID
    assert raw_token not in repr(audit.events)
    assert INVITEE_PASSWORD not in repr(audit.events)
    assert user.password_hash not in repr(audit.events)


class RecordingLoginRepository:
    sessions: list[dict[str, object]] = []

    def __init__(self, _session: object) -> None:
        self.session = SimpleNamespace(get=lambda *_args, **_kwargs: None)

    def find_tenant_by_slug(self, slug: str):  # noqa: ANN201
        return ControlRepositoryStub(None).find_tenant_by_slug(slug)

    def record_login_failure(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    def clear_login_throttle(self, *_args) -> None:  # noqa: ANN002
        return None

    def create_session(self, **values) -> None:  # noqa: ANN003
        type(self).sessions.append(values)

    def append_security_event(self, **_values):  # noqa: ANN003, ANN201
        return SimpleNamespace(id=uuid.uuid4())


def test_accept_creates_no_session_and_the_invitee_then_signs_in_through_login(
    account_access_database_url: str,
) -> None:
    from app.services.auth import AuthService

    actor_id = _seed_admin(account_access_database_url)
    email = f"accept-login-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)
    user_id, raw_token = _invite(service, mail, actor_id, email)
    RecordingLoginRepository.sessions = []

    outcome = service.accept_invitation(
        "brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.32"
    )

    assert outcome is None
    assert RecordingLoginRepository.sessions == []
    auth = AuthService(
        ControlDatabaseStub(),
        TenantRouter(account_access_database_url),
        repository_factory=RecordingLoginRepository,
        security_audit=RecordingAudit(),
    )
    login = auth.login("brbots", email, INVITEE_PASSWORD, "203.0.113.32", now=NOW)
    assert login.context.principal.user_id == user_id
    assert login.context.principal.auth_version == 1
    assert len(RecordingLoginRepository.sessions) == 1


def test_every_absent_expired_used_cancelled_or_replaced_token_shares_one_public_failure(
    account_access_database_url: str,
) -> None:
    actor_id = _seed_admin(account_access_database_url)
    mail = InMemoryMailSender()
    service, router, audit = _service(account_access_database_url, mail)
    later = AccountAccessService(
        ControlDatabaseStub(),
        router,
        mail,
        public_origin="https://crm.example.test",
        control_repository_factory=ControlRepositoryStub,
        security_audit=audit,
        clock=lambda: NOW + timedelta(hours=48, seconds=1),
    )

    expired_email = f"expired-{uuid.uuid4().hex}@example.test"
    _expired_id, expired_token = _invite(service, mail, actor_id, expired_email)

    used_email = f"used-{uuid.uuid4().hex}@example.test"
    _used_id, used_token = _invite(service, mail, actor_id, used_email)
    service.accept_invitation(
        "brbots", used_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.33"
    )

    cancelled_email = f"cancelled-open-page-{uuid.uuid4().hex}@example.test"
    cancelled_id, cancelled_token = _invite(service, mail, actor_id, cancelled_email)
    assert service.inspect_action("brbots", "invitation", cancelled_token).email == (
        cancelled_email
    )
    service.cancel_invitation(TENANT_ID, _principal(actor_id), cancelled_id)

    replaced_email = f"replaced-{uuid.uuid4().hex}@example.test"
    replaced_id, replaced_token = _invite(service, mail, actor_id, replaced_email)
    service.resend_invitation(TENANT_ID, _principal(actor_id), replaced_id, "203.0.113.33")

    cases = [
        (service, "brbots", "", None),
        (service, "brbots", "token-que-nunca-existiu", None),
        (later, "brbots", expired_token, expired_email),
        (service, "brbots", used_token, used_email),
        (service, "brbots", cancelled_token, cancelled_email),
        (service, "brbots", replaced_token, replaced_email),
        (service, "empresa-inexistente", replaced_token, replaced_email),
    ]
    for case_service, slug, raw_token, email in cases:
        before = _account_state(account_access_database_url, email) if email else None
        _assert_public_link_failure(
            lambda: case_service.inspect_action(slug, "invitation", raw_token)
        )
        _assert_public_link_failure(
            lambda: case_service.accept_invitation(
                slug, raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.33"
            )
        )
        if email:
            assert _account_state(account_access_database_url, email) == before

    calls_before = router.calls
    _assert_public_link_failure(
        lambda: service.accept_invitation(
            "empresa-inexistente",
            replaced_token,
            INVITEE_PASSWORD,
            INVITEE_PASSWORD,
            "203.0.113.33",
        )
    )
    assert router.calls == calls_before
    assert audit.events[-1]["event_type"] == "invitation.accept_failed"
    assert audit.events[-1]["outcome_code"] == "invalid_token"
    assert replaced_token not in repr(audit.events)
    assert _account_state(account_access_database_url, used_email)[:3] == (
        "Ativo",
        True,
        1,
    )
    assert _read_user(account_access_database_url, cancelled_email).status == "Cancelado"


@pytest.mark.parametrize(
    ("password", "confirmation"),
    [
        (INVITEE_PASSWORD, INVITEE_PASSWORD + "x"),
        ("a" * 7, "a" * 7),
        ("a" * 129, "a" * 129),
    ],
    ids=["confirmation-mismatch", "too-short", "too-long"],
)
def test_invalid_password_is_rejected_and_keeps_the_invitation_usable(
    account_access_database_url: str,
    password: str,
    confirmation: str,
) -> None:
    actor_id = _seed_admin(account_access_database_url)
    email = f"bad-password-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    service, router, _audit = _service(account_access_database_url, mail)
    user_id, raw_token = _invite(service, mail, actor_id, email)
    calls_before = router.calls

    with pytest.raises(AccountPasswordPolicyError):
        service.accept_invitation("brbots", raw_token, password, confirmation, "203.0.113.34")

    assert router.calls == calls_before
    assert _account_state(account_access_database_url, email) == ("Pendente", False, 0, None)
    assert len(_live_tokens(account_access_database_url, user_id)) == 1
    service.accept_invitation(
        "brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.34"
    )
    assert _account_state(account_access_database_url, email)[:3] == ("Ativo", True, 1)


def test_concurrent_acceptances_have_exactly_one_winner_and_one_version_increment(
    account_access_database_url: str,
) -> None:
    from app.security.passwords import verify_password

    actor_id = _seed_admin(account_access_database_url)
    email = f"concurrent-accept-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)
    user_id, raw_token = _invite(service, mail, actor_id, email)
    passwords = [f"senha-concorrente-{index}-2026" for index in range(4)]
    barrier = threading.Barrier(len(passwords))

    def accept(password: str) -> str:
        barrier.wait(timeout=10)
        try:
            service.accept_invitation("brbots", raw_token, password, password, "203.0.113.35")
        except AccountActionLinkInvalidError:
            return "rejected"
        return "accepted"

    with ThreadPoolExecutor(max_workers=len(passwords)) as executor:
        outcomes = list(executor.map(accept, passwords))

    user = _read_user(account_access_database_url, email)
    winner = passwords[outcomes.index("accepted")]
    assert sorted(outcomes) == ["accepted", "rejected", "rejected", "rejected"]
    assert (user.status, user.auth_enabled, user.auth_version) == ("Ativo", True, 1)
    assert [verify_password(user.password_hash, item) for item in passwords] == [
        item == winner for item in passwords
    ]
    tokens = _read_tokens(account_access_database_url, user_id)
    assert sum(token.consumed_at is not None for token in tokens) == 1


class MultiTenantRouter:
    def __init__(self, database_urls: dict[uuid.UUID, str]) -> None:
        self.database_urls = database_urls
        self.opened: list[uuid.UUID] = []
        self._lock = threading.Lock()

    @contextmanager
    def tenant_session_scope(self, tenant_id: uuid.UUID):
        with self._lock:
            self.opened.append(tenant_id)
        engine = create_engine(self.database_urls[tenant_id], poolclass=NullPool)
        session = Session(bind=engine, expire_on_commit=False)
        try:
            with session.begin():
                _set_workspace(session)
                yield session
        finally:
            session.close()
            engine.dispose()


class TwoTenantControlRepository(ControlRepositoryStub):
    def get_tenant(self, tenant_id: uuid.UUID):  # noqa: ANN201
        if tenant_id == OTHER_TENANT_ID:
            return SimpleNamespace(
                id=OTHER_TENANT_ID,
                slug="outra",
                display_name="Outra Empresa",
                status="active",
            )
        return super().get_tenant(tenant_id)

    def find_tenant_by_slug(self, slug: str):  # noqa: ANN201
        if slug == "outra":
            return self.get_tenant(OTHER_TENANT_ID)
        return super().find_tenant_by_slug(slug)


def test_link_presented_to_another_tenant_fails_without_touching_either_tenant(
    account_access_database_url: str,
    other_tenant_database_url: str,
) -> None:
    actor_id = _seed_admin(account_access_database_url)
    email = f"wrong-tenant-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    router = MultiTenantRouter(
        {
            TENANT_ID: account_access_database_url,
            OTHER_TENANT_ID: other_tenant_database_url,
        }
    )
    service = AccountAccessService(
        ControlDatabaseStub(),
        router,
        mail,
        public_origin="https://crm.example.test",
        control_repository_factory=TwoTenantControlRepository,
        security_audit=RecordingAudit(),
        clock=lambda: NOW,
    )
    user_id, raw_token = _invite(service, mail, actor_id, email)
    router.opened.clear()

    _assert_public_link_failure(lambda: service.inspect_action("outra", "invitation", raw_token))
    _assert_public_link_failure(
        lambda: service.accept_invitation(
            "outra", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.36"
        )
    )

    assert set(router.opened) == {OTHER_TENANT_ID}
    assert _read_user(other_tenant_database_url, email) is None
    assert _account_state(account_access_database_url, email) == ("Pendente", False, 0, None)
    assert len(_live_tokens(account_access_database_url, user_id)) == 1
    service.accept_invitation(
        "brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.36"
    )
    assert _account_state(account_access_database_url, email)[:3] == ("Ativo", True, 1)


def _update_user(database_url: str, user_id: str, **values: object) -> None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(bind=engine) as session, session.begin():
            _set_workspace(session)
            user = session.get(CrmUser, user_id)
            for name, value in values.items():
                setattr(user, name, value)
    finally:
        engine.dispose()


def test_accept_of_a_reused_cancelled_account_increments_its_existing_version_once(
    account_access_database_url: str,
) -> None:
    actor_id = _seed_admin(account_access_database_url)
    target_id = f"reused-{uuid.uuid4().hex}"
    email = f"{target_id}@example.test"
    _seed_user(
        account_access_database_url,
        user_id=target_id,
        email=email,
        role="Vendedor",
        status="Cancelado",
        auth_enabled=False,
    )
    _update_user(account_access_database_url, target_id, auth_version=3)
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)
    _user_id, raw_token = _invite(service, mail, actor_id, email)

    service.accept_invitation(
        "brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.37"
    )

    assert _account_state(account_access_database_url, email)[:3] == ("Ativo", True, 4)


def test_live_invitation_of_an_account_that_left_pending_is_rejected_unchanged(
    account_access_database_url: str,
) -> None:
    actor_id = _seed_admin(account_access_database_url)
    email = f"left-pending-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)
    user_id, raw_token = _invite(service, mail, actor_id, email)
    _update_user(account_access_database_url, user_id, status="Inativo")

    _assert_public_link_failure(lambda: service.inspect_action("brbots", "invitation", raw_token))
    _assert_public_link_failure(
        lambda: service.accept_invitation(
            "brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.38"
        )
    )

    assert _account_state(account_access_database_url, email) == ("Inativo", False, 0, None)
    assert len(_live_tokens(account_access_database_url, user_id)) == 1


def test_accept_locks_the_user_before_the_token_like_cancel_and_resend(
    account_access_database_url: str,
) -> None:
    from sqlalchemy.exc import OperationalError

    actor_id = _seed_admin(account_access_database_url)
    email = f"lock-order-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    service, _router, _audit = _service(account_access_database_url, mail)
    user_id, raw_token = _invite(service, mail, actor_id, email)
    token_id = _live_tokens(account_access_database_url, user_id)[0].id

    engine = create_engine(account_access_database_url, poolclass=NullPool)
    holder = Session(bind=engine)
    try:
        holder.begin()
        _set_workspace(holder)
        holder.execute(
            select(CrmUser.id).where(CrmUser.id == user_id).with_for_update()
        ).all()
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                service.accept_invitation,
                "brbots",
                raw_token,
                INVITEE_PASSWORD,
                INVITEE_PASSWORD,
                "203.0.113.39",
            )
            threading.Event().wait(2)
            assert not pending.done()
            try:
                holder.execute(
                    select(AccountActionToken.id)
                    .where(AccountActionToken.id == token_id)
                    .with_for_update(nowait=True)
                ).all()
            except OperationalError as error:  # pragma: no cover - failure path
                raise AssertionError("accept locked the token before the user") from error
            holder.rollback()
            pending.result(timeout=30)
    finally:
        holder.close()
        engine.dispose()

    assert _account_state(account_access_database_url, email)[:3] == ("Ativo", True, 1)


# --- T8: password recovery and session invalidation -------------------------

UNAVAILABLE_TENANT_ID = uuid.UUID("9c3d7e1a-2b4f-4c8d-9e0a-6f5b4a3c2d1e")
OLD_PASSWORD = "senha-antiga-segura-2026"
NEW_PASSWORD = "senha-nova-segura-2026"
RESET_TTL = timedelta(hours=48)


@pytest.fixture
def recovery_control_database():
    from app.control_database import ControlDatabase
    from app.control_models import ControlBase, ControlTenant

    admin_engine = create_engine(TEST_DATABASE_URL, poolclass=NullPool)
    schema = f"account_recovery_{uuid.uuid4().hex}"
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
    with database.session_scope() as session:
        for tenant_id, slug, display_name in (
            (TENANT_ID, "brbots", "BRBots"),
            (OTHER_TENANT_ID, "outra", "Outra Empresa"),
            (UNAVAILABLE_TENANT_ID, "fora-do-ar", "Fora do Ar"),
        ):
            session.add(
                ControlTenant(
                    id=tenant_id,
                    slug=slug,
                    display_name=display_name,
                    status="active",
                    secret_ref=f"db-{slug}",
                    expected_tenant_revision="tenant-head",
                )
            )
    try:
        yield database
    finally:
        database.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


class RecoveryRouter(MultiTenantRouter):
    """Routes known tenants; any other tenant database is unavailable."""

    @contextmanager
    def tenant_session_scope(self, tenant_id: uuid.UUID):
        from app.tenant_database import TenantUnavailableError

        if tenant_id not in self.database_urls:
            with self._lock:
                self.opened.append(tenant_id)
            raise TenantUnavailableError("tenant database unavailable")
        with super().tenant_session_scope(tenant_id) as session:
            yield session


def _recovery_service(
    control_database,  # noqa: ANN001
    router: RecoveryRouter,
    mail_sender,  # noqa: ANN001
    *,
    audit: RecordingAudit | None = None,
    clock=None,  # noqa: ANN001
    control_repository_factory=None,  # noqa: ANN001
) -> AccountAccessService:
    from app.control_database import ControlRepository

    return AccountAccessService(
        control_database,
        router,
        mail_sender,
        public_origin="https://crm.example.test",
        control_repository_factory=control_repository_factory or ControlRepository,
        security_audit=audit or RecordingAudit(),
        clock=clock or (lambda: NOW),
    )


def _recovery_auth(control_database, database_url: str):  # noqa: ANN001, ANN202
    from app.services.auth import AuthService

    return AuthService(
        control_database,
        RecoveryRouter({TENANT_ID: database_url}),
        security_audit=RecordingAudit(),
    )


def _seed_active_member(database_url: str, *, password: str = OLD_PASSWORD) -> tuple[str, str]:
    from app.security.passwords import hash_password

    user_id = f"member-{uuid.uuid4().hex}"
    email = f"{user_id}@example.test"
    _seed_user(
        database_url,
        user_id=user_id,
        email=email,
        role="Vendedor",
        status="Ativo",
        auth_enabled=True,
        password_hash=hash_password(password),
    )
    return user_id, email


def _reset_tokens(database_url: str, user_id: str) -> list[AccountActionToken]:
    return [
        token
        for token in _read_tokens(database_url, user_id)
        if token.purpose == "password_reset"
    ]


def _sessions(control_database, user_id: str) -> list:  # noqa: ANN001
    from app.control_models import AuthSession

    with control_database.session_scope() as session:
        rows = session.scalars(
            select(AuthSession).where(AuthSession.user_id == user_id)
        ).all()
        session.expunge_all()
        return list(rows)


def _unique_ip() -> str:
    return f"2001:db8::{uuid.uuid4().hex[:4]}"


def test_reset_request_result_is_identical_for_every_tenant_account_and_smtp_outcome(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    from app.services.account_access import PASSWORD_RESET_REQUEST_MESSAGE

    assert PASSWORD_RESET_REQUEST_MESSAGE == "Se o e-mail existir, enviaremos as instruções."
    database_url = account_access_database_url
    _active_id, active_email = _seed_active_member(database_url)
    _failing_id, failing_email = _seed_active_member(database_url)
    states = {}
    for status, enabled in (("Pendente", False), ("Inativo", False), ("Cancelado", False)):
        user_id = f"{status.lower()}-{uuid.uuid4().hex}"
        _seed_user(
            database_url,
            user_id=user_id,
            email=f"{user_id}@example.test",
            role="Vendedor",
            status=status,
            auth_enabled=enabled,
        )
        states[user_id] = f"{user_id}@example.test"
    disabled_id, disabled_email = _seed_active_member(database_url)
    _update_user(database_url, disabled_id, auth_enabled=False)
    states[disabled_id] = disabled_email

    router = RecoveryRouter({TENANT_ID: database_url})
    mail = InMemoryMailSender()
    failing = FailingMailSender("smtp_timeout")
    audit = RecordingAudit()
    service = _recovery_service(recovery_control_database, router, mail, audit=audit)
    failing_service = _recovery_service(
        recovery_control_database, router, failing, audit=audit
    )

    unknown_email = f"nobody-{uuid.uuid4().hex}@example.test"
    cases = [
        (service, "empresa-inexistente", active_email),
        (service, "fora-do-ar", active_email),
        (service, "brbots", unknown_email),
        (service, "brbots", "sem-arroba"),
        *[(service, "brbots", email) for email in states.values()],
        (failing_service, "brbots", failing_email),
        (service, "brbots", f"  {active_email.upper()} "),
    ]
    before = {
        user_id: _account_state(database_url, email) for user_id, email in states.items()
    }
    outcomes = [
        case_service.request_password_reset(slug, email, _unique_ip())
        for case_service, slug, email in cases
    ]

    assert outcomes == [None] * len(cases)
    assert [message.recipient for message in mail.messages] == [active_email]
    assert mail.messages[0].action_link.startswith(
        "https://crm.example.test/brbots/reset-password#token="
    )
    assert failing.attempts == 1
    for user_id, email in states.items():
        assert _account_state(database_url, email) == before[user_id]
        assert _reset_tokens(database_url, user_id) == []
    assert _read_user(database_url, unknown_email) is None
    failed_tokens = _reset_tokens(database_url, _failing_id)
    assert [(t.delivery_status, t.invalidation_reason) for t in failed_tokens] == [
        ("failed", "delivery_failed")
    ]
    ignored = [
        event["outcome_code"]
        for event in audit.events
        if event["event_type"] == "password_reset.request_ignored"
    ]
    assert ignored == [
        "unknown_tenant",
        "tenant_unavailable",
        "no_eligible_account",
        "no_eligible_account",
        *["no_eligible_account"] * len(states),
    ]
    assert any(
        event["event_type"] == "password_reset.delivery_failed"
        and event["outcome_code"] == "smtp_timeout"
        for event in audit.events
    )
    raw_token = _link_token(mail.messages[0])
    rendered_events = repr(audit.events)
    for secret in (raw_token, active_email, failing_email, unknown_email):
        assert secret not in rendered_events


def test_reset_request_for_active_user_sends_one_48h_link_and_replaces_previous_tokens(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    database_url = account_access_database_url
    user_id, email = _seed_active_member(database_url)
    mail = InMemoryMailSender()
    service = _recovery_service(
        recovery_control_database, RecoveryRouter({TENANT_ID: database_url}), mail
    )

    service.request_password_reset("brbots", email, "198.51.100.10")
    service.request_password_reset("brbots", email, "198.51.100.10")

    first_token, second_token = (_link_token(message) for message in mail.messages)
    assert [message.recipient for message in mail.messages] == [email, email]
    tokens = _reset_tokens(database_url, user_id)
    assert len(tokens) == 2
    assert tokens[0].token_digest == AccountAccessService._token_digest(
        "password_reset", first_token
    )
    assert (tokens[0].invalidated_at, tokens[0].invalidation_reason) == (NOW, "replaced")
    live = tokens[1]
    assert live.token_digest == AccountAccessService._token_digest(
        "password_reset", second_token
    )
    assert (live.expires_at, live.consumed_at, live.invalidated_at) == (
        NOW + RESET_TTL,
        None,
        None,
    )
    assert (live.created_by_user_id, live.delivery_status) == (None, "sent")
    assert service.inspect_action("brbots", "password_reset", second_token) == (
        PublicActionView(company_name="BRBots", email=email)
    )
    _assert_public_link_failure(
        lambda: service.inspect_action("brbots", "password_reset", first_token)
    )
    _assert_public_link_failure(
        lambda: service.inspect_action("brbots", "invitation", second_token)
    )
    assert _account_state(database_url, email)[:3] == ("Ativo", True, 1)


def test_reset_replaces_argon2id_consumes_once_increments_version_and_revokes_sessions(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    from app.security.passwords import verify_password
    from app.services.auth import AuthenticationError

    database_url = account_access_database_url
    user_id, email = _seed_active_member(database_url)
    auth = _recovery_auth(recovery_control_database, database_url)
    first_login = auth.login("brbots", email, OLD_PASSWORD, "198.51.100.20", now=NOW)
    second_login = auth.login("brbots", email, OLD_PASSWORD, "198.51.100.21", now=NOW)
    mail = InMemoryMailSender()
    audit = RecordingAudit()
    service = _recovery_service(
        recovery_control_database,
        RecoveryRouter({TENANT_ID: database_url}),
        mail,
        audit=audit,
    )
    service.request_password_reset("brbots", email, "198.51.100.22")
    raw_token = _link_token(mail.messages[-1])

    outcome = service.reset_password(
        "brbots", raw_token, NEW_PASSWORD, NEW_PASSWORD, "198.51.100.22"
    )

    assert outcome is None
    user = _read_user(database_url, email)
    assert (user.status, user.auth_enabled, user.auth_version) == ("Ativo", True, 2)
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(user.password_hash, NEW_PASSWORD)
    assert not verify_password(user.password_hash, OLD_PASSWORD)
    token = _reset_tokens(database_url, user_id)[-1]
    assert (token.consumed_at, token.invalidated_at) == (NOW, None)
    sessions = _sessions(recovery_control_database, user_id)
    assert len(sessions) == 2
    assert {(row.revoked_at, row.revocation_reason) for row in sessions} == {
        (NOW, "password_reset")
    }
    for login in (first_login, second_login):
        with pytest.raises(AuthenticationError):
            auth.current_session(login.token, now=NOW + timedelta(seconds=1))
    with pytest.raises(AuthenticationError):
        auth.login("brbots", email, OLD_PASSWORD, "198.51.100.23", now=NOW)
    fresh = auth.login("brbots", email, NEW_PASSWORD, "198.51.100.23", now=NOW)
    assert fresh.context.principal.auth_version == 2
    _assert_public_link_failure(
        lambda: service.reset_password(
            "brbots", raw_token, OLD_PASSWORD, OLD_PASSWORD, "198.51.100.22"
        )
    )
    assert _read_user(database_url, email).auth_version == 2
    event_types = [event["event_type"] for event in audit.events]
    assert event_types[-3:] == [
        "session.revoked",
        "password_reset.completed",
        "password_reset.failed",
    ]
    rendered = repr(audit.events)
    for secret in (raw_token, NEW_PASSWORD, OLD_PASSWORD, user.password_hash, email):
        assert secret not in rendered


def test_reset_creates_no_session_and_stale_sessions_fail_even_if_revocation_fails(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    from sqlalchemy.exc import OperationalError

    from app.control_database import ControlRepository
    from app.services.auth import AuthenticationError

    class RevocationOutageRepository(ControlRepository):
        attempts = 0

        def create_session(self, **_values):  # noqa: ANN003, ANN201
            raise AssertionError("password reset must never create a session")

        def revoke_user_sessions(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
            type(self).attempts += 1
            raise OperationalError("UPDATE auth_sessions", {}, Exception("offline"))

    database_url = account_access_database_url
    user_id, email = _seed_active_member(database_url)
    auth = _recovery_auth(recovery_control_database, database_url)
    stale = auth.login("brbots", email, OLD_PASSWORD, "198.51.100.30", now=NOW)
    mail = InMemoryMailSender()
    audit = RecordingAudit()
    service = _recovery_service(
        recovery_control_database,
        RecoveryRouter({TENANT_ID: database_url}),
        mail,
        audit=audit,
        control_repository_factory=RevocationOutageRepository,
    )
    service.request_password_reset("brbots", email, "198.51.100.31")

    service.reset_password(
        "brbots",
        _link_token(mail.messages[-1]),
        NEW_PASSWORD,
        NEW_PASSWORD,
        "198.51.100.31",
    )

    assert RevocationOutageRepository.attempts == 2
    assert audit.events[-2]["event_type"] == "password_reset.session_revocation_failed"
    assert audit.events[-1]["event_type"] == "password_reset.completed"
    assert _read_user(database_url, email).auth_version == 2
    [row] = _sessions(recovery_control_database, user_id)
    assert row.revoked_at is None and row.auth_version == 1
    with pytest.raises(AuthenticationError):
        auth.current_session(stale.token, now=NOW + timedelta(seconds=1))
    [row] = _sessions(recovery_control_database, user_id)
    assert row.revocation_reason == "auth_changed"


def test_every_unusable_reset_token_shares_one_public_failure_without_changes(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    database_url = account_access_database_url
    router = RecoveryRouter({TENANT_ID: database_url})
    mail = InMemoryMailSender()
    audit = RecordingAudit()
    service = _recovery_service(recovery_control_database, router, mail, audit=audit)
    later = _recovery_service(
        recovery_control_database,
        router,
        mail,
        audit=audit,
        clock=lambda: NOW + RESET_TTL + timedelta(seconds=1),
    )

    def requested(*, ip: str) -> tuple[str, str, str]:
        user_id, email = _seed_active_member(database_url)
        service.request_password_reset("brbots", email, ip)
        return user_id, email, _link_token(mail.messages[-1])

    _expired_id, expired_email, expired_token = requested(ip="198.51.100.40")
    _used_id, used_email, used_token = requested(ip="198.51.100.41")
    service.reset_password("brbots", used_token, NEW_PASSWORD, NEW_PASSWORD, "198.51.100.41")
    replaced_id, replaced_email, replaced_token = requested(ip="198.51.100.42")
    service.request_password_reset("brbots", replaced_email, "198.51.100.42")
    inactive_id, inactive_email, inactive_token = requested(ip="198.51.100.43")
    _update_user(database_url, inactive_id, status="Inativo", auth_enabled=False)

    class CapturingFailingMail(InMemoryMailSender):
        def send(self, message) -> None:  # noqa: ANN001
            super().send(message)
            raise MailDeliveryError("smtp_recipient_refused")

    undelivered_mail = CapturingFailingMail()
    failing = _recovery_service(
        recovery_control_database, router, undelivered_mail, audit=audit
    )
    _undelivered_id, undelivered_email = _seed_active_member(database_url)
    failing.request_password_reset("brbots", undelivered_email, "198.51.100.44")
    undelivered_token = _link_token(undelivered_mail.messages[-1])
    actor_id = _seed_admin(database_url)
    invitee_email = f"invitee-{uuid.uuid4().hex}@example.test"
    invite_service, _router, _audit = _service(database_url, mail)
    _invitee_id, invitation_token = _invite(invite_service, mail, actor_id, invitee_email)

    cases = [
        (service, "brbots", "", None),
        (service, "brbots", "x" * 513, None),
        (service, "brbots", "token-que-nunca-existiu", None),
        (later, "brbots", expired_token, expired_email),
        (service, "brbots", used_token, used_email),
        (service, "brbots", replaced_token, replaced_email),
        (service, "brbots", inactive_token, inactive_email),
        (service, "brbots", undelivered_token, undelivered_email),
        (service, "brbots", invitation_token, invitee_email),
        (service, "empresa-inexistente", replaced_token, replaced_email),
        (service, "fora-do-ar", replaced_token, replaced_email),
    ]
    for case_service, slug, raw_token, email in cases:
        before = _account_state(database_url, email) if email else None
        _assert_public_link_failure(
            lambda: case_service.inspect_action(slug, "password_reset", raw_token)
        )
        _assert_public_link_failure(
            lambda: case_service.reset_password(
                slug, raw_token, NEW_PASSWORD, NEW_PASSWORD, "198.51.100.45"
            )
        )
        if email:
            assert _account_state(database_url, email) == before

    assert audit.events[-1]["event_type"] == "password_reset.failed"
    assert audit.events[-1]["outcome_code"] == "invalid_token"
    assert _account_state(database_url, used_email)[2] == 2
    assert _account_state(database_url, replaced_email)[2] == 1
    assert len(_live_tokens(database_url, replaced_id)) == 1
    assert _account_state(database_url, invitee_email) == ("Pendente", False, 0, None)
    rendered = repr(audit.events)
    for secret in (
        expired_token,
        used_token,
        replaced_token,
        undelivered_token,
        invitation_token,
    ):
        assert secret not in rendered


def test_reset_link_presented_to_another_tenant_fails_without_touching_either_tenant(
    account_access_database_url: str,
    other_tenant_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    database_url = account_access_database_url
    user_id, email = _seed_active_member(database_url)
    router = RecoveryRouter(
        {TENANT_ID: database_url, OTHER_TENANT_ID: other_tenant_database_url}
    )
    mail = InMemoryMailSender()
    service = _recovery_service(recovery_control_database, router, mail)
    service.request_password_reset("brbots", email, "198.51.100.50")
    raw_token = _link_token(mail.messages[-1])
    router.opened.clear()

    _assert_public_link_failure(
        lambda: service.inspect_action("outra", "password_reset", raw_token)
    )
    _assert_public_link_failure(
        lambda: service.reset_password(
            "outra", raw_token, NEW_PASSWORD, NEW_PASSWORD, "198.51.100.50"
        )
    )

    assert set(router.opened) == {OTHER_TENANT_ID}
    assert _read_user(other_tenant_database_url, email) is None
    assert _account_state(database_url, email)[:3] == ("Ativo", True, 1)
    assert len(_live_tokens(database_url, user_id)) == 1
    service.reset_password("brbots", raw_token, NEW_PASSWORD, NEW_PASSWORD, "198.51.100.50")
    assert _account_state(database_url, email)[:3] == ("Ativo", True, 2)


@pytest.mark.parametrize(
    ("password", "confirmation"),
    [
        (NEW_PASSWORD, NEW_PASSWORD + "x"),
        ("a" * 7, "a" * 7),
        ("a" * 129, "a" * 129),
    ],
    ids=["confirmation-mismatch", "too-short", "too-long"],
)
def test_invalid_new_password_is_rejected_and_keeps_the_reset_link_usable(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
    password: str,
    confirmation: str,
) -> None:
    from app.security.passwords import verify_password

    database_url = account_access_database_url
    user_id, email = _seed_active_member(database_url)
    router = RecoveryRouter({TENANT_ID: database_url})
    mail = InMemoryMailSender()
    service = _recovery_service(recovery_control_database, router, mail)
    service.request_password_reset("brbots", email, _unique_ip())
    raw_token = _link_token(mail.messages[-1])
    router.opened.clear()

    with pytest.raises(AccountPasswordPolicyError):
        service.reset_password("brbots", raw_token, password, confirmation, "198.51.100.60")

    assert router.opened == []
    user = _read_user(database_url, email)
    assert user.auth_version == 1
    assert verify_password(user.password_hash, OLD_PASSWORD)
    assert len(_live_tokens(database_url, user_id)) == 1
    service.reset_password("brbots", raw_token, NEW_PASSWORD, NEW_PASSWORD, "198.51.100.60")
    assert _read_user(database_url, email).auth_version == 2


def test_concurrent_resets_have_exactly_one_winner_and_one_version_increment(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    from app.security.passwords import verify_password

    database_url = account_access_database_url
    user_id, email = _seed_active_member(database_url)
    mail = InMemoryMailSender()
    service = _recovery_service(
        recovery_control_database, RecoveryRouter({TENANT_ID: database_url}), mail
    )
    service.request_password_reset("brbots", email, "198.51.100.70")
    raw_token = _link_token(mail.messages[-1])
    passwords = [f"senha-redefinida-{index}-2026" for index in range(4)]
    barrier = threading.Barrier(len(passwords))

    def reset(password: str) -> str:
        barrier.wait(timeout=10)
        try:
            service.reset_password("brbots", raw_token, password, password, "198.51.100.70")
        except AccountActionLinkInvalidError:
            return "rejected"
        return "reset"

    with ThreadPoolExecutor(max_workers=len(passwords)) as executor:
        outcomes = list(executor.map(reset, passwords))

    user = _read_user(database_url, email)
    winner = passwords[outcomes.index("reset")]
    assert sorted(outcomes) == ["rejected", "rejected", "rejected", "reset"]
    assert user.auth_version == 2
    assert [verify_password(user.password_hash, item) for item in passwords] == [
        item == winner for item in passwords
    ]
    assert sum(t.consumed_at is not None for t in _reset_tokens(database_url, user_id)) == 1


def test_sixth_reset_request_for_one_account_in_15_minutes_is_silently_not_sent(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    database_url = account_access_database_url
    user_id, email = _seed_active_member(database_url)
    router = RecoveryRouter({TENANT_ID: database_url})
    mail = InMemoryMailSender()
    audit = RecordingAudit()
    service = _recovery_service(recovery_control_database, router, mail, audit=audit)
    after_window = _recovery_service(
        recovery_control_database,
        router,
        mail,
        audit=audit,
        clock=lambda: NOW + timedelta(minutes=15, seconds=1),
    )

    outcomes = [
        service.request_password_reset("brbots", email, f"198.51.101.{index}")
        for index in range(6)
    ]

    assert outcomes == [None] * 6
    assert len(mail.messages) == 5
    tokens = _reset_tokens(database_url, user_id)
    assert len(tokens) == 5
    [live] = _live_tokens(database_url, user_id)
    assert live.token_digest == AccountAccessService._token_digest(
        "password_reset", _link_token(mail.messages[-1])
    )
    assert audit.events[-1]["event_type"] == "password_reset.request_ignored"
    assert audit.events[-1]["outcome_code"] == "rate_limited"
    unknown = f"nobody-{uuid.uuid4().hex}@example.test"
    for index in range(6):
        assert service.request_password_reset("brbots", unknown, f"198.51.102.{index}") is None
    assert audit.events[-1]["outcome_code"] == "rate_limited"
    assert len(mail.messages) == 5

    after_window.request_password_reset("brbots", email, "198.51.101.9")
    assert len(mail.messages) == 6


def test_thirty_first_reset_request_from_one_ip_in_15_minutes_is_silently_not_sent(
    account_access_database_url: str,
    recovery_control_database,  # noqa: ANN001
) -> None:
    database_url = account_access_database_url
    _thirtieth_id, thirtieth_email = _seed_active_member(database_url)
    blocked_id, blocked_email = _seed_active_member(database_url)
    mail = InMemoryMailSender()
    audit = RecordingAudit()
    service = _recovery_service(
        recovery_control_database,
        RecoveryRouter({TENANT_ID: database_url}),
        mail,
        audit=audit,
    )
    ip = "203.0.113.200"

    for index in range(29):
        service.request_password_reset(
            "brbots", f"nobody-{index}-{uuid.uuid4().hex}@example.test", ip
        )
    service.request_password_reset("brbots", thirtieth_email, ip)
    assert service.request_password_reset("brbots", blocked_email, ip) is None

    assert [message.recipient for message in mail.messages] == [thirtieth_email]
    assert _reset_tokens(database_url, blocked_id) == []
    assert audit.events[-1]["outcome_code"] == "rate_limited"
    service.request_password_reset("brbots", blocked_email, "203.0.113.201")
    assert [message.recipient for message in mail.messages] == [
        thirtieth_email,
        blocked_email,
    ]


# --- Review follow-ups ------------------------------------------------------------


def _counting_hash(monkeypatch) -> list[str]:  # noqa: ANN001
    import app.services.account_access as module

    calls: list[str] = []
    real = module.hash_password

    def counting(password: str) -> str:
        calls.append("hash")
        return real(password)

    monkeypatch.setattr(module, "hash_password", counting)
    return calls


def test_unusable_links_are_rejected_before_any_argon2id_hash(
    account_access_database_url: str, monkeypatch  # noqa: ANN001
) -> None:
    """Accept and reset are public and unthrottled: a dead link must cost no hash."""

    actor_id = _seed_admin(account_access_database_url)
    email = f"prehash-{uuid.uuid4().hex}@example.test"
    mail = InMemoryMailSender()
    service, _router, audit = _service(account_access_database_url, mail)
    _user_id, raw_token = _invite(service, mail, actor_id, email)
    hashes = _counting_hash(monkeypatch)

    for operation, event_type in (
        (service.accept_invitation, "invitation.accept_failed"),
        (service.reset_password, "password_reset.failed"),
    ):
        with pytest.raises(AccountActionLinkInvalidError):
            operation("brbots", "x" * 43, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.70")
        assert audit.events[-1]["event_type"] == event_type
    # A live invitation token is not a password-reset token either.
    with pytest.raises(AccountActionLinkInvalidError):
        service.reset_password("brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.70")
    assert hashes == []

    service.accept_invitation("brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.70")
    assert hashes == ["hash"]
    assert _read_user(account_access_database_url, email).status == "Ativo"

    with pytest.raises(AccountActionLinkInvalidError):
        service.accept_invitation("brbots", raw_token, INVITEE_PASSWORD, INVITEE_PASSWORD, "203.0.113.70")
    assert hashes == ["hash"], "a consumed link must not be hashed again"


class _FailAfterSendRouter:
    """Delegates to the real router but fails the first tenant session after the e-mail."""

    def __init__(self, inner: TenantRouter) -> None:
        self.inner = inner
        self.fail_next = False

    @contextmanager
    def tenant_session_scope(self, tenant_id: uuid.UUID):
        from app.tenant_database import TenantUnavailableError

        if self.fail_next:
            self.fail_next = False
            raise TenantUnavailableError("tenant database unavailable")
        with self.inner.tenant_session_scope(tenant_id) as session:
            yield session


class _ArmingMailSender(InMemoryMailSender):
    def __init__(self) -> None:
        super().__init__()
        self.router: _FailAfterSendRouter | None = None

    def send(self, message) -> None:  # noqa: ANN001
        super().send(message)
        assert self.router is not None
        self.router.fail_next = True


def test_sent_invitation_is_not_an_error_when_only_recording_the_delivery_fails(
    account_access_database_url: str,
) -> None:
    """The e-mail is already out; a 503 would make the admin resend and kill that link."""

    actor_id = _seed_admin(account_access_database_url)
    email = f"record-{uuid.uuid4().hex}@example.test"
    mail = _ArmingMailSender()
    service, router, audit = _service(account_access_database_url, mail)
    failing = _FailAfterSendRouter(router)
    mail.router = failing
    service._router = failing  # noqa: SLF001 - inject the post-send outage

    result = service.invite(TENANT_ID, _principal(actor_id), _command(email), "203.0.113.71")

    assert result.delivery_status == "sent"
    assert audit.events[-1]["event_type"] == "invitation.sent"
    assert audit.events[-1]["outcome_code"] == "delivery_record_failed"
    [token] = _read_tokens(account_access_database_url, result.user_id)
    assert (token.delivery_status, token.invalidated_at, token.consumed_at) == ("pending", None, None)
    raw_token = mail.messages[-1].action_link.split("#token=", 1)[1]
    assert service.inspect_action("brbots", "invitation", raw_token).email == email
