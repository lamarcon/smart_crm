"""Tenant account invitation, acceptance, and recovery lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.control_database import ControlDatabase, ControlRepository
from app.control_models import LoginThrottle
from app.mail import (
    MailDeliveryError,
    MailSender,
    render_invitation_email,
    render_password_reset_email,
)
from app.models import AccountActionToken, CrmUser
from app.policies import Action, CURRENT_ROLES, PrincipalScope, can_perform_action
from app.repositories.account_actions import AccountActionRepository
from app.schemas import (
    ACCOUNT_ACTION_TOKEN_MAX_LENGTH,
    INVALID_ACTION_LINK_MESSAGE,
    PASSWORD_RESET_REQUEST_MESSAGE,
)
from app.security.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    hash_password,
)
from app.services.auth import AuthService, SecurityAuditService
from app.tenant_database import TenantDatabaseRouter, TenantUnavailableError


INVITATION_TTL = timedelta(hours=48)
PASSWORD_RESET_TTL = timedelta(hours=48)
RESET_THROTTLE_BUCKETS = ("reset_account", "reset_ip")
PUBLIC_ACTION_PURPOSES = frozenset({"invitation", "password_reset"})
MAX_RAW_TOKEN_LENGTH = ACCOUNT_ACTION_TOKEN_MAX_LENGTH


class AccountAccessError(RuntimeError):
    pass


class AccountActionLinkInvalidError(AccountAccessError):
    """Single public failure for every unusable invitation or reset link."""

    def __init__(self) -> None:
        super().__init__(INVALID_ACTION_LINK_MESSAGE)


class AccountAccessAuthorizationError(AccountAccessError):
    pass


class AccountAccessTenantUnavailableError(AccountAccessError):
    pass


class AccountAccessValidationError(AccountAccessError):
    pass


class AccountPasswordPolicyError(AccountAccessValidationError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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
class PublicActionView:
    company_name: str
    email: str


@dataclass(frozen=True)
class _PreparedInvitation:
    user_id: str
    email: str
    token_id: UUID
    raw_token: str
    action: str


@dataclass(frozen=True)
class _PreparedReset:
    user_id: str
    email: str
    token_id: UUID
    raw_token: str


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
        tenant_id: UUID | None,
        user_id: str | None,
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


    # Public invitation inspection and acceptance -----------------------------

    def _public_tenant(self, slug: str):  # noqa: ANN202
        if not isinstance(slug, str) or not slug:
            return None
        with self._control_database.session_scope() as session:
            tenant = self._control_repository_factory(session).find_tenant_by_slug(slug)
            if tenant is None or tenant.status != "active":
                return None
            return tenant

    @staticmethod
    def _public_workspace_id(session: Session) -> str:
        workspace_id = session.scalar(
            text("SELECT current_setting('smartcrm.workspace_id', true)")
        )
        if not workspace_id:
            raise TenantUnavailableError("tenant database unavailable")
        return str(workspace_id)

    @staticmethod
    def _usable_raw_token(raw_token: object) -> bool:
        return isinstance(raw_token, str) and 0 < len(raw_token) <= MAX_RAW_TOKEN_LENGTH

    @staticmethod
    def _validate_new_password(password: object, confirmation: object) -> None:
        if (
            not isinstance(password, str)
            or not isinstance(confirmation, str)
            or password != confirmation
        ):
            raise AccountPasswordPolicyError("password_mismatch")
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise AccountPasswordPolicyError("password_length")

    @staticmethod
    def _eligible_holder(user: CrmUser, purpose: str) -> bool:
        if purpose == "invitation":
            return user.status == "Pendente"
        return user.status == "Ativo" and bool(user.auth_enabled)

    @classmethod
    def _token_holder(
        cls,
        session: Session,
        workspace_id: str,
        purpose: str,
        token_digest: str,
        now: datetime,
        *,
        lock: bool,
    ) -> CrmUser | None:
        token_user_id = session.scalar(
            select(AccountActionToken.user_id).where(
                AccountActionToken.workspace_id == workspace_id,
                AccountActionToken.purpose == purpose,
                AccountActionToken.token_digest == token_digest,
                AccountActionToken.expires_at > now,
                AccountActionToken.consumed_at.is_(None),
                AccountActionToken.invalidated_at.is_(None),
            )
        )
        if token_user_id is None:
            return None
        statement = select(CrmUser).where(
            CrmUser.workspace_id == workspace_id,
            CrmUser.id == token_user_id,
            CrmUser.deleted_at.is_(None),
        )
        if lock:
            # Same order as invite/resend/cancel (user, then token) to avoid deadlocks.
            statement = statement.with_for_update()
        user = session.scalar(statement)
        if user is None or not cls._eligible_holder(user, purpose):
            return None
        return user

    def inspect_action(self, slug: str, purpose: str, raw_token: str) -> PublicActionView:
        if purpose not in PUBLIC_ACTION_PURPOSES or not self._usable_raw_token(raw_token):
            raise AccountActionLinkInvalidError()
        tenant = self._public_tenant(slug)
        if tenant is None:
            raise AccountActionLinkInvalidError()
        token_digest = self._token_digest(purpose, raw_token)
        now = self._clock()
        email = None
        try:
            with self._router.tenant_session_scope(tenant.id) as session:
                workspace_id = self._public_workspace_id(session)
                user = self._token_holder(
                    session, workspace_id, purpose, token_digest, now, lock=False
                )
                if user is not None:
                    email = user.normalized_email or user.email.lower()
        except TenantUnavailableError:
            raise AccountActionLinkInvalidError() from None
        if email is None:
            raise AccountActionLinkInvalidError()
        return PublicActionView(company_name=tenant.display_name, email=email)

    def _reject_acceptance(
        self,
        *,
        tenant_id: UUID | None,
        correlation_parts: tuple[object, ...],
        occurred_at: datetime,
    ) -> None:
        self._record(
            event_type="invitation.accept_failed",
            tenant_id=tenant_id,
            user_id=None,
            correlation_parts=correlation_parts,
            outcome_code="invalid_token",
            occurred_at=occurred_at,
        )
        raise AccountActionLinkInvalidError()

    def accept_invitation(
        self,
        slug: str,
        raw_token: str,
        password: str,
        confirmation: str,
        source_ip: str,
    ) -> None:
        self._validate_new_password(password, confirmation)
        now = self._clock()
        tenant = self._public_tenant(slug) if self._usable_raw_token(raw_token) else None
        if tenant is None:
            self._reject_acceptance(
                tenant_id=None,
                correlation_parts=("invitation-accept", slug, source_ip),
                occurred_at=now,
            )
        token_digest = self._token_digest("invitation", raw_token)
        correlation_parts = ("invitation-accept", tenant.id, token_digest, source_ip)
        # Argon2id is deliberately slow: hash before taking any row lock.
        password_hash = hash_password(password)

        accepted_user_id = None
        try:
            with self._router.tenant_session_scope(tenant.id) as session:
                workspace_id = self._public_workspace_id(session)
                user = self._token_holder(
                    session, workspace_id, "invitation", token_digest, now, lock=True
                )
                if user is not None:
                    token = self._account_action_repository_factory(
                        session, workspace_id
                    ).consume_token("invitation", token_digest, now)
                    if token is not None:
                        if token.user_id != user.id:
                            raise AccountActionLinkInvalidError()
                        user.password_hash = password_hash
                        user.auth_enabled = True
                        user.status = "Ativo"
                        user.auth_version = user.auth_version + 1
                        session.flush()
                        accepted_user_id = user.id
        except (TenantUnavailableError, AccountActionLinkInvalidError):
            accepted_user_id = None

        if accepted_user_id is None:
            self._reject_acceptance(
                tenant_id=tenant.id,
                correlation_parts=correlation_parts,
                occurred_at=now,
            )
        self._record(
            event_type="invitation.accepted",
            tenant_id=tenant.id,
            user_id=accepted_user_id,
            correlation_parts=correlation_parts,
            outcome_code="accepted",
            occurred_at=now,
        )

    # Public password recovery -------------------------------------------------

    def _admit_reset_request(self, account_digest: str, ip_digest: str, now: datetime) -> bool:
        """Count one recovery request; False when either bucket is already blocked.

        A bucket blocks *after* its limit is reached, so the 5th account request
        (30th per IP) is still sent and only later requests in the window are held.
        Rows are locked in a fixed order (account, then IP) before the check.
        """

        subjects = tuple(zip(RESET_THROTTLE_BUCKETS, (account_digest, ip_digest)))
        with self._control_database.session_scope() as session:
            repository = self._control_repository_factory(session)
            for bucket_type, subject_digest in subjects:
                throttle = repository.session.scalar(
                    select(LoginThrottle)
                    .where(
                        LoginThrottle.bucket_type == bucket_type,
                        LoginThrottle.subject_digest == subject_digest,
                    )
                    .with_for_update()
                )
                if (
                    throttle is not None
                    and throttle.blocked_until is not None
                    and throttle.blocked_until > now
                ):
                    return False
            for bucket_type, subject_digest in subjects:
                repository.record_account_action_request(
                    bucket_type, subject_digest, now=now
                )
            return True

    def _prepare_reset(
        self,
        tenant_id: UUID,
        email: str,
        raw_token: str,
        now: datetime,
    ) -> _PreparedReset | None:
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._public_workspace_id(session)
            user = session.scalar(
                select(CrmUser)
                .where(
                    CrmUser.workspace_id == workspace_id,
                    CrmUser.normalized_email == email,
                    CrmUser.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if user is None or not self._eligible_holder(user, "password_reset"):
                return None
            # create_token invalidates every live predecessor under the same user lock.
            token = self._account_action_repository_factory(
                session, workspace_id
            ).create_token(
                user_id=user.id,
                purpose="password_reset",
                token_digest=self._token_digest("password_reset", raw_token),
                expires_at=now + PASSWORD_RESET_TTL,
                created_by_user_id=None,
                now=now,
            )
            return _PreparedReset(
                user_id=user.id,
                email=user.normalized_email,
                token_id=token.id,
                raw_token=raw_token,
            )

    def _deliver_reset(self, tenant, prepared: _PreparedReset) -> None:  # noqa: ANN001
        message = render_password_reset_email(
            tenant.display_name,
            prepared.email,
            (
                f"{self._public_origin}/{tenant.slug}/reset-password"
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
        try:
            with self._router.tenant_session_scope(tenant.id) as session:
                workspace_id = self._public_workspace_id(session)
                self._account_action_repository_factory(
                    session, workspace_id
                ).mark_delivery(
                    prepared.token_id,
                    status=delivery_status,
                    failure_code=failure_code,
                    now=delivered_at,
                )
        except (TenantUnavailableError, SQLAlchemyError):
            # The token stays "pending"; the next request replaces it.
            failure_code = failure_code or "delivery_record_failed"
        self._record(
            event_type=(
                "password_reset.sent"
                if delivery_status == "sent"
                else "password_reset.delivery_failed"
            ),
            tenant_id=tenant.id,
            user_id=prepared.user_id,
            correlation_parts=(
                "password-reset-delivery",
                prepared.token_id,
                delivery_status,
            ),
            outcome_code=failure_code or "delivered",
            occurred_at=delivered_at,
        )

    def request_password_reset(self, slug: str, email: str, source_ip: str) -> None:
        """Start recovery without revealing tenant, account, SMTP or limit outcomes.

        Every path returns ``None``; the public layer always answers with
        ``PASSWORD_RESET_REQUEST_MESSAGE``. Outcomes are only audited.
        """

        now = self._clock()
        slug_text = slug if isinstance(slug, str) else ""
        email_text = email.strip().lower() if isinstance(email, str) else ""
        ip_text = source_ip if isinstance(source_ip, str) else ""
        account_digest, ip_digest = AuthService.login_subject_digests(
            slug_text, email_text, ip_text
        )
        correlation_parts = ("password-reset-request", account_digest, ip_digest)
        tenant_id = None

        def ignored(outcome_code: str) -> None:
            self._record(
                event_type="password_reset.request_ignored",
                tenant_id=tenant_id,
                user_id=None,
                correlation_parts=correlation_parts,
                outcome_code=outcome_code,
                occurred_at=now,
            )

        try:
            admitted = self._admit_reset_request(account_digest, ip_digest, now)
            tenant = self._public_tenant(slug_text) if admitted else None
        except SQLAlchemyError:
            # Fail closed: without a working limiter nothing is sent.
            ignored("control_unavailable")
            return
        if not admitted:
            ignored("rate_limited")
            return
        if tenant is None:
            ignored("unknown_tenant")
            return
        tenant_id = tenant.id
        if not email_text or "@" not in email_text:
            ignored("no_eligible_account")
            return

        raw_token = self._token_factory()
        if not raw_token:
            ignored("token_generation_failed")
            return
        try:
            prepared = self._prepare_reset(tenant.id, email_text, raw_token, now)
        except (TenantUnavailableError, SQLAlchemyError):
            ignored("tenant_unavailable")
            return
        if prepared is None:
            ignored("no_eligible_account")
            return

        self._record(
            event_type="password_reset.requested",
            tenant_id=tenant.id,
            user_id=prepared.user_id,
            correlation_parts=("password-reset", prepared.token_id, ip_digest),
            outcome_code="pending_delivery",
            occurred_at=now,
        )
        self._deliver_reset(tenant, prepared)

    def _reject_reset(
        self,
        *,
        tenant_id: UUID | None,
        correlation_parts: tuple[object, ...],
        occurred_at: datetime,
    ) -> None:
        self._record(
            event_type="password_reset.failed",
            tenant_id=tenant_id,
            user_id=None,
            correlation_parts=correlation_parts,
            outcome_code="invalid_token",
            occurred_at=occurred_at,
        )
        raise AccountActionLinkInvalidError()

    def _revoke_sessions_after_reset(
        self,
        tenant_id: UUID,
        user_id: str,
        correlation_parts: tuple[object, ...],
        now: datetime,
    ) -> None:
        # The new hash and auth_version are already committed; a central failure
        # must never surface as a failed reset. Stale sessions are still rejected
        # by AuthService.current_session through the auth_version mismatch.
        for _attempt in range(2):
            try:
                with self._control_database.session_scope() as session:
                    self._control_repository_factory(session).revoke_user_sessions(
                        tenant_id,
                        user_id,
                        reason="password_reset",
                        revoked_at=now,
                    )
            except Exception:  # noqa: BLE001 - retried once, then audited
                continue
            self._record(
                event_type="session.revoked",
                tenant_id=tenant_id,
                user_id=user_id,
                correlation_parts=("session-revocation", *correlation_parts),
                outcome_code="password_reset",
                occurred_at=now,
            )
            return
        self._record(
            event_type="password_reset.session_revocation_failed",
            tenant_id=tenant_id,
            user_id=user_id,
            correlation_parts=("session-revocation", *correlation_parts),
            outcome_code="revocation_failed",
            occurred_at=now,
        )

    def reset_password(
        self,
        slug: str,
        raw_token: str,
        password: str,
        confirmation: str,
        source_ip: str,
    ) -> None:
        self._validate_new_password(password, confirmation)
        now = self._clock()
        tenant = self._public_tenant(slug) if self._usable_raw_token(raw_token) else None
        if tenant is None:
            self._reject_reset(
                tenant_id=None,
                correlation_parts=("password-reset", slug, source_ip),
                occurred_at=now,
            )
        token_digest = self._token_digest("password_reset", raw_token)
        correlation_parts = ("password-reset", tenant.id, token_digest, source_ip)
        # Argon2id is deliberately slow: hash before taking any row lock.
        password_hash = hash_password(password)

        reset_user_id = None
        try:
            with self._router.tenant_session_scope(tenant.id) as session:
                workspace_id = self._public_workspace_id(session)
                user = self._token_holder(
                    session, workspace_id, "password_reset", token_digest, now, lock=True
                )
                if user is not None:
                    token = self._account_action_repository_factory(
                        session, workspace_id
                    ).consume_token("password_reset", token_digest, now)
                    if token is not None:
                        if token.user_id != user.id:
                            raise AccountActionLinkInvalidError()
                        user.password_hash = password_hash
                        user.auth_version = user.auth_version + 1
                        session.flush()
                        reset_user_id = user.id
        except (TenantUnavailableError, AccountActionLinkInvalidError):
            reset_user_id = None

        if reset_user_id is None:
            self._reject_reset(
                tenant_id=tenant.id,
                correlation_parts=correlation_parts,
                occurred_at=now,
            )
        self._revoke_sessions_after_reset(tenant.id, reset_user_id, correlation_parts, now)
        self._record(
            event_type="password_reset.completed",
            tenant_id=tenant.id,
            user_id=reset_user_id,
            correlation_parts=correlation_parts,
            outcome_code="completed",
            occurred_at=now,
        )
