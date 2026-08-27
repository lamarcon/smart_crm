"""FastAPI application and HTTP contracts for the Smart CRM."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.database import Database, database
from app.schemas import (
    BootstrapRequest,
    ResetRequest,
    RestoreRequest,
    SaveRequest,
    WorkspaceReferenceError,
)
from app.services.workspace import (
    WorkspaceAlreadyInitialized,
    WorkspaceConflict,
    WorkspaceNotInitialized,
    WorkspaceRecordNotFound,
    WorkspaceRestoreConflict,
    WorkspaceResult,
    WorkspaceService,
)


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


def _validation_path(error: RequestValidationError) -> str:
    first = error.errors()[0]
    return ".".join(str(part) for part in first.get("loc", ()))


def create_app(
    settings=None,  # noqa: ANN001 - reserved application-factory contract
    *,
    database_instance: Database | None = None,
    workspace_service: WorkspaceService | None = None,
    static_dir: Path = STATIC_DIR,
) -> FastAPI:
    del settings
    active_database = database_instance or database
    service = workspace_service or WorkspaceService(active_database)
    app = FastAPI(title="Smart CRM API", docs_url=None, redoc_url=None)

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
                    return _add_security_headers(response)
            request._body = bytes(body)

        response = await call_next(request)
        return _add_security_headers(response)

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
            available = active_database.check_database()
        except Exception:
            available = False
        if not available:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "database": "unavailable"},
            )
        return JSONResponse(content={"status": "ok", "database": "ok"})

    @app.get("/api/workspace")
    def load_workspace() -> dict:
        loaded = service.load()
        return {
            "initialized": loaded.initialized,
            "version": loaded.version,
            "state": _state_payload(loaded.state) if loaded.state is not None else None,
        }

    @app.post("/api/workspace/bootstrap", status_code=201)
    def bootstrap_workspace(payload: BootstrapRequest) -> dict:
        return _result_payload(service.bootstrap(payload.state))

    @app.put("/api/workspace")
    def save_workspace(payload: SaveRequest) -> dict:
        return _result_payload(service.save(payload.version, payload.state))

    @app.post("/api/workspace/reset")
    def reset_workspace(payload: ResetRequest) -> dict:
        return _result_payload(service.reset(payload.version, payload.state))

    @app.get("/api/workspace/deleted")
    def list_deleted(module: DeletedModule = Query()) -> dict:
        return {"module": module, "records": service.list_deleted(module)}

    @app.post("/api/workspace/restore")
    def restore_workspace(payload: RestoreRequest) -> dict:
        return _result_payload(
            service.restore(payload.version, payload.module, payload.record_id)
        )

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


def _add_security_headers(response):  # noqa: ANN001
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline'"
    return response


app = create_app()
