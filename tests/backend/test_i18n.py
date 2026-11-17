"""Interface language: catalogs, error translation, user preference and e-mails."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.i18n import (
    SUPPORTED_LOCALES,
    ErrorMessageTranslationMiddleware,
    catalog_entries,
    read_user_locale,
    resolve_locale,
    translate,
)
from app.mail import render_invitation_email, render_password_reset_email
from app.auth import SESSION_COOKIE_NAME
from test_account_access_api import (  # noqa: F401 - fixtures
    ADMIN_PASSWORD,
    ORIGIN,
    LiveStack,
    _seed_member,
    _user,
    live_stack,
)
from test_account_access_service import (  # noqa: F401 - fixtures
    account_access_database_url,
    recovery_control_database,
)

ROOT = Path(__file__).resolve().parents[2]
SLOT = re.compile(r"\{\w+\}")


# --- Language resolution ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "pt-BR"),
        ("", "pt-BR"),
        ("en", "en"),
        ("en-US,en;q=0.9", "en"),
        ("es-AR", "es"),
        ("pt", "pt-BR"),
        ("pt-PT", "pt-PT"),
        ("pt-pt,pt;q=0.8", "pt-PT"),
        ("pt-AO", "pt-PT"),
        ("pt-BR, pt-PT;q=0.9", "pt-BR"),
        ("pt-PTX", "pt-BR"),
        ("fr-FR, es;q=0.8, en;q=0.5", "es"),
        ("de, fr", "pt-BR"),
        ("en;q=0, es", "es"),
        ("en;q=0", "pt-BR"),
        ("en;q=0.5, es", "es"),
        ("pt-BR;q=0.2, en-GB;q=0.9", "en"),
    ],
)
def test_resolve_locale_follows_the_accept_language_header(header, expected) -> None:  # noqa: ANN001
    assert resolve_locale(header) == expected


# --- Catalogs ----------------------------------------------------------------------------

def test_translate_keeps_portuguese_and_unknown_text() -> None:
    assert translate("Acesso negado.", "pt-BR") == "Acesso negado."
    assert translate("Texto que não está no catálogo.", "en") == "Texto que não está no catálogo."
    assert translate("Acesso negado.", "en") == "Access denied."
    assert translate("Acesso negado.", "es") == "Acceso denegado."


def test_translate_fills_variable_parts() -> None:
    message = "Já existe um produto com o código LIC-01 (P-7)."
    assert translate(message, "en") == "A product with the code LIC-01 already exists (P-7)."
    assert translate(message, "es") == "Ya existe un producto con el código LIC-01 (P-7)."
    assert translate("Aceitar convite da {company}", "en", company="ACME") == (
        "Accept ACME's invitation"
    )


def test_write_user_locale_rejects_unsupported_languages_before_touching_the_database() -> None:
    from app.i18n import write_user_locale

    with pytest.raises(ValueError):
        write_user_locale(None, "default", "u-1", "fr")


def test_server_catalogs_have_the_same_keys_and_slots() -> None:
    english = catalog_entries("en")
    spanish = catalog_entries("es")
    assert set(english) == set(spanish)
    for source in english:
        assert sorted(SLOT.findall(source)) == sorted(SLOT.findall(english[source])), source
        assert sorted(SLOT.findall(source)) == sorted(SLOT.findall(spanish[source])), source


def _interface_dictionary(locale: str) -> dict[str, str]:
    text = (ROOT / "app" / "static" / "i18n" / f"{locale}.js").read_text(encoding="utf-8")
    body = text[text.index("= {") + 2 : text.rindex("};") + 1]
    return json.loads(body)


def test_interface_dictionaries_have_the_same_keys_and_slots() -> None:
    english = _interface_dictionary("en")
    spanish = _interface_dictionary("es")
    assert len(english) > 600
    assert set(english) == set(spanish)
    for source in english:
        expected = sorted(SLOT.findall(source))
        assert sorted(SLOT.findall(english[source])) == expected, source
        assert sorted(SLOT.findall(spanish[source])) == expected, source


def test_new_interface_text_is_translated_or_explicitly_kept() -> None:
    from i18n_inventory import interface_strings

    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    english = _interface_dictionary("en")
    kept = set(json.loads(Path(__file__).with_name("i18n_untranslated.json").read_text(encoding="utf-8"))["kept"])
    inventory = interface_strings(html)
    missing = {text: line for text, line in inventory.items() if text not in english and text not in kept}
    assert missing == {}, "Translate these texts in app/static/i18n/en.js and es.js (or list them as kept)"
    stale = kept - set(inventory)
    assert stale == set(), "Remove these entries from i18n_untranslated.json"


def test_every_error_message_raised_by_the_integrity_rules_is_translated() -> None:
    source = (ROOT / "app" / "services" / "crm_integrity.py").read_text(encoding="utf-8")
    english = catalog_entries("en")
    patterns = [re.sub(r"\\\{\w+\\\}", ".*", re.escape(key)) for key in english]
    messages = re.findall(r'f?"([^"]*[ãõçáéíóúâêô][^"]*\.)"', source)
    assert messages
    for message in messages:
        sample = re.sub(r"\{[^}]+\}", "X", message)
        assert any(re.fullmatch(pattern, sample) for pattern in patterns), message


# --- Error answers -----------------------------------------------------------------------

def _translating_app() -> TestClient:
    app = FastAPI()

    @app.get("/fail")
    def fail() -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Chave de metadado repetida: sla.", "field": "products"}})

    @app.get("/login")
    def login() -> JSONResponse:
        return JSONResponse(status_code=401, content={"error": "invalid_login", "message": "Não foi possível entrar com os dados informados."})

    @app.get("/ok")
    def ok() -> dict:
        return {"message": "Acesso negado."}

    app.add_middleware(ErrorMessageTranslationMiddleware)
    return TestClient(app)


def test_error_messages_follow_the_request_language() -> None:
    client = _translating_app()
    english = client.get("/fail", headers={"accept-language": "en-US"})
    assert english.status_code == 422
    assert english.json() == {"error": {"code": "validation_error", "message": "Duplicate metadata key: sla.", "field": "products"}}
    assert int(english.headers["content-length"]) == len(english.content)
    spanish = client.get("/login", headers={"accept-language": "es"})
    assert spanish.json() == {"error": "invalid_login", "message": "No fue posible iniciar sesión con los datos informados."}


def test_portuguese_and_success_answers_are_untouched() -> None:
    client = _translating_app()
    assert client.get("/fail").json()["error"]["message"] == "Chave de metadado repetida: sla."
    assert client.get("/fail", headers={"accept-language": "pt-BR"}).json()["error"]["message"] == "Chave de metadado repetida: sla."
    assert client.get("/ok", headers={"accept-language": "en"}).json() == {"message": "Acesso negado."}


# --- E-mails -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("locale", "subject", "label"),
    [
        ("pt-BR", "ACME convidou você para o Smart CRM", "Aceitar convite da ACME"),
        ("en", "ACME invited you to Smart CRM", "Accept ACME&#x27;s invitation"),
        ("es", "ACME te invitó a Smart CRM", "Aceptar la invitación de ACME"),
        ("pt-PT", "A ACME enviou-lhe um convite para o Smart CRM", "A ligação é válida durante 48 horas."),
    ],
)
def test_invitation_email_is_written_in_the_requested_language(locale, subject, label) -> None:  # noqa: ANN001
    message = render_invitation_email("ACME", "ana@example.test", "https://crm.test/acme/accept-invite#token=x", locale)
    assert message.subject == subject
    assert label in message.html_body


def test_password_reset_email_is_written_in_the_requested_language() -> None:
    message = render_password_reset_email("ACME", "ana@example.test", "https://crm.test/acme/reset-password#token=x", "es")
    assert message.subject == "Restablece tu contraseña en el Smart CRM de ACME"
    assert "Crear nueva contraseña" in message.html_body
    assert "tu contraseña actual sigue siendo válida" in message.text_body


# --- The user's language, live ------------------------------------------------------------

def test_user_language_is_saved_returned_by_the_session_and_used_for_invitations(live_stack: LiveStack) -> None:  # noqa: F811
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    token = live_stack.login(admin_email, ADMIN_PASSWORD)
    headers = live_stack.admin(token)

    assert live_stack.client.get("/api/auth/session", headers=headers).json()["locale"] == "pt-BR"
    saved = live_stack.client.put("/api/me/preferences", headers=headers, json={"locale": "es"})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"locale": "es"}
    assert saved.headers["cache-control"] == "no-store"
    assert live_stack.client.get("/api/auth/session", headers=headers).json()["locale"] == "es"

    rejected = live_stack.client.put("/api/me/preferences", headers={**headers, "accept-language": "en"}, json={"locale": "fr"})
    assert rejected.status_code == 422
    foreign = live_stack.client.put("/api/me/preferences", headers={"origin": "https://evil.test", "cookie": headers["cookie"]}, json={"locale": "en"})
    assert foreign.status_code == 403
    live_stack.client.cookies.clear()  # the client keeps the login cookie otherwise
    anonymous = live_stack.client.put("/api/me/preferences", headers={"origin": ORIGIN}, json={"locale": "en"})
    assert anonymous.status_code == 401
    assert live_stack.client.get("/api/auth/session", headers=headers).json()["locale"] == "es"

    email = f"en-{uuid.uuid4().hex[:8]}@example.test"
    created = live_stack.client.post(
        "/api/users/invitations",
        headers=headers,
        json={"name": "Ann", "email": email, "jobTitle": "Sales", "team": "Global", "role": "Vendedor", "locale": "en"},
    )
    assert created.status_code == 201, created.text
    assert live_stack.mail.messages[-1].subject == "BRBots invited you to Smart CRM"
    assert _stored_locale(live_stack.database_url, created.json()["user"]["id"]) == "en"

    default = live_stack.client.post(
        "/api/users/invitations",
        headers=headers,
        json={"name": "Bia", "email": f"pt-{uuid.uuid4().hex[:8]}@example.test", "jobTitle": "Vendas", "team": "Global", "role": "Vendedor"},
    )
    assert default.status_code == 201, default.text
    assert live_stack.mail.messages[-1].subject == "BRBots convidou você para o Smart CRM"


def _stored_locale(database_url: str, user_id: str) -> str:
    from sqlalchemy.orm import Session
    from test_account_access_api import _engine
    from test_account_access_service import _set_workspace

    engine = _engine(database_url)
    try:
        with Session(bind=engine) as session, session.begin():
            _set_workspace(session)
            return read_user_locale(session, "default", user_id)
    finally:
        engine.dispose()


def test_password_reset_uses_the_users_language(live_stack: LiveStack) -> None:  # noqa: F811
    _admin_id, admin_email = _seed_member(live_stack.database_url, role="Administrador")
    token = live_stack.login(admin_email, ADMIN_PASSWORD)
    assert live_stack.client.put("/api/me/preferences", headers=live_stack.admin(token), json={"locale": "en"}).status_code == 200
    before = len(live_stack.mail.messages)
    answer = live_stack.client.post("/api/auth/password/forgot", headers={"origin": ORIGIN}, json={"slug": "brbots", "email": admin_email})
    assert answer.status_code == 202
    assert len(live_stack.mail.messages) == before + 1
    assert live_stack.mail.messages[-1].subject == "Reset your password for BRBots's Smart CRM"


def test_errors_reach_the_client_in_its_language(live_stack: LiveStack) -> None:  # noqa: F811
    live_stack.client.cookies.clear()
    portuguese = live_stack.client.put("/api/me/preferences", headers={"origin": ORIGIN}, json={"locale": "en"})
    spanish = live_stack.client.put("/api/me/preferences", headers={"origin": ORIGIN, "accept-language": "es"}, json={"locale": "en"})
    assert (portuguese.status_code, spanish.status_code) == (401, 401)
    assert portuguese.json()["error"] == {"code": "unauthenticated", "message": "Sessão inválida."}
    assert spanish.json()["error"] == {"code": "unauthenticated", "message": "Sesión no válida."}


def test_supported_locales_match_the_database_rule() -> None:
    migration = (ROOT / "migrations" / "versions" / "f2b8d4a6c1e9_allow_portuguese_from_portugal.py").read_text(encoding="utf-8")
    assert "locale IN ('pt-BR', 'pt-PT', 'en', 'es')" in migration
    assert SUPPORTED_LOCALES == ("pt-BR", "pt-PT", "en", "es")
    for locale in SUPPORTED_LOCALES[1:]:
        assert (ROOT / "app" / "static" / "i18n" / f"{locale}.js").is_file(), locale
        assert (ROOT / "app" / "locales" / f"{locale}.json").is_file(), locale


# --- Portuguese from Portugal --------------------------------------------------------------
# pt-PT lists only the texts that differ from Brazilian Portuguese; the rest is shown as is.

def test_portuguese_from_portugal_only_rewrites_known_texts_and_keeps_slots() -> None:
    interface = _interface_dictionary("pt-PT")
    server = catalog_entries("pt-PT")
    assert len(interface) > 150 and len(server) > 30
    for dictionary, source in ((interface, _interface_dictionary("en")), (server, catalog_entries("en"))):
        assert set(dictionary) <= set(source)
        for key, value in dictionary.items():
            assert value != key, key
            assert sorted(SLOT.findall(value)) == sorted(SLOT.findall(key)), key


def test_portuguese_from_portugal_server_messages() -> None:
    assert translate("Este e-mail já pertence a um usuário ativo.", "pt-PT") == "Este e-mail já pertence a um utilizador ativo."
    assert translate("Já existe um contato com o e-mail a@b.pt (C-1).", "pt-PT") == "Já existe um contacto com o e-mail a@b.pt (C-1)."
    # Texts that are the same in both variants pass through unchanged.
    assert translate("Acesso negado.", "pt-PT") == "Acesso negado."
