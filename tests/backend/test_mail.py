from __future__ import annotations

import smtplib
from email.message import EmailMessage

import pytest

from app.mail import (
    InMemoryMailSender,
    MailConfigurationError,
    MailDeliveryError,
    SmtpMailSender,
    SmtpSettings,
    render_invitation_email,
    render_password_reset_email,
)


COMPANY = 'BRBots <Comercial> & "Parceiros"'
RECIPIENT = "employee@example.com"
LINK = "https://crm.example/brbots/accept#token=a&next=<login>"


class FakeSmtpClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[object] = []
        self.message: EmailMessage | None = None

    def __enter__(self) -> FakeSmtpClient:
        self.calls.append("enter")
        return self

    def __exit__(self, *_args: object) -> None:
        self.calls.append("exit")

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self, *, context: object) -> None:
        self.calls.append(("starttls", context))

    def login(self, username: str, password: str) -> None:
        self.calls.append(("login", username, password))

    def send_message(
        self,
        message: EmailMessage,
        *,
        from_addr: str,
        to_addrs: list[str],
    ) -> None:
        self.calls.append(("send_message", from_addr, to_addrs))
        self.message = message
        if self.failure is not None:
            raise self.failure


def smtp_settings(tls_mode: str = "starttls") -> SmtpSettings:
    return SmtpSettings(
        host="smtp.example.com",
        port=587 if tls_mode == "starttls" else 465,
        username="mailer@example.com",
        password="smtp-super-secret",
        from_address="smart-crm@example.com",
        tls_mode=tls_mode,
        timeout_seconds=4.5,
    )


@pytest.mark.parametrize(
    ("renderer", "subject_fragment", "path_fragment"),
    [
        (render_invitation_email, "Você foi convidado", "accept"),
        (render_password_reset_email, "Redefina sua senha", "reset"),
    ],
)
def test_fixed_templates_include_identity_and_escape_html(
    renderer,  # noqa: ANN001
    subject_fragment: str,
    path_fragment: str,
) -> None:
    message = renderer(COMPANY, RECIPIENT, LINK.replace("accept", path_fragment))

    assert message.recipient == RECIPIENT
    assert subject_fragment in message.subject
    assert COMPANY in message.subject
    assert COMPANY in message.text_body
    assert message.text_body.count(message.action_link) == 1
    assert message.html_body.count("href=") == 1
    assert message.html_body.count("&lt;") >= 2
    assert "<Comercial>" not in message.html_body
    assert 'next=<login>' not in message.html_body
    assert "Smart CRM" in message.text_body


def test_in_memory_sender_captures_messages_deterministically() -> None:
    sender = InMemoryMailSender()
    message = render_invitation_email("BRBots", RECIPIENT, LINK)

    sender.send(message)

    assert sender.messages == [message]


def test_smtp_sender_uses_starttls_before_authentication(monkeypatch) -> None:  # noqa: ANN001
    client = FakeSmtpClient()
    constructor_calls: list[tuple[object, ...]] = []

    def smtp(host: str, port: int, *, timeout: float) -> FakeSmtpClient:
        constructor_calls.append((host, port, timeout))
        return client

    monkeypatch.setattr(smtplib, "SMTP", smtp)
    sender = SmtpMailSender(smtp_settings("starttls"))

    sender.send(render_invitation_email("BRBots", RECIPIENT, LINK))

    assert constructor_calls == [("smtp.example.com", 587, 4.5)]
    assert [call[0] if isinstance(call, tuple) else call for call in client.calls] == [
        "enter",
        "ehlo",
        "starttls",
        "ehlo",
        "login",
        "send_message",
        "exit",
    ]
    assert client.message is not None
    assert client.message["From"] == "Smart CRM — BRBots <smart-crm@example.com>"
    assert client.message["To"] == RECIPIENT


def test_smtp_sender_supports_implicit_tls_without_starttls(monkeypatch) -> None:  # noqa: ANN001
    client = FakeSmtpClient()
    constructor_calls: list[tuple[object, ...]] = []

    def smtp_ssl(
        host: str,
        port: int,
        *,
        timeout: float,
        context: object,
    ) -> FakeSmtpClient:
        constructor_calls.append((host, port, timeout, context))
        return client

    monkeypatch.setattr(smtplib, "SMTP_SSL", smtp_ssl)
    sender = SmtpMailSender(smtp_settings("implicit_tls"))

    sender.send(render_password_reset_email("BRBots", RECIPIENT, LINK))

    assert constructor_calls[0][:3] == ("smtp.example.com", 465, 4.5)
    assert "starttls" not in [
        call[0] if isinstance(call, tuple) else call for call in client.calls
    ]
    assert ("login", "mailer@example.com", "smtp-super-secret") in client.calls


def test_unencrypted_smtp_mode_is_rejected() -> None:
    with pytest.raises(MailConfigurationError) as captured:
        smtp_settings("plain")

    assert captured.value.code == "smtp_tls_required"
    assert str(captured.value) == "smtp_tls_required"


def test_smtp_settings_redact_password_and_reject_header_injection() -> None:
    settings = smtp_settings()

    assert "smtp-super-secret" not in repr(settings)
    with pytest.raises(MailConfigurationError) as captured:
        SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="mailer@example.com",
            password="smtp-super-secret",
            from_address="smart-crm@example.com\r\nBcc: attacker@example.com",
            tls_mode="starttls",
        )

    assert captured.value.code == "smtp_configuration_invalid"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (smtplib.SMTPAuthenticationError(535, b"smtp-super-secret"), "smtp_auth_failed"),
        (
            smtplib.SMTPRecipientsRefused(
                {RECIPIENT: (550, b"recipient and token=a rejected")}
            ),
            "smtp_recipient_refused",
        ),
        (TimeoutError("smtp-super-secret token=a"), "smtp_timeout"),
    ],
)
def test_smtp_failures_expose_only_stable_redacted_codes(
    monkeypatch,  # noqa: ANN001
    failure: Exception,
    expected_code: str,
) -> None:
    client = FakeSmtpClient(failure=failure)
    monkeypatch.setattr(
        smtplib,
        "SMTP",
        lambda _host, _port, *, timeout: client,
    )
    sender = SmtpMailSender(smtp_settings())

    with pytest.raises(MailDeliveryError) as captured:
        sender.send(render_invitation_email("BRBots", RECIPIENT, LINK))

    assert captured.value.code == expected_code
    assert str(captured.value) == expected_code
    assert "smtp-super-secret" not in str(captured.value)
    assert "token=a" not in str(captured.value)


# --- T11: SMTP settings from the environment --------------------------------

from app.mail import UnconfiguredMailSender, smtp_settings_from_environment  # noqa: E402

FULL_SMTP_ENVIRONMENT = {
    "SMART_CRM_SMTP_HOST": "smtp.example.test",
    "SMART_CRM_SMTP_PORT": "587",
    "SMART_CRM_SMTP_USERNAME": "crm@example.test",
    "SMART_CRM_SMTP_FROM_ADDRESS": "crm@example.test",
    "SMART_CRM_SMTP_TLS_MODE": "starttls",
    "SMART_CRM_SMTP_TIMEOUT_SECONDS": "8",
    "SMART_CRM_SMTP_PASSWORD_SECRET_FILE": "C:/ProgramData/SmartCRM/service-secrets/smtp-password.bin",
}


def _never_read(_path: str) -> str:
    raise AssertionError("password file must not be read")


def test_smtp_environment_absent_means_not_configured() -> None:
    assert smtp_settings_from_environment({}, read_password=_never_read) is None
    assert smtp_settings_from_environment(
        {"SMART_CRM_SMTP_HOST": "  "}, read_password=_never_read
    ) is None


def test_smtp_environment_reads_the_password_only_from_the_secret_file() -> None:
    reads: list[str] = []

    def read(path: str) -> str:
        reads.append(path)
        return "segredo-ficticio"

    settings = smtp_settings_from_environment(FULL_SMTP_ENVIRONMENT, read_password=read)

    assert reads == [FULL_SMTP_ENVIRONMENT["SMART_CRM_SMTP_PASSWORD_SECRET_FILE"]]
    assert (settings.host, settings.port, settings.tls_mode, settings.timeout_seconds) == (
        "smtp.example.test",
        587,
        "starttls",
        8.0,
    )
    assert settings.password == "segredo-ficticio"
    assert "segredo-ficticio" not in repr(settings)


def test_smtp_environment_without_credentials_and_default_timeout() -> None:
    environment = {
        key: value
        for key, value in FULL_SMTP_ENVIRONMENT.items()
        if key
        not in {
            "SMART_CRM_SMTP_USERNAME",
            "SMART_CRM_SMTP_PASSWORD_SECRET_FILE",
            "SMART_CRM_SMTP_TIMEOUT_SECONDS",
        }
    }

    settings = smtp_settings_from_environment(environment, read_password=_never_read)

    assert (settings.username, settings.password, settings.timeout_seconds) == ("", "", 10.0)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"SMART_CRM_SMTP_PASSWORD": "texto-puro"}, "smtp_plaintext_password_rejected"),
        ({"SMART_CRM_SMTP_HOST": ""}, "smtp_configuration_incomplete"),
        ({"SMART_CRM_SMTP_FROM_ADDRESS": ""}, "smtp_configuration_incomplete"),
        ({"SMART_CRM_SMTP_TLS_MODE": ""}, "smtp_configuration_incomplete"),
        ({"SMART_CRM_SMTP_TLS_MODE": "plain"}, "smtp_tls_required"),
        ({"SMART_CRM_SMTP_PORT": "porta"}, "smtp_configuration_invalid"),
        ({"SMART_CRM_SMTP_PORT": "70000"}, "smtp_configuration_invalid"),
        ({"SMART_CRM_SMTP_TIMEOUT_SECONDS": "0"}, "smtp_configuration_invalid"),
        ({"SMART_CRM_SMTP_TIMEOUT_SECONDS": "61"}, "smtp_configuration_invalid"),
        ({"SMART_CRM_SMTP_FROM_ADDRESS": "sem-arroba"}, "smtp_configuration_invalid"),
        ({"SMART_CRM_SMTP_USERNAME": ""}, "smtp_credentials_incomplete"),
        ({"SMART_CRM_SMTP_PASSWORD_SECRET_FILE": ""}, "smtp_credentials_incomplete"),
    ],
)
def test_smtp_environment_rejects_unsafe_or_incomplete_settings(changes, code: str) -> None:
    environment = {**FULL_SMTP_ENVIRONMENT, **changes}

    with pytest.raises(MailConfigurationError) as failure:
        smtp_settings_from_environment(environment, read_password=lambda _path: "segredo-ficticio")

    assert failure.value.code == code
    assert "segredo-ficticio" not in str(failure.value)
    assert "texto-puro" not in str(failure.value)


@pytest.mark.parametrize("result", [OSError("acesso negado C:/x"), ""])
def test_smtp_environment_reports_an_unreadable_secret_without_details(result) -> None:  # noqa: ANN001
    def read(_path: str) -> str:
        if isinstance(result, Exception):
            raise result
        return result

    with pytest.raises(MailConfigurationError) as failure:
        smtp_settings_from_environment(FULL_SMTP_ENVIRONMENT, read_password=read)

    assert failure.value.code == "smtp_password_unreadable"
    assert failure.value.__cause__ is None


def test_unconfigured_sender_always_fails_delivery() -> None:
    message = render_invitation_email("BRBots", RECIPIENT, LINK)

    with pytest.raises(MailDeliveryError) as failure:
        UnconfiguredMailSender().send(message)

    assert failure.value.code == "smtp_not_configured"
