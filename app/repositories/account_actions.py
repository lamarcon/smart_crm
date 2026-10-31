"""Tenant-scoped lifecycle operations for invitation and password-reset tokens."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AccountActionToken, CrmUser


PURPOSES = frozenset({"invitation", "password_reset"})
DELIVERY_RESULTS = frozenset({"sent", "failed"})


class AccountActionScopeError(RuntimeError):
    pass


class AccountActionTokenNotFoundError(LookupError):
    pass


class AccountActionRepository:
    def __init__(self, session: Session, workspace_id: str) -> None:
        self.session = session
        context_workspace_id = session.scalar(
            text("SELECT current_setting('smartcrm.workspace_id', true)")
        )
        if not context_workspace_id:
            raise AccountActionScopeError("workspace context unavailable")
        context_workspace_id = str(context_workspace_id)
        if not workspace_id or workspace_id != context_workspace_id:
            raise AccountActionScopeError("workspace context mismatch")
        self.workspace_id = context_workspace_id

    @staticmethod
    def _validate_purpose(purpose: str) -> str:
        if purpose not in PURPOSES:
            raise ValueError("unsupported account action purpose")
        return purpose

    def _lock_user(self, user_id: str) -> None:
        locked = self.session.scalar(
            select(CrmUser.id)
            .where(
                CrmUser.workspace_id == self.workspace_id,
                CrmUser.id == user_id,
            )
            .with_for_update()
        )
        if locked is None:
            raise LookupError("account action user not found")

    def _active_tokens(
        self,
        user_id: str,
        purpose: str,
        now: datetime,
    ) -> tuple[AccountActionToken, ...]:
        tokens = self.session.scalars(
            select(AccountActionToken)
            .where(
                AccountActionToken.workspace_id == self.workspace_id,
                AccountActionToken.user_id == user_id,
                AccountActionToken.purpose == purpose,
                AccountActionToken.expires_at > now,
                AccountActionToken.consumed_at.is_(None),
                AccountActionToken.invalidated_at.is_(None),
            )
            .order_by(AccountActionToken.created_at.desc())
            .with_for_update()
        ).all()
        return tuple(tokens)

    def create_token(
        self,
        *,
        user_id: str,
        purpose: str,
        token_digest: str,
        expires_at: datetime,
        created_by_user_id: str | None,
        now: datetime,
    ) -> AccountActionToken:
        purpose = self._validate_purpose(purpose)
        self._lock_user(user_id)
        for predecessor in self._active_tokens(user_id, purpose, now):
            predecessor.invalidated_at = now
            predecessor.invalidation_reason = "replaced"
        token = AccountActionToken(
            workspace_id=self.workspace_id,
            user_id=user_id,
            purpose=purpose,
            token_digest=token_digest,
            expires_at=expires_at,
            delivery_status="pending",
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(token)
        self.session.flush()
        return token

    def invalidate_active(
        self,
        user_id: str,
        purpose: str,
        reason: str,
        now: datetime,
    ) -> int:
        purpose = self._validate_purpose(purpose)
        self._lock_user(user_id)
        tokens = self._active_tokens(user_id, purpose, now)
        for token in tokens:
            token.invalidated_at = now
            token.invalidation_reason = reason
        self.session.flush()
        return len(tokens)

    def lock_valid_token(
        self,
        purpose: str,
        token_digest: str,
        now: datetime,
    ) -> AccountActionToken | None:
        purpose = self._validate_purpose(purpose)
        return self.session.scalar(
            select(AccountActionToken)
            .where(
                AccountActionToken.workspace_id == self.workspace_id,
                AccountActionToken.purpose == purpose,
                AccountActionToken.token_digest == token_digest,
                AccountActionToken.expires_at > now,
                AccountActionToken.consumed_at.is_(None),
                AccountActionToken.invalidated_at.is_(None),
            )
            .with_for_update()
        )

    def consume_token(
        self,
        purpose: str,
        token_digest: str,
        now: datetime,
    ) -> AccountActionToken | None:
        token = self.lock_valid_token(purpose, token_digest, now)
        if token is None:
            return None
        token.consumed_at = now
        self.session.flush()
        return token

    def mark_delivery(
        self,
        token_id: UUID,
        *,
        status: str,
        failure_code: str | None,
        now: datetime,
    ) -> None:
        if status not in DELIVERY_RESULTS:
            raise ValueError("unsupported delivery result")
        token = self.session.scalar(
            select(AccountActionToken)
            .where(
                AccountActionToken.workspace_id == self.workspace_id,
                AccountActionToken.id == token_id,
            )
            .with_for_update()
        )
        if token is None:
            raise AccountActionTokenNotFoundError("account action token not found")
        token.delivery_status = status
        token.delivery_attempted_at = now
        token.delivery_failure_code = failure_code if status == "failed" else None
        if status == "failed" and token.consumed_at is None and token.invalidated_at is None:
            token.invalidated_at = now
            token.invalidation_reason = "delivery_failed"
        self.session.flush()
