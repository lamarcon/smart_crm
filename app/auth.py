"""Cookie-only FastAPI principal resolution and request guards."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import AsyncIterator
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from app.services.auth import AuthenticationError, AuthService, SessionContext
from app.tenant_database import TenantDatabaseRouter, TenantUnavailableError


SESSION_COOKIE_NAME = "__Host-smartcrm_session"
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{22,128}\Z")
_ALTERNATE_QUERY_KEYS = frozenset({"token", "session", "session_token", "access_token"})
_ALTERNATE_HEADER_KEYS = frozenset({"authorization", "x-session-token"})
_ALTERNATE_BODY_KEYS = frozenset({"token", "session", "session_token", "access_token"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@dataclass(frozen=True)
class AuthSettings:
    expected_origin: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.expected_origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("expected_origin must be an HTTPS origin without path")
        object.__setattr__(self, "expected_origin", self.expected_origin.rstrip("/"))


@dataclass(frozen=True)
class ResolvedPrincipal:
    context: SessionContext
    tenant_session: object


def _contains_alternate_body_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in _ALTERNATE_BODY_KEYS or _contains_alternate_body_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_alternate_body_key(item) for item in value)
    return False


class CookiePrincipalResolver:
    def __init__(
        self,
        auth_service: AuthService,
        router: TenantDatabaseRouter,
        settings: AuthSettings,
    ) -> None:
        self._auth_service = auth_service
        self._router = router
        self._settings = settings

    def _audit_denial(
        self,
        code: str,
        *,
        request: Request | None = None,
        context: SessionContext | None = None,
        token: str | None = None,
    ) -> None:
        if context is not None:
            tenant_id = context.principal.tenant_id
            user_id = context.principal.user_id
            source = context.token_digest
        else:
            tenant_id = None
            user_id = None
            source = token or (
                f"{request.method}\0{request.url.path}" if request is not None else "anonymous"
            )
        correlation_digest = sha256(
            f"request-denial\0{source}".encode("utf-8")
        ).hexdigest()
        try:
            self._auth_service.record_security_event(
                event_type="request.denied",
                tenant_id=tenant_id,
                user_id=user_id,
                correlation_digest=correlation_digest,
                outcome_code=code,
                occurred_at=datetime.now(timezone.utc),
            )
        except Exception:
            pass
        if request is not None:
            request.state.security_audited = True


    def _validate_origin(self, request: Request) -> None:
        if request.method.upper() in _SAFE_METHODS:
            return
        if request.headers.get("origin") != self._settings.expected_origin:
            self._audit_denial(
                "invalid_origin",
                request=request,
                token=request.cookies.get(SESSION_COOKIE_NAME),
            )
            raise _http_error(403, "invalid_origin", "Origem da requisição inválida.")

    async def _reject_alternate_session_sources(self, request: Request) -> None:
        if any(key.lower() in _ALTERNATE_QUERY_KEYS for key in request.query_params.keys()):
            self._audit_denial("unauthenticated", request=request)
            raise _http_error(401, "unauthenticated", "Sessão inválida.")
        if any(request.headers.get(key) is not None for key in _ALTERNATE_HEADER_KEYS):
            self._audit_denial("unauthenticated", request=request)
            raise _http_error(401, "unauthenticated", "Sessão inválida.")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if request.method.upper() not in _SAFE_METHODS and content_type == "application/json":
            try:
                payload = await request.json()
            except Exception:
                return
            if _contains_alternate_body_key(payload):
                self._audit_denial("unauthenticated", request=request)
                raise _http_error(401, "unauthenticated", "Sessão inválida.")

    async def __call__(self, request: Request) -> AsyncIterator[ResolvedPrincipal]:
        self._validate_origin(request)
        await self._reject_alternate_session_sources(request)
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token is None or not _TOKEN_PATTERN.fullmatch(token):
            self._audit_denial("unauthenticated", request=request, token=token)
            raise _http_error(401, "unauthenticated", "Sessão inválida.")
        try:
            context = self._auth_service.current_session(
                token,
                now=datetime.now(timezone.utc),
            )
        except AuthenticationError:
            self._audit_denial("unauthenticated", request=request, token=token)
            raise _http_error(401, "unauthenticated", "Sessão inválida.") from None

        changed_user_ids: tuple[str, ...] = ()
        try:
            with self._router.tenant_session_scope(context.principal.tenant_id) as tenant_session:
                resolved = ResolvedPrincipal(context=context, tenant_session=tenant_session)
                request.state.session_context = context
                yield resolved
                changed_user_ids = tuple(
                    sorted(getattr(tenant_session, "info", {}).get("auth_changed_user_ids", ()))
                )
        except TenantUnavailableError:
            raise _http_error(
                503,
                "tenant_unavailable",
                "Banco da empresa temporariamente indisponível.",
            ) from None

        revoked_at = datetime.now(timezone.utc)
        for user_id in changed_user_ids:
            self._auth_service.revoke_user_sessions(
                context.principal.tenant_id,
                user_id,
                reason="auth_changed",
                now=revoked_at,
            )

    def require_tenant_route(self, context: SessionContext, route_slug: str) -> None:
        if route_slug != context.tenant_slug:
            self._audit_denial("tenant_mismatch", context=context)
            raise _http_error(403, "tenant_mismatch", "Empresa da sessão não corresponde à rota.")
