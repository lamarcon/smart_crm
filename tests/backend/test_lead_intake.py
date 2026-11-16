"""Lead intake keys and the public endpoint, against a real tenant database."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthSettings
from app.main import create_app
from app.models import LeadIntakeKey, Workspace
from app.repositories.workspace import WorkspaceRepository
from app.services.lead_intake import LeadIntakeService, key_digest, parse_payload, LeadIntakeValidationError
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
from app.auth import SESSION_COOKIE_NAME

URL = "/api/public/brbots/leads"


@dataclass
class IntakeStack:
    client: TestClient
    service: LeadIntakeService
    audit: RecordingAudit
    database_url: str
    admin_cookie: str
    admin_id: str

    def admin(self, cookie: str | None = None) -> dict[str, str]:
        return {"origin": ORIGIN, "cookie": f"{SESSION_COOKIE_NAME}={cookie or self.admin_cookie}"}

    def create_key(self, **fields) -> dict:
        body = {"name": "Bot Instagram", "defaultChannel": "Instagram", "defaultResponsibleId": self.admin_id, **fields}
        response = self.client.post("/api/lead-intake/keys", headers=self.admin(), json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def send(self, secret: str | None, payload: object, **headers: str):
        merged = {"content-type": "application/json", **headers}
        if secret is not None:
            merged["x-smartcrm-key"] = secret
        return self.client.post(URL, headers=merged, content=payload if isinstance(payload, (bytes, str)) else json.dumps(payload))

    def session(self):  # noqa: ANN201
        engine = _engine(self.database_url)
        session = Session(bind=engine, expire_on_commit=False)
        session.begin()
        _set_workspace(session)
        return engine, session

    def state(self):  # noqa: ANN201
        engine, session = self.session()
        try:
            return WorkspaceRepository(session, "default").read_active()
        finally:
            session.close()
            engine.dispose()

    def version(self) -> int:
        engine, session = self.session()
        try:
            return session.get(Workspace, "default").version
        finally:
            session.close()
            engine.dispose()


@pytest.fixture
def stack(account_access_database_url: str, recovery_control_database, tmp_path: Path):  # noqa: ANN001, F811
    from app.services.auth import AuthService

    (tmp_path / "index.html").write_text("shell", encoding="utf-8")
    router = RecoveryRouter({TENANT_ID: account_access_database_url})
    audit = RecordingAudit()
    auth = AuthService(recovery_control_database, router, security_audit=audit)
    service = LeadIntakeService(recovery_control_database, router, security_audit=audit)
    app = create_app(
        database_instance=FakeDatabase(),
        static_dir=tmp_path,
        auth_service=auth,
        tenant_router=router,
        auth_settings=AuthSettings(expected_origin=ORIGIN),
        lead_intake_service=service,
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
    login = client.post("/api/auth/login", headers={"origin": ORIGIN}, json={"slug": "brbots", "email": admin_email, "password": ADMIN_PASSWORD})
    assert login.status_code == 200, login.text
    return IntakeStack(client, service, audit, account_access_database_url, login.cookies[SESSION_COOKIE_NAME], admin_id)


# --- Keys --------------------------------------------------------------------------------


def test_admin_creates_lists_and_revokes_keys_and_only_the_digest_is_stored(stack: IntakeStack) -> None:
    created = stack.create_key()
    secret = created["secret"]
    assert secret.startswith("sck_") and len(secret) > 40
    assert created["key"]["name"] == "Bot Instagram" and created["key"]["active"] is True

    listed = stack.client.get("/api/lead-intake/keys", headers=stack.admin())
    assert listed.status_code == 200
    assert secret not in listed.text
    assert created["key"]["id"] in [key["id"] for key in listed.json()["keys"]]

    engine, session = stack.session()
    try:
        row = session.scalar(select(LeadIntakeKey).where(LeadIntakeKey.name == "Bot Instagram", LeadIntakeKey.key_digest == key_digest(secret)))
        assert row is not None and secret not in row.key_digest
    finally:
        session.close()
        engine.dispose()

    revoked = stack.client.post(f"/api/lead-intake/keys/{created['key']['id']}/revoke", headers=stack.admin())
    assert revoked.status_code == 200 and revoked.json()["key"]["active"] is False
    assert stack.send(secret, {"name": "Depois da revogação"}).status_code == 401


@pytest.mark.parametrize(
    ("fields", "field"),
    [({"name": " "}, "name"), ({"defaultChannel": "Fax"}, "defaultChannel"), ({"defaultResponsibleId": "ninguem"}, "defaultResponsibleId")],
)
def test_invalid_keys_are_refused(stack: IntakeStack, fields: dict, field: str) -> None:
    body = {"name": "Bot", "defaultChannel": "Instagram", "defaultResponsibleId": stack.admin_id, **fields}
    response = stack.client.post("/api/lead-intake/keys", headers=stack.admin(), json=body)
    assert response.status_code == 422
    assert response.json()["error"]["field"] == field


def test_only_administrators_manage_keys(stack: IntakeStack) -> None:
    _seller_id, seller_email = _seed_member(stack.database_url, role="Gestor")
    login = stack.client.post("/api/auth/login", headers={"origin": ORIGIN}, json={"slug": "brbots", "email": seller_email, "password": ADMIN_PASSWORD})
    cookie = login.cookies[SESSION_COOKIE_NAME]
    assert stack.client.get("/api/lead-intake/keys", headers=stack.admin(cookie)).status_code == 403
    body = {"name": "Bot", "defaultChannel": "Site", "defaultResponsibleId": stack.admin_id}
    assert stack.client.post("/api/lead-intake/keys", headers=stack.admin(cookie), json=body).status_code == 403
    stack.client.cookies.clear()
    assert stack.client.get("/api/lead-intake/keys", headers={"origin": ORIGIN}).status_code == 401


# --- Public intake ---------------------------------------------------------------------------


def test_a_lead_is_created_with_tracking_notification_and_new_version(stack: IntakeStack) -> None:
    secret = stack.create_key()["secret"]
    before = stack.version()
    response = stack.send(secret, {
        "name": "Ana Bot", "phone": "(11) 98888-7777", "message": "Quero um orçamento",
        "externalId": "ig-1001", "profileUrl": "https://instagram.com/ana", "campaign": "Black Friday",
        "utm": {"source": "instagram", "medium": "dm"}, "inventado": "ignorado",
    })
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "created"
    lead_id = response.json()["leadId"]
    assert stack.version() == before + 1

    state = stack.state()
    lead = next(item for item in state.leads if item["id"] == lead_id)
    assert (lead["name"], lead["phone"], lead["source"], lead["stage"], lead["responsibleId"]) == ("Ana Bot", "(11) 98888-7777", "Instagram", "Em contato", stack.admin_id)
    tracking = lead["tracking"]
    assert {key: tracking[key] for key in ("channel", "externalId", "campaign", "utmSource", "utmMedium", "intakeKeyName")} == {
        "channel": "Instagram", "externalId": "ig-1001", "campaign": "Black Friday", "utmSource": "instagram", "utmMedium": "dm", "intakeKeyName": "Bot Instagram",
    }
    assert tracking["messages"][0]["text"] == "Quero um orçamento"
    assert "inventado" not in json.dumps(lead)
    notice = next(item for item in state.notifications if item["userId"] == stack.admin_id and "Ana Bot" in item["detail"])
    assert notice["text"] == "Novo Lead pelo canal Instagram"
    assert any(event["event_type"] == "lead_intake.accepted" for event in stack.audit.events)


def test_same_external_id_updates_the_open_lead_instead_of_duplicating(stack: IntakeStack) -> None:
    secret = stack.create_key()["secret"]
    first = stack.send(secret, {"name": "Bruno", "externalId": "ig-2002", "message": "Oi"}).json()
    second = stack.send(secret, {"name": "Bruno", "email": "bruno@example.test", "externalId": "ig-2002", "message": "Ainda quero"})
    assert second.status_code == 200
    assert second.json() == {"leadId": first["leadId"], "status": "updated"}
    leads = [item for item in stack.state().leads if (item.get("tracking") or {}).get("externalId") == "ig-2002"]
    assert len(leads) == 1
    assert leads[0]["email"] == "bruno@example.test"
    assert [message["text"] for message in leads[0]["tracking"]["messages"]] == ["Oi", "Ainda quero"]
    # Another channel with the same id is another person.
    other = stack.send(secret, {"name": "Bruno Site", "externalId": "ig-2002", "channel": "Site"})
    assert other.status_code == 201 and other.json()["leadId"] != first["leadId"]


def test_new_ids_never_reuse_deleted_leads(stack: IntakeStack) -> None:
    secret = stack.create_key()["secret"]
    first = stack.send(secret, {"name": "Primeiro"}).json()["leadId"]
    engine, session = stack.session()
    try:
        repository = WorkspaceRepository(session, "default")
        state = repository.read_active()
        data = state.model_dump(by_alias=True, exclude_none=True)
        data["leads"] = [item for item in data["leads"] if item["id"] != first]
        repository.reconcile(type(state).model_validate(data))
        session.commit()
    finally:
        session.close()
        engine.dispose()
    second = stack.send(secret, {"name": "Segundo"}).json()["leadId"]
    assert int(second.split("-")[1]) > int(first.split("-")[1])


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"message": "sem contato"}, 422, "validation_error"),
        ({"name": "X", "email": "nao-e-email"}, 422, "validation_error"),
        ({"name": "X", "channel": "Fax"}, 422, "validation_error"),
        ({"name": {"nested": True}}, 422, "validation_error"),
        ("[1, 2]", 422, "validation_error"),
        ("{quebrado", 400, "invalid_json"),
        ({"name": "X" * 20000}, 413, "payload_too_large"),
    ],
)
def test_invalid_bodies_are_refused(stack: IntakeStack, payload: object, status: int, code: str) -> None:
    secret = stack.create_key()["secret"]
    response = stack.send(secret, payload)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def test_wrong_keys_and_unknown_companies_get_generic_errors(stack: IntakeStack) -> None:
    assert stack.send(None, {"name": "X"}).status_code == 401
    assert stack.send("sck_" + "x" * 43, {"name": "X"}).status_code == 401
    assert stack.send("outra-coisa", {"name": "X"}).status_code == 401
    unknown = stack.client.post("/api/public/nao-existe/leads", headers={"x-smartcrm-key": "sck_abc"}, json={"name": "X"})
    assert unknown.status_code == 404
    assert any(event["outcome_code"] == "invalid_key" for event in stack.audit.events)


def test_rate_limits_answer_429(stack: IntakeStack) -> None:
    secret = stack.create_key()["secret"]
    stack.service.key_limiter.limit = 2
    assert stack.send(secret, {"name": "Um"}).status_code == 201
    assert stack.send(secret, {"name": "Dois"}).status_code == 201
    limited = stack.send(secret, {"name": "Três"})
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"

    stack.service.key_limiter.limit = 60
    # Repeated wrong keys from one address get 429, but a valid key still works.
    fresh = stack.create_key(name="Site")["secret"]
    for _ in range(10):
        assert stack.send("sck_errada", {"name": "X"}).status_code == 401
    assert stack.send("sck_errada", {"name": "X"}).status_code == 429
    assert stack.send("sem-prefixo", {"name": "X"}).status_code == 429
    assert stack.send(fresh, {"name": "Ainda entra"}).status_code == 201

    # The address limit applies to everything from that address.
    stack.service.ip_limiter.limit = len(stack.service.ip_limiter._hits["testclient"])
    assert stack.send(fresh, {"name": "Excesso"}).status_code == 429


def test_stale_tabs_cannot_overwrite_an_intake_lead(stack: IntakeStack) -> None:
    secret = stack.create_key()["secret"]
    loaded = stack.client.get("/api/workspace", headers=stack.admin())
    assert loaded.status_code == 200, loaded.text
    snapshot = loaded.json()
    lead_id = stack.send(secret, {"name": "Concorrente"}).json()["leadId"]
    stale = stack.client.put(
        "/api/workspace", headers=stack.admin(), json={"version": snapshot["version"], "state": snapshot["state"]}
    )
    assert stale.status_code == 409, stale.text
    assert any(item["id"] == lead_id for item in stack.state().leads)


def test_payload_parser_rules() -> None:
    assert parse_payload({"phone": 11999990000}).phone == "11999990000"
    assert parse_payload({"email": " A@B.COM "}).email == "A@B.COM"
    with pytest.raises(LeadIntakeValidationError):
        parse_payload({"name": "x", "utm": "texto"})


@pytest.mark.parametrize(("role", "status"), [("Assistente", "Ativo"), ("Vendedor", "Inativo")])
def test_the_default_responsible_must_be_an_active_seller(stack: IntakeStack, role: str, status: str) -> None:
    user_id, _email = _seed_member(stack.database_url, role=role, status=status)
    body = {"name": "Bot", "defaultChannel": "Site", "defaultResponsibleId": user_id}
    response = stack.client.post("/api/lead-intake/keys", headers=stack.admin(), json=body)
    assert response.status_code == 422
    assert response.json()["error"]["field"] == "defaultResponsibleId"
