"""Secure, injectable email delivery for tenant account actions."""

from __future__ import annotations

import html
import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr
from typing import Callable, Mapping, Protocol


_TLS_MODES = frozenset({"starttls", "implicit_tls"})


class MailConfigurationError(ValueError):
    """A stable configuration failure that never contains credentials."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MailDeliveryError(RuntimeError):
    """A stable delivery failure that never contains message or server details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    from_address: str
    tls_mode: str
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.tls_mode not in _TLS_MODES:
            raise MailConfigurationError("smtp_tls_required")
        if (
            not self.host
            or not self.from_address
            or any("\r" in value or "\n" in value for value in (self.host, self.from_address))
            or not (1 <= self.port <= 65535)
        ):
            raise MailConfigurationError("smtp_configuration_invalid")
        if self.timeout_seconds <= 0:
            raise MailConfigurationError("smtp_configuration_invalid")
        if bool(self.username) != bool(self.password):
            raise MailConfigurationError("smtp_credentials_incomplete")


@dataclass(frozen=True)
class OutboundMessage:
    company: str
    recipient: str
    subject: str
    text_body: str
    html_body: str
    action_link: str


class MailSender(Protocol):
    def send(self, message: OutboundMessage) -> None: ...


class InMemoryMailSender:
    """Deterministic sender for service, route and acceptance tests."""

    def __init__(self) -> None:
        self.messages: list[OutboundMessage] = []

    def send(self, message: OutboundMessage) -> None:
        self.messages.append(message)


def _validated_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or "\r" in normalized or "\n" in normalized:
        raise MailConfigurationError(f"invalid_{field_name}")
    return normalized


def _render_message(
    *,
    company: str,
    recipient: str,
    link: str,
    subject: str,
    heading: str,
    instruction: str,
    action_label: str,
) -> OutboundMessage:
    normalized_company = _validated_text(company, field_name="company")
    normalized_recipient = _validated_text(recipient, field_name="recipient")
    normalized_link = _validated_text(link, field_name="action_link")
    escaped_company = html.escape(normalized_company)
    escaped_heading = html.escape(heading)
    escaped_instruction = html.escape(instruction)
    escaped_link = html.escape(normalized_link, quote=True)
    escaped_label = html.escape(action_label)
    return OutboundMessage(
        company=normalized_company,
        recipient=normalized_recipient,
        subject=subject.format(company=normalized_company),
        text_body=(
            f"Smart CRM — {normalized_company}\n\n"
            f"{heading}\n\n"
            f"{instruction}\n\n"
            f"{normalized_link}\n"
        ),
        html_body=(
            "<!doctype html><html><body>"
            f"<p><strong>Smart CRM — {escaped_company}</strong></p>"
            f"<h1>{escaped_heading}</h1>"
            f"<p>{escaped_instruction}</p>"
            f'<p><a href="{escaped_link}">{escaped_label}</a></p>'
            "</body></html>"
        ),
        action_link=normalized_link,
    )


def render_invitation_email(
    company: str,
    recipient: str,
    link: str,
) -> OutboundMessage:
    return _render_message(
        company=company,
        recipient=recipient,
        link=link,
        subject="Você foi convidado para o Smart CRM da {company}",
        heading="Seu convite para o Smart CRM",
        instruction="Use o link abaixo para criar sua senha e aceitar o convite.",
        action_label="Aceitar convite",
    )


def render_password_reset_email(
    company: str,
    recipient: str,
    link: str,
) -> OutboundMessage:
    return _render_message(
        company=company,
        recipient=recipient,
        link=link,
        subject="Redefina sua senha no Smart CRM da {company}",
        heading="Redefinição de senha",
        instruction="Use o link abaixo para criar uma nova senha.",
        action_label="Redefinir senha",
    )


class SmtpMailSender:
    def __init__(self, settings: SmtpSettings) -> None:
        self._settings = settings

    def _email_message(self, message: OutboundMessage) -> EmailMessage:
        email_message = EmailMessage()
        email_message["From"] = formataddr(
            (f"Smart CRM — {message.company}", self._settings.from_address)
        )
        email_message["To"] = message.recipient
        email_message["Subject"] = message.subject
        email_message.set_content(message.text_body)
        email_message.add_alternative(message.html_body, subtype="html")
        return email_message

    def _deliver(self, client: smtplib.SMTP, message: OutboundMessage) -> None:
        if self._settings.username:
            client.login(self._settings.username, self._settings.password)
        client.send_message(
            self._email_message(message),
            from_addr=self._settings.from_address,
            to_addrs=[message.recipient],
        )

    def send(self, message: OutboundMessage) -> None:
        context = ssl.create_default_context()
        try:
            if self._settings.tls_mode == "implicit_tls":
                with smtplib.SMTP_SSL(
                    self._settings.host,
                    self._settings.port,
                    timeout=self._settings.timeout_seconds,
                    context=context,
                ) as client:
                    self._deliver(client, message)
                return

            with smtplib.SMTP(
                self._settings.host,
                self._settings.port,
                timeout=self._settings.timeout_seconds,
            ) as client:
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
                self._deliver(client, message)
        except smtplib.SMTPAuthenticationError:
            raise MailDeliveryError("smtp_auth_failed") from None
        except smtplib.SMTPRecipientsRefused:
            raise MailDeliveryError("smtp_recipient_refused") from None
        except (TimeoutError, socket.timeout):
            raise MailDeliveryError("smtp_timeout") from None
        except ssl.SSLError:
            raise MailDeliveryError("smtp_tls_failed") from None
        except smtplib.SMTPException:
            raise MailDeliveryError("smtp_protocol_error") from None
        except OSError:
            raise MailDeliveryError("smtp_unavailable") from None


class UnconfiguredMailSender:
    """Used when no SMTP setting exists: every delivery fails without side effects."""

    def send(self, message: OutboundMessage) -> None:  # noqa: ARG002
        raise MailDeliveryError("smtp_not_configured")


SMTP_ENVIRONMENT_KEYS = (
    "SMART_CRM_SMTP_HOST",
    "SMART_CRM_SMTP_PORT",
    "SMART_CRM_SMTP_USERNAME",
    "SMART_CRM_SMTP_FROM_ADDRESS",
    "SMART_CRM_SMTP_TLS_MODE",
    "SMART_CRM_SMTP_TIMEOUT_SECONDS",
    "SMART_CRM_SMTP_PASSWORD_SECRET_FILE",
)
SMTP_PLAINTEXT_PASSWORD_KEY = "SMART_CRM_SMTP_PASSWORD"
DEFAULT_SMTP_TIMEOUT_SECONDS = 10.0
MAX_SMTP_TIMEOUT_SECONDS = 60.0


def smtp_settings_from_environment(
    environ: Mapping[str, str],
    *,
    read_password: Callable[[str], str],
) -> SmtpSettings | None:
    """Build SMTP settings from non-secret keys plus a DPAPI-protected password file.

    Returns ``None`` when no SMTP key is present. A plaintext password key, a
    partial configuration or an unreadable secret raises a code-only
    ``MailConfigurationError`` that never includes values.
    """

    if environ.get(SMTP_PLAINTEXT_PASSWORD_KEY):
        raise MailConfigurationError("smtp_plaintext_password_rejected")
    values = {key: (environ.get(key) or "").strip() for key in SMTP_ENVIRONMENT_KEYS}
    if not any(values.values()):
        return None
    host = values["SMART_CRM_SMTP_HOST"]
    from_address = values["SMART_CRM_SMTP_FROM_ADDRESS"]
    tls_mode = values["SMART_CRM_SMTP_TLS_MODE"]
    if not host or not from_address or not tls_mode:
        raise MailConfigurationError("smtp_configuration_incomplete")
    try:
        port = int(values["SMART_CRM_SMTP_PORT"])
        raw_timeout = values["SMART_CRM_SMTP_TIMEOUT_SECONDS"]
        timeout = float(raw_timeout) if raw_timeout else DEFAULT_SMTP_TIMEOUT_SECONDS
    except ValueError:
        raise MailConfigurationError("smtp_configuration_invalid") from None
    if not 0 < timeout <= MAX_SMTP_TIMEOUT_SECONDS or "@" not in from_address:
        raise MailConfigurationError("smtp_configuration_invalid")
    username = values["SMART_CRM_SMTP_USERNAME"]
    secret_file = values["SMART_CRM_SMTP_PASSWORD_SECRET_FILE"]
    password = ""
    if username or secret_file:
        if not username or not secret_file:
            raise MailConfigurationError("smtp_credentials_incomplete")
        try:
            password = read_password(secret_file)
        except Exception:
            raise MailConfigurationError("smtp_password_unreadable") from None
        if not password:
            raise MailConfigurationError("smtp_password_unreadable")
    return SmtpSettings(
        host=host,
        port=port,
        username=username,
        password=password,
        from_address=from_address,
        tls_mode=tls_mode,
        timeout_seconds=timeout,
    )
