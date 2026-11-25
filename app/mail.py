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

from app.i18n import translate


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


def _single_line(value: str | None, limit: int = 255) -> str:
    return " ".join(str(value or "").split())[:limit]


def _initials(company: str) -> str:
    words = [word for word in company.replace("-", " ").split() if word[:1].isalnum()]
    if len(words) == 1:
        return words[0][:2].upper()
    letters = "".join(word[0] for word in words[:2]) or company[:2]
    return letters.upper()[:2]


# Fixed light palette: e-mail clients ignore CSS variables and most dark-mode rules.
_INK = "#1f1e1d"
_MUTED = "#5f5e5a"
_FAINT = "#888780"
_LINE = "#e6e4dd"
_CANVAS = "#f4f3ef"
_PANEL = "#f7f6f2"
_ACCENT = "#185fa5"
_ACCENT_SOFT = "#e6f1fb"
_FONT = "Arial, Helvetica, sans-serif"


@dataclass(frozen=True)
class _EmailContent:
    subject: str
    header_caption: str
    greeting: str
    intro: str
    details: tuple[tuple[str, str], ...]
    note_title: str | None
    note: str | None
    action_label: str
    validity: str
    fallback: str
    footer: str


def _html_body(company: str, content: _EmailContent, link: str, lang: str) -> str:
    e = html.escape
    rows = "".join(
        f'<tr><td style="padding:3px 16px 3px 0;color:{_MUTED};font-size:13px;white-space:nowrap">{e(label)}</td>'
        f'<td style="padding:3px 0;color:{_INK};font-size:13px">{e(value)}</td></tr>'
        for label, value in content.details
    )
    note = (
        f'<tr><td style="padding:0 28px 16px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0">'
        f'<tr><td style="border-left:3px solid {_ACCENT};padding:4px 0 4px 12px">'
        f'<div style="font-size:12px;color:{_MUTED}">{e(content.note_title or "")}</div>'
        f'<div style="font-size:14px;color:{_INK};white-space:pre-line">{e(content.note)}</div>'
        f"</td></tr></table></td></tr>"
        if content.note
        else ""
    )
    link_attr = e(link, quote=True)
    return (
        f'<!doctype html><html lang="{e(lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{e(content.subject)}</title></head>"
        f'<body style="margin:0;padding:0;background:{_CANVAS};font-family:{_FONT};color:{_INK}">'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{_CANVAS}"><tr><td align="center" style="padding:24px 12px">'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid {_LINE};border-radius:10px">'
        f'<tr><td align="center" style="padding:24px 28px 18px;border-bottom:1px solid {_LINE}">'
        f'<div style="display:inline-block;width:44px;height:44px;line-height:44px;border-radius:10px;background:{_ACCENT_SOFT};color:{_ACCENT};font-size:17px;font-weight:bold;text-align:center">{e(_initials(company))}</div>'
        f'<div style="margin-top:8px;font-size:20px;font-weight:bold;color:{_INK}">{e(company)}</div>'
        f'<div style="font-size:13px;color:{_MUTED}">{e(content.header_caption)}</div>'
        "</td></tr>"
        f'<tr><td style="padding:22px 28px 6px"><div style="font-size:18px;font-weight:bold;color:{_INK}">{e(content.greeting)}</div>'
        f'<p style="margin:8px 0 16px;font-size:15px;line-height:1.6;color:{_INK}">{e(content.intro)}</p></td></tr>'
        f"{note}"
        f'<tr><td style="padding:0 28px 20px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{_PANEL};border-radius:8px">'
        f'<tr><td style="padding:12px 16px"><table role="presentation" cellspacing="0" cellpadding="0">{rows}</table></td></tr></table></td></tr>'
        f'<tr><td align="center" style="padding:0 28px 18px">'
        f'<a href="{link_attr}" style="display:inline-block;background:{_ACCENT};color:#ffffff;text-decoration:none;font-size:15px;font-weight:bold;padding:12px 26px;border-radius:8px">{e(content.action_label)}</a>'
        "</td></tr>"
        f'<tr><td style="padding:0 28px 22px;font-size:13px;line-height:1.6;color:{_MUTED}">'
        f'<p style="margin:0 0 10px">{e(content.validity)}</p>'
        f'<p style="margin:0">{e(content.fallback)}<br><a href="{link_attr}" style="color:{_ACCENT};word-break:break-all">{e(link)}</a></p>'
        "</td></tr>"
        f'<tr><td style="padding:14px 28px;border-top:1px solid {_LINE};font-size:12px;line-height:1.5;color:{_FAINT}">{e(content.footer)}</td></tr>'
        "</table></td></tr></table></body></html>"
    )


def _text_body(company: str, content: _EmailContent, link: str) -> str:
    lines = [company, content.header_caption, "", content.greeting, "", content.intro, ""]
    if content.note:
        lines += [f"{content.note_title}:", content.note, ""]
    lines += [f"{label}: {value}" for label, value in content.details]
    lines += ["", f"{content.action_label}:", link, "", content.validity, "", "--", content.footer, ""]
    return "\n".join(lines)


def _message(company: str, recipient: str, link: str, locale: str, content: _EmailContent) -> OutboundMessage:
    return OutboundMessage(
        company=company,
        recipient=recipient,
        subject=content.subject,
        text_body=_text_body(company, content, link),
        html_body=_html_body(company, content, link, locale),
        action_link=link,
    )


def _access_url(link: str) -> str:
    """The company's CRM address: the action link without its page and token."""

    base = link.split("#", 1)[0].rstrip("/")
    return base.rsplit("/", 1)[0] if base.count("/") > 3 else base


def _greeting(name: str, locale: str) -> str:
    first = name.split()[0] if name.split() else ""
    return translate("Olá, {name}!", locale, name=first) if first else translate("Olá!", locale)


def render_invitation_email(
    company: str,
    recipient: str,
    link: str,
    locale: str = "pt-BR",
    *,
    recipient_name: str | None = None,
    inviter_name: str | None = None,
    role: str | None = None,
    message: str | None = None,
) -> OutboundMessage:
    company = _validated_text(company, field_name="company")
    recipient = _validated_text(recipient, field_name="recipient")
    link = _validated_text(link, field_name="action_link")
    inviter = _single_line(inviter_name)
    note = "\n".join(line.rstrip() for line in str(message or "").strip().splitlines())[:500] or None
    intro = (
        translate("{inviter}, da {company}, convidou você para acessar o Smart Control da empresa.", locale, inviter=inviter, company=company)
        if inviter
        else translate("A {company} convidou você para acessar o Smart Control da empresa.", locale, company=company)
    )
    details = [
        (translate("Empresa", locale), company),
        (translate("Endereço", locale), _access_url(link)),
    ]
    if role:
        details.append((translate("Perfil", locale), translate(_single_line(role), locale)))
    details.append((translate("Seu login", locale), recipient))
    content = _EmailContent(
        subject=translate("{company} convidou você para o Smart Control", locale, company=company),
        header_caption=translate("convite para o Smart Control da empresa", locale),
        greeting=_greeting(_single_line(recipient_name), locale),
        intro=intro,
        details=tuple(details),
        note_title=translate("Mensagem de {inviter}", locale, inviter=inviter) if inviter else translate("Mensagem do administrador", locale),
        note=note,
        action_label=translate("Aceitar convite da {company}", locale, company=company),
        validity=translate("O link vale por 48 horas. Depois disso, peça um novo convite ao administrador.", locale),
        fallback=translate("Se o botão não funcionar, copie este endereço no navegador:", locale),
        footer=translate(
            "Enviado pelo Smart Control em nome da {company}. Se você não conhece a {company} ou não esperava este convite, ignore este e-mail.",
            locale,
            company=company,
        ),
    )
    return _message(company, recipient, link, locale, content)


def render_password_reset_email(
    company: str,
    recipient: str,
    link: str,
    locale: str = "pt-BR",
    *,
    recipient_name: str | None = None,
) -> OutboundMessage:
    company = _validated_text(company, field_name="company")
    recipient = _validated_text(recipient, field_name="recipient")
    link = _validated_text(link, field_name="action_link")
    content = _EmailContent(
        subject=translate("Redefina sua senha no Smart Control da {company}", locale, company=company),
        header_caption=translate("redefinição de senha do Smart Control", locale),
        greeting=_greeting(_single_line(recipient_name), locale),
        intro=translate("Recebemos um pedido para redefinir a senha do seu acesso ao Smart Control da {company}.", locale, company=company),
        details=(
            (translate("Empresa", locale), company),
            (translate("Endereço", locale), _access_url(link)),
            (translate("Seu login", locale), recipient),
        ),
        note_title=None,
        note=None,
        action_label=translate("Criar nova senha", locale),
        validity=translate("O link vale por 48 horas e só pode ser usado uma vez.", locale),
        fallback=translate("Se o botão não funcionar, copie este endereço no navegador:", locale),
        footer=translate(
            "Enviado pelo Smart Control em nome da {company}. Se você não pediu a redefinição, ignore este e-mail: sua senha atual continua valendo.",
            locale,
            company=company,
        ),
    )
    return _message(company, recipient, link, locale, content)


class SmtpMailSender:
    def __init__(self, settings: SmtpSettings) -> None:
        self._settings = settings

    def _email_message(self, message: OutboundMessage) -> EmailMessage:
        email_message = EmailMessage()
        email_message["From"] = formataddr(
            (f"{message.company} · Smart Control", self._settings.from_address)
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
