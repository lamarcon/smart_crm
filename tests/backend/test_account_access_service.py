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
TENANT_HEAD = "b4e2c9a7d6f1"
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
