"""Authorized activity timeline reads and immutable observation writes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CrmActivityEvent, CrmUser, Deal, DealAssistant
from app.policies import PrincipalScope, RecordScope, can_mutate_record, can_read_record
from app.repositories.activity import ActivityPageRows, ActivityRepository, NewActivityEvent
from app.schemas import (
    ActivityActorResponse,
    ActivityEventResponse,
    ActivityPage,
    ActivityQuery,
    CompanyActivityQuery,
    ObservationCreateRequest,
)


class ActivityServiceError(RuntimeError):
    pass


class ActivityNotFoundError(ActivityServiceError):
    pass


class ActivityAuthorizationError(ActivityServiceError):
    pass


class ActivityValidationError(ActivityServiceError):
    pass


SubjectKind = Literal["deal", "company"]


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
