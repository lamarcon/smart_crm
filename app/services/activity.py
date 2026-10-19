"""Authorized activity timeline reads and immutable observation writes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Literal, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CrmActivityEvent, CrmUser, Deal, DealAssistant, DealPipelineStage
from app.policies import PrincipalScope, RecordScope, can_mutate_record, can_read_record
from app.repositories.activity import ActivityPageRows, ActivityRepository, NewActivityEvent
from app.schemas import (
    ActivityActorResponse,
    ActivityEventResponse,
    ActivityPage,
    ActivityQuery,
    CompanyActivityQuery,
    ObservationCreateRequest,
    WorkspaceState,
)
from app.services.deal_automation import DealTransition


class ActivityServiceError(RuntimeError):
    pass


class ActivityNotFoundError(ActivityServiceError):
    pass


class ActivityAuthorizationError(ActivityServiceError):
    pass


class ActivityValidationError(ActivityServiceError):
    pass


SubjectKind = Literal["deal", "company"]

_COMPANY_STANDARD_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Empresa"),
    ("ownerId", "Proprietário"),
    ("city", "Cidade"),
    ("segment", "Segmento"),
    ("phone", "Telefone"),
)


def _actor_name(state: WorkspaceState, principal: PrincipalScope) -> str:
    return next(
        (
            str(user.get("name") or "Usuário")
            for user in state.users
            if user.get("id") == principal.user_id
        ),
        "Usuário",
    )


def collect_deal_transitions(
    before: WorkspaceState,
    after: WorkspaceState,
    stage_registry: Sequence[DealPipelineStage],
    principal: PrincipalScope,
    *,
    occurred_at: datetime,
) -> tuple[DealTransition, ...]:
    """Build trusted transitions from canonical snapshots and stage records."""

    if occurred_at.tzinfo is None:
        raise ValueError("transition timestamp must be timezone-aware")
    before_by_id = {str(record.get("id")): record for record in before.deals}
    stages = {stage.id: stage for stage in stage_registry}
    transitions: list[DealTransition] = []
    for record in after.deals:
        deal_id = str(record.get("id"))
        previous = before_by_id.get(deal_id)
        if previous is None:
            continue
        try:
            from_stage_id = UUID(str(previous.get("stageId")))
            to_stage_id = UUID(str(record.get("stageId")))
        except (TypeError, ValueError, AttributeError) as error:
            raise ActivityValidationError("canonical stage identity is invalid") from error
        if from_stage_id == to_stage_id:
            continue
        from_stage = stages.get(from_stage_id)
        to_stage = stages.get(to_stage_id)
        if from_stage is None or to_stage is None:
            raise ActivityValidationError("canonical stage identity is unavailable")
        transitions.append(
            DealTransition(
                deal_id=deal_id,
                from_stage_id=from_stage.id,
                to_stage_id=to_stage.id,
                from_stage_name=from_stage.name,
                to_stage_name=to_stage.name,
                source="user",
                occurred_at=occurred_at,
            )
        )
    return tuple(transitions)


def movement_events_for_transitions(
    transitions: Sequence[DealTransition],
    before: WorkspaceState,
    principal: PrincipalScope,
    operation_key: str,
) -> tuple[NewActivityEvent, ...]:
    if not isinstance(operation_key, str) or not operation_key.strip():
        raise ValueError("activity operation key must be non-empty")
    actor_name = _actor_name(before, principal)
    events: list[NewActivityEvent] = []
    for transition in transitions:
        if transition.occurred_at is None:
            raise ActivityValidationError("transition timestamp is unavailable")
        events.append(
            NewActivityEvent(
                deal_id=transition.deal_id,
                company_id=None,
                category="movement",
                event_type="deal.stage_changed",
                actor_user_id=principal.user_id,
                actor_name=actor_name,
                summary=(
                    f"Etapa alterada de {transition.from_stage_name} "
                    f"para {transition.to_stage_name}"
                ),
                details={
                    "fromStageId": (
                        str(transition.from_stage_id)
                        if transition.from_stage_id is not None
                        else None
                    ),
                    "fromStageName": transition.from_stage_name,
                    "toStageId": str(transition.to_stage_id),
                    "toStageName": transition.to_stage_name,
                    "source": transition.source,
                },
                dedupe_key=(
                    f"movement:{operation_key.strip()}:{transition.deal_id}:"
                    f"{transition.to_stage_id}"
                ),
                occurred_at=transition.occurred_at,
            )
        )
    return tuple(events)


def _custom_values(record: dict) -> dict[str, object]:
    return {
        str(item.get("key")): item.get("value")
        for item in (record.get("customFields") or [])
        if isinstance(item, dict) and item.get("key") is not None
    }


def collect_company_changes(
    before: WorkspaceState,
    after: WorkspaceState,
    principal: PrincipalScope,
    operation_key: str,
    *,
    occurred_at: datetime,
) -> tuple[NewActivityEvent, ...]:
    """Return one creation/change event per Company using whitelisted fields only."""

    if not isinstance(operation_key, str) or not operation_key.strip():
        raise ValueError("activity operation key must be non-empty")
    if occurred_at.tzinfo is None:
        raise ValueError("company activity timestamp must be timezone-aware")
    actor_name = _actor_name(before, principal)
    before_by_id = {str(record.get("id")): record for record in before.companies}
    custom_labels = {
        str(item.get("key")): str(item.get("label") or item.get("key"))
        for item in after.custom_field_schemas.get("companies", [])
        if item.get("key") is not None
    }
    events: list[NewActivityEvent] = []
    for record in after.companies:
        company_id = str(record.get("id"))
        previous = before_by_id.get(company_id)
        changes: list[dict[str, object]] = []
        for field, label in _COMPANY_STANDARD_FIELDS:
            old_value = previous.get(field) if previous is not None else None
            new_value = record.get(field)
            if previous is None or old_value != new_value:
                changes.append(
                    {
                        "field": field,
                        "label": label,
                        "before": old_value,
                        "after": new_value,
                    }
                )
        old_custom = _custom_values(previous or {})
        new_custom = _custom_values(record)
        for key in sorted(set(old_custom) | set(new_custom)):
            old_value = old_custom.get(key)
            new_value = new_custom.get(key)
            if previous is None or old_value != new_value:
                changes.append(
                    {
                        "field": f"custom:{key}",
                        "label": custom_labels.get(key, key),
                        "before": old_value,
                        "after": new_value,
                    }
                )
        if not changes:
            continue
        created = previous is None
        events.append(
            NewActivityEvent(
                deal_id=None,
                company_id=company_id,
                category="change",
                event_type="company.created" if created else "company.updated",
                actor_user_id=principal.user_id,
                actor_name=actor_name,
                summary="Empresa criada" if created else "Empresa atualizada",
                details={"changes": changes},
                dedupe_key=(
                    f"company-{'created' if created else 'updated'}:"
                    f"{operation_key.strip()}:{company_id}"
                ),
                occurred_at=occurred_at,
            )
        )
    return tuple(events)


class ActivityService:
    """Apply record policy while keeping activity persistence append-only."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def deal_timeline(
        self,
        session: Session,
        principal: PrincipalScope,
        deal_id: str,
        query: ActivityQuery,
    ) -> ActivityPage:
        self._require_subject(session, principal, "deal", deal_id, mutate=False)
        rows = ActivityRepository(session, principal.workspace_id).list_for_deal(
            deal_id, query.category, query.cursor, query.limit
        )
        return self._page(rows)

    def company_timeline(
        self,
        session: Session,
        principal: PrincipalScope,
        company_id: str,
        query: ActivityQuery | CompanyActivityQuery,
    ) -> ActivityPage:
        self._require_subject(session, principal, "company", company_id, mutate=False)
        rows = ActivityRepository(session, principal.workspace_id).list_for_company(
            company_id, query.category, query.cursor, query.limit
        )
        return self._page(rows)

    def add_deal_observation(
        self,
        session: Session,
        principal: PrincipalScope,
        deal_id: str,
        request: ObservationCreateRequest,
    ) -> ActivityEventResponse:
        return self._add_observation(session, principal, "deal", deal_id, request)

    def add_company_observation(
        self,
        session: Session,
        principal: PrincipalScope,
        company_id: str,
        request: ObservationCreateRequest,
    ) -> ActivityEventResponse:
        return self._add_observation(session, principal, "company", company_id, request)

    def _add_observation(
        self,
        session: Session,
        principal: PrincipalScope,
        subject_kind: SubjectKind,
        subject_id: str,
        request: ObservationCreateRequest,
    ) -> ActivityEventResponse:
        self._require_subject(session, principal, subject_kind, subject_id, mutate=True)
        text_value = request.text.strip() if isinstance(request.text, str) else ""
        if not 1 <= len(text_value) <= 4_000:
            raise ActivityValidationError("observation text must contain 1 to 4000 characters")

        actor = session.scalar(
            select(CrmUser).where(
                CrmUser.workspace_id == principal.workspace_id,
                CrmUser.id == principal.user_id,
                CrmUser.deleted_at.is_(None),
            )
        )
        if actor is None:
            raise ActivityAuthorizationError("activity mutation forbidden")

        repository = ActivityRepository(session, principal.workspace_id)
        event = repository.append(
            NewActivityEvent(
                deal_id=subject_id if subject_kind == "deal" else None,
                company_id=subject_id if subject_kind == "company" else None,
                category="observation",
                event_type=f"{subject_kind}.observation_added",
                actor_user_id=actor.id,
                actor_name=actor.name,
                summary="Observação adicionada",
                details={"text": text_value},
                dedupe_key=f"observation:{request.idempotency_key}",
                occurred_at=self._clock(),
            )
        )
        return self._response(event)

    def _require_subject(
        self,
        session: Session,
        principal: PrincipalScope,
        subject_kind: SubjectKind,
        subject_id: str,
        *,
        mutate: bool,
    ) -> Deal | Company:
        if subject_kind == "deal":
            subject = session.scalar(
                select(Deal).where(
                    Deal.workspace_id == principal.workspace_id,
                    Deal.id == subject_id,
                    Deal.deleted_at.is_(None),
                )
            )
            if subject is None:
                raise ActivityNotFoundError("activity subject not found")
            assistant_ids = tuple(
                session.scalars(
                    select(DealAssistant.user_id).where(
                        DealAssistant.workspace_id == principal.workspace_id,
                        DealAssistant.deal_id == subject_id,
                    )
                ).all()
            )
            record = RecordScope(
                responsible_id=subject.responsible_id,
                assistant_ids=assistant_ids,
                team_id=subject.team_id,
            )
            module = "deals"
        else:
            subject = session.scalar(
                select(Company).where(
                    Company.workspace_id == principal.workspace_id,
                    Company.id == subject_id,
                    Company.deleted_at.is_(None),
                )
            )
            if subject is None:
                raise ActivityNotFoundError("activity subject not found")
            record = RecordScope(
                responsible_id=subject.owner_id,
                assistant_ids=(),
                team_id=None,
            )
            module = "companies"

        if not can_read_record(principal, module, record):
            raise ActivityNotFoundError("activity subject not found")
        if mutate and not can_mutate_record(principal, module, record):
            raise ActivityAuthorizationError("activity mutation forbidden")
        return subject

    @classmethod
    def _page(cls, rows: ActivityPageRows) -> ActivityPage:
        return ActivityPage(
            items=[cls._response(item) for item in rows.items],
            nextCursor=rows.next_cursor,
        )

    @staticmethod
    def _response(event: CrmActivityEvent) -> ActivityEventResponse:
        return ActivityEventResponse(
            id=event.id,
            category=event.category,
            eventType=event.event_type,
            actor=ActivityActorResponse(
                id=event.actor_user_id,
                name=event.actor_name,
                kind="user" if event.actor_user_id is not None else "system",
            ),
            summary=event.summary,
            details=event.details,
            occurredAt=event.occurred_at,
        )
