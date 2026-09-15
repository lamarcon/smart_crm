from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthSettings, SESSION_COOKIE_NAME
from app.main import create_app
from app.policies import PrincipalScope
from app.schemas import LOGIN_FAILURE_MESSAGE, PersistedCounts, WorkspaceState
from app.services.auth import (
    AuthenticationError,
    LoginResult,
    SessionContext,
    TenantLocation,
)
from app.services.workspace import WorkspaceLoad, WorkspaceResult
from app.tenant_database import TenantUnavailableError


ORIGIN = "https://sc2030.brbots.com"
TOKEN = "S" * 43
TENANT_ID = uuid4()
STATE = WorkspaceState.model_validate(
    {
        "users": [], "leads": [], "contacts": [], "companies": [], "deals": [],
        "notifications": [], "customFieldSchemas": {}, "moduleFieldSettings": {}, "ui": {},
    }
)
COUNTS = PersistedCounts(
    users=0, leads=0, contacts=0, companies=0, deals=0,
    quotes=0, notifications=0, customFields=0,
)


def session_context(role: str = "Administrador", slug: str = "cliente-a") -> SessionContext:
    return SessionContext(
        principal=PrincipalScope(
            tenant_id=TENANT_ID,
            workspace_id="default",
            user_id="u-1",
            role=role,
            team_id="team-a",
            auth_version=2,
        ),
        tenant_slug=slug,
        tenant_display_name="Cliente A",
        user_name="Ana",
        email="ana@example.test",
        token_digest="d" * 64,
    )


class FakeAuthGateway:
    def __init__(self, role: str = "Administrador") -> None:
        self.context = session_context(role)
        self.location = TenantLocation(TENANT_ID, "cliente-a", "Cliente A")
        self.login_failure: Exception | None = None
        self.session_failure: Exception | None = None
        self.calls: list[tuple] = []

    def locate_tenant(self, slug: str):  # noqa: ANN201
        self.calls.append(("locate", slug))
        return self.location if slug == "cliente-a" else None

    def login(self, slug: str, email: str, password: str, ip_address: str, *, now):  # noqa: ANN001, ANN201
        self.calls.append(("login", slug, email, password, ip_address))
        if self.login_failure is not None:
            raise self.login_failure
        return LoginResult(token=TOKEN, context=self.context)

    def current_session(self, token: str, *, now):  # noqa: ANN001, ANN201
        self.calls.append(("session", token))
        if self.session_failure is not None:
            raise self.session_failure
        if token != TOKEN:
            raise AuthenticationError("invalid")
        return self.context

    def logout(self, token: str, *, now):  # noqa: ANN001, ANN201
        self.calls.append(("logout", token))
        return token == TOKEN


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list = []
        self.unavailable = False

    @contextmanager
    def tenant_session_scope(self, tenant_id):  # noqa: ANN001, ANN201
        self.calls.append(tenant_id)
        if self.unavailable:
            raise TenantUnavailableError("tenant unavailable")
        yield SimpleNamespace(marker="tenant-a")


@dataclass
class FakeWorkspaceService:
    calls: list[tuple] = field(default_factory=list)

    def load(self) -> WorkspaceLoad:
        self.calls.append(("load",))
        return WorkspaceLoad(True, 1, STATE)

    def bootstrap(self, state: WorkspaceState) -> WorkspaceResult:
        self.calls.append(("bootstrap", state))
        return WorkspaceResult(1, STATE, COUNTS)

    def save(self, version: int, state: WorkspaceState) -> WorkspaceResult:
        self.calls.append(("save", version, state))
        return WorkspaceResult(version + 1, STATE, COUNTS)

    def reset(self, version: int, state: WorkspaceState) -> WorkspaceResult:
        self.calls.append(("reset", version, state))
        return WorkspaceResult(version + 1, STATE, COUNTS)

    def list_deleted(self, module: str) -> list[dict]:
        self.calls.append(("list_deleted", module))
        return []

    def restore(self, version: int, module: str, record_id: str) -> WorkspaceResult:
        self.calls.append(("restore", version, module, record_id))
        return WorkspaceResult(version + 1, STATE, COUNTS)


class FakeDatabase:
    def check_database(self) -> bool:
        return True


@pytest.fixture
def secure_client_factory(tmp_path: Path):
    (tmp_path / "index.html").write_text("<!doctype html><title>tenant shell</title>", encoding="utf-8")

    def make(role: str = "Administrador"):
        gateway = FakeAuthGateway(role)
        router = FakeRouter()
        workspace = FakeWorkspaceService()
        app = create_app(
            database_instance=FakeDatabase(),
            workspace_service=workspace,
            static_dir=tmp_path,
            auth_service=gateway,
            tenant_router=router,
            auth_settings=AuthSettings(expected_origin=ORIGIN),
        )
        return TestClient(app, base_url=ORIGIN, raise_server_exceptions=False), gateway, router, workspace

    return make


def auth_headers(*, origin: bool = False) -> dict[str, str]:
    headers = {"cookie": f"{SESSION_COOKIE_NAME}={TOKEN}"}
    if origin:
        headers["origin"] = ORIGIN
    return headers


def test_locate_returns_canonical_active_tenant_without_session(secure_client_factory) -> None:  # noqa: ANN001
    client, gateway, router, _workspace = secure_client_factory()

    response = client.post("/api/auth/locate", headers={"origin": ORIGIN}, json={"identifier": "CLIENTE-A"})

    assert response.status_code == 200
    assert response.json() == {"slug": "cliente-a", "display_name": "Cliente A"}
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")
    assert gateway.calls == [("locate", "cliente-a")]
    assert router.calls == []


def test_unknown_tenant_locator_uses_generic_failure(secure_client_factory) -> None:  # noqa: ANN001
    client, _gateway, _router, _workspace = secure_client_factory()

    response = client.post("/api/auth/locate", headers={"origin": ORIGIN}, json={"identifier": "missing"})

    assert response.status_code == 404
    assert response.json()["error"]["message"] == LOGIN_FAILURE_MESSAGE
    assert response.headers["cache-control"] == "no-store"


def test_login_sets_only_hardened_cookie_and_never_returns_token(secure_client_factory) -> None:  # noqa: ANN001
    client, gateway, _router, _workspace = secure_client_factory()

    response = client.post(
        "/api/auth/login",
        headers={"origin": ORIGIN},
        json={"slug": "cliente-a", "email": "ana@example.test", "password": "correct horse battery staple"},
    )

    cookie = response.headers["set-cookie"]
    assert response.status_code == 200
    assert response.json()["tenant_slug"] == "cliente-a"
    assert TOKEN not in response.text
    assert cookie.startswith(f"{SESSION_COOKIE_NAME}={TOKEN};")
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie
    assert gateway.calls[0][0] == "login"


@pytest.mark.parametrize("failure", [AuthenticationError("bad"), TenantUnavailableError("down")])
def test_login_failures_are_publicly_identical(secure_client_factory, failure: Exception) -> None:  # noqa: ANN001
    client, gateway, _router, _workspace = secure_client_factory()
    gateway.login_failure = failure

    response = client.post(
        "/api/auth/login",
        headers={"origin": ORIGIN},
        json={"slug": "cliente-a", "email": "ana@example.test", "password": "correct horse battery staple"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == {"code": "invalid_login", "message": LOGIN_FAILURE_MESSAGE}
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")


def test_session_returns_current_immutable_identity_without_token(secure_client_factory) -> None:  # noqa: ANN001
    client, _gateway, _router, _workspace = secure_client_factory()

    response = client.get("/api/auth/session", headers=auth_headers())

    assert response.status_code == 200
    assert response.json()["user_id"] == "u-1"
    assert response.json()["role"] == "Administrador"
    assert "token" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_logout_revokes_server_session_and_expires_same_cookie(secure_client_factory) -> None:  # noqa: ANN001
    client, gateway, _router, _workspace = secure_client_factory()

    response = client.post("/api/auth/logout", headers=auth_headers(origin=True))

    cookie = response.headers["set-cookie"]
    assert response.status_code == 204
    assert gateway.calls[-1] == ("logout", TOKEN)
    assert cookie.startswith(f'{SESSION_COOKIE_NAME}="";')
    assert "Max-Age=0" in cookie and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/api/workspace", None),
        ("POST", "/api/workspace/bootstrap", {"state": STATE.model_dump(by_alias=True)}),
        ("PUT", "/api/workspace", {"version": 1, "state": STATE.model_dump(by_alias=True)}),
        ("POST", "/api/workspace/reset", {"version": 1, "state": STATE.model_dump(by_alias=True)}),
        ("GET", "/api/workspace/deleted?module=leads", None),
        ("POST", "/api/workspace/restore", {"version": 1, "module": "leads", "id": "L-1"}),
    ],
)
def test_every_workspace_route_rejects_anonymous_access(secure_client_factory, method: str, path: str, json_body) -> None:  # noqa: ANN001
    client, _gateway, _router, workspace = secure_client_factory()
    headers = {"origin": ORIGIN} if method not in {"GET", "HEAD"} else {}

    response = client.request(method, path, headers=headers, json=json_body)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert workspace.calls == []


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/api/workspace/bootstrap", {"state": STATE.model_dump(by_alias=True)}),
        ("POST", "/api/workspace/reset", {"version": 1, "state": STATE.model_dump(by_alias=True)}),
        ("GET", "/api/workspace/deleted?module=leads", None),
        ("POST", "/api/workspace/restore", {"version": 1, "module": "leads", "id": "L-1"}),
    ],
)
def test_non_admin_cannot_call_privileged_workspace_routes(secure_client_factory, method: str, path: str, json_body) -> None:  # noqa: ANN001
    client, _gateway, _router, workspace = secure_client_factory("Vendedor")
    headers = auth_headers(origin=method != "GET")

    response = client.request(method, path, headers=headers, json=json_body)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert workspace.calls == []


def test_forged_browser_authority_does_not_change_workspace_session(secure_client_factory) -> None:  # noqa: ANN001
    client, gateway, router, workspace = secure_client_factory()
    payload = {
        "version": 1,
        "tenant_id": str(uuid4()),
        "dsn": "postgresql://evil",
        "role": "Administrador",
        "state": STATE.model_dump(by_alias=True),
    }
    headers = {**auth_headers(origin=True), "x-tenant": "cliente-b", "x-role": "Owner"}

    response = client.put("/api/workspace", headers=headers, json=payload)

    assert response.status_code == 200
    assert gateway.calls[0] == ("session", TOKEN)
    assert router.calls == [TENANT_ID]
    assert workspace.calls[0][0] == "save"


def test_tenant_database_outage_returns_stable_503_without_workspace_call(secure_client_factory) -> None:  # noqa: ANN001
    client, _gateway, router, workspace = secure_client_factory()
    router.unavailable = True

    response = client.get("/api/workspace", headers=auth_headers())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tenant_unavailable"
    assert workspace.calls == []


def test_root_and_valid_tenant_paths_serve_shell_but_invalid_slug_does_not(secure_client_factory) -> None:  # noqa: ANN001
    client, _gateway, _router, _workspace = secure_client_factory()

    root = client.get("/")
    tenant = client.get("/cliente-a")
    invalid = client.get("/cliente_a")

    assert root.status_code == 200 and "tenant shell" in root.text
    assert tenant.status_code == 200 and "tenant shell" in tenant.text
    assert invalid.status_code == 404


def test_session_cookie_on_other_tenant_path_is_rejected_without_switch(secure_client_factory) -> None:  # noqa: ANN001
    client, gateway, router, _workspace = secure_client_factory()

    response = client.get("/cliente-b", headers=auth_headers())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "tenant_mismatch"
    assert gateway.calls == [("session", TOKEN)]
    assert router.calls == []


@pytest.mark.parametrize("path", ["/api/auth/locate", "/api/auth/login", "/api/auth/logout"])
def test_unsafe_auth_routes_require_expected_origin(secure_client_factory, path: str) -> None:  # noqa: ANN001
    client, gateway, _router, _workspace = secure_client_factory()
    bodies = {
        "/api/auth/locate": {"identifier": "cliente-a"},
        "/api/auth/login": {"slug": "cliente-a", "email": "ana@example.test", "password": "correct horse battery staple"},
        "/api/auth/logout": None,
    }

    response = client.post(path, headers=auth_headers() if path.endswith("logout") else {}, json=bodies[path])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"
    assert gateway.calls == []
