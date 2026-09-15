"""Transactional and versioned workspace operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Workspace
from app.policies import (
    Action,
    PrincipalScope,
    RecordScope,
    can_mutate_record,
    can_perform_action,
    can_read_record,
)
from app.repositories.workspace import WorkspaceRepository, team_id_for_name
from app.schemas import PersistedCounts, WorkspaceState, count_state, validate_references


class WorkspaceServiceError(RuntimeError):
    pass


class WorkspaceNotInitialized(WorkspaceServiceError):
    pass


class WorkspaceAlreadyInitialized(WorkspaceServiceError):
    def __init__(self, current_version: int) -> None:
        super().__init__("Workspace já inicializado")
        self.current_version = current_version


class WorkspaceConflict(WorkspaceServiceError):
    def __init__(self, current_version: int) -> None:
        super().__init__("Versão do workspace desatualizada")
        self.current_version = current_version


class WorkspaceRecordNotFound(WorkspaceServiceError):
    pass


class WorkspaceRestoreConflict(WorkspaceServiceError):
    pass


class WorkspaceAuthorizationError(WorkspaceServiceError):
    pass


@dataclass(frozen=True)
class WorkspaceLoad:
    initialized: bool
    version: int
    state: WorkspaceState | None


@dataclass(frozen=True)
class WorkspaceResult:
    version: int
    state: WorkspaceState
    counts: PersistedCounts


def _require_action(principal: PrincipalScope, action: Action) -> None:
    if not can_perform_action(principal, action):
        raise WorkspaceAuthorizationError("principal is not authorized")


def _record_scope(record: dict) -> RecordScope:
    team_value = record.get("team")
    team_id = record.get("teamId")
    if not team_id and isinstance(team_value, str) and team_value:
        team_id = team_id_for_name(team_value)
    return RecordScope(
        responsible_id=record.get("responsibleId"),
        assistant_ids=tuple(record.get("assistants") or ()),
        team_id=team_id,
    )


def _project_ui(ui: dict, user_id: str) -> dict:
    filters = [
        deepcopy(item)
        for item in ui.get("savedFilters") or []
        if item.get("userId") == user_id
    ]
    view_modes = ui.get("viewModesByUser") or {}
    dashboard_scopes = ui.get("dashboardScopeByUser") or {}
    return {
        "savedFilters": filters,
        "viewModesByUser": (
            {user_id: deepcopy(view_modes[user_id])} if user_id in view_modes else {}
        ),
        "dashboardScopeByUser": (
            {user_id: dashboard_scopes[user_id]}
            if user_id in dashboard_scopes
            else {}
        ),
    }


def project_workspace_state(
    canonical: WorkspaceState,
    principal: PrincipalScope,
) -> WorkspaceState:
    _require_action(principal, Action.READ)
    data = deepcopy(canonical.model_dump(by_alias=True, exclude_none=True))
    data.pop("currentUserId", None)
    if principal.role == "Administrador":
        return WorkspaceState.model_validate(data)

    for module in ("leads", "deals"):
        data[module] = [
            record
            for record in data[module]
            if can_read_record(principal, module, _record_scope(record))
        ]
    data["notifications"] = [
        item
        for item in data["notifications"]
        if item.get("userId") == principal.user_id
    ]
    data["ui"] = _project_ui(data.get("ui") or {}, principal.user_id)
    return WorkspaceState.model_validate(data)


def _merge_scoped_records(
    module: str,
    canonical: list[dict],
    submitted: list[dict],
    principal: PrincipalScope,
) -> list[dict]:
    canonical_by_id = {record.get("id"): record for record in canonical}
    visible_ids = {
        record_id
        for record_id, record in canonical_by_id.items()
        if can_mutate_record(principal, module, _record_scope(record))
    }
    authorized: list[dict] = []
    for record in submitted:
        record_id = record.get("id")
        if record_id in canonical_by_id and record_id not in visible_ids:
            raise WorkspaceAuthorizationError("record is outside principal scope")
        if not can_mutate_record(principal, module, _record_scope(record)):
            raise WorkspaceAuthorizationError("record is outside principal scope")
        authorized.append(deepcopy(record))
    invisible = [
        deepcopy(record)
        for record_id, record in canonical_by_id.items()
        if record_id not in visible_ids
    ]
    return [*authorized, *invisible]


def _merge_notifications(
    canonical: list[dict],
    submitted: list[dict],
    principal: PrincipalScope,
) -> list[dict]:
    if any(item.get("userId") != principal.user_id for item in submitted):
        raise WorkspaceAuthorizationError("notification is outside principal scope")
    invisible = [
        deepcopy(item)
        for item in canonical
        if item.get("userId") != principal.user_id
    ]
    return [*deepcopy(submitted), *invisible]


def _merge_ui(canonical: dict, submitted: dict, principal: PrincipalScope) -> dict:
    user_id = principal.user_id
    submitted_filters = submitted.get("savedFilters") or []
    submitted_modes = submitted.get("viewModesByUser") or {}
    submitted_scopes = submitted.get("dashboardScopeByUser") or {}
    if (
        any(item.get("userId") != user_id for item in submitted_filters)
        or any(key != user_id for key in submitted_modes)
        or any(key != user_id for key in submitted_scopes)
    ):
        raise WorkspaceAuthorizationError("preference is outside principal scope")

    merged = deepcopy(canonical)
    merged["savedFilters"] = [
        deepcopy(item)
        for item in canonical.get("savedFilters") or []
        if item.get("userId") != user_id
    ] + deepcopy(submitted_filters)
    modes = deepcopy(canonical.get("viewModesByUser") or {})
    modes.pop(user_id, None)
    modes.update(deepcopy(submitted_modes))
    merged["viewModesByUser"] = modes
    scopes = deepcopy(canonical.get("dashboardScopeByUser") or {})
    scopes.pop(user_id, None)
    scopes.update(deepcopy(submitted_scopes))
    merged["dashboardScopeByUser"] = scopes
    return merged


def merge_authorized_state(
    canonical: WorkspaceState,
    submitted: WorkspaceState,
    principal: PrincipalScope,
) -> WorkspaceState:
    _require_action(principal, Action.UPDATE)
    canonical_data = canonical.model_dump(by_alias=True, exclude_none=True)
    submitted_data = submitted.model_dump(by_alias=True, exclude_none=True)
    if principal.role == "Administrador":
        merged_data = deepcopy(submitted_data)
    else:
        projected_data = project_workspace_state(canonical, principal).model_dump(
            by_alias=True,
            exclude_none=True,
        )
        for key in ("users", "customFieldSchemas", "moduleFieldSettings"):
            if submitted_data.get(key) != projected_data.get(key):
                raise WorkspaceAuthorizationError("administrative snapshot change")

        merged_data = deepcopy(canonical_data)
        for module in ("contacts", "companies"):
            merged_data[module] = deepcopy(submitted_data[module])
        for module in ("leads", "deals"):
            merged_data[module] = _merge_scoped_records(
                module,
                canonical_data[module],
                submitted_data[module],
                principal,
            )
        merged_data["notifications"] = _merge_notifications(
            canonical_data["notifications"],
            submitted_data["notifications"],
            principal,
        )
        merged_data["ui"] = _merge_ui(
            canonical_data.get("ui") or {},
            submitted_data.get("ui") or {},
            principal,
        )

    merged_data.pop("currentUserId", None)
    merged = WorkspaceState.model_validate(merged_data)
    validate_references(merged)
    return merged


def _state_with_principal_identity(
    state: WorkspaceState,
    principal: PrincipalScope,
) -> WorkspaceState:
    data = state.model_dump(by_alias=True, exclude_none=True)
    data.pop("currentUserId", None)
    result = WorkspaceState.model_validate(data)
    validate_references(result)
    return result


class WorkspaceService:
    def __init__(
        self,
        repository_factory: Callable[[Session, str], WorkspaceRepository] = WorkspaceRepository,
    ) -> None:
        self.repository_factory = repository_factory

    def _repository(
        self,
        session: Session,
        principal: PrincipalScope,
    ) -> WorkspaceRepository:
        return self.repository_factory(session, principal.workspace_id)

    def load(self, session: Session, principal: PrincipalScope) -> WorkspaceLoad:
        _require_action(principal, Action.READ)
        repository = self._repository(session, principal)
        workspace = self._workspace(session, principal)
        if workspace.initialized_at is None:
            return WorkspaceLoad(False, workspace.version, None)
        canonical = repository.read_active()
        return WorkspaceLoad(
            True,
            workspace.version,
            project_workspace_state(canonical, principal),
        )

    def bootstrap(
        self,
        session: Session,
        principal: PrincipalScope,
        state: WorkspaceState,
    ) -> WorkspaceResult:
        _require_action(principal, Action.IMPORT_DATA)
        state = _state_with_principal_identity(state, principal)
        repository = self._repository(session, principal)
        workspace = self._locked_workspace(session, principal)
        if workspace.initialized_at is not None:
            raise WorkspaceAlreadyInitialized(workspace.version)
        repository.reconcile(state)
        workspace.version = 1
        workspace.initialized_at = datetime.now(timezone.utc)
        session.flush()
        return self._result(repository, principal, workspace.version)

    def save(
        self,
        session: Session,
        principal: PrincipalScope,
        expected_version: int,
        state: WorkspaceState,
    ) -> WorkspaceResult:
        _require_action(principal, Action.UPDATE)
        repository = self._repository(session, principal)
        workspace = self._locked_initialized(session, principal)
        self._check_version(workspace, expected_version)
        canonical = repository.read_active()
        merged = merge_authorized_state(canonical, state, principal)
        repository.reconcile(merged)
        workspace.version += 1
        session.flush()
        return self._result(repository, principal, workspace.version)

    def reset(
        self,
        session: Session,
        principal: PrincipalScope,
        expected_version: int,
        state: WorkspaceState,
    ) -> WorkspaceResult:
        _require_action(principal, Action.RESET_WORKSPACE)
        state = _state_with_principal_identity(state, principal)
        repository = self._repository(session, principal)
        workspace = self._locked_initialized(session, principal)
        self._check_version(workspace, expected_version)
        repository.reconcile(state)
        workspace.version += 1
        session.flush()
        return self._result(repository, principal, workspace.version)

    def list_deleted(
        self,
        session: Session,
        principal: PrincipalScope,
        module: str,
    ) -> list[dict]:
        _require_action(principal, Action.RESTORE_DELETED)
        repository = self._repository(session, principal)
        workspace = self._workspace(session, principal)
        if workspace.initialized_at is None:
            raise WorkspaceNotInitialized("Workspace não inicializado")
        return repository.list_deleted(module)

    def restore(
        self,
        session: Session,
        principal: PrincipalScope,
        expected_version: int,
        module: str,
        record_id: str,
    ) -> WorkspaceResult:
        _require_action(principal, Action.RESTORE_DELETED)
        repository = self._repository(session, principal)
        workspace = self._locked_initialized(session, principal)
        self._check_version(workspace, expected_version)
        self._check_restore_uniqueness(repository, module, record_id)
        if not repository.restore_record(module, record_id):
            raise WorkspaceRecordNotFound("Registro excluído não encontrado")
        workspace.version += 1
        session.flush()
        return self._result(repository, principal, workspace.version)

    @staticmethod
    def _result(
        repository: WorkspaceRepository,
        principal: PrincipalScope,
        version: int,
    ) -> WorkspaceResult:
        canonical = repository.read_active()
        projected = project_workspace_state(canonical, principal)
        return WorkspaceResult(
            version=version,
            state=projected,
            counts=count_state(projected),
        )

    @staticmethod
    def _workspace(session: Session, principal: PrincipalScope) -> Workspace:
        workspace = session.scalar(
            select(Workspace).where(Workspace.id == principal.workspace_id)
        )
        if workspace is None:
            raise WorkspaceNotInitialized("Schema do workspace não foi inicializado")
        return workspace

    @staticmethod
    def _locked_workspace(session: Session, principal: PrincipalScope) -> Workspace:
        workspace = session.scalar(
            select(Workspace)
            .where(Workspace.id == principal.workspace_id)
            .with_for_update()
        )
        if workspace is None:
            raise WorkspaceNotInitialized("Schema do workspace não foi inicializado")
        return workspace

    def _locked_initialized(
        self,
        session: Session,
        principal: PrincipalScope,
    ) -> Workspace:
        workspace = self._locked_workspace(session, principal)
        if workspace.initialized_at is None:
            raise WorkspaceNotInitialized("Workspace não inicializado")
        return workspace

    @staticmethod
    def _check_version(workspace: Workspace, expected_version: int) -> None:
        if workspace.version != expected_version:
            raise WorkspaceConflict(workspace.version)

    @staticmethod
    def _check_restore_uniqueness(
        repository: WorkspaceRepository, module: str, record_id: str
    ) -> None:
        if module != "users":
            return
        deleted = next(
            (item for item in repository.list_deleted(module) if item.get("id") == record_id),
            None,
        )
        if deleted is None:
            return
        email = str(deleted.get("email", "")).casefold()
        if email and any(
            str(item.get("email", "")).casefold() == email
            for item in repository.read_active().users
        ):
            raise WorkspaceRestoreConflict("E-mail já pertence a um usuário ativo")
