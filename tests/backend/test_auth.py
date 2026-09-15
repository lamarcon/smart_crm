from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import (
    SESSION_COOKIE_NAME,
    AuthSettings,
    CookiePrincipalResolver,
)
from app.policies import PrincipalScope
from app.services.auth import AuthenticationError, SessionContext


VALID_TOKEN = "A" * 43
EXPECTED_ORIGIN = "https://sc2030.brbots.com"
TENANT_ID = uuid4()


def context(slug: str = "cliente-a") -> SessionContext:
    return SessionContext(
        principal=PrincipalScope(
            tenant_id=TENANT_ID,
            workspace_id="default",
            user_id="u-1",
            role="Administrador",
            team_id="team-a",
            auth_version=3,
        ),
        tenant_slug=slug,
        tenant_display_name="Cliente A",
        user_name="Ana",
        email="ana@example.test",
        token_digest="d" * 64,
    )


class FakeAuthService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: dict[str, Exception] = {}

    def current_session(self, token: str, *, now):  # noqa: ANN001, ANN201
        self.calls.append(token)
        failure = self.failures.get(token)
        if failure is not None:
            raise failure
        return context()


class FakeRouter:
    def __init__(self) -> None:
        self.opened: list = []
        self.closed: list = []

    @contextmanager
    def tenant_session_scope(self, tenant_id):  # noqa: ANN001, ANN201
        self.opened.append(tenant_id)
        try:
            yield SimpleNamespace(marker="tenant-session")
        finally:
            self.closed.append(tenant_id)


@pytest.fixture
def auth_client():  # noqa: ANN201
    service = FakeAuthService()
    router = FakeRouter()
    resolver = CookiePrincipalResolver(
        service,
        router,
        AuthSettings(expected_origin=EXPECTED_ORIGIN),
    )
    app = FastAPI()

    @app.api_route("/protected/{slug}", methods=["GET", "POST"])
    async def protected(slug: str, resolved=Depends(resolver)):  # noqa: ANN001, ANN201
        resolver.require_tenant_route(resolved.context, slug)
        return {
            "tenant": str(resolved.context.principal.tenant_id),
            "user": resolved.context.principal.user_id,
            "db": resolved.tenant_session.marker,
        }

    return TestClient(app, base_url=EXPECTED_ORIGIN), service, router


def cookie_header(token: str = VALID_TOKEN) -> dict[str, str]:
    return {"cookie": f"{SESSION_COOKIE_NAME}={token}"}


def test_valid_cookie_resolves_immutable_principal_and_closes_tenant_session(auth_client) -> None:  # noqa: ANN001
    client, service, router = auth_client

    response = client.get("/protected/cliente-a", headers=cookie_header())

    assert response.status_code == 200
    assert response.json() == {"tenant": str(TENANT_ID), "user": "u-1", "db": "tenant-session"}
    assert service.calls == [VALID_TOKEN]
    assert router.opened == [TENANT_ID]
    assert router.closed == [TENANT_ID]


def test_missing_cookie_is_401_without_auth_lookup(auth_client) -> None:  # noqa: ANN001
    client, service, router = auth_client

    response = client.get("/protected/cliente-a")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthenticated"
    assert service.calls == []
    assert router.opened == []


@pytest.mark.parametrize("token", ["", "short", "invalid.token", "x" * 129])
def test_malformed_cookie_is_rejected_before_auth_lookup(auth_client, token: str) -> None:  # noqa: ANN001
    client, service, router = auth_client

    response = client.get("/protected/cliente-a", headers=cookie_header(token))

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthenticated"
    assert service.calls == []
    assert router.opened == []


@pytest.mark.parametrize("state", ["unknown", "expired", "revoked"])
def test_unknown_expired_or_revoked_cookie_is_401(auth_client, state: str) -> None:  # noqa: ANN001
    client, service, router = auth_client
    service.failures[VALID_TOKEN] = AuthenticationError(state)

    response = client.get("/protected/cliente-a", headers=cookie_header())

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthenticated"
    assert service.calls == [VALID_TOKEN]
    assert router.opened == []


@pytest.mark.parametrize(
    "source",
    [
        {"authorization": f"Bearer {VALID_TOKEN}"},
        {"x-session-token": VALID_TOKEN},
    ],
)
def test_application_headers_cannot_supply_session(auth_client, source: dict[str, str]) -> None:  # noqa: ANN001
    client, service, router = auth_client

    response = client.get("/protected/cliente-a", headers=source)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthenticated"
    assert service.calls == []
    assert router.opened == []


def test_query_token_is_rejected_even_when_valid_cookie_exists(auth_client) -> None:  # noqa: ANN001
    client, service, router = auth_client

    response = client.get(
        f"/protected/cliente-a?token={VALID_TOKEN}",
        headers=cookie_header(),
    )

    assert response.status_code == 401
    assert service.calls == []
    assert router.opened == []


def test_body_token_is_rejected_even_when_valid_cookie_exists(auth_client) -> None:  # noqa: ANN001
    client, service, router = auth_client
    headers = {**cookie_header(), "origin": EXPECTED_ORIGIN}

    response = client.post("/protected/cliente-a", headers=headers, json={"session_token": VALID_TOKEN})

    assert response.status_code == 401
    assert service.calls == []
    assert router.opened == []


def test_forged_tenant_dsn_user_and_role_headers_never_change_principal(auth_client) -> None:  # noqa: ANN001
    client, service, router = auth_client
    headers = {
        **cookie_header(),
        "x-tenant": "cliente-b",
        "x-workspace": "other",
        "x-database-url": "postgresql://evil",
        "x-user-id": "attacker",
        "x-role": "Administrador",
    }

    response = client.get("/protected/cliente-a", headers=headers)

    assert response.status_code == 200
    assert response.json()["tenant"] == str(TENANT_ID)
    assert response.json()["user"] == "u-1"
    assert service.calls == [VALID_TOKEN]
    assert router.opened == [TENANT_ID]


def test_route_tenant_mismatch_is_403_without_remapping(auth_client) -> None:  # noqa: ANN001
    client, service, router = auth_client

    response = client.get("/protected/cliente-b", headers=cookie_header())

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "tenant_mismatch"
    assert service.calls == [VALID_TOKEN]
    assert router.opened == [TENANT_ID]
    assert router.closed == [TENANT_ID]


@pytest.mark.parametrize("origin", [None, "http://sc2030.brbots.com", "https://evil.example", EXPECTED_ORIGIN + "/"])
def test_unsafe_methods_require_exact_expected_https_origin(auth_client, origin: str | None) -> None:  # noqa: ANN001
    client, service, router = auth_client
    headers = cookie_header()
    if origin is not None:
        headers["origin"] = origin

    response = client.post("/protected/cliente-a", headers=headers, json={})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "invalid_origin"
    assert service.calls == []
    assert router.opened == []


def test_exact_expected_origin_allows_unsafe_method(auth_client) -> None:  # noqa: ANN001
    client, service, router = auth_client
    headers = {**cookie_header(), "origin": EXPECTED_ORIGIN}

    response = client.post("/protected/cliente-a", headers=headers, json={})

    assert response.status_code == 200
    assert response.json()["user"] == "u-1"
    assert service.calls == [VALID_TOKEN]
    assert router.closed == [TENANT_ID]
