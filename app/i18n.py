"""Server-side translation of user-facing messages.

Portuguese (pt-BR) is the source language: services keep raising and storing
messages in Portuguese, and the catalogs in ``app/locales`` map that text to
English and Spanish. ``{name}`` in a catalog key marks a variable part, so
messages built with f-strings are translated too. Unknown text is returned
unchanged, which keeps every Portuguese answer exactly as before.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from sqlalchemy import text

SUPPORTED_LOCALES = ("pt-BR", "pt-PT", "en", "es")
DEFAULT_LOCALE = "pt-BR"
LOCALES_DIR = Path(__file__).resolve().parent / "locales"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_LETTER = re.compile(r"[A-Za-zÀ-ÿ]")


def supported_locale(value: object) -> str | None:
    """Maps a language tag (``en-US``, ``es``, ``pt``) to a supported locale."""

    text = str(value or "").strip().lower()
    # Portuguese from Portugal and the African countries; any other "pt" is Brazilian.
    if re.match(r"pt[-_](pt|ao|mz|cv|gw|st|tl)(?![a-z0-9])", text):
        return "pt-PT"
    if text.startswith("pt"):
        return "pt-BR"
    if text.startswith("en"):
        return "en"
    if text.startswith("es"):
        return "es"
    return None


def resolve_locale(accept_language: str | None) -> str:
    """Picks the first supported language of an Accept-Language header, by weight."""

    candidates: list[tuple[float, int, str]] = []
    for index, item in enumerate((accept_language or "").split(",")):
        tag, _, params = item.strip().partition(";")
        weight = 1.0
        match = re.search(r"q\s*=\s*([0-9.]+)", params)
        if match:
            try:
                weight = float(match.group(1))
            except ValueError:
                weight = 0.0
        locale = supported_locale(tag)
        if locale and weight > 0:
            candidates.append((-weight, index, locale))
    return sorted(candidates)[0][2] if candidates else DEFAULT_LOCALE


@dataclass(frozen=True)
class _Pattern:
    prefix: str
    regex: re.Pattern[str]
    names: tuple[str, ...]
    target: str


@dataclass(frozen=True)
class _Catalog:
    exact: dict[str, str]
    patterns: tuple[_Pattern, ...]


def _compile(entries: dict[str, str]) -> _Catalog:
    exact: dict[str, str] = {}
    patterns: list[_Pattern] = []
    for source, target in entries.items():
        if not _PLACEHOLDER.search(source):
            exact[source] = target
            continue
        parts = _PLACEHOLDER.split(source)
        names = tuple(parts[1::2])
        regex = "".join(
            "(.*?)" if index % 2 else re.escape(part) for index, part in enumerate(parts)
        )
        patterns.append(_Pattern(parts[0], re.compile(f"^{regex}$", re.S), names, target))
    patterns.sort(key=lambda pattern: len(pattern.prefix), reverse=True)
    return _Catalog(exact, tuple(patterns))


@lru_cache(maxsize=None)
def catalog(locale: str) -> _Catalog:
    if locale == DEFAULT_LOCALE:
        return _Catalog({}, ())
    path = LOCALES_DIR / f"{locale}.json"
    return _compile(json.loads(path.read_text(encoding="utf-8")))


def read_user_locale(session, workspace_id: str, user_id: str) -> str:  # noqa: ANN001
    value = session.execute(
        text("SELECT locale FROM crm_users WHERE workspace_id = :workspace_id AND id = :user_id"),
        {"workspace_id": workspace_id, "user_id": user_id},
    ).scalar()
    return value if value in SUPPORTED_LOCALES else DEFAULT_LOCALE


def write_user_locale(session, workspace_id: str, user_id: str, locale: str) -> bool:  # noqa: ANN001
    if locale not in SUPPORTED_LOCALES:
        raise ValueError("unsupported locale")
    result = session.execute(
        text(
            "UPDATE crm_users SET locale = :locale "
            "WHERE workspace_id = :workspace_id AND id = :user_id AND deleted_at IS NULL"
        ),
        {"locale": locale, "workspace_id": workspace_id, "user_id": user_id},
    )
    return result.rowcount == 1


def catalog_entries(locale: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{locale}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def translate(text: str, locale: str, **params: object) -> str:
    """Translates a Portuguese message; ``params`` fill ``{name}`` slots."""

    translated = _translate_text(text, locale)
    if params:
        translated = _PLACEHOLDER.sub(
            lambda match: str(params.get(match.group(1), match.group(0))), translated
        )
    return translated


def _translate_text(text: str, locale: str) -> str:
    if locale not in SUPPORTED_LOCALES or locale == DEFAULT_LOCALE:
        return text
    if not isinstance(text, str) or not _LETTER.search(text):
        return text
    stripped = text.strip()
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    table = catalog(locale)
    if stripped in table.exact:
        return lead + table.exact[stripped] + trail
    for pattern in table.patterns:
        if not stripped.startswith(pattern.prefix):
            continue
        match = pattern.regex.match(stripped)
        if match is None:
            continue
        values = dict(zip(pattern.names, match.groups()))
        return lead + _PLACEHOLDER.sub(
            lambda found: values.get(found.group(1), found.group(0)), pattern.target
        ) + trail
    return text


class ErrorMessageTranslationMiddleware:
    """Translates ``message`` in JSON error answers to the request's language.

    The error ``code`` and every other field stay as they are, so clients that
    branch on codes are unaffected. Success answers are never touched.
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(_decoded_headers(scope.get("headers", ())))
        locale = resolve_locale(headers.get("accept-language"))
        if locale == DEFAULT_LOCALE:
            await self.app(scope, receive, send)
            return

        start_message: dict | None = None
        body = bytearray()

        async def translating_send(message) -> None:  # noqa: ANN001
            nonlocal start_message
            if message["type"] == "http.response.start":
                response_headers = dict(_decoded_headers(message.get("headers", ())))
                is_json = response_headers.get("content-type", "").startswith("application/json")
                if message.get("status", 200) >= 400 and is_json:
                    start_message = message
                    return
                await send(message)
                return
            if start_message is None or message["type"] != "http.response.body":
                await send(message)
                return
            body.extend(message.get("body", b""))
            if message.get("more_body", False):
                return
            translated = _translated_error_body(bytes(body), locale)
            start_headers = [
                (name, value)
                for name, value in start_message.get("headers", ())
                if name.lower() != b"content-length"
            ]
            start_headers.append((b"content-length", str(len(translated)).encode("ascii")))
            await send({**start_message, "headers": start_headers})
            await send({"type": "http.response.body", "body": translated, "more_body": False})

        await self.app(scope, receive, translating_send)


def _decoded_headers(raw: Iterable[tuple[bytes, bytes]]) -> Iterable[tuple[str, str]]:
    for name, value in raw:
        yield name.decode("latin-1").lower(), value.decode("latin-1")


def _translated_error_body(body: bytes, locale: str) -> bytes:
    try:
        payload = json.loads(body)
    except ValueError:
        return body
    if not isinstance(payload, dict):
        return body
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        error["message"] = translate(error["message"], locale)
    if isinstance(payload.get("message"), str):
        payload["message"] = translate(payload["message"], locale)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
