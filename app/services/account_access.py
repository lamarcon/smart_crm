"""Tenant account invitation, acceptance, and recovery lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.control_database import ControlDatabase, ControlRepository
from app.mail import MailDeliveryError, MailSender, render_invitation_email
from app.models import CrmUser
from app.policies import Action, CURRENT_ROLES, PrincipalScope, can_perform_action
from app.repositories.account_actions import AccountActionRepository
from app.services.auth import SecurityAuditService
from app.tenant_database import TenantDatabaseRouter


INVITATION_TTL = timedelta(hours=48)


class AccountAccessError(RuntimeError):
    pass


class AccountAccessAuthorizationError(AccountAccessError):
    pass


class AccountAccessTenantUnavailableError(AccountAccessError):
    pass


class AccountAccessValidationError(AccountAccessError):
    pass


class AccountAlreadyActiveError(AccountAccessError):
    pass


class AccountRequiresReactivationError(AccountAccessError):
    pass


class InvitationStateError(AccountAccessError):
    pass


@dataclass(frozen=True)
class InvitationCommand:
    name: str
    email: str
    job_title: str
    team_id: str | None
    role: str


@dataclass(frozen=True)
class InvitationResult:
    user_id: str
    status: str
    delivery_status: str
    delivery_failure_code: str | None = None


@dataclass(frozen=True)
class UserAccessResult:
    user_id: str
    status: str


@dataclass(frozen=True)
class _PreparedInvitation:
    user_id: str
    email: str
    token_id: UUID
    raw_token: str
    action: str


class TenantRouter(Protocol):
    def tenant_session_scope(self, tenant_id: UUID): ...  # noqa: ANN201


class AuditRecorder(Protocol):
    def record(self, **values): ...  # noqa: ANN003, ANN201


ControlRepositoryFactory = Callable[[object], ControlRepository]
AccountActionRepositoryFactory = Callable[[Session, str], AccountActionRepository]
Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]


class AccountAccessService:
    def __init__(
        self,
        control_database: ControlDatabase,
        router: TenantDatabaseRouter | TenantRouter,
        mail_sender: MailSender,
        *,
        public_origin: str,
        control_repository_factory: ControlRepositoryFactory = ControlRepository,
        account_action_repository_factory: AccountActionRepositoryFactory = (
            AccountActionRepository
        ),
        security_audit: AuditRecorder | None = None,
        clock: Clock | None = None,
        token_factory: TokenFactory | None = None,
    ) -> None:
        self._control_database = control_database
        self._router = router
        self._mail_sender = mail_sender
        self._public_origin = public_origin.rstrip("/")
        self._control_repository_factory = control_repository_factory
        self._account_action_repository_factory = account_action_repository_factory
        self._security_audit = security_audit or SecurityAuditService(
            control_database,
            repository_factory=control_repository_factory,
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_factory = token_factory or (lambda: token_urlsafe(32))

    @staticmethod
    def _authorize(tenant_id: UUID, actor: PrincipalScope) -> None:
        if (
            not isinstance(actor, PrincipalScope)
            or actor.tenant_id != tenant_id
            or not can_perform_action(actor, Action.MANAGE_USERS)
        ):
            raise AccountAccessAuthorizationError("principal is not authorized")

    def _tenant(self, tenant_id: UUID):  # noqa: ANN201
        with self._control_database.session_scope() as session:
            tenant = self._control_repository_factory(session).get_tenant(tenant_id)
            if tenant is None or tenant.status != "active":
                raise AccountAccessTenantUnavailableError("tenant unavailable")
            return tenant

    @staticmethod
    def _workspace_id(session: Session, actor: PrincipalScope) -> str:
        workspace_id = session.scalar(
            text("SELECT current_setting('smartcrm.workspace_id', true)")
        )
        if not workspace_id or str(workspace_id) != actor.workspace_id:
            raise AccountAccessAuthorizationError("principal is not authorized")
        return str(workspace_id)

    @staticmethod
    def _normalized_command(command: InvitationCommand) -> InvitationCommand:
        name = command.name.strip()
        email = command.email.strip().lower()
        job_title = command.job_title.strip()
        if not name or not email or "@" not in email or command.role not in CURRENT_ROLES:
            raise AccountAccessValidationError("invalid invitation")
        return InvitationCommand(
            name=name,
            email=email,
            job_title=job_title,
            team_id=command.team_id,
            role=command.role,
        )

    @staticmethod
    def _token_digest(purpose: str, raw_token: str) -> str:
        return sha256(f"{purpose}\0{raw_token}".encode("utf-8")).hexdigest()

    def _record(
        self,
        *,
        event_type: str,
        tenant_id: UUID,
        user_id: str,
        correlation_parts: tuple[object, ...],
        outcome_code: str,
        occurred_at: datetime,
    ) -> None:
        self._security_audit.record(
            event_type=event_type,
            tenant_id=tenant_id,
            user_id=user_id,
            correlation_digest=SecurityAuditService.correlation_digest(
                *correlation_parts
            ),
            outcome_code=outcome_code,
            occurred_at=occurred_at,
        )

    def _prepare_invitation(
        self,
        tenant_id: UUID,
        actor: PrincipalScope,
        command: InvitationCommand,
    ) -> _PreparedInvitation:
        for attempt in range(2):
            raw_token = self._token_factory()
            if not raw_token:
                raise AccountAccessValidationError("token generation failed")
            now = self._clock()
            try:
                with self._router.tenant_session_scope(tenant_id) as session:
                    workspace_id = self._workspace_id(session, actor)
                    user = session.scalar(
                        select(CrmUser)
                        .where(
                            CrmUser.workspace_id == workspace_id,
                            CrmUser.normalized_email == command.email,
                            CrmUser.deleted_at.is_(None),
                        )
                        .with_for_update()
                    )
                    created = user is None
                    if user is None:
                        user = CrmUser(
                            id=f"user-{uuid4().hex}",
                            workspace_id=workspace_id,
                            name=command.name,
                            email=command.email,
                            normalized_email=command.email,
                            password_hash=None,
                            auth_enabled=False,
                            auth_version=0,
                            job_title=command.job_title,
                            team_id=command.team_id,
                            role=command.role,
                            status="Pendente",
                            invited_at=now,
                            payload={},
                        )
                        session.add(user)
                        session.flush()
                    elif user.status == "Ativo":
                        raise AccountAlreadyActiveError("account is already active")
                    elif user.status == "Inativo":
                        raise AccountRequiresReactivationError(
                            "account requires administrative reactivation"
                        )
                    elif user.status not in {"Pendente", "Cancelado"}:
                        raise InvitationStateError("account cannot be invited")
                    else:
                        user.name = command.name
                        user.email = command.email
                        user.normalized_email = command.email
                        user.job_title = command.job_title
                        user.team_id = command.team_id
                        user.role = command.role
                        user.status = "Pendente"
                        user.password_hash = None
                        user.auth_enabled = False
                        user.invited_at = now

                    repository = self._account_action_repository_factory(
                        session, workspace_id
                    )
                    token = repository.create_token(
                        user_id=user.id,
                        purpose="invitation",
                        token_digest=self._token_digest("invitation", raw_token),
                        expires_at=now + INVITATION_TTL,
                        created_by_user_id=actor.user_id,
                        now=now,
                    )
                    return _PreparedInvitation(
                        user_id=user.id,
                        email=user.normalized_email,
                        token_id=token.id,
                        raw_token=raw_token,
                        action="created" if created else "resent",
                    )
            except IntegrityError:
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("invitation preparation did not complete")

    def _prepare_resend(
        self,
        tenant_id: UUID,
        actor: PrincipalScope,
        user_id: str,
    ) -> _PreparedInvitation:
        now = self._clock()
        raw_token = self._token_factory()
        if not raw_token:
            raise AccountAccessValidationError("token generation failed")
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._workspace_id(session, actor)
            user = session.scalar(
                select(CrmUser)
                .where(
                    CrmUser.workspace_id == workspace_id,
                    CrmUser.id == user_id,
                    CrmUser.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if user is None or user.status != "Pendente":
                raise InvitationStateError("invitation is not pending")
            user.auth_enabled = False
            user.password_hash = None
            user.invited_at = now
            token = self._account_action_repository_factory(
                session, workspace_id
            ).create_token(
                user_id=user.id,
                purpose="invitation",
                token_digest=self._token_digest("invitation", raw_token),
                expires_at=now + INVITATION_TTL,
                created_by_user_id=actor.user_id,
                now=now,
            )
            return _PreparedInvitation(
                user_id=user.id,
                email=user.normalized_email or user.email.lower(),
                token_id=token.id,
                raw_token=raw_token,
                action="resent",
            )

    def _deliver(
        self,
        tenant_id: UUID,
        actor: PrincipalScope,
        tenant,  # noqa: ANN001
        prepared: _PreparedInvitation,
        source_ip: str,
    ) -> InvitationResult:
        prepared_at = self._clock()
        self._record(
            event_type=f"invitation.{prepared.action}",
            tenant_id=tenant_id,
            user_id=prepared.user_id,
            correlation_parts=(
                "invitation",
                prepared.token_id,
                actor.user_id,
                source_ip,
            ),
            outcome_code="pending_delivery",
            occurred_at=prepared_at,
        )
        message = render_invitation_email(
            tenant.display_name,
            prepared.email,
            (
                f"{self._public_origin}/{tenant.slug}/accept-invite"
                f"#token={prepared.raw_token}"
            ),
        )
        delivery_status = "sent"
        failure_code = None
        try:
            self._mail_sender.send(message)
        except MailDeliveryError as error:
            delivery_status = "failed"
            failure_code = error.code

        delivered_at = self._clock()
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._workspace_id(session, actor)
            self._account_action_repository_factory(
                session, workspace_id
            ).mark_delivery(
                prepared.token_id,
                status=delivery_status,
                failure_code=failure_code,
                now=delivered_at,
            )
        self._record(
            event_type=(
                "invitation.sent"
                if delivery_status == "sent"
                else "invitation.delivery_failed"
            ),
            tenant_id=tenant_id,
            user_id=prepared.user_id,
            correlation_parts=("invitation-delivery", prepared.token_id, delivery_status),
            outcome_code=failure_code or "delivered",
            occurred_at=delivered_at,
        )
        return InvitationResult(
            user_id=prepared.user_id,
            status="Pendente",
            delivery_status=delivery_status,
            delivery_failure_code=failure_code,
        )

    def invite(
        self,
        tenant_id: UUID,
        actor: PrincipalScope,
        command: InvitationCommand,
        source_ip: str,
    ) -> InvitationResult:
        self._authorize(tenant_id, actor)
        normalized = self._normalized_command(command)
        tenant = self._tenant(tenant_id)
        prepared = self._prepare_invitation(tenant_id, actor, normalized)
        return self._deliver(tenant_id, actor, tenant, prepared, source_ip)

    def resend_invitation(
        self,
        tenant_id: UUID,
        actor: PrincipalScope,
        user_id: str,
        source_ip: str,
    ) -> InvitationResult:
        self._authorize(tenant_id, actor)
        tenant = self._tenant(tenant_id)
        prepared = self._prepare_resend(tenant_id, actor, user_id)
        return self._deliver(tenant_id, actor, tenant, prepared, source_ip)

    def cancel_invitation(
        self,
        tenant_id: UUID,
        actor: PrincipalScope,
        user_id: str,
    ) -> UserAccessResult:
        self._authorize(tenant_id, actor)
        self._tenant(tenant_id)
        now = self._clock()
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._workspace_id(session, actor)
            user = session.scalar(
                select(CrmUser)
                .where(
                    CrmUser.workspace_id == workspace_id,
                    CrmUser.id == user_id,
                    CrmUser.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if user is None or user.status != "Pendente":
                raise InvitationStateError("invitation is not pending")
            user.status = "Cancelado"
            user.auth_enabled = False
            self._account_action_repository_factory(
                session, workspace_id
            ).invalidate_active(
                user.id,
                "invitation",
                "cancelled",
                now,
            )
        self._record(
            event_type="invitation.cancelled",
            tenant_id=tenant_id,
            user_id=user_id,
            correlation_parts=("invitation-cancel", tenant_id, user_id, actor.user_id),
            outcome_code="cancelled",
            occurred_at=now,
        )
        return UserAccessResult(user_id=user_id, status="Cancelado")

