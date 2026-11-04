"""SMTP smoke test for the Windows release, run as SmartCRMService.

Usage: ``python -m app.mail_cli smoke --to responsavel@empresa``. The password
comes only from the DPAPI file named by ``SMART_CRM_SMTP_PASSWORD_SECRET_FILE``;
the output is a single line with ``PASS`` or a redacted failure code.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Callable, Mapping, Sequence

from app.mail import (
    MailConfigurationError,
    MailDeliveryError,
    MailSender,
    OutboundMessage,
    SmtpMailSender,
    SmtpSettings,
    smtp_settings_from_environment,
)
from app.security.secrets import read_dpapi_secret_file


RECIPIENT_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")


def smoke_message(recipient: str) -> OutboundMessage:
    text = (
        "Este e-mail confirma que o Smart CRM consegue enviar convites e links de "
        "recuperacao de senha por este servidor SMTP. Nenhuma acao e necessaria."
    )
    return OutboundMessage(
        company="Teste de SMTP",
        recipient=recipient,
        subject="Smart CRM - teste de SMTP",
        text_body=text,
        html_body=f"<p>{text}</p>",
        action_link="",
    )


def run_smoke(
    recipient: str,
    *,
    environ: Mapping[str, str],
    read_password: Callable[[str], str] = read_dpapi_secret_file,
    sender_factory: Callable[[SmtpSettings], MailSender] = SmtpMailSender,
) -> tuple[int, str]:
    if len(recipient) > 254 or not RECIPIENT_PATTERN.fullmatch(recipient):
        return 2, "smtp smoke: FAIL code=smtp_recipient_invalid"
    try:
        settings = smtp_settings_from_environment(environ, read_password=read_password)
    except MailConfigurationError as error:
        return 2, f"smtp smoke: FAIL code={error.code}"
    if settings is None:
        return 2, "smtp smoke: FAIL code=smtp_not_configured"
    try:
        sender_factory(settings).send(smoke_message(recipient))
    except MailDeliveryError as error:
        return 1, f"smtp smoke: FAIL code={error.code}"
    return 0, "smtp smoke: PASS"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.mail_cli")
    commands = parser.add_subparsers(dest="command", required=True)
    smoke = commands.add_parser("smoke", help="send one SMTP test message")
    smoke.add_argument("--to", required=True)
    arguments = parser.parse_args(argv)
    code, line = run_smoke(arguments.to, environ=os.environ)
    print(line)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
