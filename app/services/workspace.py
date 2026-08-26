"""Transactional and versioned workspace operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Database
from app.models import Workspace
from app.repositories.workspace import WorkspaceRepository
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


class WorkspaceService:
    def __init__(
        self,
        database: Database,
        repository_factory: Callable[[Session], WorkspaceRepository] = WorkspaceRepository,
    ) -> None:
        self.database = database
        self.repository_factory = repository_factory

    def load(self) -> WorkspaceLoad:
        with self.database.session_scope() as session:
            workspace = self._workspace(session)
            if workspace.initialized_at is None:
                return WorkspaceLoad(False, workspace.version, None)
            state = self.repository_factory(session).read_active()
            return WorkspaceLoad(True, workspace.version, state)

    def bootstrap(self, state: WorkspaceState) -> WorkspaceResult:
        validate_references(state)
        with self.database.session_scope() as session:
            workspace = self._locked_workspace(session)
            if workspace.initialized_at is not None:
                raise WorkspaceAlreadyInitialized(workspace.version)
            repository = self.repository_factory(session)
            repository.reconcile(state)
            workspace.version = 1
            workspace.initialized_at = datetime.now(timezone.utc)
            session.flush()
            return self._result(repository, workspace.version)

    def save(self, expected_version: int, state: WorkspaceState) -> WorkspaceResult:
        return self._replace(expected_version, state)

    def reset(self, expected_version: int, state: WorkspaceState) -> WorkspaceResult:
        return self._replace(expected_version, state)

    def list_deleted(self, module: str) -> list[dict]:
        with self.database.session_scope() as session:
            workspace = self._workspace(session)
            if workspace.initialized_at is None:
                raise WorkspaceNotInitialized("Workspace não inicializado")
            return self.repository_factory(session).list_deleted(module)

    def restore(self, expected_version: int, module: str, record_id: str) -> WorkspaceResult:
        with self.database.session_scope() as session:
            workspace = self._locked_initialized(session)
            self._check_version(workspace, expected_version)
            repository = self.repository_factory(session)
            self._check_restore_uniqueness(repository, module, record_id)
            if not repository.restore_record(module, record_id):
                raise WorkspaceRecordNotFound("Registro excluído não encontrado")
            workspace.version += 1
            session.flush()
            return self._result(repository, workspace.version)

    def _replace(self, expected_version: int, state: WorkspaceState) -> WorkspaceResult:
        validate_references(state)
        with self.database.session_scope() as session:
            workspace = self._locked_initialized(session)
            self._check_version(workspace, expected_version)
            repository = self.repository_factory(session)
            repository.reconcile(state)
            workspace.version += 1
            session.flush()
            return self._result(repository, workspace.version)

    def _result(self, repository: WorkspaceRepository, version: int) -> WorkspaceResult:
        canonical = repository.read_active()
        return WorkspaceResult(version=version, state=canonical, counts=count_state(canonical))

    def _workspace(self, session: Session) -> Workspace:
        workspace = session.get(Workspace, "default")
        if workspace is None:
            raise WorkspaceNotInitialized("Schema do workspace não foi inicializado")
        return workspace

    def _locked_workspace(self, session: Session) -> Workspace:
        workspace = session.scalar(
            select(Workspace).where(Workspace.id == "default").with_for_update()
        )
        if workspace is None:
            raise WorkspaceNotInitialized("Schema do workspace não foi inicializado")
        return workspace

    def _locked_initialized(self, session: Session) -> Workspace:
        workspace = self._locked_workspace(session)
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
