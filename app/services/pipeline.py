"""Versioned domain service for tenant-scoped deal pipeline configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DealPipeline, DealPipelineAuditEvent, DealPipelineStage, Workspace
from app.policies import CURRENT_ROLES, PrincipalScope
from app.repositories.pipeline import DealPipelineAggregate, DealPipelineRepository
from app.schemas import (
    DealPipelineAuditEventResponse,
    DealPipelineAuditPage,
    DealPipelineResponse,
    DealPipelineStageResponse,
    DealPipelineUpdateRequest,
)


_COLOR_PATTERN = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_SEMANTIC_TYPES = frozenset({"open", "won", "lost"})


class DealPipelineServiceError(RuntimeError):
    code = "pipeline_error"


class DealPipelineAuthorizationError(DealPipelineServiceError):
    code = "pipeline_forbidden"


class DealPipelineValidationError(DealPipelineServiceError):
    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


class DealPipelineVersionConflict(DealPipelineServiceError):
    code = "pipeline_version_conflict"

    def __init__(self, current_version: int) -> None:
        super().__init__("Versão do funil desatualizada")
        self.current_version = current_version


@dataclass(frozen=True)
class _ValidatedStage:
    current: DealPipelineStage | None
    name: str
    semantic_type: str
    color: str
    position: int


def _validation(code: str, field: str, message: str) -> DealPipelineValidationError:
    return DealPipelineValidationError(code, field, message)


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _stage_state(stage: DealPipelineStage, default_stage_id: UUID | None) -> dict:
    return {
        "id": str(stage.id),
        "name": stage.name,
        "semanticType": stage.semantic_type,
        "color": stage.color.upper(),
        "position": stage.position,
        "systemKey": stage.system_key,
        "active": stage.archived_at is None,
        "initial": stage.id == default_stage_id,
        "archivedAt": _timestamp(stage.archived_at),
    }


def _aggregate_state(aggregate: DealPipelineAggregate) -> dict:
    pipeline = aggregate.pipeline
    return {
        "id": str(pipeline.id),
        "name": pipeline.name,
        "pipelineVersion": pipeline.version,
        "defaultStageId": str(pipeline.default_stage_id),
        "stages": [
            _stage_state(stage, pipeline.default_stage_id)
            for stage in sorted(aggregate.stages, key=lambda item: (item.position, item.id))
        ],
    }


class DealPipelineService:
    """Validate and mutate the single default pipeline in the caller transaction."""

    def __init__(
        self,
        repository_factory: Callable[[Session, str], DealPipelineRepository] = DealPipelineRepository,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository_factory = repository_factory
        self.uuid_factory = uuid_factory

    def _repository(
        self, session: Session, principal: PrincipalScope
    ) -> DealPipelineRepository:
        return self.repository_factory(session, principal.workspace_id)

    @staticmethod
    def _require_authenticated(principal: PrincipalScope) -> None:
        if principal.role not in CURRENT_ROLES:
            raise DealPipelineAuthorizationError("principal is not authorized")

    @staticmethod
    def _require_admin(principal: PrincipalScope) -> None:
        if principal.role != "Administrador":
            raise DealPipelineAuthorizationError("principal is not authorized")

    def load(
        self,
        session: Session,
        principal: PrincipalScope,
        *,
        include_archived: bool = False,
    ) -> DealPipelineResponse:
        self._require_authenticated(principal)
        if include_archived:
            self._require_admin(principal)
        repository = self._repository(session, principal)
        aggregate = repository.load_default(include_archived=include_archived)
        return self._response(session, principal, aggregate)

    def update(
        self,
        session: Session,
        principal: PrincipalScope,
        request: DealPipelineUpdateRequest,
    ) -> DealPipelineResponse:
        self._require_admin(principal)
        repository = self._repository(session, principal)
        pipeline = repository.lock_default()
        if pipeline.version != request.pipeline_version:
            raise DealPipelineVersionConflict(pipeline.version)

        aggregate = repository.load_default(include_archived=True)
        validated = self._validate_configuration(aggregate, request)
        before_state = _aggregate_state(aggregate)
        actions: list[dict] = []
        original_values = {
            stage.id: (stage.name, stage.color.upper(), stage.position)
            for stage in aggregate.stages
        }

        # Move active rows out of the partial unique indexes' final key space so
        # swaps of names or positions remain a single atomic aggregate update.
        active_current = [stage for stage in aggregate.stages if stage.archived_at is None]
        for temporary_position, stage in enumerate(active_current, start=1000):
            stage.name = f"__pipeline_tmp_{stage.id.hex}"
            stage.position = temporary_position
        session.flush()

        resulting: list[DealPipelineStage] = []
        for item in validated:
            stage = item.current
            if stage is None:
                stage = DealPipelineStage(
                    id=self.uuid_factory(),
                    workspace_id=principal.workspace_id,
                    pipeline_id=pipeline.id,
                    name=item.name,
                    semantic_type=item.semantic_type,
                    color=item.color,
                    position=item.position,
                    system_key=None,
                    archived_at=None,
                )
                session.add(stage)
                actions.append(
                    {
                        "type": "stage.created",
                        "stageId": str(stage.id),
                        "name": stage.name,
                        "semanticType": stage.semantic_type,
                        "color": stage.color,
                        "position": stage.position,
                    }
                )
            else:
                original_name, original_color, original_position = original_values[stage.id]
                if original_name != item.name:
                    actions.append(
                        {
                            "type": "stage.renamed",
                            "stageId": str(stage.id),
                            "from": original_name,
                            "to": item.name,
                        }
                    )
                if original_color != item.color:
                    actions.append(
                        {
                            "type": "stage.recolored",
                            "stageId": str(stage.id),
                            "from": original_color,
                            "to": item.color,
                        }
                    )
                if original_position != item.position:
                    actions.append(
                        {
                            "type": "stage.reordered",
                            "stageId": str(stage.id),
                            "from": original_position,
                            "to": item.position,
                        }
                    )
                stage.name = item.name
                stage.color = item.color
                stage.position = item.position
            resulting.append(stage)

        if pipeline.default_stage_id != request.default_stage_id:
            actions.append(
                {
                    "type": "pipeline.initial_stage_changed",
                    "fromStageId": str(pipeline.default_stage_id),
                    "toStageId": str(request.default_stage_id),
                }
            )
        pipeline.default_stage_id = request.default_stage_id
        pipeline.version += 1
        session.flush()

        after_aggregate = DealPipelineAggregate(
            pipeline=pipeline,
            stages=tuple(sorted(resulting, key=lambda item: (item.position, item.id))),
        )
        after_state = _aggregate_state(after_aggregate)
        repository.append_audit(
            pipeline_id=pipeline.id,
            actor_user_id=principal.user_id,
            pipeline_version=pipeline.version,
            action="pipeline.updated",
            actions=actions,
            before_state=before_state,
            after_state=after_state,
            transfer_summary=[],
        )
        return self._response(session, principal, after_aggregate)

    def history(
        self,
        session: Session,
        principal: PrincipalScope,
        *,
        before_id: int | None = None,
        limit: int = 50,
    ) -> DealPipelineAuditPage:
        self._require_admin(principal)
        repository = self._repository(session, principal)
        pipeline = repository.load_default().pipeline
        events = repository.list_audit(pipeline.id, before_id=before_id, limit=limit)
        items = [self._audit_response(event) for event in events]
        next_before = items[-1].id if len(items) == limit else None
        return DealPipelineAuditPage(items=items, nextBefore=next_before)

    @staticmethod
    def _validate_configuration(
        aggregate: DealPipelineAggregate,
        request: DealPipelineUpdateRequest,
    ) -> list[_ValidatedStage]:
        if request.transfers:
            raise _validation(
                "pipeline_transfer_not_supported",
                "transfers",
                "Transferências são processadas junto ao arquivamento",
            )

        all_by_id = {stage.id: stage for stage in aggregate.stages}
        active_ids = {
            stage.id for stage in aggregate.stages if stage.archived_at is None
        }
        submitted_ids = [stage.id for stage in request.stages if stage.id is not None]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise _validation(
                "pipeline_stage_duplicate_id", "stages", "Etapa repetida na configuração"
            )
        unknown_ids = set(submitted_ids) - set(all_by_id)
        if unknown_ids:
            raise _validation(
                "pipeline_stage_not_found", "stages", "Etapa não pertence ao funil"
            )
        if set(submitted_ids) != active_ids:
            raise _validation(
                "pipeline_stage_identity_changed",
                "stages",
                "Etapas existentes não podem ser removidas ou substituídas",
            )

        if any(stage.archived for stage in request.stages):
            raise _validation(
                "pipeline_archive_not_supported",
                "stages",
                "Arquivamento requer o fluxo de transferência",
            )
        if len(request.stages) > 50:
            raise _validation(
                "pipeline_stage_limit", "stages", "O funil aceita no máximo 50 etapas ativas"
            )

        validated: list[_ValidatedStage] = []
        normalized_names: set[str] = set()
        positions: set[int] = set()
        semantic_counts = {semantic: 0 for semantic in _SEMANTIC_TYPES}
        default_item: _ValidatedStage | None = None
        for index, submitted in enumerate(request.stages):
            field = f"stages[{index}]"
            name = submitted.name.strip()
            if not 1 <= len(name) <= 80:
                raise _validation(
                    "pipeline_stage_name_invalid", f"{field}.name", "Nome deve ter de 1 a 80 caracteres"
                )
            normalized_name = name.casefold()
            if normalized_name in normalized_names:
                raise _validation(
                    "pipeline_stage_name_duplicate", f"{field}.name", "Nome de etapa duplicado"
                )
            normalized_names.add(normalized_name)
            if not _COLOR_PATTERN.fullmatch(submitted.color):
                raise _validation(
                    "pipeline_stage_color_invalid", f"{field}.color", "Cor deve usar #RRGGBB"
                )
            if submitted.position in positions:
                raise _validation(
                    "pipeline_stage_position_duplicate",
                    f"{field}.position",
                    "Posição de etapa duplicada",
                )
            positions.add(submitted.position)
            current = all_by_id.get(submitted.id) if submitted.id is not None else None
            if current is not None and current.archived_at is not None:
                raise _validation(
                    "pipeline_stage_archived", f"{field}.id", "Etapa arquivada não pode ser reativada"
                )
            if current is not None and current.semantic_type != submitted.semantic_type:
                raise _validation(
                    "pipeline_stage_semantic_immutable",
                    f"{field}.semanticType",
                    "Tipo semântico de etapa existente é imutável",
                )
            item = _ValidatedStage(
                current=current,
                name=name,
                semantic_type=submitted.semantic_type,
                color=submitted.color.upper(),
                position=submitted.position,
            )
            validated.append(item)
            semantic_counts[item.semantic_type] += 1
            if submitted.id == request.default_stage_id:
                default_item = item

        if positions != set(range(len(validated))):
            raise _validation(
                "pipeline_stage_positions_invalid",
                "stages",
                "Posições devem ser contínuas de zero a n-1",
            )
        missing_semantic = next(
            (semantic for semantic, count in semantic_counts.items() if count == 0), None
        )
        if missing_semantic is not None:
            raise _validation(
                "pipeline_semantic_minimum",
                "stages",
                f"O funil requer uma etapa ativa do tipo {missing_semantic}",
            )
        if default_item is None:
            raise _validation(
                "pipeline_default_stage_invalid",
                "defaultStageId",
                "Etapa inicial deve ser uma etapa ativa do funil",
            )
        if default_item.semantic_type != "open":
            raise _validation(
                "pipeline_default_stage_not_open",
                "defaultStageId",
                "Etapa inicial deve ter tipo open",
            )
        return validated

    @staticmethod
    def _workspace_version(
        session: Session, principal: PrincipalScope
    ) -> int:
        version = session.scalar(
            select(Workspace.version).where(Workspace.id == principal.workspace_id)
        )
        if version is None:
            raise DealPipelineServiceError("workspace not found")
        return int(version)

    @classmethod
    def _response(
        cls,
        session: Session,
        principal: PrincipalScope,
        aggregate: DealPipelineAggregate,
    ) -> DealPipelineResponse:
        pipeline = aggregate.pipeline
        return DealPipelineResponse(
            id=pipeline.id,
            name=pipeline.name,
            pipelineVersion=pipeline.version,
            workspaceVersion=cls._workspace_version(session, principal),
            defaultStageId=pipeline.default_stage_id,
            stages=[
                DealPipelineStageResponse(
                    id=stage.id,
                    name=stage.name,
                    semanticType=stage.semantic_type,
                    color=stage.color.upper(),
                    position=stage.position,
                    systemKey=stage.system_key,
                    active=stage.archived_at is None,
                    initial=stage.id == pipeline.default_stage_id,
                    archivedAt=stage.archived_at,
                )
                for stage in sorted(aggregate.stages, key=lambda item: (item.position, item.id))
            ],
            transferCounts={},
        )

    @staticmethod
    def _audit_response(event: DealPipelineAuditEvent) -> DealPipelineAuditEventResponse:
        return DealPipelineAuditEventResponse(
            id=event.id,
            pipelineId=event.pipeline_id,
            actorUserId=event.actor_user_id,
            pipelineVersion=event.pipeline_version,
            action=event.action,
            actions=event.actions,
            beforeState=event.before_state,
            afterState=event.after_state,
            transferSummary=event.transfer_summary,
            createdAt=event.created_at,
        )
