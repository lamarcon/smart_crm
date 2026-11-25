"""Personal API tokens and the REST API v1, against a real tenant database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE_NAME, AuthSettings
from app.main import create_app
from app.models import ApiToken, CrmUser, Workspace
from app.repositories.workspace import WorkspaceRepository
from app.services.api_tokens import MAX_ACTIVE_TOKENS_PER_USER, ApiTokenService, token_digest
from test_account_access_api import (  # noqa: F401 - fixtures
    ADMIN_PASSWORD,
    ORIGIN,
    _engine,
    _seed_member,
)
from test_account_access_service import (  # noqa: F401 - fixtures
    RecordingAudit,
    RecoveryRouter,
    TENANT_ID,
    _set_workspace,
    account_access_database_url,
    recovery_control_database,
)
from test_auth_api import FakeDatabase

BASE = "/api/v1/brbots"


@dataclass
class ApiStack:
    client: TestClient
    service: ApiTokenService
    audit: RecordingAudit
    database_url: str
    cookies: dict[str, str]
    users: dict[str, str]

    def signed_in(self, who: str = "admin") -> dict[str, str]:
        return {"origin": ORIGIN, "cookie": f"{SESSION_COOKIE_NAME}={self.cookies[who]}"}

    def login(self, who: str, email: str) -> None:
        response = self.client.post("/api/auth/login", headers={"origin": ORIGIN}, json={"slug": "brbots", "email": email, "password": ADMIN_PASSWORD})
        assert response.status_code == 200, response.text
        self.cookies[who] = response.cookies[SESSION_COOKIE_NAME]

    def create_token(self, who: str = "admin", **fields) -> dict:
        body = {"name": "Integração ERP", "access": "write", **fields}
        response = self.client.post("/api/me/api-tokens", headers=self.signed_in(who), json=body)
        assert response.status_code == 201, response.text
        return response.json()

    @staticmethod
    def bearer(secret: str) -> dict[str, str]:
        return {"authorization": f"Bearer {secret}"}

    def session(self):  # noqa: ANN201
        engine = _engine(self.database_url)
        session = Session(bind=engine, expire_on_commit=False)
        session.begin()
        _set_workspace(session)
        return engine, session

    def run(self, operation):  # noqa: ANN001, ANN201
        engine, session = self.session()
        try:
            result = operation(session)
            session.commit()
            return result
        finally:
            session.close()
            engine.dispose()

    def state(self):  # noqa: ANN201
        return self.run(lambda session: WorkspaceRepository(session, "default").read_active())


@pytest.fixture
def stack(account_access_database_url: str, recovery_control_database, tmp_path: Path):  # noqa: ANN001, F811
    from app.services.auth import AuthService

    (tmp_path / "index.html").write_text("shell", encoding="utf-8")
    router = RecoveryRouter({TENANT_ID: account_access_database_url})
    audit = RecordingAudit()
    auth = AuthService(recovery_control_database, router, security_audit=audit)
    service = ApiTokenService(recovery_control_database, router, security_audit=audit)
    app = create_app(
        database_instance=FakeDatabase(),
        static_dir=tmp_path,
        auth_service=auth,
        tenant_router=router,
        auth_settings=AuthSettings(expected_origin=ORIGIN),
        api_token_service=service,
    )
    client = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)
    engine = _engine(account_access_database_url)
    try:
        with Session(bind=engine) as session, session.begin():
            _set_workspace(session)
            workspace = session.get(Workspace, "default")
            workspace.initialized_at = workspace.initialized_at or datetime.now(timezone.utc)
    finally:
        engine.dispose()
    admin_id, admin_email = _seed_member(account_access_database_url, role="Administrador")
    seller_id, seller_email = _seed_member(account_access_database_url, role="Vendedor")
    stack = ApiStack(client, service, audit, account_access_database_url, {}, {"admin": admin_id, "seller": seller_id})
    stack.login("admin", admin_email)
    stack.login("seller", seller_email)
    return stack


# --- Token management --------------------------------------------------------------------


def test_a_user_creates_lists_and_revokes_tokens_and_only_the_digest_is_stored(stack: ApiStack) -> None:
    created = stack.create_token(access="read", expiresInDays=30)
    secret = created["secret"]
    token = created["token"]
    assert secret.startswith("sct_") and len(secret) > 40
    assert (token["name"], token["access"], token["hint"], token["active"]) == ("Integração ERP", "read", secret[-4:], True)
    assert token["expiresAt"] is not None

    listed = stack.client.get("/api/me/api-tokens", headers=stack.signed_in())
    assert listed.status_code == 200
    assert secret not in listed.text
    assert [item["id"] for item in listed.json()["tokens"]] == [token["id"]]

    row = stack.run(lambda session: session.scalar(select(ApiToken).where(ApiToken.token_digest == token_digest(secret))))
    assert row is not None and row.user_id == stack.users["admin"]

    revoked = stack.client.post(f"/api/me/api-tokens/{token['id']}/revoke", headers=stack.signed_in())
    assert revoked.status_code == 200 and revoked.json()["token"]["active"] is False
    assert stack.client.get(f"{BASE}/me", headers=stack.bearer(secret)).status_code == 401


def test_token_fields_are_validated(stack: ApiStack) -> None:
    headers = stack.signed_in()
    for body, field in (
        ({"name": "", "access": "read"}, "name"),
        ({"name": "x" * 121, "access": "read"}, "name"),
        ({"name": "ERP", "access": "admin"}, "access"),
        ({"name": "ERP", "access": "read", "expiresInDays": 7}, "expiresInDays"),
    ):
        response = stack.client.post("/api/me/api-tokens", headers=headers, json=body)
        assert response.status_code == 422, body
        assert response.json()["error"]["field"] == field


def test_management_needs_a_session_and_the_expected_origin(stack: ApiStack) -> None:
    stack.client.cookies.clear()
    assert stack.client.get("/api/me/api-tokens").status_code == 401
    response = stack.client.post(
        "/api/me/api-tokens",
        headers={"cookie": stack.signed_in()["cookie"], "origin": "https://evil.example"},
        json={"name": "ERP", "access": "read"},
    )
    assert response.status_code == 403


def test_each_user_sees_only_their_tokens_and_admins_see_and_revoke_all(stack: ApiStack) -> None:
    seller = stack.create_token("seller", name="Planilha")
    admin = stack.create_token("admin", name="ERP")

    mine = stack.client.get("/api/me/api-tokens", headers=stack.signed_in("seller")).json()["tokens"]
    assert [item["id"] for item in mine] == [seller["token"]["id"]]
    assert stack.client.get("/api/me/api-tokens?all=true", headers=stack.signed_in("seller")).status_code == 403
    # Someone else's token looks missing to a non-admin.
    other = stack.client.post(f"/api/me/api-tokens/{admin['token']['id']}/revoke", headers=stack.signed_in("seller"))
    assert other.status_code == 404

    everyone = stack.client.get("/api/me/api-tokens?all=true", headers=stack.signed_in("admin")).json()["tokens"]
    assert {seller["token"]["id"], admin["token"]["id"]} <= {item["id"] for item in everyone}
    assert {item["userId"] for item in everyone} >= {stack.users["seller"], stack.users["admin"]}
    assert stack.client.post(f"/api/me/api-tokens/{seller['token']['id']}/revoke", headers=stack.signed_in("admin")).status_code == 200
    assert stack.client.get(f"{BASE}/me", headers=stack.bearer(seller["secret"])).status_code == 401


def test_active_tokens_per_user_are_limited(stack: ApiStack) -> None:
    for index in range(MAX_ACTIVE_TOKENS_PER_USER):
        stack.create_token(name=f"Token {index}")
    response = stack.client.post("/api/me/api-tokens", headers=stack.signed_in(), json={"name": "Mais um", "access": "read"})
    assert response.status_code == 422


# --- Authentication ----------------------------------------------------------------------


def test_me_describes_the_token_user_and_their_permissions(stack: ApiStack) -> None:
    secret = stack.create_token("seller", access="read")["secret"]
    response = stack.client.get(f"{BASE}/me", headers=stack.bearer(secret))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["id"] == stack.users["seller"] and body["user"]["role"] == "Vendedor"
    assert body["token"]["access"] == "read"
    assert body["permissions"]["leads"]["read"] in ("own", "team", "all")


@pytest.mark.parametrize(
    "headers",
    [{}, {"authorization": "Bearer "}, {"authorization": "Basic abc"}, {"authorization": "Bearer sct_naoexiste_0000000000000000000"}, {"authorization": "Bearer sck_wrongprefix"}],
)
def test_missing_or_unknown_tokens_are_refused(stack: ApiStack, headers: dict) -> None:
    response = stack.client.get(f"{BASE}/leads", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_a_token_of_another_tenant_route_or_an_unknown_tenant_is_refused(stack: ApiStack) -> None:
    secret = stack.create_token()["secret"]
    assert stack.client.get("/api/v1/outra-empresa/leads", headers=stack.bearer(secret)).status_code == 404


def test_expired_tokens_and_inactive_owners_stop_working(stack: ApiStack) -> None:
    expiring = stack.create_token(name="Expira", expiresInDays=30)
    assert stack.client.get(f"{BASE}/me", headers=stack.bearer(expiring["secret"])).status_code == 200
    stack.run(lambda session: session.execute(
        update(ApiToken).where(ApiToken.token_digest == token_digest(expiring["secret"])).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    ))
    assert stack.client.get(f"{BASE}/me", headers=stack.bearer(expiring["secret"])).status_code == 401

    seller = stack.create_token("seller")["secret"]
    stack.run(lambda session: session.execute(update(CrmUser).where(CrmUser.id == stack.users["seller"]).values(status="Inativo")))
    assert stack.client.get(f"{BASE}/me", headers=stack.bearer(seller)).status_code == 401


def test_a_profile_change_applies_to_existing_tokens(stack: ApiStack) -> None:
    secret = stack.create_token("seller")["secret"]
    stack.run(lambda session: session.execute(update(CrmUser).where(CrmUser.id == stack.users["seller"]).values(role="Gestor")))
    assert stack.client.get(f"{BASE}/me", headers=stack.bearer(secret)).json()["user"]["role"] == "Gestor"


def test_repeated_wrong_tokens_from_one_address_are_rate_limited(stack: ApiStack) -> None:
    statuses = [
        stack.client.get(f"{BASE}/leads", headers={"authorization": f"Bearer sct_wrong{index:030d}"}).status_code
        for index in range(25)
    ]
    assert statuses[0] == 401 and statuses[-1] == 429


def test_read_tokens_cannot_write(stack: ApiStack) -> None:
    secret = stack.create_token(access="read")["secret"]
    response = stack.client.post(f"{BASE}/leads", headers=stack.bearer(secret), json={"name": "Via API"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "read_only_token"


def test_last_use_is_recorded(stack: ApiStack) -> None:
    created = stack.create_token(access="read")
    stack.client.get(f"{BASE}/me", headers=stack.bearer(created["secret"]))
    listed = stack.client.get("/api/me/api-tokens", headers=stack.signed_in()).json()["tokens"]
    assert listed[0]["lastUsedAt"] is not None


# --- Records -----------------------------------------------------------------------------


def test_create_read_update_list_and_delete_a_lead(stack: ApiStack) -> None:
    secret = stack.create_token()["secret"]
    headers = stack.bearer(secret)
    created = stack.client.post(f"{BASE}/leads", headers=headers, json={"name": "Maria API", "company": "ACME", "email": "maria@acme.test", "id": "L-999"})
    assert created.status_code == 201, created.text
    lead = created.json()
    assert lead["id"] != "L-999" and lead["id"].startswith("L-")
    assert (lead["stage"], lead["responsibleId"]) == ("Em contato", stack.users["admin"])
    assert lead["createdAt"] == lead["updatedAt"]

    fetched = stack.client.get(f"{BASE}/leads/{lead['id']}", headers=headers)
    assert fetched.status_code == 200 and fetched.json()["email"] == "maria@acme.test"

    changed = stack.client.patch(f"{BASE}/leads/{lead['id']}", headers=headers, json={"phone": "11 99999-0000", "company": None})
    assert changed.status_code == 200, changed.text
    assert changed.json()["phone"] == "11 99999-0000" and "company" not in changed.json()

    listed = stack.client.get(f"{BASE}/leads?limit=1", headers=headers).json()
    assert listed["total"] >= 1 and len(listed["items"]) == 1 and listed["limit"] == 1

    version = stack.run(lambda session: session.get(Workspace, "default").version)
    assert stack.client.delete(f"{BASE}/leads/{lead['id']}", headers=headers).status_code == 204
    assert stack.client.get(f"{BASE}/leads/{lead['id']}", headers=headers).status_code == 404
    assert stack.run(lambda session: session.get(Workspace, "default").version) == version + 1
    assert all(item["id"] != lead["id"] for item in stack.state().leads)


def test_create_a_company_contact_product_and_deal(stack: ApiStack) -> None:
    headers = stack.bearer(stack.create_token()["secret"])
    company = stack.client.post(f"{BASE}/companies", headers=headers, json={"name": "ACME Ltda", "city": "SP"})
    assert company.status_code == 201, company.text
    assert company.json()["ownerId"] == stack.users["admin"]
    contact = stack.client.post(f"{BASE}/contacts", headers=headers, json={"name": "João", "company": "ACME Ltda", "companyId": company.json()["id"]})
    assert contact.status_code == 201, contact.text
    product = stack.client.post(f"{BASE}/products", headers=headers, json={"name": "Licença", "sku": "LIC", "price": 100, "currency": "BRL", "unit": "un", "active": True})
    assert product.status_code == 201, product.text
    deal = stack.client.post(
        f"{BASE}/deals",
        headers=headers,
        json={"title": "Venda ACME", "company": "ACME Ltda", "companyId": company.json()["id"], "amount": 500},
    )
    assert deal.status_code == 201, deal.text
    body = deal.json()
    assert body["id"].startswith("N-") and body["stageId"] and body["pipelineId"]

    pipelines = stack.client.get(f"{BASE}/pipelines", headers=headers).json()["items"]
    assert body["pipelineId"] in [pipeline["id"] for pipeline in pipelines]


def test_unknown_records_and_modules_answer_404(stack: ApiStack) -> None:
    headers = stack.bearer(stack.create_token()["secret"])
    assert stack.client.get(f"{BASE}/leads/L-424242", headers=headers).status_code == 404
    assert stack.client.patch(f"{BASE}/leads/L-424242", headers=headers, json={"name": "x"}).status_code == 404
    assert stack.client.delete(f"{BASE}/leads/L-424242", headers=headers).status_code == 404
    assert stack.client.get(f"{BASE}/users", headers=headers).status_code == 404


def test_bodies_must_be_json_objects(stack: ApiStack) -> None:
    headers = {**stack.bearer(stack.create_token()["secret"]), "content-type": "application/json"}
    assert stack.client.post(f"{BASE}/leads", headers=headers, content=b"[1, 2]").status_code == 422
    assert stack.client.post(f"{BASE}/leads", headers=headers, content=b"{nope").status_code == 400
    assert stack.client.post(f"{BASE}/leads", headers=headers, content=b"x" * (256 * 1024 + 1)).status_code == 413


def test_a_seller_token_only_reaches_the_seller_records(stack: ApiStack) -> None:
    admin = stack.bearer(stack.create_token()["secret"])
    seller = stack.bearer(stack.create_token("seller")["secret"])
    theirs = stack.client.post(f"{BASE}/leads", headers=admin, json={"name": "Do admin"}).json()
    mine = stack.client.post(f"{BASE}/leads", headers=seller, json={"name": "Do vendedor"})
    assert mine.status_code == 201, mine.text
    assert mine.json()["responsibleId"] == stack.users["seller"]

    visible = [item["id"] for item in stack.client.get(f"{BASE}/leads", headers=seller).json()["items"]]
    assert mine.json()["id"] in visible and theirs["id"] not in visible
    assert stack.client.get(f"{BASE}/leads/{theirs['id']}", headers=seller).status_code == 404
    assert stack.client.patch(f"{BASE}/leads/{theirs['id']}", headers=seller, json={"name": "Invadido"}).status_code == 404
    # Moving their own Lead to someone else is outside the seller's scope.
    moved = stack.client.patch(f"{BASE}/leads/{mine.json()['id']}", headers=seller, json={"responsibleId": stack.users["admin"]})
    assert moved.status_code == 403
    names = {item["id"]: item["name"] for item in stack.state().leads}
    assert names[theirs["id"]] == "Do admin"
