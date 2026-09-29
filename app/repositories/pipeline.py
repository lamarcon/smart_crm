"""Tenant-scoped persistence operations for the customizable deal pipeline."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import (
    Deal,
    DealPipeline,
    DealPipelineAuditEvent,
    DealPipelineStage,
    DealStageHistory,
)


class PipelineScopeError(RuntimeError):
    """Raised before business SQL when the trusted workspace context is invalid."""


class PipelineNotFoundError(LookupError):
    pass


class PipelineStageNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class DealPipelineAggregate:
    pipeline: DealPipeline
    stages: tuple[DealPipelineStage, ...]


_COMMERCIAL_AUDIT_KEYS = frozenset(
    {
        "amount",
        "companies",
        "contacts",
        "deals",
        "leads",
        "notifications",
        "payload",
        "quotes",
        "record",
    }
)


def _contains_commercial_payload(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in _COMMERCIAL_AUDIT_KEYS
            or _contains_commercial_payload(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_commercial_payload(item) for item in value)
    return False


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class DealPipelineRepository:
    """Read and mutate one pipeline without trusting caller-provided scope."""

    def __init__(self, session: Session, workspace_id: str) -> None:
        self.session = session
        context_workspace_id = session.scalar(
            text("SELECT current_setting('smartcrm.workspace_id', true)")
        )
        if not context_workspace_id:
            raise PipelineScopeError("workspace context unavailable")
        context_workspace_id = str(context_workspace_id)
        if not workspace_id or workspace_id != context_workspace_id:
            raise PipelineScopeError("workspace context mismatch")
        self.workspace_id = context_workspace_id

    def load_default(self, *, include_archived: bool = False) -> DealPipelineAggregate:
        pipeline = self.session.scalar(
            select(DealPipeline).where(
                DealPipeline.workspace_id == self.workspace_id,
                DealPipeline.is_default.is_(True),
            )
        )
        if pipeline is None:
            raise PipelineNotFoundError("default pipeline not found")
        stage_query = select(DealPipelineStage).where(
            DealPipelineStage.workspace_id == self.workspace_id,
            DealPipelineStage.pipeline_id == pipeline.id,
        )
        if not include_archived:
            stage_query = stage_query.where(DealPipelineStage.archived_at.is_(None))
        stages = self.session.scalars(
            stage_query.order_by(
                DealPipelineStage.position.asc(),
                DealPipelineStage.id.asc(),
            )
        ).all()
        return DealPipelineAggregate(pipeline=pipeline, stages=tuple(stages))

    def lock_default(self) -> DealPipeline:
        pipeline = self.session.scalar(
            select(DealPipeline)
            .where(
                DealPipeline.workspace_id == self.workspace_id,
                DealPipeline.is_default.is_(True),
            )
            .with_for_update()
        )
        if pipeline is None:
            raise PipelineNotFoundError("default pipeline not found")
        return pipeline

    def load_stage(
        self,
        stage_id: UUID,
        *,
        pipeline_id: UUID | None = None,
        include_archived: bool = True,
        for_update: bool = False,
    ) -> DealPipelineStage:
        query = select(DealPipelineStage).where(
            DealPipelineStage.workspace_id == self.workspace_id,
            DealPipelineStage.id == stage_id,
        )
        if pipeline_id is not None:
            query = query.where(DealPipelineStage.pipeline_id == pipeline_id)
        if not include_archived:
            query = query.where(DealPipelineStage.archived_at.is_(None))
        if for_update:
            query = query.with_for_update()
        stage = self.session.scalar(query)
        if stage is None:
            raise PipelineStageNotFoundError("pipeline stage not found")
        return stage

    def count_deals_by_stage(self, stage_ids: Iterable[UUID]) -> dict[UUID, int]:
        requested = tuple(dict.fromkeys(stage_ids))
        if not requested:
            return {}
        rows = self.session.execute(
            select(Deal.stage_id, func.count(Deal.id))
            .where(
                Deal.workspace_id == self.workspace_id,
                Deal.stage_id.in_(requested),
            )
            .group_by(Deal.stage_id)
        ).all()
        counts = {stage_id: 0 for stage_id in requested}
        counts.update({stage_id: int(count) for stage_id, count in rows})
        return counts

    def transfer_deals(
        self,
        source_id: UUID,
        target: DealPipelineStage,
        actor_user_id: str,
        changed_at: datetime,
    ) -> int:
        canonical_target = self.load_stage(
            target.id,
            pipeline_id=target.pipeline_id,
            include_archived=False,
            for_update=True,
        )
        source = self.load_stage(
            source_id,
            pipeline_id=canonical_target.pipeline_id,
            include_archived=True,
            for_update=True,
        )
        if source.id == canonical_target.id:
            raise ValueError("transfer target must differ from source")

        deals = self.session.scalars(
            select(Deal)
            .where(
                Deal.workspace_id == self.workspace_id,
                Deal.pipeline_id == canonical_target.pipeline_id,
                Deal.stage_id == source.id,
            )
            .order_by(Deal.id.asc())
            .with_for_update()
        ).all()
        if not deals:
            return 0

        positions = dict(
            self.session.execute(
                select(
                    DealStageHistory.deal_id,
                    func.coalesce(func.max(DealStageHistory.position), -1),
                )
                .where(
                    DealStageHistory.workspace_id == self.workspace_id,
                    DealStageHistory.deal_id.in_([deal.id for deal in deals]),
                )
                .group_by(DealStageHistory.deal_id)
            ).all()
        )
        changed_at_text = _timestamp(changed_at)
        for deal in deals:
            record = deepcopy((deal.payload or {}).get("record") or {})
            history = list(record.get("stageHistory") or [])
            history.append(
                {
                    "from": source.name,
                    "to": canonical_target.name,
                    "fromStageId": str(source.id),
                    "toStageId": str(canonical_target.id),
                    "at": changed_at_text,
                    "byId": actor_user_id,
                }
            )
            record.update(
                {
                    "pipelineId": str(canonical_target.pipeline_id),
                    "stageId": str(canonical_target.id),
                    "stage": canonical_target.name,
                    "stageChangedAt": changed_at_text,
                    "stageChangedById": actor_user_id,
                    "stageHistory": history,
                }
            )
            if canonical_target.semantic_type == "won":
                if deal.won_at is None:
                    deal.won_at = changed_at
                record["wonAt"] = _timestamp(deal.won_at)
            else:
                deal.won_at = None
                record.pop("wonAt", None)

            deal.pipeline_id = canonical_target.pipeline_id
            deal.stage_id = canonical_target.id
            deal.stage = canonical_target.name
            deal.stage_changed_at = changed_at
            deal.stage_changed_by_id = actor_user_id
            deal.payload = {
                **(deal.payload or {}),
                "record": record,
            }
            next_position = int(positions.get(deal.id, -1)) + 1
            positions[deal.id] = next_position
            self.session.add(
                DealStageHistory(
                    workspace_id=self.workspace_id,
                    deal_id=deal.id,
                    position=next_position,
                    from_stage=source.name,
                    to_stage=canonical_target.name,
                    from_stage_id=source.id,
                    to_stage_id=canonical_target.id,
                    changed_at=changed_at,
                    changed_by_id=actor_user_id,
                )
            )
        self.session.flush()
        return len(deals)

    def append_audit(
        self,
        *,
        pipeline_id: UUID,
        actor_user_id: str,
        pipeline_version: int,
        action: str,
        actions: list[dict[str, Any]],
        before_state: dict[str, Any],
        after_state: dict[str, Any],
        transfer_summary: list[dict[str, Any]],
    ) -> DealPipelineAuditEvent:
        payloads: tuple[object, ...] = (
            actions,
            before_state,
            after_state,
            transfer_summary,
        )
        if any(_contains_commercial_payload(payload) for payload in payloads):
            raise ValueError("pipeline audit cannot contain commercial payloads")
        pipeline = self.session.scalar(
            select(DealPipeline.id).where(
                DealPipeline.workspace_id == self.workspace_id,
                DealPipeline.id == pipeline_id,
            )
        )
        if pipeline is None:
            raise PipelineNotFoundError("pipeline not found")
        event = DealPipelineAuditEvent(
            workspace_id=self.workspace_id,
            pipeline_id=pipeline_id,
            actor_user_id=actor_user_id,
            pipeline_version=pipeline_version,
            action=action,
            actions=deepcopy(actions),
            before_state=deepcopy(before_state),
            after_state=deepcopy(after_state),
            transfer_summary=deepcopy(transfer_summary),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_audit(
        self,
        pipeline_id: UUID,
        *,
        before_id: int | None = None,
        limit: int = 50,
    ) -> tuple[DealPipelineAuditEvent, ...]:
        if not 1 <= limit <= 50:
            raise ValueError("audit limit must be between 1 and 50")
        query = select(DealPipelineAuditEvent).where(
            DealPipelineAuditEvent.workspace_id == self.workspace_id,
            DealPipelineAuditEvent.pipeline_id == pipeline_id,
        )
        if before_id is not None:
            query = query.where(DealPipelineAuditEvent.id < before_id)
        events = self.session.scalars(
            query.order_by(DealPipelineAuditEvent.id.desc()).limit(limit)
        ).all()
        return tuple(events)
