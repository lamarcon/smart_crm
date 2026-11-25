"""REST API v1: Leads, Contatos, Empresas, Negócios and Produtos with personal tokens.

Routes live under ``/api/v1/{tenant_slug}`` and take ``Authorization: Bearer
sct_...``. Every call runs as the token's user: reads go through the same
projection as the screens (only the records that user may see) and writes go
through the same workspace save (permissions per record, references, stage
rules, history, automations and the workspace version), so open screens reload
instead of overwriting API changes.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, Query, Request
from fastapi import Path as FastAPIPath
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import select

from app.models import Company, Contact, Deal, Lead, Product
from app.policies import SCOPE_NONE, permission_scope
from app.schemas import WorkspaceReferenceError, WorkspaceState
from app.services.api_tokens import (
    RETRY_AFTER_SECONDS,
    ApiRequestContext,
    ApiTokenInvalidError,
    ApiTokenNotFoundError,
    ApiTokenRateLimitedError,
    ApiTokenReadOnlyError,
    ApiTokenService,
)
from app.services.pipeline import DealPipelineService
from app.services.workspace import (
    WorkspaceAuthorizationError,
    WorkspaceConflict,
    WorkspaceNotInitialized,
    WorkspaceService,
    WorkspaceStageConflict,
)
from app.tenant_database import TenantUnavailableError

API_MODULES: dict[str, tuple[str, type]] = {
    "leads": ("L", Lead),
    "contacts": ("C", Contact),
    "companies": ("E", Company),
    "deals": ("N", Deal),
    "products": ("P", Product),
}
MAX_BODY_BYTES = 256 * 1024
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
SAVE_ATTEMPTS = 3
PROTECTED_FIELDS = frozenset({"id", "createdAt", "restricted"})


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def _error(status: int, code: str, message: str, **details: object) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **details}})


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_number(ids: list[str], prefix: str) -> int:
    highest = 0
    for value in ids:
        head, _, number = str(value).partition("-")
        if head == prefix and number.isdigit():
            highest = max(highest, int(number))
    return highest + 1


def _require(context: ApiRequestContext, module: str, action: str) -> None:
    if permission_scope(context.principal, module, action) == SCOPE_NONE:
        raise ApiError(403, "forbidden", "O perfil deste token não permite esta ação.")


def _visible(records: list[dict]) -> list[dict]:
    return [record for record in records if not record.get("restricted")]


def register_api_v1(
    app: FastAPI,
    *,
    token_service: ApiTokenService | None,
    workspace_service: WorkspaceService,
    pipeline_service: DealPipelineService,
    source_ip: Callable[[Request], str],
    clock: Callable[[], datetime] | None = None,
) -> None:
    now_of = clock or (lambda: datetime.now(timezone.utc))

    def run(request: Request, slug: str, *, write: bool, operation: Callable[[ApiRequestContext], Any]) -> Any:
        if token_service is None:
            raise ApiError(503, "api_unavailable", "API temporariamente indisponível.")
        raw_token = token_service.bearer_token(request.headers.get("authorization"))
        attempts = SAVE_ATTEMPTS if write else 1
        for attempt in range(attempts):
            try:
                with token_service.request(slug, raw_token, source_ip(request), write=write) as context:
                    return operation(context)
            except WorkspaceConflict:
                if attempt == attempts - 1:
                    raise ApiError(409, "version_conflict", "O workspace mudou durante a gravação. Tente de novo.") from None
        raise AssertionError("unreachable")

    async def call(request: Request, slug: str, *, write: bool, operation: Callable[[ApiRequestContext], Any], status: int = 200) -> Response:
        try:
            result = await run_in_threadpool(run, request, slug, write=write, operation=operation)
        except ApiError as error:
            return _error(error.status, error.code, error.message, **error.details)
        except ApiTokenRateLimitedError:
            response = _error(429, "rate_limited", "Muitas requisições. Aguarde e tente novamente.")
            response.headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
            return response
        except ApiTokenReadOnlyError:
            return _error(403, "read_only_token", "Este token é só de leitura.")
        except ApiTokenInvalidError:
            response = _error(401, "invalid_token", "Token de API inválido.")
            response.headers["WWW-Authenticate"] = 'Bearer realm="smart-control"'
            return response
        except ApiTokenNotFoundError:
            return _error(404, "not_found", "Empresa não encontrada.")
        except WorkspaceAuthorizationError:
            return _error(403, "forbidden", "O perfil deste token não permite esta ação.")
        except WorkspaceReferenceError as error:
            return _error(422, "validation_error", str(error))
        except ValidationError as error:
            return _error(422, "validation_error", "Dados inválidos.", detail=error.errors(include_url=False, include_context=False))
        except WorkspaceStageConflict:
            return _error(409, "stage_conflict", "A etapa informada não pertence ao funil do Negócio.")
        except WorkspaceNotInitialized:
            return _error(409, "workspace_not_initialized", "O workspace ainda não foi inicializado.")
        except TenantUnavailableError:
            return _error(503, "unavailable", "Serviço temporariamente indisponível.")
        if status == 204:
            return Response(status_code=204)
        return JSONResponse(status_code=status, content=result)

    async def read_body(request: Request) -> dict:
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            raise ApiError(413, "payload_too_large", "O corpo excede 256 KB.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise ApiError(413, "payload_too_large", "O corpo excede 256 KB.")
        try:
            payload = json.loads(bytes(body).decode("utf-8")) if body else None
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "invalid_json", "Envie um JSON válido em UTF-8.") from None
        if not isinstance(payload, dict):
            raise ApiError(422, "validation_error", "Envie um objeto JSON com os campos do registro.")
        return payload

    def load_data(context: ApiRequestContext) -> tuple[int, dict]:
        loaded = workspace_service.load(context.session, context.principal)
        if not loaded.initialized or loaded.state is None:
            raise WorkspaceNotInitialized("workspace not initialized")
        return loaded.version, loaded.state.model_dump(by_alias=True, exclude_none=True)

    def save_data(context: ApiRequestContext, version: int, data: dict, module: str, record_id: str | None) -> dict | None:
        result = workspace_service.save(context.session, context.principal, version, WorkspaceState.model_validate(data))
        if record_id is None:
            return None
        saved = result.state.model_dump(by_alias=True, exclude_none=True)
        return next((item for item in saved.get(module) or [] if item.get("id") == record_id), None)

    def users_by_id(data: dict) -> dict[str, dict]:
        return {str(user.get("id")): user for user in data.get("users") or []}

    def fill_team(record: dict, data: dict) -> None:
        responsible = users_by_id(data).get(str(record.get("responsibleId") or ""))
        if responsible and responsible.get("team"):
            record["team"] = responsible["team"]

    # Routes -----------------------------------------------------------------------------

    @app.get("/api/v1/{tenant_slug}/me")
    async def api_me(request: Request, tenant_slug: str = FastAPIPath(min_length=1, max_length=64)) -> Response:
        def operation(context: ApiRequestContext) -> dict:
            principal = context.principal
            return {
                "user": {"id": principal.user_id, "name": context.user_name, "role": principal.role},
                "token": {"id": context.token_id, "access": context.access},
                "permissions": {
                    module: {
                        action: permission_scope(principal, module, action)
                        for action in ("read", "create", "update", "delete")
                    }
                    for module in API_MODULES
                },
            }

        return await call(request, tenant_slug, write=False, operation=operation)

    @app.get("/api/v1/{tenant_slug}/pipelines")
    async def api_pipelines(request: Request, tenant_slug: str = FastAPIPath(min_length=1, max_length=64)) -> Response:
        def operation(context: ApiRequestContext) -> dict:
            _require(context, "deals", "read")
            pipelines = pipeline_service.list(context.session, context.principal)
            return {"items": [pipeline.model_dump(by_alias=True, mode="json") for pipeline in pipelines]}

        return await call(request, tenant_slug, write=False, operation=operation)

    @app.get("/api/v1/{tenant_slug}/{module}")
    async def api_list(
        request: Request,
        tenant_slug: str = FastAPIPath(min_length=1, max_length=64),
        module: str = FastAPIPath(min_length=1, max_length=32),
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> Response:
        if module not in API_MODULES:
            return _error(404, "not_found", "Recurso não encontrado.")

        def operation(context: ApiRequestContext) -> dict:
            _require(context, module, "read")
            _version, data = load_data(context)
            records = _visible(data.get(module) or [])
            return {"items": records[offset: offset + limit], "total": len(records), "limit": limit, "offset": offset}

        return await call(request, tenant_slug, write=False, operation=operation)

    @app.get("/api/v1/{tenant_slug}/{module}/{record_id}")
    async def api_get(
        request: Request,
        tenant_slug: str = FastAPIPath(min_length=1, max_length=64),
        module: str = FastAPIPath(min_length=1, max_length=32),
        record_id: str = FastAPIPath(min_length=1, max_length=128),
    ) -> Response:
        if module not in API_MODULES:
            return _error(404, "not_found", "Recurso não encontrado.")

        def operation(context: ApiRequestContext) -> dict:
            _require(context, module, "read")
            _version, data = load_data(context)
            record = next((item for item in _visible(data.get(module) or []) if item.get("id") == record_id), None)
            if record is None:
                raise ApiError(404, "not_found", "Registro não encontrado.")
            return record

        return await call(request, tenant_slug, write=False, operation=operation)

    @app.post("/api/v1/{tenant_slug}/{module}")
    async def api_create(
        request: Request,
        tenant_slug: str = FastAPIPath(min_length=1, max_length=64),
        module: str = FastAPIPath(min_length=1, max_length=32),
    ) -> Response:
        if module not in API_MODULES:
            return _error(404, "not_found", "Recurso não encontrado.")
        try:
            payload = await read_body(request)
        except ApiError as error:
            return _error(error.status, error.code, error.message)
        prefix, model = API_MODULES[module]

        def operation(context: ApiRequestContext) -> dict:
            _require(context, module, "create")
            version, data = load_data(context)
            ids = list(context.session.scalars(select(model.id).where(model.workspace_id == context.principal.workspace_id)))
            stamp = _stamp(now_of())
            record = {key: deepcopy(value) for key, value in payload.items() if key not in PROTECTED_FIELDS}
            record["id"] = f"{prefix}-{_next_number(ids, prefix)}"
            record["createdAt"] = stamp
            record["updatedAt"] = stamp
            user_id = context.principal.user_id
            if module == "leads":
                record.setdefault("stage", "Em contato")
                record.setdefault("responsibleId", user_id)
                record.setdefault("assistants", [])
                fill_team(record, data)
            elif module == "deals":
                record.setdefault("responsibleId", user_id)
                record.setdefault("assistants", [])
                record.setdefault("quotes", [])
                # A new deal starts at the initial stage of its pipeline (the main one by default).
                pipelines = pipeline_service.list(context.session, context.principal)
                wanted = str(record.get("pipelineId") or "")
                pipeline = next(
                    (item for item in pipelines if (str(item.id) == wanted if wanted else item.is_default)),
                    None,
                )
                if pipeline is None:
                    raise ApiError(422, "validation_error", "Funil não encontrado.", field="pipelineId")
                record["pipelineId"] = str(pipeline.id)
                record["stageId"] = str(pipeline.default_stage_id)
                record.pop("stage", None)
                record["stageChangedAt"] = stamp
                record["stageChangedById"] = user_id
                fill_team(record, data)
            elif module == "companies":
                record.setdefault("ownerId", user_id)
            data[module] = [record, *(data.get(module) or [])]
            saved = save_data(context, version, data, module, record["id"])
            if saved is None:
                raise ApiError(403, "forbidden", "O perfil deste token não permite esta ação.")
            return saved

        return await call(request, tenant_slug, write=True, operation=operation, status=201)

    @app.patch("/api/v1/{tenant_slug}/{module}/{record_id}")
    async def api_update(
        request: Request,
        tenant_slug: str = FastAPIPath(min_length=1, max_length=64),
        module: str = FastAPIPath(min_length=1, max_length=32),
        record_id: str = FastAPIPath(min_length=1, max_length=128),
    ) -> Response:
        if module not in API_MODULES:
            return _error(404, "not_found", "Recurso não encontrado.")
        try:
            payload = await read_body(request)
        except ApiError as error:
            return _error(error.status, error.code, error.message)

        def operation(context: ApiRequestContext) -> dict:
            _require(context, module, "update")
            version, data = load_data(context)
            records = data.get(module) or []
            record = next((item for item in records if item.get("id") == record_id and not item.get("restricted")), None)
            if record is None:
                raise ApiError(404, "not_found", "Registro não encontrado.")
            for key, value in payload.items():
                if key in PROTECTED_FIELDS:
                    continue
                if value is None:
                    record.pop(key, None)
                else:
                    record[key] = deepcopy(value)
            record["updatedAt"] = _stamp(now_of())
            if module in ("leads", "deals") and "responsibleId" in payload:
                fill_team(record, data)
            saved = save_data(context, version, data, module, record_id)
            if saved is None:
                raise ApiError(403, "forbidden", "O perfil deste token não permite esta ação.")
            return saved

        return await call(request, tenant_slug, write=True, operation=operation)

    @app.delete("/api/v1/{tenant_slug}/{module}/{record_id}")
    async def api_delete(
        request: Request,
        tenant_slug: str = FastAPIPath(min_length=1, max_length=64),
        module: str = FastAPIPath(min_length=1, max_length=32),
        record_id: str = FastAPIPath(min_length=1, max_length=128),
    ) -> Response:
        if module not in API_MODULES:
            return _error(404, "not_found", "Recurso não encontrado.")

        def operation(context: ApiRequestContext) -> None:
            _require(context, module, "delete")
            version, data = load_data(context)
            records = data.get(module) or []
            if not any(item.get("id") == record_id and not item.get("restricted") for item in records):
                raise ApiError(404, "not_found", "Registro não encontrado.")
            data[module] = [item for item in records if item.get("id") != record_id]
            save_data(context, version, data, module, None)

        return await call(request, tenant_slug, write=True, operation=operation, status=204)
