"""Personal API tokens for the REST API v1.

A token belongs to one user and acts with that user's *current* profile: role,
team and the role permissions stored for the workspace are read again on every
request, so a profile change applies at once and a user who is no longer active
stops every token they own. ``read`` tokens only reach GET routes.

Tokens are shown once and stored as a sha256 digest plus their last four
characters. Requests are rate limited per token and wrong tokens per address.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Callable, Iterator
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.control_database import ControlDatabase, ControlRepository
from app.models import ApiToken, CrmUser
from app.policies import CURRENT_ROLES, Action, PrincipalScope, can_perform_action
from app.repositories.permissions import read_role_permissions
from app.services.auth import SecurityAuditService
from app.services.lead_intake import SlidingWindowLimiter
from app.tenant_database import TenantUnavailableError

TOKEN_PREFIX = "sct_"
ACCESS_LEVELS = ("read", "write")
EXPIRATION_DAYS = (30, 90, 365)
MAX_RAW_TOKEN_LENGTH = 128
MAX_ACTIVE_TOKENS_PER_USER = 10
TOKEN_LIMIT_PER_MINUTE = 120
FAILED_ATTEMPTS_PER_IP = 20
FAILED_WINDOW_SECONDS = 600
RETRY_AFTER_SECONDS = 60
LAST_USED_RESOLUTION = timedelta(minutes=1)


class ApiTokenError(RuntimeError):
    """Base class of the API token errors."""


class ApiTokenAuthorizationError(ApiTokenError):
    """The signed-in user may not manage this token."""


class ApiTokenValidationError(ApiTokenError):
    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


class ApiTokenNotFoundError(ApiTokenError):
    """No token (or tenant) with this identifier."""


class ApiTokenInvalidError(ApiTokenError):
    """Missing, unknown, revoked or expired token, or an inactive owner."""


class ApiTokenRateLimitedError(ApiTokenError):
    """Too many requests for this token or failed attempts from this address."""


class ApiTokenReadOnlyError(ApiTokenError):
    """A read token was used on a route that writes."""


@dataclass(frozen=True)
class ApiTokenView:
    id: str
    name: str
    access: str
    user_id: str
    user_name: str
    hint: str
    created_at: datetime | None
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


@dataclass(frozen=True)
class CreatedApiToken:
    token: ApiTokenView
    raw_token: str


@dataclass(frozen=True)
class ApiRequestContext:
    """An authenticated API request: the owner's principal and an open tenant session."""

    principal: PrincipalScope
    session: Session
    token_id: str
    access: str
    user_name: str


def token_digest(raw_token: str) -> str:
    return sha256(f"api-token\0{raw_token}".encode("utf-8")).hexdigest()


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


class ApiTokenService:
    def __init__(
        self,
        control_database: ControlDatabase,
        router,  # noqa: ANN001 - TenantDatabaseRouter or a test double
        *,
        security_audit=None,  # noqa: ANN001
        control_repository_factory=ControlRepository,  # noqa: ANN001
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        import time

        self._control_database = control_database
        self._router = router
        self._control_repository_factory = control_repository_factory
        self._security_audit = security_audit or SecurityAuditService(
            control_database, repository_factory=control_repository_factory
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        ticks = monotonic or time.monotonic
        self._token_factory = token_factory or (lambda: TOKEN_PREFIX + token_urlsafe(32))
        self.token_limiter = SlidingWindowLimiter(TOKEN_LIMIT_PER_MINUTE, 60, ticks)
        self.failure_limiter = SlidingWindowLimiter(FAILED_ATTEMPTS_PER_IP, FAILED_WINDOW_SECONDS, ticks)

    # Shared helpers ---------------------------------------------------------------------

    def _record(self, event_type: str, tenant_id: UUID | None, user_id: str | None, outcome: str, *parts: object) -> None:
        try:
            self._security_audit.record(
                event_type=event_type,
                tenant_id=tenant_id,
                user_id=user_id,
                correlation_digest=SecurityAuditService.correlation_digest(event_type, *parts),
                outcome_code=outcome,
                occurred_at=self._clock(),
            )
        except Exception:
            pass

    @staticmethod
    def _session_workspace(session: Session) -> str:
        workspace_id = session.scalar(text("SELECT current_setting('smartcrm.workspace_id', true)"))
        if not workspace_id:
            raise TenantUnavailableError("tenant database unavailable")
        return str(workspace_id)

    def _actor_workspace(self, session: Session, tenant_id: UUID, actor: PrincipalScope) -> str:
        if not isinstance(actor, PrincipalScope) or actor.tenant_id != tenant_id:
            raise ApiTokenAuthorizationError("principal is not authorized")
        workspace_id = self._session_workspace(session)
        if workspace_id != actor.workspace_id:
            raise ApiTokenAuthorizationError("principal is not authorized")
        return workspace_id

    @staticmethod
    def _view(row: ApiToken, user_name: str) -> ApiTokenView:
        return ApiTokenView(
            id=str(row.id),
            name=row.name,
            access=row.access,
            user_id=row.user_id,
            user_name=user_name,
            hint=row.token_hint,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )

    @staticmethod
    def _user_names(session: Session, workspace_id: str) -> dict[str, str]:
        return dict(session.execute(select(CrmUser.id, CrmUser.name).where(CrmUser.workspace_id == workspace_id)).all())

    # Management (signed-in user) --------------------------------------------------------

    def list_tokens(self, tenant_id: UUID, actor: PrincipalScope, *, all_users: bool = False) -> list[ApiTokenView]:
        if all_users and not can_perform_action(actor, Action.MANAGE_USERS):
            raise ApiTokenAuthorizationError("only admins list every token")
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._actor_workspace(session, tenant_id, actor)
            query = select(ApiToken).where(ApiToken.workspace_id == workspace_id)
            if not all_users:
                query = query.where(ApiToken.user_id == actor.user_id)
            rows = session.scalars(
                query.order_by(ApiToken.revoked_at.is_not(None), ApiToken.created_at.desc())
            ).all()
            names = self._user_names(session, workspace_id)
            return [self._view(row, names.get(row.user_id, "")) for row in rows]

    def create_token(
        self,
        tenant_id: UUID,
        actor: PrincipalScope,
        *,
        name: object,
        access: object,
        expires_in_days: object = None,
    ) -> CreatedApiToken:
        name = _clean(name)
        if not name or len(name) > 120:
            raise ApiTokenValidationError("Informe um nome de até 120 caracteres.", "name")
        if access not in ACCESS_LEVELS:
            raise ApiTokenValidationError("Escolha o acesso: leitura ou leitura e escrita.", "access")
        if expires_in_days is not None and expires_in_days not in EXPIRATION_DAYS:
            raise ApiTokenValidationError("Escolha a validade: 30, 90 ou 365 dias, ou sem validade.", "expiresInDays")
        now = self._clock()
        raw_token = self._token_factory()
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._actor_workspace(session, tenant_id, actor)
            owner = session.scalar(
                select(CrmUser)
                .where(CrmUser.workspace_id == workspace_id, CrmUser.id == actor.user_id, CrmUser.deleted_at.is_(None))
                .with_for_update()
            )
            if owner is None or owner.status != "Ativo":
                raise ApiTokenAuthorizationError("inactive user")
            active = session.scalar(
                select(func.count())
                .select_from(ApiToken)
                .where(
                    ApiToken.workspace_id == workspace_id,
                    ApiToken.user_id == owner.id,
                    ApiToken.revoked_at.is_(None),
                    (ApiToken.expires_at.is_(None)) | (ApiToken.expires_at > now),
                )
            )
            if active >= MAX_ACTIVE_TOKENS_PER_USER:
                raise ApiTokenValidationError(
                    f"Cada usuário pode ter até {MAX_ACTIVE_TOKENS_PER_USER} tokens ativos. Revogue um antes de criar outro.",
                    "name",
                )
            row = ApiToken(
                workspace_id=workspace_id,
                user_id=owner.id,
                name=name,
                access=str(access),
                token_digest=token_digest(raw_token),
                token_hint=raw_token[-4:],
                expires_at=now + timedelta(days=int(expires_in_days)) if expires_in_days else None,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            view = self._view(row, owner.name)
        self._record("api_token.created", tenant_id, actor.user_id, view.access, view.id)
        return CreatedApiToken(token=view, raw_token=raw_token)

    def revoke_token(self, tenant_id: UUID, actor: PrincipalScope, token_id: str) -> ApiTokenView:
        try:
            parsed = UUID(str(token_id))
        except ValueError:
            raise ApiTokenNotFoundError("token not found") from None
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._actor_workspace(session, tenant_id, actor)
            row = session.scalar(
                select(ApiToken)
                .where(ApiToken.workspace_id == workspace_id, ApiToken.id == parsed)
                .with_for_update()
            )
            if row is None:
                raise ApiTokenNotFoundError("token not found")
            if row.user_id != actor.user_id and not can_perform_action(actor, Action.MANAGE_USERS):
                # Someone else's token is reported as missing, not as forbidden.
                raise ApiTokenNotFoundError("token not found")
            if row.revoked_at is None:
                row.revoked_at = self._clock()
                row.revoked_by_user_id = actor.user_id
                session.flush()
            view = self._view(row, self._user_names(session, workspace_id).get(row.user_id, ""))
        self._record("api_token.revoked", tenant_id, actor.user_id, "revoked", view.id)
        return view

    # API requests -----------------------------------------------------------------------

    def _tenant(self, slug: object):  # noqa: ANN202
        if not isinstance(slug, str) or not slug or len(slug) > 64:
            return None
        with self._control_database.session_scope() as session:
            tenant = self._control_repository_factory(session).find_tenant_by_slug(slug)
            if tenant is None or tenant.status != "active":
                return None
            return tenant

    def _reject(self, tenant_id: UUID | None, source_ip: str, reason: str) -> None:
        blocked = not self.failure_limiter.hit(source_ip)
        self._record("api_token.rejected", tenant_id, None, "rate_limited_ip" if blocked else reason, source_ip)
        if blocked:
            raise ApiTokenRateLimitedError("too many failed attempts")
        raise ApiTokenInvalidError(reason)

    @staticmethod
    def bearer_token(authorization: str | None) -> str | None:
        if not authorization:
            return None
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer":
            return None
        return value.strip() or None

    @contextmanager
    def request(self, slug: str, raw_token: object, source_ip: str, *, write: bool) -> Iterator[ApiRequestContext]:
        """Authenticates one API call and keeps its tenant transaction open for the route."""

        if self.failure_limiter.blocked(source_ip):
            raise ApiTokenRateLimitedError("too many failed attempts")
        tenant = self._tenant(slug)
        if tenant is None:
            if not self.failure_limiter.hit(source_ip):
                raise ApiTokenRateLimitedError("too many failed attempts")
            raise ApiTokenNotFoundError("tenant not found")
        if not isinstance(raw_token, str) or not raw_token.startswith(TOKEN_PREFIX) or len(raw_token) > MAX_RAW_TOKEN_LENGTH:
            self._reject(tenant.id, source_ip, "invalid_token")
        digest = token_digest(raw_token)
        if not self.token_limiter.hit(digest):
            self._record("api_token.rejected", tenant.id, None, "rate_limited_token", digest)
            raise ApiTokenRateLimitedError("too many requests")

        now = self._clock()
        rejection: str | None = None
        with self._router.tenant_session_scope(tenant.id) as session:
            workspace_id = self._session_workspace(session)
            row = session.scalar(
                select(ApiToken).where(ApiToken.workspace_id == workspace_id, ApiToken.token_digest == digest)
            )
            owner = None
            if row is not None and row.revoked_at is None and (row.expires_at is None or row.expires_at > now):
                owner = session.scalar(
                    select(CrmUser).where(
                        CrmUser.workspace_id == workspace_id,
                        CrmUser.id == row.user_id,
                        CrmUser.deleted_at.is_(None),
                    )
                )
            if owner is None or owner.status != "Ativo" or owner.role not in CURRENT_ROLES:
                rejection = "invalid_token"
            elif write and row.access != "write":
                rejection = "read_only"
            if rejection is None:
                if row.last_used_at is None or now - row.last_used_at >= LAST_USED_RESOLUTION:
                    row.last_used_at = now
                    session.flush()
                principal = PrincipalScope(
                    tenant_id=tenant.id,
                    workspace_id=workspace_id,
                    user_id=owner.id,
                    role=owner.role,
                    team_id=owner.team_id,
                    auth_version=owner.auth_version,
                    permissions=read_role_permissions(session, workspace_id, owner.role),
                )
                yield ApiRequestContext(
                    principal=principal, session=session, token_id=str(row.id), access=row.access, user_name=owner.name
                )
                return
        if rejection == "read_only":
            self._record("api_token.rejected", tenant.id, None, "read_only", digest)
            raise ApiTokenReadOnlyError("read token used to write")
        self._reject(tenant.id, source_ip, "invalid_token")


def token_view_payload(view: ApiTokenView, now: datetime) -> dict:
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "id": view.id,
        "name": view.name,
        "access": view.access,
        "userId": view.user_id,
        "userName": view.user_name,
        "hint": view.hint,
        "createdAt": iso(view.created_at),
        "lastUsedAt": iso(view.last_used_at),
        "expiresAt": iso(view.expires_at),
        "revokedAt": iso(view.revoked_at),
        "active": view.active(now),
    }
