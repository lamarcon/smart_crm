"""Versioned domain service for tenant-scoped deal pipeline configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CrmUser, DealPipeline, DealPipelineAuditEvent, DealPipelineStage, Workspace
from app.policies import CURRENT_ROLES, PrincipalScope
from app.repositories.activity import ActivityRepository
from app.repositories.pipeline import DealPipelineAggregate, DealPipelineRepository
from app.schemas import (
    DealPipelineAuditEventResponse,
    DealPipelineAuditPage,
    DealPipelineResponse,
    DealPipelineStageResponse,
    DealPipelineUpdateRequest,
)
from app.services.activity import movement_events_for_transitions
from app.services.deal_automation import DealAutomationExecutor, DealTransition


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

    def __init__(self, current_version: int, current_workspace_version: int | None = None) -> None:
        super().__init__("Versão do funil desatualizada")
        self.current_version = current_version
        self.current_workspace_version = current_workspace_version


@dataclass(frozen=True)
class _ValidatedStage:
    current: DealPipelineStage | None
    name: str
    semantic_type: str
    color: str
    position: int
    archived: bool


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
        activity_repository_factory: Callable[[Session, str], ActivityRepository] = ActivityRepository,
        automation_executor: DealAutomationExecutor | None = None,
        uuid_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository_factory = repository_factory
        self.activity_repository_factory = activity_repository_factory
        self.uuid_factory = uuid_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.automation_executor = automation_executor or DealAutomationExecutor(clock=self.clock)

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
        archive_items = [item for item in validated if item.archived]
        active_items = [item for item in validated if not item.archived]
        transfer_plan, transfer_counts = self._validate_archive_plan(
            repository,
            pipeline,
            archive_items,
            active_items,
            request.transfers,
        )
        workspace = None
        if sum(transfer_counts.values()) > 0:
            workspace = self._locked_workspace(session, principal)
            if workspace.version != request.workspace_version:
                raise DealPipelineVersionConflict(pipeline.version, workspace.version)
        before_state = _aggregate_state(aggregate)
        actions: list[dict] = []
        original_values = {
            stage.id: (stage.name, stage.color.upper(), stage.position)
            for stage in aggregate.stages
        }

        changed_at = self.clock()
        transfer_summary: list[dict] = []
        for source, target in transfer_plan:
            transferred = repository.transfer_deals(
                source.id,
                target,
                principal.user_id,
                changed_at,
            )
            transfer_counts[source.id] = len(transferred)
            transfer_summary.append(
                {
                    "sourceStageId": str(source.id),
                    "targetStageId": str(target.id),
                    "count": len(transferred),
                }
            )
            operation_key = (
                f"pipeline-transfer:{pipeline.id}:{request.pipeline_version}:"
                f"{source.id}:{target.id}"
            )
            transitions = tuple(
                DealTransition(
                    deal_id=result.deal_id,
                    from_stage_id=result.from_stage_id,
                    to_stage_id=result.to_stage_id,
                    from_stage_name=result.from_stage_name,
                    to_stage_name=result.to_stage_name,
                    source="pipeline_transfer",
                    occurred_at=changed_at,
                )
                for result in transferred
            )
            if transitions:
                actor_name = session.scalar(
                    select(CrmUser.name).where(
                        CrmUser.workspace_id == principal.workspace_id,
                        CrmUser.id == principal.user_id,
                    )
                )
                activity_repository = self.activity_repository_factory(
                    session, principal.workspace_id
                )
                activity_repository.append_many(
                    movement_events_for_transitions(
                        transitions,
                        None,
                        principal,
                        operation_key,
                        actor_name=actor_name,
                    )
                )
                for transition, result in zip(transitions, transferred, strict=True):
                    if not result.deleted:
                        self.automation_executor.execute_for_transition(
                            session,
                            principal,
                            transition,
                            operation_key,
                        )

        for item in archive_items:
            assert item.current is not None
            item.current.archived_at = changed_at
            actions.append(
                {
                    "type": "stage.archived",
                    "stageId": str(item.current.id),
                    "transferCount": transfer_counts[item.current.id],
                    "targetStageId": (
                        str(request.transfers[item.current.id])
                        if item.current.id in request.transfers
                        else None
                    ),
                }
            )
        if archive_items:
            session.flush()

        # Move remaining active rows out of the partial unique indexes' final
        # key space so swaps remain a single atomic aggregate update.
        active_current = [
            stage
            for stage in aggregate.stages
            if stage.archived_at is None
        ]
        for temporary_position, stage in enumerate(active_current, start=1000):
            stage.name = f"__pipeline_tmp_{stage.id.hex}"
            stage.position = temporary_position
        session.flush()

        resulting: list[DealPipelineStage] = []
        renamed: list[DealPipelineStage] = []
        for item in active_items:
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
                if original_name != item.name:
                    renamed.append(stage)
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
        if workspace is not None:
            workspace.version += 1
        session.flush()

        for stage in renamed:
            repository.synchronize_stage_name(stage.id, stage.name)

        response_aggregate = DealPipelineAggregate(
            pipeline=pipeline,
            stages=tuple(sorted(resulting, key=lambda item: (item.position, item.id))),
        )
        prior_archived = [
            stage
            for stage in aggregate.stages
            if stage.archived_at is not None and stage not in resulting
        ]
        after_aggregate = DealPipelineAggregate(
            pipeline=pipeline,
            stages=tuple([*resulting, *prior_archived]),
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
            transfer_summary=transfer_summary,
        )
        return self._response(
            session,
            principal,
            response_aggregate,
            transfer_counts=transfer_counts,
        )

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

        if sum(not stage.archived for stage in request.stages) > 50:
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
            if not submitted.archived:
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
            if not submitted.archived:
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
            if submitted.archived and current is None:
                raise _validation(
                    "pipeline_new_stage_archived",
                    f"{field}.archived",
                    "Uma nova etapa não pode nascer arquivada",
                )
            if submitted.archived and current is not None and (
                name != current.name or submitted.color.upper() != current.color.upper()
            ):
                raise _validation(
                    "pipeline_archived_stage_modified",
                    field,
                    "A etapa deve ser arquivada sem alterar nome ou cor",
                )
            item = _ValidatedStage(
                current=current,
                name=name,
                semantic_type=submitted.semantic_type,
                color=submitted.color.upper(),
                position=submitted.position,
                archived=submitted.archived,
            )
            validated.append(item)
            if not item.archived:
                semantic_counts[item.semantic_type] += 1
            if submitted.id == request.default_stage_id and not item.archived:
                default_item = item

        active_count = sum(not item.archived for item in validated)
        if positions != set(range(active_count)):
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
    def _validate_archive_plan(
        repository: DealPipelineRepository,
        pipeline: DealPipeline,
        archive_items: list[_ValidatedStage],
        active_items: list[_ValidatedStage],
        transfers: dict[UUID, UUID],
    ) -> tuple[list[tuple[DealPipelineStage, DealPipelineStage]], dict[UUID, int]]:
        archived_by_id = {
            item.current.id: item.current
            for item in archive_items
            if item.current is not None
        }
        active_by_id = {
            item.current.id: item.current
            for item in active_items
            if item.current is not None
        }
        if set(transfers) - set(archived_by_id):
            raise _validation(
                "pipeline_transfer_source_invalid",
                "transfers",
                "Origem de transferência deve ser arquivada nesta gravação",
            )
        counts = repository.count_deals_by_stage(archived_by_id)
        plan: list[tuple[DealPipelineStage, DealPipelineStage]] = []
        for source_id, source in archived_by_id.items():
            count = counts[source_id]
            target_id = transfers.get(source_id)
            if count > 0 and target_id is None:
                raise _validation(
                    "pipeline_archive_target_required",
                    f"transfers.{source_id}",
                    "Etapa ocupada exige destino ativo",
                )
            if count == 0 and target_id is None:
                continue
            if count == 0:
                raise _validation(
                    "pipeline_archive_target_unnecessary",
                    f"transfers.{source_id}",
                    "Etapa vazia não requer transferência",
                )
            target = active_by_id.get(target_id)
            if target is None or target.id == source.id:
                raise _validation(
                    "pipeline_archive_target_invalid",
                    f"transfers.{source_id}",
                    "Destino deve ser outra etapa ativa do mesmo funil",
                )
            try:
                canonical_target = repository.load_stage(
                    target.id,
                    pipeline_id=pipeline.id,
                    include_archived=False,
                    for_update=True,
                )
            except LookupError as error:
                raise _validation(
                    "pipeline_archive_target_invalid",
                    f"transfers.{source_id}",
                    "Destino deve ser outra etapa ativa do mesmo funil",
                ) from error
            plan.append((source, canonical_target))
        return plan, counts

    @staticmethod
    def _locked_workspace(
        session: Session, principal: PrincipalScope
    ) -> Workspace:
        workspace = session.scalar(
            select(Workspace)
            .where(Workspace.id == principal.workspace_id)
            .with_for_update()
        )
        if workspace is None:
            raise DealPipelineServiceError("workspace not found")
        return workspace

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
        *,
        transfer_counts: dict[UUID, int] | None = None,
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
            transferCounts=transfer_counts or {},
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
