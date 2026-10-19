"""Server-owned Deal stage automations with deterministic side effects."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.models import (
    CrmActivityEvent,
    CrmUser,
    Deal,
    DealPipelineStage,
    Notification,
    Team,
)
from app.policies import PrincipalScope
from app.repositories.activity import ActivityRepository, NewActivityEvent


AutomationOutcome = Literal["success", "failure"]
BILLING_AUTOMATION_KEY = "billing"
BILLING_AUTOMATION_NAME = "Automação de Faturamento"
BILLING_ASSIGNEE_ID = "u-billing"


class DealAutomationError(RuntimeError):
    """Raised when trusted canonical transition data cannot be processed."""


@dataclass(frozen=True, slots=True)
class DealTransition:
    deal_id: str
    from_stage_id: UUID | None
    to_stage_id: UUID
    from_stage_name: str | None = None
    to_stage_name: str = ""
    source: Literal["user", "pipeline_transfer"] = "user"
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AutomationAction:
    type: str
    summary: str

    def details(self) -> dict[str, str]:
        return {"type": self.type, "summary": self.summary}


@dataclass(frozen=True, slots=True)
class AutomationResult:
    automation_key: str
    automation_name: str
    result: AutomationOutcome
    actions: tuple[AutomationAction, ...]
    failure_code: str | None
    execution_key: str

    def details(self) -> dict[str, object]:
        return {
            "automationKey": self.automation_key,
            "automationName": self.automation_name,
            "result": self.result,
            "actions": [action.details() for action in self.actions],
            "failureCode": self.failure_code,
        }


class DealAutomationExecutor:
    """Execute the canonical billing rule inside the caller's transaction."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute_for_transition(
        self,
        session: Session,
        principal: PrincipalScope,
        transition: DealTransition,
        operation_key: str,
    ) -> AutomationResult | None:
        if not isinstance(transition, DealTransition):
            raise TypeError("automation requires a DealTransition")
        if not isinstance(operation_key, str) or not operation_key.strip():
            raise ValueError("automation operation key must be non-empty")

        stage = session.scalar(
            select(DealPipelineStage).where(
                DealPipelineStage.workspace_id == principal.workspace_id,
                DealPipelineStage.id == transition.to_stage_id,
                DealPipelineStage.archived_at.is_(None),
            )
        )
        if stage is None:
            raise DealAutomationError("automation target stage unavailable")
        if stage.system_key != BILLING_AUTOMATION_KEY:
            return None

        repository = ActivityRepository(session, principal.workspace_id)
        execution_key = self._execution_key(principal, transition, operation_key)
        existing = repository.find_by_dedupe_key(execution_key)
        if existing is not None:
            return self._existing_result(existing, execution_key)

        deal = session.scalar(
            select(Deal).where(
                Deal.workspace_id == principal.workspace_id,
                Deal.id == transition.deal_id,
                Deal.deleted_at.is_(None),
            )
        )
        if deal is None:
            raise DealAutomationError("automation deal unavailable")

        target = session.scalar(
            select(CrmUser).where(
                CrmUser.workspace_id == principal.workspace_id,
                CrmUser.id == BILLING_ASSIGNEE_ID,
                CrmUser.role == "Faturamento",
                CrmUser.status == "Ativo",
                CrmUser.deleted_at.is_(None),
            )
        )
        if target is None:
            result = AutomationResult(
                automation_key=BILLING_AUTOMATION_KEY,
                automation_name=BILLING_AUTOMATION_NAME,
                result="failure",
                actions=(),
                failure_code="billing_target_unavailable",
                execution_key=execution_key,
            )
            self._append_event(repository, deal.id, result)
            return result

        deal.responsible_id = target.id
        deal.team_id = target.team_id
        target_team_name = session.scalar(
            select(Team.name).where(
                Team.workspace_id == principal.workspace_id,
                Team.id == target.team_id,
            )
        )
        packed_payload = deepcopy(deal.payload) if isinstance(deal.payload, dict) else {}
        packed_record = dict(packed_payload.get("record") or {})
        packed_record["responsibleId"] = target.id
        if target_team_name is not None:
            packed_record["team"] = target_team_name
        packed_payload["record"] = packed_record
        deal.payload = packed_payload
        actions: list[AutomationAction] = [
            AutomationAction(
                type="assignment",
                summary=f"Responsável alterado para {target.name}",
            )
        ]

        recipients = [target]
        actor = session.scalar(
            select(CrmUser).where(
                CrmUser.workspace_id == principal.workspace_id,
                CrmUser.id == principal.user_id,
                CrmUser.status == "Ativo",
                CrmUser.deleted_at.is_(None),
            )
        )
        if actor is not None and actor.id != target.id:
            recipients.append(actor)

        for recipient in recipients:
            self._append_notification(
                session,
                principal.workspace_id,
                deal.id,
                target.name,
                recipient,
                execution_key,
            )
            actions.append(
                AutomationAction(
                    type="notification",
                    summary=f"Notificação enviada para {recipient.name}",
                )
            )

        result = AutomationResult(
            automation_key=BILLING_AUTOMATION_KEY,
            automation_name=BILLING_AUTOMATION_NAME,
            result="success",
            actions=tuple(actions),
            failure_code=None,
            execution_key=execution_key,
        )
        self._append_event(repository, deal.id, result)
        return result

    @staticmethod
    def _execution_key(
        principal: PrincipalScope,
        transition: DealTransition,
        operation_key: str,
    ) -> str:
        digest = sha256(
            (
                f"{principal.workspace_id}\0{transition.deal_id}\0"
                f"{transition.to_stage_id}\0{operation_key.strip()}"
            ).encode("utf-8")
        ).hexdigest()
        return f"automation:{BILLING_AUTOMATION_KEY}:{digest}"

    def _append_event(
        self,
        repository: ActivityRepository,
        deal_id: str,
        result: AutomationResult,
    ) -> None:
        summary = (
            "Automação de faturamento executada"
            if result.result == "success"
            else "Automação de faturamento não executada"
        )
        repository.append(
            NewActivityEvent(
                deal_id=deal_id,
                company_id=None,
                category="automation",
                event_type="deal.automation_executed",
                actor_user_id=None,
                actor_name="Sistema",
                summary=summary,
                details=result.details(),
                dedupe_key=result.execution_key,
                occurred_at=self._clock(),
            )
        )

    @staticmethod
    def _append_notification(
        session: Session,
        workspace_id: str,
        deal_id: str,
        target_name: str,
        recipient: CrmUser,
        execution_key: str,
    ) -> None:
        notification_digest = sha256(
            f"{execution_key}\0{recipient.id}".encode("utf-8")
        ).hexdigest()
        notification_id = f"automation-{notification_digest}"
        target_recipient = recipient.id == BILLING_ASSIGNEE_ID
        notification_text = (
            "Responsabilidade alterada automaticamente."
            if target_recipient
            else "Automação de Faturamento executada."
        )
        notification_detail = (
            f"{deal_id} agora está com {target_name}"
            if target_recipient
            else f"{deal_id} foi atribuído à {target_name}"
        )
        position = int(
            session.scalar(
                select(func.count()).select_from(Notification).where(
                    Notification.workspace_id == workspace_id,
                    Notification.deleted_at.is_(None),
                )
            )
            or 0
        )
        session.execute(
            postgresql_insert(Notification)
            .values(
                id=notification_id,
                workspace_id=workspace_id,
                user_id=recipient.id,
                text=notification_text,
                detail=notification_detail,
                displayed_time="Agora",
                is_read=False,
                payload={
                    "position": position,
                    "record": {
                        "id": notification_id,
                        "userId": recipient.id,
                        "text": notification_text,
                        "detail": notification_detail,
                        "time": "Agora",
                        "read": False,
                    },
                    "source": "deal_automation",
                    "automationKey": BILLING_AUTOMATION_KEY,
                    "dealId": deal_id,
                },
            )
            .on_conflict_do_nothing(index_elements=[Notification.id])
        )

    @staticmethod
    def _existing_result(
        event: CrmActivityEvent,
        execution_key: str,
    ) -> AutomationResult:
        details = event.details if isinstance(event.details, dict) else {}
        action_rows = details.get("actions")
        actions: list[AutomationAction] = []
        if isinstance(action_rows, list):
            for row in action_rows:
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("type"), str)
                    and isinstance(row.get("summary"), str)
                ):
                    actions.append(
                        AutomationAction(type=row["type"], summary=row["summary"])
                    )
        outcome = details.get("result")
        if outcome not in {"success", "failure"}:
            raise DealAutomationError("stored automation result is invalid")
        failure_code = details.get("failureCode")
        return AutomationResult(
            automation_key=BILLING_AUTOMATION_KEY,
            automation_name=BILLING_AUTOMATION_NAME,
            result=outcome,
            actions=tuple(actions),
            failure_code=failure_code if isinstance(failure_code, str) else None,
            execution_key=execution_key,
        )
