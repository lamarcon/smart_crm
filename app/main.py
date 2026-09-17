"""FastAPI application and HTTP contracts for the Smart CRM."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.auth import (
    AuthSettings,
    CookiePrincipalResolver,
    ResolvedPrincipal,
    SESSION_COOKIE_NAME,
)
from app.database import Database, database
from app.policies import Action, can_perform_action
from app.schemas import (
    BootstrapRequest,
    LOGIN_FAILURE_MESSAGE,
    LocateTenantRequest,
    LocateTenantResponse,
    LoginRequest,
    ResetRequest,
    RestoreRequest,
    SaveRequest,
    SessionResponse,
    WorkspaceReferenceError,
    normalize_tenant_identifier,
)
from app.services.auth import AuthenticationError, AuthService, SessionContext
from app.services.workspace import (
    WorkspaceAlreadyInitialized,
    WorkspaceAuthorizationError,
    WorkspaceConflict,
    WorkspaceNotInitialized,
    WorkspaceRecordNotFound,
    WorkspaceRestoreConflict,
    WorkspaceResult,
    WorkspaceService,
)
from app.tenant_database import TenantDatabaseRouter, TenantUnavailableError


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
MAX_BOOTSTRAP_BYTES = 25 * 1024 * 1024
LOG = logging.getLogger("smart-crm-api")
DeletedModule = Literal[
    "users", "leads", "contacts", "companies", "deals", "quotes", "notifications"
]


def _error(
    status_code: int,
    code: str,
    message: str,
    **details: object,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, **details}},
    )


def _state_payload(state) -> dict:  # noqa: ANN001
    return state.model_dump(by_alias=True, exclude_none=True)


def _result_payload(result: WorkspaceResult) -> dict:
    return {
        "version": result.version,
        "counts": result.counts.model_dump(by_alias=True),
        "state": _state_payload(result.state),
    }


def _session_payload(context: SessionContext) -> SessionResponse:
    return SessionResponse(
        tenant_id=context.principal.tenant_id,
        tenant_slug=context.tenant_slug,
        tenant_display_name=context.tenant_display_name,
        user_id=context.principal.user_id,
        user_name=context.user_name,
        email=context.email,
        role=context.principal.role,
    )


def _validation_path(error: RequestValidationError) -> str:
    first = error.errors()[0]
    return ".".join(str(part) for part in first.get("loc", ()))


def create_app(
    settings=None,  # noqa: ANN001 - reserved application-factory contract
    *,
    database_instance: Database | None = None,
    workspace_service: WorkspaceService | None = None,
    static_dir: Path = STATIC_DIR,
    auth_service: AuthService | None = None,
    tenant_router: TenantDatabaseRouter | None = None,
    auth_settings: AuthSettings | None = None,
    principal_dependency: Callable | None = None,
    health_check: Callable[[], bool] | None = None,
) -> FastAPI:
    del settings
    active_database = database_instance or database
    active_health_check = health_check or active_database.check_database
    service = workspace_service or WorkspaceService()
    active_auth_settings = auth_settings or AuthSettings(
        expected_origin="https://sc2030.brbots.com"
    )

    if principal_dependency is not None:
        resolve_principal = principal_dependency
    elif auth_service is not None and tenant_router is not None:
        resolve_principal = CookiePrincipalResolver(
            auth_service,
            tenant_router,
            active_auth_settings,
        )
    else:
        async def resolve_principal() -> None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "auth_unavailable",
                    "message": "Autenticação temporariamente indisponível.",
                },
            )

    app = FastAPI(title="Smart CRM API", docs_url=None, redoc_url=None)

    def audit_request_denial(
        request: Request,
        outcome_code: str,
        context: SessionContext | None = None,
    ) -> None:
        if getattr(request.state, "security_audited", False) or auth_service is None:
            return
        active_context = context or getattr(request.state, "session_context", None)
        if active_context is None:
            tenant_id = None
            user_id = None
            source = request.cookies.get(SESSION_COOKIE_NAME) or (
                f"{request.method}\0{request.url.path}"
            )
        else:
            tenant_id = active_context.principal.tenant_id
            user_id = active_context.principal.user_id
            source = active_context.token_digest
        correlation_digest = sha256(
            f"request-denial\0{source}".encode("utf-8")
        ).hexdigest()
        try:
            auth_service.record_security_event(
                event_type="request.denied",
                tenant_id=tenant_id,
                user_id=user_id,
                correlation_digest=correlation_digest,
                outcome_code=outcome_code,
                occurred_at=datetime.now(timezone.utc),
            )
        except Exception:
            pass
        request.state.security_audited = True


    @app.middleware("http")
    async def contract_middleware(request: Request, call_next):  # noqa: ANN001
        if (
            request.method == "POST"
            and request.url.path == "/api/workspace/bootstrap"
        ):
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_BOOTSTRAP_BYTES:
                        response = _error(
                            413,
                            "payload_too_large",
                            "O corpo da migração excede 25 MB.",
                        )
                        response.headers["Cache-Control"] = "no-store"
                        return _add_security_headers(response)
                except ValueError:
                    pass

            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_BOOTSTRAP_BYTES:
                    response = _error(
                        413,
                        "payload_too_large",
                        "O corpo da migração excede 25 MB.",
                    )
                    response.headers["Cache-Control"] = "no-store"
                    return _add_security_headers(response)
            request._body = bytes(body)

        response = await call_next(request)
        if request.url.path.startswith(("/api/auth", "/api/workspace")):
            response.headers["Cache-Control"] = "no-store"
        return _add_security_headers(response)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        if error.status_code in {401, 403}:
            outcome_code = (
                str(error.detail.get("code", "request_rejected"))
                if isinstance(error.detail, dict)
                else "request_rejected"
            )
            audit_request_denial(request, outcome_code)
        if isinstance(error.detail, dict):
            code = str(error.detail.get("code", "request_rejected"))
            message = str(error.detail.get("message", "Requisição rejeitada."))
            details = {
                key: value
                for key, value in error.detail.items()
                if key not in {"code", "message"}
            }
            response = _error(error.status_code, code, message, **details)
        else:
            response = _error(error.status_code, "request_rejected", str(error.detail))
        if error.headers:
            response.headers.update(error.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return _error(
            422,
            "validation_error",
            "Payload inválido.",
            path=_validation_path(error),
        )

    @app.exception_handler(WorkspaceReferenceError)
    async def reference_error(
        _request: Request, error: WorkspaceReferenceError
    ) -> JSONResponse:
        return _error(
            422,
            "validation_error",
            error.message,
            path=error.path,
        )

    @app.exception_handler(WorkspaceAlreadyInitialized)
    async def already_initialized(
        _request: Request, error: WorkspaceAlreadyInitialized
    ) -> JSONResponse:
        return _error(
            409,
            "workspace_already_initialized",
            "Workspace já inicializado.",
            currentVersion=error.current_version,
        )

    @app.exception_handler(WorkspaceConflict)
    async def version_conflict(
        _request: Request, error: WorkspaceConflict
    ) -> JSONResponse:
        return _error(
            409,
            "version_conflict",
            "Versão do workspace desatualizada.",
            currentVersion=error.current_version,
        )

    @app.exception_handler(WorkspaceNotInitialized)
    async def not_initialized(
        _request: Request, _error_value: WorkspaceNotInitialized
    ) -> JSONResponse:
        return _error(
            409,
            "workspace_not_initialized",
            "Workspace não inicializado.",
        )

    @app.exception_handler(WorkspaceRecordNotFound)
    async def record_not_found(
        _request: Request, _error_value: WorkspaceRecordNotFound
    ) -> JSONResponse:
        return _error(404, "record_not_found", "Registro excluído não encontrado.")

    @app.exception_handler(WorkspaceRestoreConflict)
    async def restore_conflict(
        _request: Request, _error_value: WorkspaceRestoreConflict
    ) -> JSONResponse:
        return _error(409, "restore_conflict", "O registro não pode ser recuperado.")

    @app.exception_handler(WorkspaceAuthorizationError)
    async def authorization_error(
        request: Request,
        _error_value: WorkspaceAuthorizationError,
    ) -> JSONResponse:
        audit_request_denial(request, "forbidden")
        return _error(403, "forbidden", "Acesso negado.")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request: Request, error: SQLAlchemyError) -> JSONResponse:
        error_id = str(uuid.uuid4())
        LOG.error("database request failed errorId=%s", error_id, exc_info=error)
        return _error(
            503,
            "database_unavailable",
            "Banco de dados indisponível.",
            errorId=error_id,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        error_id = str(uuid.uuid4())
        LOG.error("unexpected persistence failure errorId=%s", error_id, exc_info=error)
        return _error(
            500,
            "persistence_error",
            "Não foi possível concluir a operação.",
            errorId=error_id,
        )

    @app.get("/health")
    def health() -> JSONResponse:
        try:
            available = active_health_check()
        except Exception:
            available = False
        if not available:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded"},
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            content={"status": "ok"},
            headers={"Cache-Control": "no-store"},
        )

    def require_auth_service() -> AuthService:
        if auth_service is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "auth_unavailable",
                    "message": "Autenticação temporariamente indisponível.",
                },
            )
        return auth_service

    def require_expected_origin(request: Request) -> None:
        if request.headers.get("origin") != active_auth_settings.expected_origin:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "invalid_origin",
                    "message": "Origem da requisição inválida.",
                },
            )

    def require_action(principal: ResolvedPrincipal, action: Action) -> None:
        if not can_perform_action(principal.context.principal, action):
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Acesso negado."},
            )

    @app.post("/api/auth/locate", response_model=LocateTenantResponse)
    def locate_tenant(
        payload: LocateTenantRequest,
        request: Request,
    ):
        require_expected_origin(request)
        location = require_auth_service().locate_tenant(payload.slug)
        if location is None:
            return _error(404, "invalid_login", LOGIN_FAILURE_MESSAGE)
        return LocateTenantResponse(
            slug=location.slug,
            display_name=location.display_name,
        )

    @app.post("/api/auth/login", response_model=SessionResponse)
    def login(payload: LoginRequest, request: Request, response: Response):
        require_expected_origin(request)
        try:
            result = require_auth_service().login(
                payload.slug,
                payload.email,
                payload.password,
                request.client.host if request.client is not None else "unknown",
                now=datetime.now(timezone.utc),
            )
        except (AuthenticationError, TenantUnavailableError):
            return _error(401, "invalid_login", LOGIN_FAILURE_MESSAGE)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=result.token,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return _session_payload(result.context)

    @app.get("/api/auth/session", response_model=SessionResponse)
    def current_session(
        principal: ResolvedPrincipal = Depends(resolve_principal),
    ) -> SessionResponse:
        return _session_payload(principal.context)

    @app.post(
        "/api/auth/logout",
        status_code=204,
        response_class=Response,
        response_model=None,
    )
    def logout(request: Request, response: Response) -> None:
        require_expected_origin(request)
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token:
            require_auth_service().logout(token, now=datetime.now(timezone.utc))
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value="",
            max_age=0,
            expires=0,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )

    @app.get("/api/workspace")
    def load_workspace(
        principal: ResolvedPrincipal = Depends(resolve_principal),
    ) -> dict:
        require_action(principal, Action.READ)
        loaded = service.load(principal.tenant_session, principal.context.principal)
        return {
            "initialized": loaded.initialized,
            "version": loaded.version,
            "state": _state_payload(loaded.state) if loaded.state is not None else None,
        }

    @app.post("/api/workspace/bootstrap", status_code=201)
    def bootstrap_workspace(
        payload: BootstrapRequest,
        principal: ResolvedPrincipal = Depends(resolve_principal),
    ) -> dict:
        require_action(principal, Action.IMPORT_DATA)
        return _result_payload(
            service.bootstrap(
                principal.tenant_session,
                principal.context.principal,
                payload.state,
            )
        )

    @app.put("/api/workspace")
    def save_workspace(
        payload: SaveRequest,
        principal: ResolvedPrincipal = Depends(resolve_principal),
    ) -> dict:
        require_action(principal, Action.UPDATE)
        return _result_payload(
            service.save(
                principal.tenant_session,
                principal.context.principal,
                payload.version,
                payload.state,
            )
        )

    @app.post("/api/workspace/reset")
    def reset_workspace(
        payload: ResetRequest,
        principal: ResolvedPrincipal = Depends(resolve_principal),
    ) -> dict:
        require_action(principal, Action.RESET_WORKSPACE)
        return _result_payload(
            service.reset(
                principal.tenant_session,
                principal.context.principal,
                payload.version,
                payload.state,
            )
        )

    @app.get("/api/workspace/deleted")
    def list_deleted(
        module: DeletedModule = Query(),
        principal: ResolvedPrincipal = Depends(resolve_principal),
    ) -> dict:
        require_action(principal, Action.RESTORE_DELETED)
        return {
            "module": module,
            "records": service.list_deleted(
                principal.tenant_session,
                principal.context.principal,
                module,
            ),
        }

    @app.post("/api/workspace/restore")
    def restore_workspace(
        payload: RestoreRequest,
        principal: ResolvedPrincipal = Depends(resolve_principal),
    ) -> dict:
        require_action(principal, Action.RESTORE_DELETED)
        return _result_payload(
            service.restore(
                principal.tenant_session,
                principal.context.principal,
                payload.version,
                payload.module,
                payload.record_id,
            )
        )

    @app.get("/")
    def root_shell() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/{tenant_slug}")
    def tenant_shell(tenant_slug: str, request: Request):
        try:
            normalized_slug = normalize_tenant_identifier(tenant_slug)
        except ValueError:
            return _error(404, "tenant_not_found", LOGIN_FAILURE_MESSAGE)

        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token is not None:
            try:
                context = require_auth_service().current_session(
                    token,
                    now=datetime.now(timezone.utc),
                )
            except AuthenticationError:
                audit_request_denial(request, "unauthenticated")
                return _error(401, "unauthenticated", "Sessão inválida.")
            request.state.session_context = context
            if context.tenant_slug != normalized_slug:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "tenant_mismatch",
                        "message": "Empresa da sess\u00e3o n\u00e3o corresponde \u00e0 rota.",
                    },
                )
        return FileResponse(static_dir / "index.html")

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


def _add_security_headers(response):  # noqa: ANN001
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline'"
    return response


app = create_app()
