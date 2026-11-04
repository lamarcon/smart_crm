"""HTTP contract for invitation administration, acceptance and password recovery."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.auth import AuthSettings, SESSION_COOKIE_NAME
from app.main import create_app
from app.mail import InMemoryMailSender
from app.models import AccountActionToken, CrmUser, Team
from app.schemas import (
    INVALID_ACTION_LINK_MESSAGE,
    PASSWORD_MISMATCH_MESSAGE,
    PASSWORD_RESET_REQUEST_MESSAGE,
)
from app.services.account_access import (
    AccountAccessAuthorizationError,
    AccountAccessService,
    AccountAccessTenantUnavailableError,
    AccountAccessValidationError,
    AccountActionLinkInvalidError,
    AccountActionRateLimitedError,
    AccountAlreadyActiveError,
    AccountPasswordPolicyError,
    AccountReactivationStateError,
    AccountRequiresReactivationError,
    AccountUserView,
    InvitationResult,
    InvitationStateError,
    PublicActionView,
    UserAccessResult,
)
from app.tenant_database import TenantUnavailableError
from test_account_access_service import (  # noqa: F401 - fixtures
    TENANT_ID,
    RecordingAudit,
    RecoveryRouter,
    _set_workspace,
    account_access_database_url,
    recovery_control_database,
)
from test_auth_api import TENANT_ID as SESSION_TENANT_ID
from test_auth_api import TOKEN, FakeAuthGateway, FakeDatabase, FakeRouter


ORIGIN = "https://sc2030.brbots.com"
INVITED_AT = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
RAW_TOKEN = "dG9rZW4tZmljdGljaW8tcGFyYS10ZXN0ZXMtMTIzNDU2"
ADMIN_PASSWORD = "senha-admin-ficticia-2026"
INVITEE_PASSWORD = "convite-2026"
NEW_PASSWORD = "nova-senha-2026"


# --- Route contract with a recording service -------------------------------


@dataclass
class FakeAccountService:
    calls: list[tuple] = field(default_factory=list)
    failure: Exception | None = None
    delivery_status: str = "sent"
    status: str = "Pendente"

    def _maybe_fail(self) -> None:
        if self.failure is not None:
            raise self.failure

    def invite(self, tenant_id, actor, command, source_ip):  # noqa: ANN001, ANN201
        self.calls.append(("invite", tenant_id, actor.user_id, command, source_ip))
        self._maybe_fail()
        return InvitationResult(
            "user-new", "Pendente", self.delivery_status, None, workspace_version=8
        )

    def resend_invitation(self, tenant_id, actor, user_id, source_ip):  # noqa: ANN001, ANN201
        self.calls.append(("resend", tenant_id, actor.user_id, user_id, source_ip))
        self._maybe_fail()
        return InvitationResult(user_id, "Pendente", self.delivery_status, None)

    def cancel_invitation(self, tenant_id, actor, user_id):  # noqa: ANN001, ANN201
        self.calls.append(("cancel", tenant_id, actor.user_id, user_id))
        self._maybe_fail()
        self.status = "Cancelado"
        return UserAccessResult(user_id, "Cancelado")

    def reactivate_user(self, tenant_id, actor, user_id):  # noqa: ANN001, ANN201
        self.calls.append(("reactivate", tenant_id, actor.user_id, user_id))
        self._maybe_fail()
        self.status = "Ativo"
        return UserAccessResult(user_id, "Ativo")

    def account_user(self, tenant_id, actor, user_id):  # noqa: ANN001, ANN201
        self.calls.append(("account_user", user_id))
        return AccountUserView(
            id=user_id,
            name="Bia",
            email="bia@example.test",
            job_title="Vendas",
            team="Comercial",
            role="Vendedor",
            status=self.status,
            invited_at=INVITED_AT,
        )

    def inspect_action(self, slug, purpose, raw_token):  # noqa: ANN001, ANN201
        self.calls.append(("inspect", slug, purpose, raw_token))
        self._maybe_fail()
        return PublicActionView(company_name="Cliente A", email="bia@example.test")

    def accept_invitation(self, slug, raw_token, password, confirmation, source_ip):  # noqa: ANN001, ANN201
        self.calls.append(("accept", slug, raw_token, password, confirmation, source_ip))
        self._maybe_fail()

    def reset_password(self, slug, raw_token, password, confirmation, source_ip):  # noqa: ANN001, ANN201
        self.calls.append(("reset", slug, raw_token, password, confirmation, source_ip))
        self._maybe_fail()

    def request_password_reset(self, slug, email, source_ip):  # noqa: ANN001, ANN201
        self.calls.append(("forgot", slug, email, source_ip))
        self._maybe_fail()


@pytest.fixture
def account_client_factory(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>", encoding="utf-8")

    def make(role: str = "Administrador", *, with_service: bool = True):
        gateway = FakeAuthGateway(role)
        router = FakeRouter()
        service = FakeAccountService()
        app = create_app(
            database_instance=FakeDatabase(),
            static_dir=tmp_path,
            auth_service=gateway,
            tenant_router=router,
            auth_settings=AuthSettings(expected_origin=ORIGIN),
            account_access_service=service if with_service else None,
        )
        client = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)
        return client, gateway, router, service

    return make


def admin_headers(*, origin: str | None = ORIGIN, cookie: bool = True) -> dict[str, str]:
    headers: dict[str, str] = {}
    if cookie:
        headers["cookie"] = f"{SESSION_COOKIE_NAME}={TOKEN}"
    if origin is not None:
        headers["origin"] = origin
    return headers


INVITATION_BODY = {
    "name": " Bia ",
    "email": " BIA@Example.Test ",
    "jobTitle": "Vendas",
    "team": "Comercial",
    "role": "Vendedor",
}
ADMIN_ROUTES = [
    ("/api/users/invitations", INVITATION_BODY),
    ("/api/users/user-9/invitation/resend", None),
    ("/api/users/user-9/invitation/cancel", None),
    ("/api/users/user-9/reactivate", None),
]
EXPECTED_USER = {
    "id": "user-new",
    "name": "Bia",
    "email": "bia@example.test",
    "jobTitle": "Vendas",
    "team": "Comercial",
    "role": "Vendedor",
    "status": "Pendente",
    "invitedAt": "2026-11-04T12:00:00Z",
}


def _business_calls(service: FakeAccountService) -> list[tuple]:
    return [call for call in service.calls if call[0] != "account_user"]


@pytest.mark.parametrize("delivery_status", ["sent", "failed"])
def test_admin_invitation_returns_server_confirmed_user_and_delivery(
    account_client_factory, delivery_status: str
) -> None:  # noqa: ANN001
    client, _gateway, router, service = account_client_factory()
    service.delivery_status = delivery_status

    response = client.post("/api/users/invitations", headers=admin_headers(), json=INVITATION_BODY)

    assert response.status_code == 201
    assert response.json() == {
        "user": EXPECTED_USER,
        "deliveryStatus": delivery_status,
        "workspaceVersion": 8,
    }
    assert response.headers["cache-control"] == "no-store"
    [(name, tenant_id, actor_id, command, source_ip)] = _business_calls(service)
    assert (name, tenant_id, actor_id, source_ip) == (
        "invite",
        SESSION_TENANT_ID,
        "u-1",
        "testclient",
    )
    assert (command.name, command.email, command.job_title, command.role, command.team_name) == (
        "Bia",
        "bia@example.test",
        "Vendas",
        "Vendedor",
        "Comercial",
    )
    # The route authenticates without holding a tenant connection of its own.
    assert router.calls == []


@pytest.mark.parametrize(
    ("path", "name", "status"),
    [
        ("/api/users/user-9/invitation/resend", "resend", "Pendente"),
        ("/api/users/user-9/invitation/cancel", "cancel", "Cancelado"),
        ("/api/users/user-9/reactivate", "reactivate", "Ativo"),
    ],
)
def test_admin_user_actions_delegate_and_return_the_row(
    account_client_factory, path: str, name: str, status: str
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()

    response = client.post(path, headers=admin_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == "user-9"
    assert body["user"]["status"] == status
    assert ("deliveryStatus" in body) is (name == "resend")
    [call] = _business_calls(service)
    assert call[:4] == (name, SESSION_TENANT_ID, "u-1", "user-9")


@pytest.mark.parametrize(("path", "body"), ADMIN_ROUTES)
def test_admin_routes_require_a_session_before_any_side_effect(
    account_client_factory, path: str, body
) -> None:  # noqa: ANN001
    client, gateway, _router, service = account_client_factory()

    response = client.post(path, headers=admin_headers(cookie=False), json=body)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert service.calls == []
    assert gateway.security_events[-1]["outcome_code"] == "unauthenticated"


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
@pytest.mark.parametrize(("path", "body"), ADMIN_ROUTES)
def test_admin_routes_reject_invalid_origin_before_reading_the_session(
    account_client_factory, path: str, body, origin
) -> None:  # noqa: ANN001
    client, gateway, _router, service = account_client_factory()

    response = client.post(path, headers=admin_headers(origin=origin), json=body)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"
    assert service.calls == []
    assert gateway.calls == []


@pytest.mark.parametrize("role", ["Gestor", "Vendedor", "Assistente", "Faturamento"])
@pytest.mark.parametrize(("path", "body"), ADMIN_ROUTES)
def test_non_admin_receives_403_without_service_call(
    account_client_factory, role: str, path: str, body
) -> None:  # noqa: ANN001
    client, gateway, _router, service = account_client_factory(role)

    response = client.post(path, headers=admin_headers(), json=body)

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "forbidden", "message": "Acesso negado."}
    assert service.calls == []
    assert gateway.security_events[-1]["outcome_code"] == "forbidden"


@pytest.mark.parametrize(
    "changes",
    [{"email": "invalido"}, {"role": "Dono"}, {"name": ""}, {"status": "Ativo"}, {"jobTitle": "x" * 256}],
)
def test_invalid_invitation_body_is_rejected_without_service_call(
    account_client_factory, changes
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()

    response = client.post(
        "/api/users/invitations", headers=admin_headers(), json={**INVITATION_BODY, **changes}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


def test_user_id_path_is_bounded(account_client_factory) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()

    response = client.post(f"/api/users/{'u' * 129}/invitation/cancel", headers=admin_headers())

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (AccountActionRateLimitedError("limit"), 429, "rate_limited"),
        (AccountAlreadyActiveError("active"), 409, "account_active"),
        (AccountRequiresReactivationError("inactive"), 409, "account_inactive"),
        (InvitationStateError("not pending"), 409, "invitation_not_pending"),
        (AccountReactivationStateError("not inactive"), 409, "account_not_inactive"),
        (AccountAccessValidationError("invalid"), 422, "validation_error"),
        (AccountAccessTenantUnavailableError("down"), 503, "tenant_unavailable"),
        (TenantUnavailableError("down"), 503, "tenant_unavailable"),
        (AccountAccessAuthorizationError("denied"), 403, "forbidden"),
    ],
)
@pytest.mark.parametrize(("path", "body"), ADMIN_ROUTES)
def test_admin_service_outcomes_map_to_stable_errors(
    account_client_factory, path: str, body, failure: Exception, status: int, code: str
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()
    service.failure = failure

    response = client.post(path, headers=admin_headers(), json=body)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert str(failure) not in response.json()["error"]["message"]
    if status == 429:
        assert response.headers["retry-after"] == "900"
    assert [call[0] for call in service.calls if call[0] == "account_user"] == []


def test_admin_database_failure_is_a_redacted_503(account_client_factory) -> None:  # noqa: ANN001
    from sqlalchemy.exc import OperationalError

    client, _gateway, _router, service = account_client_factory()
    service.failure = OperationalError("SELECT secret", {}, Exception("password=hunter2"))

    response = client.post("/api/users/invitations", headers=admin_headers(), json=INVITATION_BODY)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "hunter2" not in response.text


def test_routes_report_unavailable_when_the_service_is_not_configured(account_client_factory) -> None:  # noqa: ANN001
    client, _gateway, _router, _service = account_client_factory(with_service=False)

    admin = client.post("/api/users/invitations", headers=admin_headers(), json=INVITATION_BODY)
    inspect = client.post(
        "/api/auth/invitations/inspect",
        headers={"origin": ORIGIN},
        json={"slug": "cliente-a", "token": RAW_TOKEN},
    )
    forgot = client.post(
        "/api/auth/password/forgot",
        headers={"origin": ORIGIN},
        json={"slug": "cliente-a", "email": "a@example.test"},
    )

    assert (admin.status_code, admin.json()["error"]["code"]) == (503, "account_access_unavailable")
    assert inspect.status_code == 503
    assert (forgot.status_code, forgot.json()) == (202, {"message": PASSWORD_RESET_REQUEST_MESSAGE})


def test_admin_routes_need_the_cookie_resolver(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("shell", encoding="utf-8")
    service = FakeAccountService()
    app = create_app(
        database_instance=FakeDatabase(),
        static_dir=tmp_path,
        principal_dependency=lambda: None,
        account_access_service=service,
    )
    client = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)

    response = client.post("/api/users/invitations", headers=admin_headers(), json=INVITATION_BODY)

    assert (response.status_code, response.json()["error"]["code"]) == (503, "auth_unavailable")
    assert service.calls == []


INSPECT_ROUTES = [
    ("/api/auth/invitations/inspect", "invitation"),
    ("/api/auth/password/reset/inspect", "password_reset"),
]
PASSWORD_ROUTES = [
    ("/api/auth/invitations/accept", "accept"),
    ("/api/auth/password/reset", "reset"),
]
INVALID_LINK = {"error": {"code": "invalid_link", "message": INVALID_ACTION_LINK_MESSAGE}}


def _password_body(**changes: object) -> dict[str, object]:
    return {
        "slug": "Cliente-A",
        "token": RAW_TOKEN,
        "password": INVITEE_PASSWORD,
        "password_confirmation": INVITEE_PASSWORD,
        **changes,
    }


@pytest.mark.parametrize(("path", "purpose"), INSPECT_ROUTES)
def test_inspect_returns_only_company_and_email_without_session(
    account_client_factory, path: str, purpose: str
) -> None:  # noqa: ANN001
    client, gateway, router, service = account_client_factory()

    response = client.post(path, headers={"origin": ORIGIN}, json={"slug": "Cliente-A", "token": RAW_TOKEN})

    assert response.status_code == 200
    assert response.json() == {"company_name": "Cliente A", "email": "bia@example.test"}
    assert service.calls == [("inspect", "cliente-a", purpose, RAW_TOKEN)]
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert gateway.calls == [] and router.calls == []


@pytest.mark.parametrize(("path", "purpose"), INSPECT_ROUTES)
@pytest.mark.parametrize(
    "body",
    [
        {"slug": "cliente-a"},
        {"slug": "cliente-a", "token": ""},
        {"slug": "cliente-a", "token": "t" * 513},
        {"slug": "api", "token": RAW_TOKEN},
        {"slug": "cliente-a", "token": RAW_TOKEN, "tenant_id": str(uuid.uuid4())},
        {"token": RAW_TOKEN},
        None,
    ],
)
def test_inspect_malformed_links_get_the_single_invalid_link_answer(
    account_client_factory, path: str, purpose: str, body
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()

    response = client.post(path, headers={"origin": ORIGIN}, json=body)

    assert (response.status_code, response.json()) == (400, INVALID_LINK)
    assert service.calls == []


@pytest.mark.parametrize(("path", "purpose"), INSPECT_ROUTES)
def test_inspect_unusable_link_gets_the_same_answer(
    account_client_factory, path: str, purpose: str
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()
    service.failure = AccountActionLinkInvalidError()

    response = client.post(path, headers={"origin": ORIGIN}, json={"slug": "cliente-a", "token": RAW_TOKEN})

    assert (response.status_code, response.json()) == (400, INVALID_LINK)


@pytest.mark.parametrize(
    "path", [path for path, _ in INSPECT_ROUTES] + [path for path, _ in PASSWORD_ROUTES]
)
def test_token_routes_never_accept_query_parameters(account_client_factory, path: str) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()

    response = client.post(
        f"{path}?token={RAW_TOKEN}",
        headers={"origin": ORIGIN},
        json=_password_body() if "inspect" not in path else {"slug": "cliente-a", "token": RAW_TOKEN},
    )

    assert (response.status_code, response.json()) == (400, INVALID_LINK)
    assert service.calls == []


@pytest.mark.parametrize(
    "path",
    [path for path, _ in INSPECT_ROUTES]
    + [path for path, _ in PASSWORD_ROUTES]
    + ["/api/auth/password/forgot"],
)
@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_public_routes_require_the_expected_origin(account_client_factory, path: str, origin) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()
    headers = {} if origin is None else {"origin": origin}

    response = client.post(path, headers=headers, json=_password_body(email="a@example.test"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"
    assert service.calls == []


@pytest.mark.parametrize(("path", "name"), PASSWORD_ROUTES)
def test_password_routes_complete_without_creating_a_session(
    account_client_factory, path: str, name: str
) -> None:  # noqa: ANN001
    client, gateway, _router, service = account_client_factory()

    response = client.post(path, headers={"origin": ORIGIN}, json=_password_body())

    assert response.status_code == 204
    assert response.content == b""
    assert "set-cookie" not in response.headers
    assert service.calls == [
        (name, "cliente-a", RAW_TOKEN, INVITEE_PASSWORD, INVITEE_PASSWORD, "testclient")
    ]
    assert gateway.calls == []


@pytest.mark.parametrize(("path", "name"), PASSWORD_ROUTES)
@pytest.mark.parametrize(
    ("changes", "code", "message"),
    [
        ({"password_confirmation": "outra-senha"}, "password_mismatch", PASSWORD_MISMATCH_MESSAGE),
        ({"password": "curta", "password_confirmation": "curta"}, "invalid_password", None),
        ({"password": "p" * 129, "password_confirmation": "p" * 129}, "invalid_password", None),
        ({"password_confirmation": None}, "invalid_password", None),
    ],
)
def test_password_routes_explain_password_problems_without_calling_the_service(
    account_client_factory, path: str, name: str, changes, code: str, message
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()

    response = client.post(path, headers={"origin": ORIGIN}, json=_password_body(**changes))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    if message is not None:
        assert response.json()["error"]["message"] == message
    assert INVITEE_PASSWORD not in response.text
    assert service.calls == []


@pytest.mark.parametrize(("path", "name"), PASSWORD_ROUTES)
@pytest.mark.parametrize(
    "changes",
    [{"token": ""}, {"token": None}, {"slug": "cliente_a"}, {"tenant_id": "x"}],
)
def test_password_routes_with_malformed_links_get_invalid_link(
    account_client_factory, path: str, name: str, changes
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()

    response = client.post(path, headers={"origin": ORIGIN}, json=_password_body(**changes))

    assert (response.status_code, response.json()) == (400, INVALID_LINK)
    assert service.calls == []


@pytest.mark.parametrize(("path", "name"), PASSWORD_ROUTES)
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (AccountActionLinkInvalidError(), 400, "invalid_link"),
        (AccountPasswordPolicyError("password_length"), 422, "invalid_password"),
        (AccountPasswordPolicyError("password_mismatch"), 422, "password_mismatch"),
    ],
)
def test_password_route_service_outcomes(
    account_client_factory, path: str, name: str, failure, status: int, code: str
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()
    service.failure = failure

    response = client.post(path, headers={"origin": ORIGIN}, json=_password_body())

    assert (response.status_code, response.json()["error"]["code"]) == (status, code)


@pytest.mark.parametrize(
    "failure", [None, RuntimeError("smtp password=hunter2"), TenantUnavailableError("down")]
)
def test_forgot_password_always_answers_202_and_runs_after_the_response(
    account_client_factory, failure
) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()
    service.failure = failure

    response = client.post(
        "/api/auth/password/forgot",
        headers={"origin": ORIGIN},
        json={"slug": "Cliente-A", "email": " Ana@Example.Test "},
    )

    assert (response.status_code, response.json()) == (202, {"message": PASSWORD_RESET_REQUEST_MESSAGE})
    assert "hunter2" not in response.text
    assert service.calls == [("forgot", "cliente-a", "ana@example.test", "testclient")]


@pytest.mark.parametrize(
    "body",
    [
        {"slug": "cliente-a", "email": "invalido"},
        {"slug": "cliente_a", "email": "a@example.test"},
        {"slug": "cliente-a"},
        {"slug": "cliente-a", "email": "a@example.test", "token": RAW_TOKEN},
        None,
    ],
)
def test_forgot_password_malformed_requests_get_the_same_202(account_client_factory, body) -> None:  # noqa: ANN001
    client, _gateway, _router, service = account_client_factory()

    response = client.post("/api/auth/password/forgot", headers={"origin": ORIGIN}, json=body)

    assert (response.status_code, response.json()) == (202, {"message": PASSWORD_RESET_REQUEST_MESSAGE})
    assert service.calls == []


@pytest.mark.parametrize("page", ["accept-invite", "reset-password"])
def test_public_pages_serve_the_shell_without_reading_a_session(account_client_factory, page: str) -> None:  # noqa: ANN001
    client, gateway, _router, service = account_client_factory()

    response = client.get(f"/Cliente-A/{page}", headers={"cookie": f"{SESSION_COOKIE_NAME}={TOKEN}"})
    invalid = client.get(f"/cliente_a/{page}")

    assert response.status_code == 200
    assert "<title>shell</title>" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert gateway.calls == [] and service.calls == []
    assert invalid.status_code == 404


# --- End to end on PostgreSQL ----------------------------------------------


def _engine(database_url: str):  # noqa: ANN202
    return create_engine(database_url, poolclass=NullPool)


def _seed_member(
    database_url: str,
    *,
    role: str,
    status: str = "Ativo",
    password: str | None = ADMIN_PASSWORD,
    email: str | None = None,
    normalized: bool = True,
) -> tuple[str, str]:
    from app.security.passwords import hash_password

    user_id = f"user-{uuid.uuid4().hex}"
    address = email or f"{user_id}@example.test"
    engine = _engine(database_url)
    try:
        with Session(bind=engine) as session, session.begin():
            _set_workspace(session)
            session.add(
                CrmUser(
                    id=user_id,
                    workspace_id="default",
                    name=user_id,
                    email=address,
                    normalized_email=address.lower() if normalized else None,
                    password_hash=hash_password(password) if password else None,
                    auth_enabled=password is not None,
                    auth_version=1,
                    job_title="",
                    role=role,
                    status=status,
                    payload={},
                )
            )
    finally:
        engine.dispose()
    return user_id, address.lower()


def _user(database_url: str, user_id: str) -> CrmUser:
    engine = _engine(database_url)
    try:
        with Session(bind=engine, expire_on_commit=False) as session, session.begin():
            _set_workspace(session)
            return session.get(CrmUser, user_id)
    finally:
        engine.dispose()


def _count(database_url: str, model, *conditions) -> int:  # noqa: ANN001
    from sqlalchemy import func

    engine = _engine(database_url)
    try:
        with Session(bind=engine) as session, session.begin():
            _set_workspace(session)
            return session.scalar(select(func.count()).select_from(model).where(*conditions))
    finally:
        engine.dispose()


@dataclass
class LiveStack:
    client: TestClient
    mail: InMemoryMailSender
    audit: RecordingAudit
    database_url: str

    def login(self, email: str, password: str) -> str:
        response = self.client.post(
            "/api/auth/login",
            headers={"origin": ORIGIN},
            json={"slug": "brbots", "email": email, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.cookies[SESSION_COOKIE_NAME]

    def admin(self, token: str) -> dict[str, str]:
        return {"origin": ORIGIN, "cookie": f"{SESSION_COOKIE_NAME}={token}"}

    def link_token(self, index: int = -1) -> str:
        return self.mail.messages[index].action_link.split("#token=", 1)[1]


@pytest.fixture
def live_stack(account_access_database_url: str, recovery_control_database, tmp_path: Path):  # noqa: ANN001, F811
    from app.services.auth import AuthService

    (tmp_path / "index.html").write_text("shell", encoding="utf-8")
    router = RecoveryRouter({TENANT_ID: account_access_database_url})
    audit = RecordingAudit()
    mail = InMemoryMailSender()
    auth = AuthService(recovery_control_database, router, security_audit=audit)
    service = AccountAccessService(
        recovery_control_database,
        router,
        mail,
        public_origin=ORIGIN,
        security_audit=audit,
    )
    app = create_app(
        database_instance=FakeDatabase(),
        static_dir=tmp_path,
        auth_service=auth,
        tenant_router=router,
        auth_settings=AuthSettings(expected_origin=ORIGIN),
        account_access_service=service,
    )
    client = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)
    return LiveStack(client, mail, audit, account_access_database_url)


def test_live_invite_accept_and_login_round_trip(live_stack: LiveStack) -> None:
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    session = live_stack.login(admin_email, ADMIN_PASSWORD)
    email = f"novo-{uuid.uuid4().hex[:8]}@example.test"

    created = live_stack.client.post(
        "/api/users/invitations",
        headers=live_stack.admin(session),
        json={"name": "Novo", "email": email.upper(), "jobTitle": "Vendas", "team": "Equipe API", "role": "Vendedor"},
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["deliveryStatus"] == "sent"
    assert {key: body["user"][key] for key in ("email", "team", "status", "role")} == {
        "email": email,
        "team": "Equipe API",
        "status": "Pendente",
        "role": "Vendedor",
    }
    link = live_stack.mail.messages[-1].action_link
    assert link.startswith(f"{ORIGIN}/brbots/accept-invite#token=")
    token = live_stack.link_token()
    assert token not in created.text
    assert _count(live_stack.database_url, Team, Team.name == "Equipe API") == 1

    inspected = live_stack.client.post(
        "/api/auth/invitations/inspect", headers={"origin": ORIGIN}, json={"slug": "brbots", "token": token}
    )
    assert inspected.json() == {"company_name": "BRBots", "email": email}

    accepted = live_stack.client.post(
        "/api/auth/invitations/accept",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "token": token, "password": INVITEE_PASSWORD, "password_confirmation": INVITEE_PASSWORD},
    )
    assert accepted.status_code == 204
    assert "set-cookie" not in accepted.headers
    user = _user(live_stack.database_url, body["user"]["id"])
    assert (user.status, user.auth_enabled) == ("Ativo", True)
    assert live_stack.login(email, INVITEE_PASSWORD)

    replay = live_stack.client.post(
        "/api/auth/invitations/accept",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "token": token, "password": "outra-senha-2026", "password_confirmation": "outra-senha-2026"},
    )
    assert (replay.status_code, replay.json()) == (400, INVALID_LINK)
    other_tenant = live_stack.client.post(
        "/api/auth/invitations/inspect", headers={"origin": ORIGIN}, json={"slug": "outra", "token": token}
    )
    assert (other_tenant.status_code, other_tenant.json()) == (400, INVALID_LINK)


def test_live_resend_and_cancel_replace_and_end_the_invitation(live_stack: LiveStack) -> None:
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    session = live_stack.login(admin_email, ADMIN_PASSWORD)
    email = f"reenvio-{uuid.uuid4().hex[:8]}@example.test"
    created = live_stack.client.post(
        "/api/users/invitations",
        headers=live_stack.admin(session),
        json={"name": "Reenvio", "email": email, "jobTitle": "Vendas", "role": "Assistente"},
    ).json()
    user_id = created["user"]["id"]
    first_token = live_stack.link_token()

    resent = live_stack.client.post(
        f"/api/users/{user_id}/invitation/resend", headers=live_stack.admin(session)
    )
    assert resent.status_code == 200
    assert resent.json()["deliveryStatus"] == "sent"
    second_token = live_stack.link_token()
    stale = live_stack.client.post(
        "/api/auth/invitations/inspect", headers={"origin": ORIGIN}, json={"slug": "brbots", "token": first_token}
    )
    assert stale.status_code == 400

    cancelled = live_stack.client.post(
        f"/api/users/{user_id}/invitation/cancel", headers=live_stack.admin(session)
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["user"]["status"] == "Cancelado"
    after_cancel = live_stack.client.post(
        "/api/auth/invitations/inspect", headers={"origin": ORIGIN}, json={"slug": "brbots", "token": second_token}
    )
    assert after_cancel.status_code == 400
    again = live_stack.client.post(
        f"/api/users/{user_id}/invitation/cancel", headers=live_stack.admin(session)
    )
    assert (again.status_code, again.json()["error"]["code"]) == (409, "invitation_not_pending")


def test_live_non_admin_cannot_invite_and_nothing_is_written(live_stack: LiveStack) -> None:
    _member_id, member_email = _seed_member(live_stack.database_url, role="Gestor")
    session = live_stack.login(member_email, ADMIN_PASSWORD)
    email = f"negado-{uuid.uuid4().hex[:8]}@example.test"

    response = live_stack.client.post(
        "/api/users/invitations",
        headers=live_stack.admin(session),
        json={"name": "Negado", "email": email, "jobTitle": "Vendas", "role": "Vendedor"},
    )

    assert response.status_code == 403
    assert _count(live_stack.database_url, CrmUser, CrmUser.normalized_email == email) == 0
    assert live_stack.mail.messages == []


def test_live_invitation_account_limit_returns_429_without_sending(live_stack: LiveStack) -> None:
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    session = live_stack.login(admin_email, ADMIN_PASSWORD)
    email = f"limite-{uuid.uuid4().hex[:8]}@example.test"
    body = {"name": "Limite", "email": email, "jobTitle": "Vendas", "role": "Vendedor"}

    statuses = [
        live_stack.client.post("/api/users/invitations", headers=live_stack.admin(session), json=body).status_code
        for _ in range(5)
    ]
    sent_before = len(live_stack.mail.messages)
    sixth = live_stack.client.post("/api/users/invitations", headers=live_stack.admin(session), json=body)

    assert statuses == [201] * 5
    assert sent_before == 5
    assert (sixth.status_code, sixth.json()["error"]["code"]) == (429, "rate_limited")
    assert sixth.headers["retry-after"] == "900"
    assert len(live_stack.mail.messages) == 5
    invitee = _user_by_email(live_stack.database_url, email)
    live = _count(
        live_stack.database_url,
        AccountActionToken,
        AccountActionToken.user_id == invitee.id,
        AccountActionToken.invalidated_at.is_(None),
    )
    assert live == 1
    resend = live_stack.client.post(
        f"/api/users/{invitee.id}/invitation/resend", headers=live_stack.admin(session)
    )
    assert resend.status_code == 429
    assert len(live_stack.mail.messages) == 5
    assert any(event["event_type"] == "invitation.rate_limited" for event in live_stack.audit.events)


def test_live_invitation_ip_limit_returns_429_on_the_31st_request(live_stack: LiveStack) -> None:
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    session = live_stack.login(admin_email, ADMIN_PASSWORD)
    prefix = uuid.uuid4().hex[:8]

    statuses = [
        live_stack.client.post(
            "/api/users/invitations",
            headers=live_stack.admin(session),
            json={"name": f"IP {index}", "email": f"ip-{prefix}-{index}@example.test", "jobTitle": "Vendas", "role": "Vendedor"},
        ).status_code
        for index in range(31)
    ]

    assert statuses == [201] * 30 + [429]
    assert len(live_stack.mail.messages) == 30
    assert _count(
        live_stack.database_url, CrmUser, CrmUser.normalized_email == f"ip-{prefix}-30@example.test"
    ) == 0


def _user_by_email(database_url: str, email: str) -> CrmUser:
    engine = _engine(database_url)
    try:
        with Session(bind=engine, expire_on_commit=False) as session, session.begin():
            _set_workspace(session)
            return session.scalar(select(CrmUser).where(CrmUser.normalized_email == email))
    finally:
        engine.dispose()


@pytest.mark.parametrize(("status", "code"), [("Ativo", "account_active"), ("Inativo", "account_inactive")])
def test_live_invite_matches_legacy_roster_users_case_insensitively(
    live_stack: LiveStack, status: str, code: str
) -> None:
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    session = live_stack.login(admin_email, ADMIN_PASSWORD)
    legacy_id, legacy_email = _seed_member(
        live_stack.database_url,
        role="Vendedor",
        status=status,
        password=None,
        email=f"Legado-{uuid.uuid4().hex[:8]}@Example.Test",
        normalized=False,
    )

    response = live_stack.client.post(
        "/api/users/invitations",
        headers=live_stack.admin(session),
        json={"name": "Legado", "email": legacy_email, "jobTitle": "Vendas", "role": "Vendedor"},
    )

    assert (response.status_code, response.json()["error"]["code"]) == (409, code)
    assert _user(live_stack.database_url, legacy_id).status == status
    assert live_stack.mail.messages == []


def test_live_cancelled_legacy_user_is_reinvited_without_duplicate(live_stack: LiveStack) -> None:
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    session = live_stack.login(admin_email, ADMIN_PASSWORD)
    legacy_id, legacy_email = _seed_member(
        live_stack.database_url,
        role="Vendedor",
        status="Cancelado",
        password=None,
        email=f"Volta-{uuid.uuid4().hex[:8]}@Example.Test",
        normalized=False,
    )

    response = live_stack.client.post(
        "/api/users/invitations",
        headers=live_stack.admin(session),
        json={"name": "Volta", "email": legacy_email, "jobTitle": "Vendas", "role": "Vendedor"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["user"]["id"] == legacy_id
    row = _user(live_stack.database_url, legacy_id)
    assert (row.status, row.normalized_email) == ("Pendente", legacy_email)


def test_live_reactivation_is_admin_only_and_requires_inactive(live_stack: LiveStack) -> None:
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    admin_session = live_stack.login(admin_email, ADMIN_PASSWORD)
    _manager_id, manager_email = _seed_member(live_stack.database_url, role="Gestor")
    manager_session = live_stack.login(manager_email, ADMIN_PASSWORD)
    inactive_id, inactive_email = _seed_member(
        live_stack.database_url, role="Vendedor", status="Inativo"
    )

    denied = live_stack.client.post(
        f"/api/users/{inactive_id}/reactivate", headers=live_stack.admin(manager_session)
    )
    assert denied.status_code == 403
    assert _user(live_stack.database_url, inactive_id).status == "Inativo"

    reactivated = live_stack.client.post(
        f"/api/users/{inactive_id}/reactivate", headers=live_stack.admin(admin_session)
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["user"]["status"] == "Ativo"
    row = _user(live_stack.database_url, inactive_id)
    assert (row.status, row.auth_version) == ("Ativo", 2)
    assert live_stack.login(inactive_email, ADMIN_PASSWORD)
    assert any(
        event["event_type"] == "user.reactivated" and event["user_id"] == inactive_id
        for event in live_stack.audit.events
    )

    again = live_stack.client.post(
        f"/api/users/{inactive_id}/reactivate", headers=live_stack.admin(admin_session)
    )
    assert (again.status_code, again.json()["error"]["code"]) == (409, "account_not_inactive")
    assert _user(live_stack.database_url, inactive_id).auth_version == 2


def test_live_password_recovery_revokes_sessions_and_uses_the_new_password(live_stack: LiveStack) -> None:
    member_id, member_email = _seed_member(live_stack.database_url, role="Vendedor")
    old_session = live_stack.login(member_email, ADMIN_PASSWORD)

    unknown = live_stack.client.post(
        "/api/auth/password/forgot",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "email": f"ninguem-{uuid.uuid4().hex[:6]}@example.test"},
    )
    known = live_stack.client.post(
        "/api/auth/password/forgot", headers={"origin": ORIGIN}, json={"slug": "brbots", "email": member_email}
    )
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json() == {"message": PASSWORD_RESET_REQUEST_MESSAGE}
    assert len(live_stack.mail.messages) == 1
    link = live_stack.mail.messages[-1].action_link
    assert link.startswith(f"{ORIGIN}/brbots/reset-password#token=")
    token = live_stack.link_token()

    inspected = live_stack.client.post(
        "/api/auth/password/reset/inspect", headers={"origin": ORIGIN}, json={"slug": "brbots", "token": token}
    )
    assert inspected.status_code == 200
    reset = live_stack.client.post(
        "/api/auth/password/reset",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD},
    )
    assert reset.status_code == 204

    stale = live_stack.client.get(
        "/api/auth/session", headers={"cookie": f"{SESSION_COOKIE_NAME}={old_session}"}
    )
    assert stale.status_code == 401
    assert live_stack.login(member_email, NEW_PASSWORD)
    old_password = live_stack.client.post(
        "/api/auth/login",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "email": member_email, "password": ADMIN_PASSWORD},
    )
    assert old_password.status_code == 401
    replay = live_stack.client.post(
        "/api/auth/password/reset",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "token": token, "password": "terceira-2026", "password_confirmation": "terceira-2026"},
    )
    assert (replay.status_code, replay.json()) == (400, INVALID_LINK)
    assert _user(live_stack.database_url, member_id).auth_version == 2


# --- Account actions advance the workspace version ------------------------------


def _workspace_version(database_url: str, *, initialize_at: int | None = None) -> int | None:
    """Read (and optionally create/initialize) the shared ``default`` workspace row."""

    from app.models import Workspace

    engine = _engine(database_url)
    try:
        with Session(bind=engine) as session, session.begin():
            _set_workspace(session)
            workspace = session.get(Workspace, "default")
            if initialize_at is not None:
                if workspace is None:
                    workspace = Workspace(id="default", version=initialize_at)
                    session.add(workspace)
                workspace.version = initialize_at
                workspace.initialized_at = datetime.now(timezone.utc)
                session.flush()
            return None if workspace is None else workspace.version
    finally:
        engine.dispose()


def test_live_account_actions_advance_the_workspace_version_once_each(live_stack: LiveStack) -> None:
    """Regression: a tab loaded before an account change must get 409, not overwrite it.

    Every action that changes a user visible in the snapshot (invite, resend,
    cancel, accept, reactivate) advances the version in the same transaction and
    returns it; failed actions and password resets leave it unchanged.
    """

    url = live_stack.database_url
    version = _workspace_version(url, initialize_at=40)
    _admin_id, admin_email = _seed_member(url, role="Administrador")
    admin = live_stack.admin(live_stack.login(admin_email, ADMIN_PASSWORD))
    email = f"versao-{uuid.uuid4().hex[:8]}@example.test"

    created = live_stack.client.post(
        "/api/users/invitations",
        headers=admin,
        json={"name": "Versão", "email": email, "jobTitle": "Vendas", "team": None, "role": "Vendedor"},
    )
    assert created.status_code == 201, created.text
    version += 1
    assert created.json()["workspaceVersion"] == version == _workspace_version(url)
    user_id = created.json()["user"]["id"]

    resent = live_stack.client.post(f"/api/users/{user_id}/invitation/resend", headers=admin)
    version += 1
    assert resent.json()["workspaceVersion"] == version == _workspace_version(url)

    duplicate_active = live_stack.client.post(
        "/api/users/invitations",
        headers=admin,
        json={"name": "Admin", "email": admin_email, "jobTitle": "Diretora", "team": None, "role": "Vendedor"},
    )
    assert duplicate_active.status_code == 409
    assert _workspace_version(url) == version, "a rejected invitation must not advance the version"

    invalid_accept = live_stack.client.post(
        "/api/auth/invitations/accept",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "token": "x" * 43, "password": INVITEE_PASSWORD, "password_confirmation": INVITEE_PASSWORD},
    )
    assert invalid_accept.status_code == 400
    assert _workspace_version(url) == version

    accepted = live_stack.client.post(
        "/api/auth/invitations/accept",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "token": live_stack.link_token(), "password": INVITEE_PASSWORD, "password_confirmation": INVITEE_PASSWORD},
    )
    assert accepted.status_code == 204
    version += 1
    assert _workspace_version(url) == version

    live_stack.client.post(
        "/api/auth/password/forgot", headers={"origin": ORIGIN}, json={"slug": "brbots", "email": email}
    )
    reset = live_stack.client.post(
        "/api/auth/password/reset",
        headers={"origin": ORIGIN},
        json={"slug": "brbots", "token": live_stack.link_token(), "password": "redefinida-2026", "password_confirmation": "redefinida-2026"},
    )
    assert reset.status_code == 204
    assert _workspace_version(url) == version, "a password reset changes nothing the snapshot shows"

    other = f"cancelar-{uuid.uuid4().hex[:8]}@example.test"
    pending = live_stack.client.post(
        "/api/users/invitations",
        headers=admin,
        json={"name": "Cancelar", "email": other, "jobTitle": "SDR", "team": None, "role": "Vendedor"},
    ).json()
    version += 1
    cancelled = live_stack.client.post(
        f"/api/users/{pending['user']['id']}/invitation/cancel", headers=admin
    )
    version += 1
    assert cancelled.json()["workspaceVersion"] == version == _workspace_version(url)
    cancelled_again = live_stack.client.post(
        f"/api/users/{pending['user']['id']}/invitation/cancel", headers=admin
    )
    assert cancelled_again.status_code == 409
    assert _workspace_version(url) == version

    inactive_id, _inactive_email = _seed_member(url, role="Vendedor", status="Inativo")
    reactivated = live_stack.client.post(f"/api/users/{inactive_id}/reactivate", headers=admin)
    version += 1
    assert reactivated.json()["workspaceVersion"] == version == _workspace_version(url)
