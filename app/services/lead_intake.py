"""Lead intake: admin-managed secret keys and the public endpoint that external
systems (the Instagram bot, a future site form) call to create leads.

Keys are shown once and stored only as a sha256 digest. Every accepted lead is
written through the same workspace snapshot path as a save (workspace row lock,
reconcile, version bump), so open tabs reload instead of overwriting it.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any, Callable, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.control_database import ControlDatabase, ControlRepository
from app.models import CrmUser, Lead, LeadIntakeKey, Notification, Workspace
from app.policies import Action, PrincipalScope, can_perform_action
from app.repositories.workspace import WorkspaceRepository
from app.schemas import WorkspaceState, validate_references
from app.services.auth import SecurityAuditService
from app.tenant_database import TenantUnavailableError

LEAD_CHANNELS = (
    "Site", "Instagram", "WhatsApp", "Google Ads", "Meta Ads", "Busca orgânica",
    "Redes sociais", "E-mail", "Indicação", "Evento", "Telefone", "Outro",
)
RESPONSIBLE_ROLES = frozenset({"Administrador", "Gestor", "Vendedor", "Faturamento"})
KEY_PREFIX = "sck_"
MAX_RAW_KEY_LENGTH = 128
MAX_BODY_BYTES = 16 * 1024
MAX_TRACKED_MESSAGES = 20
KEY_LIMIT_PER_MINUTE = 60
IP_LIMIT_PER_MINUTE = 120
FAILED_ATTEMPTS_PER_IP = 10
FAILED_WINDOW_SECONDS = 600
RETRY_AFTER_SECONDS = 60
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LeadIntakeError(RuntimeError):
    """Base error for lead intake."""


class LeadIntakeAuthorizationError(LeadIntakeError):
    pass


class LeadIntakeValidationError(LeadIntakeError):
    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


class LeadIntakeNotFoundError(LeadIntakeError):
    pass


class LeadIntakeKeyInvalidError(LeadIntakeError):
    pass


class LeadIntakeRateLimitedError(LeadIntakeError):
    pass


class LeadIntakeUnavailableError(LeadIntakeError):
    pass


# --- Payloads -----------------------------------------------------------------------------


def _clean(value: object) -> str:
    return str(value).strip() if value is not None else ""


class UtmPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = Field(default="", max_length=200)
    medium: str = Field(default="", max_length=200)
    campaign: str = Field(default="", max_length=200)
    term: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=200)


class LeadIntakePayload(BaseModel):
    """What an external system may send; unknown fields are ignored."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=40)
    company: str = Field(default="", max_length=160)
    message: str = Field(default="", max_length=2000)
    channel: str = Field(default="", max_length=32)
    external_id: str = Field(default="", alias="externalId", max_length=128)
    profile_url: str = Field(default="", alias="profileUrl", max_length=500)
    campaign: str = Field(default="", max_length=120)
    utm: UtmPayload = Field(default_factory=UtmPayload)
    page_url: str = Field(default="", alias="pageUrl", max_length=1000)
    referrer: str = Field(default="", max_length=1000)

    @field_validator(
        "name", "email", "phone", "company", "message", "channel", "external_id",
        "profile_url", "campaign", "page_url", "referrer", mode="before",
    )
    @classmethod
    def _text(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        if not isinstance(value, str):
            raise ValueError("must be text")
        return value.strip()

    @field_validator("utm", mode="before")
    @classmethod
    def _utm(cls, value: object) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("must be an object")
        return {key: _clean(item) for key, item in value.items() if isinstance(item, (str, int, float))}


def parse_payload(raw: object) -> LeadIntakePayload:
    if not isinstance(raw, dict):
        raise LeadIntakeValidationError("Envie um objeto JSON.")
    try:
        payload = LeadIntakePayload.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        field = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__") or None
        raise LeadIntakeValidationError(f"Campo inválido: {field}.", field) from None
    if not (payload.name or payload.email or payload.phone):
        raise LeadIntakeValidationError("Informe ao menos nome, e-mail ou telefone.")
    if payload.email and not _EMAIL.match(payload.email):
        raise LeadIntakeValidationError("E-mail inválido.", "email")
    if payload.channel and payload.channel not in LEAD_CHANNELS:
        raise LeadIntakeValidationError("Canal não suportado.", "channel")
    return payload


# --- Rate limiting --------------------------------------------------------------------------


class SlidingWindowLimiter:
    """In-memory limiter; enough for one application process."""

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float]) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key, self._clock())) >= self.limit

    def hit(self, key: str) -> bool:
        """Count one attempt; False when the limit was already reached."""

        with self._lock:
            now = self._clock()
            if len(self._hits) > 10_000:
                for stale in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
                    del self._hits[stale]
            hits = self._recent(key, now)
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


# --- Views ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class LeadIntakeKeyView:
    id: str
    name: str
    default_channel: str
    default_responsible_id: str
    created_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class CreatedLeadIntakeKey:
    key: LeadIntakeKeyView
    raw_key: str


@dataclass(frozen=True)
class LeadIntakeResult:
    lead_id: str
    status: Literal["created", "updated"]
    workspace_version: int


def key_digest(raw_key: str) -> str:
    return sha256(f"lead-intake\0{raw_key}".encode("utf-8")).hexdigest()


def _next_number(ids: list[str], prefix: str) -> int:
    highest = 0
    for value in ids:
        head, _, number = str(value).partition("-")
        if head == prefix and number.isdigit():
            highest = max(highest, int(number))
    return highest + 1


class LeadIntakeService:
    def __init__(
        self,
        control_database: ControlDatabase,
        router,  # noqa: ANN001 - TenantDatabaseRouter or a test double
        *,
        security_audit=None,  # noqa: ANN001
        control_repository_factory=ControlRepository,  # noqa: ANN001
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        key_factory: Callable[[], str] | None = None,
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
        self._key_factory = key_factory or (lambda: KEY_PREFIX + token_urlsafe(32))
        self.key_limiter = SlidingWindowLimiter(KEY_LIMIT_PER_MINUTE, 60, ticks)
        self.ip_limiter = SlidingWindowLimiter(IP_LIMIT_PER_MINUTE, 60, ticks)
        self.failure_limiter = SlidingWindowLimiter(FAILED_ATTEMPTS_PER_IP, FAILED_WINDOW_SECONDS, ticks)

    # Shared helpers ---------------------------------------------------------------------

    def _record(self, event_type: str, tenant_id: UUID | None, outcome: str, *parts: object) -> None:
        self._security_audit.record(
            event_type=event_type,
            tenant_id=tenant_id,
            user_id=None,
            correlation_digest=SecurityAuditService.correlation_digest(event_type, *parts),
            outcome_code=outcome,
            occurred_at=self._clock(),
        )

    @staticmethod
    def _authorize(tenant_id: UUID, actor: PrincipalScope) -> None:
        if (
            not isinstance(actor, PrincipalScope)
            or actor.tenant_id != tenant_id
            or not can_perform_action(actor, Action.MANAGE_USERS)
        ):
            raise LeadIntakeAuthorizationError("principal is not authorized")

    @staticmethod
    def _session_workspace(session: Session) -> str:
        workspace_id = session.scalar(text("SELECT current_setting('smartcrm.workspace_id', true)"))
        if not workspace_id:
            raise TenantUnavailableError("tenant database unavailable")
        return str(workspace_id)

    def _admin_workspace(self, session: Session, actor: PrincipalScope) -> str:
        workspace_id = self._session_workspace(session)
        if workspace_id != actor.workspace_id:
            raise LeadIntakeAuthorizationError("principal is not authorized")
        return workspace_id

    @staticmethod
    def _view(row: LeadIntakeKey) -> LeadIntakeKeyView:
        return LeadIntakeKeyView(
            id=str(row.id),
            name=row.name,
            default_channel=row.default_channel,
            default_responsible_id=row.default_responsible_id,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            revoked_at=row.revoked_at,
        )

    # Administration ---------------------------------------------------------------------

    def list_keys(self, tenant_id: UUID, actor: PrincipalScope) -> list[LeadIntakeKeyView]:
        self._authorize(tenant_id, actor)
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._admin_workspace(session, actor)
            rows = session.scalars(
                select(LeadIntakeKey)
                .where(LeadIntakeKey.workspace_id == workspace_id)
                .order_by(LeadIntakeKey.revoked_at.is_not(None), LeadIntakeKey.created_at.desc())
            ).all()
            return [self._view(row) for row in rows]

    def create_key(
        self,
        tenant_id: UUID,
        actor: PrincipalScope,
        *,
        name: str,
        default_channel: str,
        default_responsible_id: str,
    ) -> CreatedLeadIntakeKey:
        self._authorize(tenant_id, actor)
        name = _clean(name)
        if not name or len(name) > 120:
            raise LeadIntakeValidationError("Informe um nome de até 120 caracteres.", "name")
        if default_channel not in LEAD_CHANNELS:
            raise LeadIntakeValidationError("Canal não suportado.", "defaultChannel")
        raw_key = self._key_factory()
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._admin_workspace(session, actor)
            responsible = session.scalar(
                select(CrmUser).where(
                    CrmUser.workspace_id == workspace_id,
                    CrmUser.id == default_responsible_id,
                    CrmUser.deleted_at.is_(None),
                )
            )
            if responsible is None or responsible.status != "Ativo" or responsible.role not in RESPONSIBLE_ROLES:
                raise LeadIntakeValidationError("Escolha um responsável ativo.", "defaultResponsibleId")
            row = LeadIntakeKey(
                workspace_id=workspace_id,
                name=name,
                key_digest=key_digest(raw_key),
                default_channel=default_channel,
                default_responsible_id=responsible.id,
                created_by_user_id=actor.user_id,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            view = self._view(row)
        self._record("lead_intake.key_created", tenant_id, "created", view.id, actor.user_id)
        return CreatedLeadIntakeKey(key=view, raw_key=raw_key)

    def revoke_key(self, tenant_id: UUID, actor: PrincipalScope, key_id: str) -> LeadIntakeKeyView:
        self._authorize(tenant_id, actor)
        try:
            parsed = UUID(str(key_id))
        except ValueError:
            raise LeadIntakeNotFoundError("key not found") from None
        with self._router.tenant_session_scope(tenant_id) as session:
            workspace_id = self._admin_workspace(session, actor)
            row = session.scalar(
                select(LeadIntakeKey)
                .where(LeadIntakeKey.workspace_id == workspace_id, LeadIntakeKey.id == parsed)
                .with_for_update()
            )
            if row is None:
                raise LeadIntakeNotFoundError("key not found")
            if row.revoked_at is None:
                row.revoked_at = self._clock()
                session.flush()
            view = self._view(row)
        self._record("lead_intake.key_revoked", tenant_id, "revoked", view.id, actor.user_id)
        return view

    # Public intake ----------------------------------------------------------------------

    def _public_tenant(self, slug: str):  # noqa: ANN202
        if not isinstance(slug, str) or not slug or len(slug) > 64:
            return None
        with self._control_database.session_scope() as session:
            tenant = self._control_repository_factory(session).find_tenant_by_slug(slug)
            if tenant is None or tenant.status != "active":
                return None
            return tenant

    def _reject_key(self, tenant_id: UUID | None, source_ip: str, reason: str) -> None:
        # Repeated wrong keys from one address get 429 instead of 401. Valid keys
        # are never blocked, so nobody can lock the bot out by guessing on purpose.
        blocked = not self.failure_limiter.hit(source_ip)
        self._record("lead_intake.rejected", tenant_id, "rate_limited_ip" if blocked else reason, source_ip)
        if blocked:
            raise LeadIntakeRateLimitedError("too many failed attempts")
        raise LeadIntakeKeyInvalidError(reason)

    def submit(self, slug: str, raw_key: object, raw_payload: object, source_ip: str) -> LeadIntakeResult:
        if not self.ip_limiter.hit(source_ip):
            self._record("lead_intake.rejected", None, "rate_limited_ip", source_ip)
            raise LeadIntakeRateLimitedError("too many requests")
        tenant = self._public_tenant(slug)
        if tenant is None:
            if not self.failure_limiter.hit(source_ip):
                raise LeadIntakeRateLimitedError("too many failed attempts")
            raise LeadIntakeNotFoundError("tenant not found")
        if not isinstance(raw_key, str) or not raw_key.startswith(KEY_PREFIX) or len(raw_key) > MAX_RAW_KEY_LENGTH:
            self._reject_key(tenant.id, source_ip, "invalid_key")
        digest = key_digest(raw_key)
        if not self.key_limiter.hit(digest):
            self._record("lead_intake.rejected", tenant.id, "rate_limited_key", digest)
            raise LeadIntakeRateLimitedError("too many requests")
        try:
            payload = parse_payload(raw_payload)
        except LeadIntakeValidationError:
            self._record("lead_intake.rejected", tenant.id, "invalid_payload", digest)
            raise

        try:
            with self._router.tenant_session_scope(tenant.id) as session:
                result = self._write_lead(session, digest, payload)
        except TenantUnavailableError:
            raise LeadIntakeUnavailableError("tenant unavailable") from None
        if result is None:
            self._reject_key(tenant.id, source_ip, "invalid_key")
        self._record("lead_intake.accepted", tenant.id, result.status, digest, result.lead_id)
        return result

    def _write_lead(self, session: Session, digest: str, payload: LeadIntakePayload) -> LeadIntakeResult | None:
        workspace_id = self._session_workspace(session)
        key = session.scalar(
            select(LeadIntakeKey).where(
                LeadIntakeKey.workspace_id == workspace_id,
                LeadIntakeKey.key_digest == digest,
                LeadIntakeKey.revoked_at.is_(None),
            )
        )
        if key is None:
            return None
        # Same lock order as a workspace save: the workspace row before any record.
        workspace = session.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        if workspace is None or workspace.initialized_at is None:
            raise LeadIntakeUnavailableError("workspace not initialized")
        now = self._clock()
        stamp = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        key.last_used_at = now

        repository = WorkspaceRepository(session, workspace_id)
        data = repository.read_active().model_dump(by_alias=True, exclude_none=True)
        channel = payload.channel or key.default_channel
        users = {user["id"]: user for user in data.get("users", [])}
        responsible = users.get(key.default_responsible_id)
        if responsible is None or responsible.get("status") != "Ativo":
            responsible = next(
                (user for user in data.get("users", []) if user.get("status") == "Ativo" and user.get("role") == "Administrador"),
                responsible,
            )
        responsible_id = responsible["id"] if responsible else key.default_responsible_id

        tracking_update = {
            "channel": channel,
            "tool": key.name,
            "campaign": payload.campaign,
            "externalId": payload.external_id,
            "profileUrl": payload.profile_url,
            "utmSource": payload.utm.source,
            "utmMedium": payload.utm.medium,
            "utmCampaign": payload.utm.campaign,
            "utmTerm": payload.utm.term,
            "utmContent": payload.utm.content,
            "pageUrl": payload.page_url,
            "referrer": payload.referrer,
            "intakeKeyName": key.name,
        }
        tracking_update = {name: value for name, value in tracking_update.items() if value}
        message = {"at": stamp, "text": payload.message} if payload.message else None

        existing = None
        if payload.external_id:
            existing = next(
                (
                    lead for lead in data["leads"]
                    if lead.get("stage") == "Em contato"
                    and (lead.get("tracking") or {}).get("externalId") == payload.external_id
                    and (lead.get("tracking") or {}).get("channel") == channel
                ),
                None,
            )

        if existing is not None:
            for field, value in (("name", payload.name), ("email", payload.email), ("phone", payload.phone), ("company", payload.company)):
                if value and not str(existing.get(field) or "").strip():
                    existing[field] = value
            tracking = deepcopy(existing.get("tracking") or {})
            tracking.update(tracking_update)
            tracking["lastReceivedAt"] = stamp
            if message:
                tracking["messages"] = [*(tracking.get("messages") or []), message][-MAX_TRACKED_MESSAGES:]
            existing["tracking"] = tracking
            existing["updatedAt"] = stamp
            lead_id, status = existing["id"], "updated"
            notice = ("Lead voltou a falar", f"{existing.get('name') or payload.name} enviou um novo contato pelo canal {channel}.")
        else:
            all_lead_ids = list(session.scalars(select(Lead.id).where(Lead.workspace_id == workspace_id)))
            lead_id = f"L-{_next_number(all_lead_ids, 'L')}"
            name = payload.name or payload.email or payload.phone
            tracking = {**tracking_update, "receivedAt": stamp, "lastReceivedAt": stamp}
            if message:
                tracking["messages"] = [message]
            lead = {
                "id": lead_id,
                "name": name,
                "company": payload.company,
                "email": payload.email,
                "phone": payload.phone,
                "segment": "",
                "source": channel,
                "stage": "Em contato",
                "responsibleId": responsible_id,
                "assistants": [],
                "createdAt": stamp,
                "updatedAt": stamp,
                "tracking": tracking,
            }
            if responsible and responsible.get("team"):
                lead["team"] = responsible["team"]
            data["leads"].insert(0, lead)
            status = "created"
            notice = (f"Novo Lead pelo canal {channel}", f"{name} chegou pela captação automática ({key.name}).")

        all_notification_ids = list(session.scalars(select(Notification.id).where(Notification.workspace_id == workspace_id)))
        data["notifications"].insert(0, {
            "id": f"NT-{_next_number(all_notification_ids, 'NT')}",
            "userId": responsible_id,
            "text": notice[0],
            "detail": notice[1],
            "time": "Agora",
            "read": False,
        })

        state = WorkspaceState.model_validate(data)
        validate_references(state)
        repository.reconcile(state)
        workspace.version += 1
        session.flush()
        return LeadIntakeResult(lead_id=lead_id, status=status, workspace_version=workspace.version)


def key_view_payload(view: LeadIntakeKeyView) -> dict[str, Any]:
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "id": view.id,
        "name": view.name,
        "defaultChannel": view.default_channel,
        "defaultResponsibleId": view.default_responsible_id,
        "createdAt": iso(view.created_at),
        "lastUsedAt": iso(view.last_used_at),
        "revokedAt": iso(view.revoked_at),
        "active": view.revoked_at is None,
    }
