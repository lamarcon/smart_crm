"""Transactional and versioned workspace operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Workspace
from app.policies import (
    ADMIN_ROLE,
    MODULES as PERMISSION_MODULES,
    Action,
    PrincipalScope,
    RecordScope,
    allowed,
    can_perform_action,
    record_allowed,
)
from app.repositories.workspace import WorkspaceRepository, _date as parse_timestamp, team_id_for_name
from app.repositories.activity import ActivityRepository
from app.repositories.pipeline import DealPipelineAggregate, DealPipelineRepository
from app.schemas import PersistedCounts, WorkspaceState, count_state, validate_references
from app.services.crm_integrity import enforce_crm_integrity, propagate_renames
from app.services.exchange_rates import BASE_CURRENCY, BRASILIA, ExchangeRateService
from app.services.activity import (
    collect_company_changes,
    collect_deal_transitions,
    movement_events_for_transitions,
)
from app.services.deal_automation import DealAutomationExecutor
from app.services.deal_amounts import ItemPriceNotAllowed, enforce_item_prices, normalize_deal_amounts


class WorkspaceServiceError(RuntimeError):
    pass


class WorkspaceNotInitialized(WorkspaceServiceError):
    pass


class WorkspaceAlreadyInitialized(WorkspaceServiceError):
    def __init__(self, current_version: int) -> None:
        super().__init__("Workspace já inicializado")
        self.current_version = current_version


class WorkspaceConflict(WorkspaceServiceError):
    def __init__(self, current_version: int) -> None:
        super().__init__("Versão do workspace desatualizada")
        self.current_version = current_version


class WorkspaceRecordNotFound(WorkspaceServiceError):
    pass


class WorkspaceRestoreConflict(WorkspaceServiceError):
    pass


class WorkspaceAuthorizationError(WorkspaceServiceError):
    pass


class WorkspaceStageConflict(WorkspaceServiceError):
    def __init__(self, current_version: int) -> None:
        super().__init__("Configuração de etapas foi alterada")
        self.current_version = current_version


@dataclass(frozen=True)
class WorkspaceLoad:
    initialized: bool
    version: int
    state: WorkspaceState | None


@dataclass(frozen=True)
class WorkspaceResult:
    version: int
    state: WorkspaceState
    counts: PersistedCounts


def _require_action(principal: PrincipalScope, action: Action) -> None:
    if not can_perform_action(principal, action):
        raise WorkspaceAuthorizationError("principal is not authorized")


def _record_scope(record: dict) -> RecordScope:
    team_value = record.get("team")
    team_id = record.get("teamId")
    if not team_id and isinstance(team_value, str) and team_value:
        team_id = team_id_for_name(team_value)
    return RecordScope(
        responsible_id=record.get("responsibleId"),
        assistant_ids=tuple(record.get("assistants") or ()),
        team_id=team_id,
    )


def _project_ui(ui: dict, user_id: str) -> dict:
    filters = [
        deepcopy(item)
        for item in ui.get("savedFilters") or []
        if item.get("userId") == user_id
    ]
    view_modes = ui.get("viewModesByUser") or {}
    dashboard_scopes = ui.get("dashboardScopeByUser") or {}
    return {
        "savedFilters": filters,
        "viewModesByUser": (
            {user_id: deepcopy(view_modes[user_id])} if user_id in view_modes else {}
        ),
        "dashboardScopeByUser": (
            {user_id: dashboard_scopes[user_id]}
            if user_id in dashboard_scopes
            else {}
        ),
    }


# Fields that point from one record to another module's record.
_REFERENCE_FIELDS = (("companyId", "companies"), ("contactId", "contacts"))


def _user_teams(users: list[dict]) -> dict[str, str | None]:
    teams: dict[str, str | None] = {}
    for user in users:
        team_id = user.get("teamId")
        team_name = user.get("team")
        if not team_id and isinstance(team_name, str) and team_name:
            team_id = team_id_for_name(team_name)
        teams[str(user.get("id"))] = team_id
    return teams


def _module_scope(module: str, record: dict, user_teams: dict[str, str | None]) -> RecordScope:
    """Who owns a record, for the scopes "own" and "team"."""

    if module in ("leads", "deals"):
        return _record_scope(record)
    if module == "companies":
        owner = record.get("ownerId")
        return RecordScope(
            responsible_id=owner,
            assistant_ids=(),
            team_id=user_teams.get(str(owner)) if owner else None,
        )
    # Contacts and products have no owner: only "none" or "all" apply.
    return RecordScope(responsible_id=None, assistant_ids=(), team_id=None)


def _restricted_stub(record: dict) -> dict:
    """What a user sees of a linked record outside their permissions: its name only."""

    return {"id": record.get("id"), "name": record.get("name") or record.get("title") or "", "restricted": True}


def _references(data: dict) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {"companies": set(), "contacts": set(), "products": set()}
    for module in ("leads", "contacts", "deals"):
        for record in data[module]:
            for field, target in _REFERENCE_FIELDS:
                if record.get(field):
                    found[target].add(str(record[field]))
            for quote in record.get("quotes") or []:
                if quote.get("productId"):
                    found["products"].add(str(quote["productId"]))
    return found


def project_workspace_state(
    canonical: WorkspaceState,
    principal: PrincipalScope,
) -> WorkspaceState:
    _require_action(principal, Action.READ)
    data = deepcopy(canonical.model_dump(by_alias=True, exclude_none=True))
    data.pop("currentUserId", None)
    if principal.role == ADMIN_ROLE:
        return WorkspaceState.model_validate(data)

    teams = _user_teams(data.get("users") or [])
    hidden: dict[str, list[dict]] = {}
    for module in PERMISSION_MODULES:
        records = data.get(module) or []
        data[module] = [
            record
            for record in records
            if record_allowed(principal, module, "read", _module_scope(module, record, teams))
        ]
        visible_ids = {record.get("id") for record in data[module]}
        hidden[module] = [record for record in records if record.get("id") not in visible_ids]
    # Linked records outside the permissions keep only their name, so screens can show it.
    for module, ids in _references(data).items():
        data[module].extend(_restricted_stub(record) for record in hidden[module] if record.get("id") in ids)
    data["notifications"] = [
        item
        for item in data["notifications"]
        if item.get("userId") == principal.user_id
    ]
    data["ui"] = _project_ui(data.get("ui") or {}, principal.user_id)
    return WorkspaceState.model_validate(data)


def _merge_module(
    module: str,
    canonical: list[dict],
    submitted: list[dict],
    principal: PrincipalScope,
    teams: dict[str, str | None],
) -> list[dict]:
    """Applies one module of a submitted snapshot, checking each create, change and delete."""

    def scope(record: dict) -> RecordScope:
        return _module_scope(module, record, teams)

    def require(condition: bool) -> None:
        if not condition:
            raise WorkspaceAuthorizationError(f"{module}: record is outside principal scope")

    canonical_by_id = {record.get("id"): record for record in canonical}
    readable = {
        record_id
        for record_id, record in canonical_by_id.items()
        if record_allowed(principal, module, "read", scope(record))
    }
    result: list[dict] = []
    seen: set[object] = set()
    for record in submitted:
        record_id = record.get("id")
        seen.add(record_id)
        before = canonical_by_id.get(record_id)
        if record.get("restricted") is True:
            # A name-only stub: whatever comes back, the stored record is kept as it is.
            require(before is not None and record_id not in readable)
            continue
        if before is None:
            require(allowed(principal, module, "create"))
            require(record_allowed(principal, module, "read", scope(record)))
            if record.get("bitrixId"):
                require(allowed(principal, module, "import"))
            result.append(deepcopy(record))
            continue
        require(record_id in readable)
        if record != before:
            require(record_allowed(principal, module, "update", scope(before)))
            require(record_allowed(principal, module, "update", scope(record)))
        result.append(deepcopy(record))
    for record_id in readable - seen:
        require(record_allowed(principal, module, "delete", scope(canonical_by_id[record_id])))
    # Records the user cannot see are kept as they are.
    invisible = [deepcopy(record) for record_id, record in canonical_by_id.items() if record_id not in readable]
    return [*result, *invisible]


def _merge_notifications(
    canonical: list[dict],
    submitted: list[dict],
    principal: PrincipalScope,
) -> list[dict]:
    if any(item.get("userId") != principal.user_id for item in submitted):
        raise WorkspaceAuthorizationError("notification is outside principal scope")
    invisible = [
        deepcopy(item)
        for item in canonical
        if item.get("userId") != principal.user_id
    ]
    return [*deepcopy(submitted), *invisible]


def _merge_ui(canonical: dict, submitted: dict, principal: PrincipalScope) -> dict:
    user_id = principal.user_id
    submitted_filters = submitted.get("savedFilters") or []
    submitted_modes = submitted.get("viewModesByUser") or {}
    submitted_scopes = submitted.get("dashboardScopeByUser") or {}
    if (
        any(item.get("userId") != user_id for item in submitted_filters)
        or any(key != user_id for key in submitted_modes)
        or any(key != user_id for key in submitted_scopes)
    ):
        raise WorkspaceAuthorizationError("preference is outside principal scope")

    merged = deepcopy(canonical)
    merged["savedFilters"] = [
        deepcopy(item)
        for item in canonical.get("savedFilters") or []
        if item.get("userId") != user_id
    ] + deepcopy(submitted_filters)
    modes = deepcopy(canonical.get("viewModesByUser") or {})
    modes.pop(user_id, None)
    modes.update(deepcopy(submitted_modes))
    merged["viewModesByUser"] = modes
    scopes = deepcopy(canonical.get("dashboardScopeByUser") or {})
    scopes.pop(user_id, None)
    scopes.update(deepcopy(submitted_scopes))
    merged["dashboardScopeByUser"] = scopes
    return merged


def merge_authorized_state(
    canonical: WorkspaceState,
    submitted: WorkspaceState,
    principal: PrincipalScope,
) -> WorkspaceState:
    _require_action(principal, Action.UPDATE)
    canonical_data = canonical.model_dump(by_alias=True, exclude_none=True)
    submitted_data = submitted.model_dump(by_alias=True, exclude_none=True)
    if principal.role == ADMIN_ROLE:
        merged_data = deepcopy(submitted_data)
        if "teams" not in merged_data and "teams" in canonical_data:
            merged_data["teams"] = deepcopy(canonical_data["teams"])
    else:
        projected_data = project_workspace_state(canonical, principal).model_dump(
            by_alias=True,
            exclude_none=True,
        )
        for key in ("users", "customFieldSchemas", "moduleFieldSettings"):
            if submitted_data.get(key) != projected_data.get(key):
                raise WorkspaceAuthorizationError("administrative snapshot change")

        merged_data = deepcopy(canonical_data)
        teams = _user_teams(canonical_data.get("users") or [])
        for module in PERMISSION_MODULES:
            merged_data[module] = _merge_module(
                module,
                canonical_data.get(module) or [],
                submitted_data.get(module) or [],
                principal,
                teams,
            )
        merged_data["notifications"] = _merge_notifications(
            canonical_data["notifications"],
            submitted_data["notifications"],
            principal,
        )
        merged_data["ui"] = _merge_ui(
            canonical_data.get("ui") or {},
            submitted_data.get("ui") or {},
            principal,
        )

    merged_data.pop("currentUserId", None)
    merged = WorkspaceState.model_validate(merged_data)
    validate_references(merged)
    return merged


def _preserve_server_stage_metadata(
    canonical: WorkspaceState,
    submitted: WorkspaceState,
) -> WorkspaceState:
    canonical_deals = {
        str(record.get("id")): record for record in canonical.deals
    }
    data = submitted.model_dump(by_alias=True, exclude_none=True)
    protected_fields = (
        "stageHistory",
        "stageChangedAt",
        "stageChangedById",
        "wonAt",
        # The frozen exchange rate is decided by the server, never by the client.
        "fxRate",
        "fxRateDate",
    )
    for record in data["deals"]:
        existing = canonical_deals.get(str(record.get("id")))
        for field in protected_fields:
            if existing is not None and field in existing:
                record[field] = deepcopy(existing[field])
            else:
                record.pop(field, None)
    # Lead tracking (channel, UTMs, external id) is recorded by the lead intake API
    # only; a workspace save can neither forge nor erase it.
    canonical_leads = {str(record.get("id")): record for record in canonical.leads}
    for record in data["leads"]:
        existing = canonical_leads.get(str(record.get("id")))
        if existing is not None and "tracking" in existing:
            record["tracking"] = deepcopy(existing["tracking"])
        else:
            record.pop("tracking", None)
    return WorkspaceState.model_validate(data)


_UNTRUSTED_ACTIVITY_KEYS = frozenset(
    {
        "activity",
        "activities",
        "activityHistory",
        "history",
        "actor",
        "actorId",
        "actorName",
        "occurredAt",
        "timestamp",
        "tenantId",
        "workspaceId",
        "eventType",
        "details",
        "dedupeKey",
    }
)


def _strip_untrusted_activity_metadata(state: WorkspaceState) -> WorkspaceState:
    data = state.model_dump(by_alias=True, exclude_none=True)
    for module in ("companies", "deals"):
        for record in data[module]:
            for key in _UNTRUSTED_ACTIVITY_KEYS:
                record.pop(key, None)
    return WorkspaceState.model_validate(data)


def _state_with_principal_identity(
    state: WorkspaceState,
    principal: PrincipalScope,
) -> WorkspaceState:
    data = state.model_dump(by_alias=True, exclude_none=True)
    data.pop("currentUserId", None)
    result = WorkspaceState.model_validate(data)
    validate_references(result)
    return result


class WorkspaceService:
    def __init__(
        self,
        repository_factory: Callable[[Session, str], WorkspaceRepository] = WorkspaceRepository,
        pipeline_repository_factory: Callable[
            [Session, str], DealPipelineRepository
        ] = DealPipelineRepository,
        clock: Callable[[], datetime] | None = None,
        activity_repository_factory: Callable[
            [Session, str], ActivityRepository
        ] = ActivityRepository,
        automation_executor: DealAutomationExecutor | None = None,
        exchange_rates: ExchangeRateService | None = None,
    ) -> None:
        self.repository_factory = repository_factory
        self.pipeline_repository_factory = pipeline_repository_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.activity_repository_factory = activity_repository_factory
        self.automation_executor = automation_executor or DealAutomationExecutor(
            clock=self.clock
        )
        self.exchange_rates = exchange_rates

    def _apply_exchange_rate(self, record: dict, existing: dict | None, won: bool) -> None:
        """Freeze a foreign-currency deal's PTAX rate on the day it was won."""

        currency = str(record.get("currency") or BASE_CURRENCY).upper()
        record["currency"] = currency
        if not won or currency == BASE_CURRENCY:
            record.pop("fxRate", None)
            record.pop("fxRateDate", None)
            return
        same_currency = existing is not None and str(existing.get("currency") or BASE_CURRENCY).upper() == currency
        if same_currency and record.get("fxRate") and record.get("fxRateDate"):
            return
        record.pop("fxRate", None)
        record.pop("fxRateDate", None)
        if self.exchange_rates is None:
            return
        won_at = parse_timestamp(record.get("wonAt")) or self.clock()
        if won_at.tzinfo is None:
            won_at = won_at.replace(tzinfo=timezone.utc)
        rate = self.exchange_rates.rate_on(currency, won_at.astimezone(BRASILIA).date())
        if rate is not None:
            record["fxRate"] = format(rate.rate.normalize(), "f")
            record["fxRateDate"] = rate.date.isoformat()

    def _repository(
        self,
        session: Session,
        principal: PrincipalScope,
    ) -> WorkspaceRepository:
        return self.repository_factory(session, principal.workspace_id)

    def _pipeline_repository(
        self,
        session: Session,
        principal: PrincipalScope,
    ) -> DealPipelineRepository:
        return self.pipeline_repository_factory(session, principal.workspace_id)

    def load(self, session: Session, principal: PrincipalScope) -> WorkspaceLoad:
        _require_action(principal, Action.READ)
        repository = self._repository(session, principal)
        workspace = self._workspace(session, principal)
        if workspace.initialized_at is None:
            return WorkspaceLoad(False, workspace.version, None)
        canonical = repository.read_active()
        return WorkspaceLoad(
            True,
            workspace.version,
            project_workspace_state(canonical, principal),
        )

    def bootstrap(
        self,
        session: Session,
        principal: PrincipalScope,
        state: WorkspaceState,
    ) -> WorkspaceResult:
        _require_action(principal, Action.IMPORT_DATA)
        state = _state_with_principal_identity(state, principal)
        repository = self._repository(session, principal)
        pipeline_repository = self._pipeline_repository(session, principal)
        pipeline_repository.lock_all()
        aggregate = pipeline_repository.list_pipelines()
        workspace = self._locked_workspace(session, principal)
        if workspace.initialized_at is not None:
            raise WorkspaceAlreadyInitialized(workspace.version)
        state = normalize_deal_amounts(state)
        state = self._canonicalize_deal_stages(
            state,
            None,
            aggregate,
            principal,
            workspace.version,
            allow_legacy_new=True,
        )
        repository.reconcile(state)
        workspace.version = 1
        workspace.initialized_at = datetime.now(timezone.utc)
        session.flush()
        return self._result(repository, principal, workspace.version)

    def save(
        self,
        session: Session,
        principal: PrincipalScope,
        expected_version: int,
        state: WorkspaceState,
    ) -> WorkspaceResult:
        _require_action(principal, Action.UPDATE)
        repository = self._repository(session, principal)
        pipeline_repository = self._pipeline_repository(session, principal)
        pipeline_repository.lock_all()
        aggregate = pipeline_repository.list_pipelines()
        workspace = self._locked_initialized(session, principal)
        self._check_version(workspace, expected_version)
        canonical = repository.read_active()
        state = _preserve_server_stage_metadata(canonical, state)
        state = _strip_untrusted_activity_metadata(state)
        merged = merge_authorized_state(canonical, state, principal)
        merged = propagate_renames(canonical, merged)
        merged = normalize_deal_amounts(merged)
        try:
            enforce_item_prices(canonical, merged, principal)
        except ItemPriceNotAllowed as error:
            raise WorkspaceAuthorizationError(f"item price: {error}") from None
        enforce_crm_integrity(canonical, merged, principal)
        occurred_at = self.clock()
        merged = self._canonicalize_deal_stages(
            merged,
            canonical,
            aggregate,
            principal,
            workspace.version,
            occurred_at=occurred_at,
        )
        operation_key = f"workspace:{principal.workspace_id}:{workspace.version + 1}"
        transitions = collect_deal_transitions(
            canonical,
            merged,
            tuple(stage for pipeline in aggregate for stage in pipeline.stages),
            principal,
            occurred_at=occurred_at,
        )
        movement_events = movement_events_for_transitions(
            transitions,
            canonical,
            principal,
            operation_key,
        )
        company_events = collect_company_changes(
            canonical,
            merged,
            principal,
            operation_key,
            occurred_at=occurred_at,
        )
        repository.reconcile(merged)
        activity_repository = self.activity_repository_factory(
            session, principal.workspace_id
        )
        activity_repository.append_many((*movement_events, *company_events))
        for transition in transitions:
            self.automation_executor.execute_for_transition(
                session,
                principal,
                transition,
                operation_key,
            )
        workspace.version += 1
        session.flush()
        return self._result(repository, principal, workspace.version)

    def reset(
        self,
        session: Session,
        principal: PrincipalScope,
        expected_version: int,
        state: WorkspaceState,
    ) -> WorkspaceResult:
        _require_action(principal, Action.RESET_WORKSPACE)
        state = _state_with_principal_identity(state, principal)
        repository = self._repository(session, principal)
        pipeline_repository = self._pipeline_repository(session, principal)
        pipeline_repository.lock_all()
        aggregate = pipeline_repository.list_pipelines()
        workspace = self._locked_initialized(session, principal)
        self._check_version(workspace, expected_version)
        canonical = repository.read_active()
        state = normalize_deal_amounts(state)
        state = self._canonicalize_deal_stages(
            state,
            canonical,
            aggregate,
            principal,
            workspace.version,
            allow_legacy_new=True,
        )
        repository.reconcile(state)
        workspace.version += 1
        session.flush()
        return self._result(repository, principal, workspace.version)

    def list_deleted(
        self,
        session: Session,
        principal: PrincipalScope,
        module: str,
    ) -> list[dict]:
        _require_action(principal, Action.RESTORE_DELETED)
        repository = self._repository(session, principal)
        workspace = self._workspace(session, principal)
        if workspace.initialized_at is None:
            raise WorkspaceNotInitialized("Workspace não inicializado")
        return repository.list_deleted(module)

    def restore(
        self,
        session: Session,
        principal: PrincipalScope,
        expected_version: int,
        module: str,
        record_id: str,
    ) -> WorkspaceResult:
        _require_action(principal, Action.RESTORE_DELETED)
        repository = self._repository(session, principal)
        workspace = self._locked_initialized(session, principal)
        self._check_version(workspace, expected_version)
        self._check_restore_uniqueness(repository, module, record_id)
        if not repository.restore_record(module, record_id):
            raise WorkspaceRecordNotFound("Registro excluído não encontrado")
        workspace.version += 1
        session.flush()
        return self._result(repository, principal, workspace.version)

    @staticmethod
    def _result(
        repository: WorkspaceRepository,
        principal: PrincipalScope,
        version: int,
    ) -> WorkspaceResult:
        canonical = repository.read_active()
        projected = project_workspace_state(canonical, principal)
        return WorkspaceResult(
            version=version,
            state=projected,
            counts=count_state(projected),
        )

    def _canonicalize_deal_stages(
        self,
        submitted: WorkspaceState,
        canonical: WorkspaceState | None,
        aggregate: tuple[DealPipelineAggregate, ...] | DealPipelineAggregate,
        principal: PrincipalScope,
        workspace_version: int,
        *,
        allow_legacy_new: bool = False,
        occurred_at: datetime | None = None,
    ) -> WorkspaceState:
        data = submitted.model_dump(by_alias=True, exclude_none=True)
        canonical_deals = {
            str(record.get("id")): record
            for record in (canonical.deals if canonical is not None else [])
        }
        pipelines = (aggregate,) if isinstance(aggregate, DealPipelineAggregate) else tuple(aggregate)
        pipelines_by_id = {item.pipeline.id: item.pipeline for item in pipelines}
        default_pipeline = next(
            (item.pipeline for item in pipelines if item.pipeline.is_default), pipelines[0].pipeline
        )
        active_by_id = {stage.id: stage for item in pipelines for stage in item.stages}
        names_by_pipeline = {
            item.pipeline.id: {stage.name: stage for stage in item.stages} for item in pipelines
        }

        def by_name(name: object, pipeline_id: UUID | None):  # noqa: ANN202
            """A stage name inside one pipeline (the main one when none is named)."""

            return names_by_pipeline.get(pipeline_id or default_pipeline.id, {}).get(str(name or ""))

        now = occurred_at or self.clock()
        now_text = now.isoformat().replace("+00:00", "Z")

        def parse_uuid(value: object) -> UUID:
            try:
                return UUID(str(value))
            except (TypeError, ValueError, AttributeError):
                raise WorkspaceStageConflict(workspace_version) from None

        def stage_for_reference(record: dict, existing: dict | None):  # noqa: ANN202
            pipeline_value = record.get("pipelineId")
            stage_value = record.get("stageId")
            if pipeline_value is None and stage_value is None and existing is not None:
                pipeline_value = existing.get("pipelineId")
                stage_value = existing.get("stageId")
            elif pipeline_value is None or stage_value is None:
                if allow_legacy_new and existing is None:
                    named = parse_uuid(pipeline_value) if pipeline_value is not None else None
                    legacy = by_name(record.get("stage"), named)
                    if legacy is not None:
                        return legacy
                raise WorkspaceStageConflict(workspace_version)
            pipeline_id = parse_uuid(pipeline_value)
            stage_id = parse_uuid(stage_value)
            stage = active_by_id.get(stage_id)
            # The stage must belong to the deal's pipeline, and that pipeline must be active.
            if pipeline_id not in pipelines_by_id or stage is None or stage.pipeline_id != pipeline_id:
                raise WorkspaceStageConflict(workspace_version)
            return stage

        def imported_history(items: list[dict], pipeline_id: UUID) -> list[dict]:
            result: list[dict] = []
            for item in items:
                target = None
                if item.get("toStageId") is not None:
                    target = active_by_id.get(parse_uuid(item["toStageId"]))
                if target is None:
                    target = by_name(item.get("to"), pipeline_id)
                if target is None:
                    raise WorkspaceStageConflict(workspace_version)
                source = None
                if item.get("fromStageId") is not None:
                    source = active_by_id.get(parse_uuid(item["fromStageId"]))
                if source is None and item.get("from"):
                    source = by_name(item["from"], pipeline_id)
                result.append(
                    {
                        "from": item.get("from"),
                        "to": item.get("to") or target.name,
                        "fromStageId": str(source.id) if source is not None else None,
                        "toStageId": str(target.id),
                        "at": item.get("at") or now_text,
                        "byId": item.get("byId") or principal.user_id,
                    }
                )
            return result

        for record in data["deals"]:
            existing = canonical_deals.get(str(record.get("id")))
            stage = stage_for_reference(record, existing)
            pipeline = pipelines_by_id[stage.pipeline_id]
            # A new deal starts at the initial stage of its own pipeline.
            if existing is None and not allow_legacy_new and stage.id != pipeline.default_stage_id:
                raise WorkspaceStageConflict(workspace_version)

            if existing is None:
                history = (
                    imported_history(list(record.get("stageHistory") or []), pipeline.id)
                    if allow_legacy_new
                    else []
                )
                if not allow_legacy_new:
                    record["stageChangedAt"] = record.get("stageChangedAt") or now_text
                    record["stageChangedById"] = principal.user_id
            else:
                history = deepcopy(existing.get("stageHistory") or [])
                existing_stage_id = parse_uuid(existing.get("stageId"))
                if existing_stage_id != stage.id:
                    previous = active_by_id.get(existing_stage_id)
                    if previous is None:
                        raise WorkspaceStageConflict(workspace_version)
                    history.append(
                        {
                            "from": previous.name,
                            "to": stage.name,
                            "fromStageId": str(previous.id),
                            "toStageId": str(stage.id),
                            "at": now_text,
                            "byId": principal.user_id,
                        }
                    )
                    record["stageChangedAt"] = now_text
                    record["stageChangedById"] = principal.user_id
                else:
                    if existing.get("stageChangedAt") is not None:
                        record["stageChangedAt"] = existing["stageChangedAt"]
                    else:
                        record.pop("stageChangedAt", None)
                    if existing.get("stageChangedById") is not None:
                        record["stageChangedById"] = existing["stageChangedById"]
                    else:
                        record.pop("stageChangedById", None)

            record.update(
                {
                    "pipelineId": str(pipeline.id),
                    "stageId": str(stage.id),
                    "stage": stage.name,
                    "stageHistory": history,
                }
            )
            if stage.semantic_type == "won":
                previous_won_at = existing.get("wonAt") if existing is not None else None
                record["wonAt"] = previous_won_at or now_text
            else:
                record.pop("wonAt", None)
            self._apply_exchange_rate(record, existing, stage.semantic_type == "won")
        return WorkspaceState.model_validate(data)

    @staticmethod
    def _workspace(session: Session, principal: PrincipalScope) -> Workspace:
        workspace = session.scalar(
            select(Workspace).where(Workspace.id == principal.workspace_id)
        )
        if workspace is None:
            raise WorkspaceNotInitialized("Schema do workspace não foi inicializado")
        return workspace

    @staticmethod
    def _locked_workspace(session: Session, principal: PrincipalScope) -> Workspace:
        workspace = session.scalar(
            select(Workspace)
            .where(Workspace.id == principal.workspace_id)
            .with_for_update()
        )
        if workspace is None:
            raise WorkspaceNotInitialized("Schema do workspace não foi inicializado")
        return workspace

    def _locked_initialized(
        self,
        session: Session,
        principal: PrincipalScope,
    ) -> Workspace:
        workspace = self._locked_workspace(session, principal)
        if workspace.initialized_at is None:
            raise WorkspaceNotInitialized("Workspace não inicializado")
        return workspace

    @staticmethod
    def _check_version(workspace: Workspace, expected_version: int) -> None:
        if workspace.version != expected_version:
            raise WorkspaceConflict(workspace.version)

    @staticmethod
    def _check_restore_uniqueness(
        repository: WorkspaceRepository, module: str, record_id: str
    ) -> None:
        if module != "users":
            return
        deleted = next(
            (item for item in repository.list_deleted(module) if item.get("id") == record_id),
            None,
        )
        if deleted is None:
            return
        email = str(deleted.get("email", "")).casefold()
        if email and any(
            str(item.get("email", "")).casefold() == email
            for item in repository.read_active().users
        ):
            raise WorkspaceRestoreConflict("E-mail já pertence a um usuário ativo")
