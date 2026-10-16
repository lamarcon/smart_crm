"""Append-only tenant persistence for Deal and Company activity streams."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from sqlalchemy import and_, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.models import CrmActivityEvent


ActivityCategory = Literal["movement", "automation", "observation", "change"]
_ACTIVITY_CATEGORIES = frozenset({"movement", "automation", "observation", "change"})
_CURSOR_VERSION = 1


class ActivityScopeError(RuntimeError):
    """Raised before activity SQL when the trusted workspace context is invalid."""


class ActivityCursorError(ValueError):
    """Raised when a repository cursor cannot represent a valid timeline position."""


@dataclass(frozen=True, slots=True)
class NewActivityEvent:
    """Server-built event draft; workspace scope is supplied only by the repository."""

    deal_id: str | None
    company_id: str | None
    category: ActivityCategory
    event_type: str
    actor_user_id: str | None
    actor_name: str
    summary: str
    details: dict[str, Any]
    dedupe_key: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ActivityPageRows:
    items: tuple[CrmActivityEvent, ...]
    next_cursor: str | None


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _normalize_timestamp(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _encode_cursor(event: CrmActivityEvent) -> str:
    timestamp = _normalize_timestamp(event.occurred_at).isoformat().replace("+00:00", "Z")
    payload = json.dumps(
        {"v": _CURSOR_VERSION, "t": timestamp, "i": event.id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 2_048:
        raise ActivityCursorError("invalid activity cursor")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            (cursor + padding).encode("ascii"), altchars=b"-_", validate=True
        )
        payload = json.loads(raw.decode("utf-8"))
        if set(payload) != {"v", "t", "i"} or payload["v"] != _CURSOR_VERSION:
            raise ValueError
        event_id = payload["i"]
        if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
            raise ValueError
        encoded_timestamp = payload["t"]
        if not isinstance(encoded_timestamp, str):
            raise ValueError
        occurred_at = datetime.fromisoformat(encoded_timestamp.replace("Z", "+00:00"))
        if occurred_at.tzinfo is None:
            raise ValueError
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ActivityCursorError("invalid activity cursor") from error
    return occurred_at.astimezone(timezone.utc), event_id


class ActivityRepository:
    """Append and page immutable activity rows within one verified tenant scope."""

    def __init__(self, session: Session, workspace_id: str) -> None:
        self.session = session
        context_workspace_id = session.scalar(
            text("SELECT current_setting('smartcrm.workspace_id', true)")
        )
        if not context_workspace_id:
            raise ActivityScopeError("workspace context unavailable")
        context_workspace_id = str(context_workspace_id)
        if not workspace_id or workspace_id != context_workspace_id:
            raise ActivityScopeError("workspace context mismatch")
        self.workspace_id = context_workspace_id

    def append(self, event: NewActivityEvent) -> CrmActivityEvent:
        if not isinstance(event, NewActivityEvent):
            raise TypeError("activity append requires NewActivityEvent")
        if (event.deal_id is None) == (event.company_id is None):
            raise ValueError("activity event requires exactly one subject")
        if event.category not in _ACTIVITY_CATEGORIES:
            raise ValueError("invalid activity category")
        _require_text(event.event_type, "event_type")
        _require_text(event.actor_name, "actor_name")
        _require_text(event.summary, "summary")
        _require_text(event.dedupe_key, "dedupe_key")
        occurred_at = _normalize_timestamp(event.occurred_at)
        if not isinstance(event.details, dict):
            raise TypeError("activity details must be a dictionary")

        statement = (
            postgresql_insert(CrmActivityEvent)
            .values(
                workspace_id=self.workspace_id,
                deal_id=event.deal_id,
                company_id=event.company_id,
                category=event.category,
                event_type=event.event_type,
                actor_user_id=event.actor_user_id,
                actor_name=event.actor_name,
                summary=event.summary,
                details=deepcopy(event.details),
                dedupe_key=event.dedupe_key,
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    CrmActivityEvent.workspace_id,
                    CrmActivityEvent.dedupe_key,
                ]
            )
            .returning(CrmActivityEvent.id)
        )
        inserted_id = self.session.scalar(statement)
        if inserted_id is None:
            existing = self.find_by_dedupe_key(event.dedupe_key)
            if existing is None:  # pragma: no cover - guarded by the unique conflict target
                raise RuntimeError("activity dedupe conflict could not be resolved")
            return existing
        inserted = self.session.scalar(
            select(CrmActivityEvent).where(
                CrmActivityEvent.workspace_id == self.workspace_id,
                CrmActivityEvent.id == inserted_id,
            )
        )
        if inserted is None:  # pragma: no cover - INSERT RETURNING and RLS share one scope
            raise RuntimeError("inserted activity event is unavailable")
        return inserted

    def append_many(
        self, events: Sequence[NewActivityEvent]
    ) -> tuple[CrmActivityEvent, ...]:
        return tuple(self.append(event) for event in events)

    def find_by_dedupe_key(self, key: str) -> CrmActivityEvent | None:
        _require_text(key, "dedupe_key")
        return self.session.scalar(
            select(CrmActivityEvent).where(
                CrmActivityEvent.workspace_id == self.workspace_id,
                CrmActivityEvent.dedupe_key == key,
            )
        )

    def list_for_deal(
        self,
        deal_id: str,
        category: ActivityCategory | None,
        cursor: str | None,
        limit: int,
    ) -> ActivityPageRows:
        return self._list_for_subject(
            deal_id=_require_text(deal_id, "deal_id"),
            company_id=None,
            category=category,
            cursor=cursor,
            limit=limit,
        )

    def list_for_company(
        self,
        company_id: str,
        category: ActivityCategory | None,
        cursor: str | None,
        limit: int,
    ) -> ActivityPageRows:
        return self._list_for_subject(
            deal_id=None,
            company_id=_require_text(company_id, "company_id"),
            category=category,
            cursor=cursor,
            limit=limit,
        )

    def _list_for_subject(
        self,
        *,
        deal_id: str | None,
        company_id: str | None,
        category: ActivityCategory | None,
        cursor: str | None,
        limit: int,
    ) -> ActivityPageRows:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("activity limit must be between 1 and 50")
        if category is not None and category not in _ACTIVITY_CATEGORIES:
            raise ValueError("invalid activity category")

        query = select(CrmActivityEvent).where(
            CrmActivityEvent.workspace_id == self.workspace_id
        )
        if deal_id is not None:
            query = query.where(CrmActivityEvent.deal_id == deal_id)
        else:
            query = query.where(CrmActivityEvent.company_id == company_id)
        if category is not None:
            query = query.where(CrmActivityEvent.category == category)
        if cursor is not None:
            occurred_at, event_id = _decode_cursor(cursor)
            query = query.where(
                or_(
                    CrmActivityEvent.occurred_at < occurred_at,
                    and_(
                        CrmActivityEvent.occurred_at == occurred_at,
                        CrmActivityEvent.id < event_id,
                    ),
                )
            )

        rows = self.session.scalars(
            query.order_by(
                CrmActivityEvent.occurred_at.desc(),
                CrmActivityEvent.id.desc(),
            ).limit(limit + 1)
        ).all()
        items = tuple(rows[:limit])
        next_cursor = _encode_cursor(items[-1]) if len(rows) > limit and items else None
        return ActivityPageRows(items=items, next_cursor=next_cursor)
