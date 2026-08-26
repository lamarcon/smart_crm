"""Relational serializer and reconciler for one Smart CRM workspace."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Contact,
    CrmUser,
    CustomFieldDefinition,
    CustomFieldValue,
    Deal,
    DealAssistant,
    DealStageHistory,
    ExternalSourceField,
    Lead,
    LeadAssistant,
    ModuleFieldSetting,
    Notification,
    Quote,
    RecordVisibleCustomField,
    SavedFilter,
    Team,
    UserDashboardPreference,
    UserModulePreference,
)
from app.schemas import MODULES, WorkspaceState


ENTITY_MODELS = {
    "users": CrmUser,
    "leads": Lead,
    "contacts": Contact,
    "companies": Company,
    "deals": Deal,
    "notifications": Notification,
    "quotes": Quote,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _packed(record: dict[str, Any], position: int) -> dict[str, Any]:
    return {"position": position, "record": record}


def _unpack(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return int(payload.get("position", 0)), dict(payload.get("record") or {})


def _team_id(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:20]
    return f"team-{digest}"


class WorkspaceRepository:
    def __init__(self, session: Session, workspace_id: str = "default") -> None:
        self.session = session
        self.workspace_id = workspace_id

    def reconcile(self, state: WorkspaceState, *, fail_after: str | None = None) -> None:
        data = state.model_dump(by_alias=True, exclude_none=True)
        teams = self._reconcile_teams(data)
        self._reconcile_users(data["users"], teams)
        self.session.flush()
        self._reconcile_companies(data["companies"], teams)
        if fail_after == "companies":
            raise RuntimeError("forced repository failure")
        self.session.flush()
        self._reconcile_contacts(data["contacts"])
        self._reconcile_leads(data["leads"], teams)
        self._reconcile_deals(data["deals"], teams)
        self._reconcile_notifications(data["notifications"])
        definitions = self._reconcile_definitions(data.get("customFieldSchemas") or {})
        self.session.flush()
        self._reconcile_record_fields(data, definitions)
        self._reconcile_module_settings(data.get("moduleFieldSettings") or {})
        self._reconcile_preferences(data.get("ui") or {})
        if fail_after == "preferences":
            raise RuntimeError("forced repository failure")
        self.session.flush()

    def read_active(self) -> WorkspaceState:
        state: dict[str, Any] = {
            "users": self._read_payloads(CrmUser),
            "leads": self._read_payloads(Lead),
            "contacts": self._read_payloads(Contact),
            "companies": self._read_payloads(Company),
            "deals": self._read_payloads(Deal),
            "notifications": self._read_payloads(Notification),
            "customFieldSchemas": {module: [] for module in MODULES},
            "moduleFieldSettings": {module: {"hiddenStandardFields": [], "hiddenCustomFieldKeys": []} for module in MODULES},
            "ui": {"savedFilters": [], "viewModesByUser": {}, "dashboardScopeByUser": {}},
        }
        definitions = self.session.scalars(
            select(CustomFieldDefinition)
            .where(
                CustomFieldDefinition.workspace_id == self.workspace_id,
                CustomFieldDefinition.deleted_at.is_(None),
            )
            .order_by(CustomFieldDefinition.module, CustomFieldDefinition.position)
        ).all()
        for definition in definitions:
            item: dict[str, Any] = {
                "key": definition.key,
                "label": definition.label,
                "type": definition.field_type,
                "position": definition.position,
            }
            if definition.options:
                item["options"] = definition.options
            if definition.source != "custom":
                item["source"] = definition.source
            if definition.source_name is not None:
                item["sourceName"] = definition.source_name
            if definition.source_occurrence is not None:
                item["sourceOccurrence"] = definition.source_occurrence
            if definition.user_created:
                item["userCreated"] = True
            state["customFieldSchemas"].setdefault(definition.module, []).append(item)

        settings = self.session.scalars(
            select(ModuleFieldSetting).where(ModuleFieldSetting.workspace_id == self.workspace_id)
        ).all()
        for setting in settings:
            state["moduleFieldSettings"][setting.module] = {
                "hiddenStandardFields": setting.hidden_standard_fields,
                "hiddenCustomFieldKeys": setting.hidden_custom_field_keys,
            }

        filters = self.session.scalars(
            select(SavedFilter).where(
                SavedFilter.workspace_id == self.workspace_id,
                SavedFilter.deleted_at.is_(None),
            )
        ).all()
        packed_filters = sorted(
            ((int(item.filter.get("__position", 0)), item) for item in filters),
            key=lambda pair: pair[0],
        )
        for _position, item in packed_filters:
            state["ui"]["savedFilters"].append(
                {
                    "id": item.id,
                    "userId": item.user_id,
                    "scope": item.scope,
                    "name": item.name,
                    "filter": item.filter.get("value", {}),
                    "updatedAt": item.updated_at.isoformat().replace("+00:00", "Z"),
                }
            )
        module_preferences = self.session.scalars(
            select(UserModulePreference).where(UserModulePreference.workspace_id == self.workspace_id)
        ).all()
        for preference in module_preferences:
            state["ui"]["viewModesByUser"].setdefault(preference.user_id, {})[
                preference.module
            ] = preference.view_mode
        dashboard_preferences = self.session.scalars(
            select(UserDashboardPreference).where(UserDashboardPreference.workspace_id == self.workspace_id)
        ).all()
        for preference in dashboard_preferences:
            state["ui"]["dashboardScopeByUser"][preference.user_id] = preference.scope
        return WorkspaceState.model_validate(state)

    def list_deleted(self, module: str) -> list[dict[str, Any]]:
        model = ENTITY_MODELS[module]
        rows = self.session.scalars(
            select(model).where(
                model.workspace_id == self.workspace_id,
                model.deleted_at.is_not(None),
            )
        ).all()
        return [_unpack(row.payload)[1] for row in rows]

    def restore_record(self, module: str, record_id: str) -> bool:
        model = ENTITY_MODELS[module]
        row = self.session.get(model, record_id)
        if row is None or row.deleted_at is None:
            return False
        row.deleted_at = None
        return True

    def _read_payloads(self, model) -> list[dict[str, Any]]:  # noqa: ANN001
        rows = self.session.scalars(
            select(model).where(
                model.workspace_id == self.workspace_id,
                model.deleted_at.is_(None),
            )
        ).all()
        unpacked = sorted((_unpack(row.payload) for row in rows), key=lambda pair: pair[0])
        return [record for _position, record in unpacked]

    def _soft_delete_absent(self, model, present: set[str], extra=()) -> None:  # noqa: ANN001
        criteria = [model.deleted_at.is_(None), *extra]
        if hasattr(model, "workspace_id"):
            criteria.insert(0, model.workspace_id == self.workspace_id)
        rows = self.session.scalars(select(model).where(*criteria)).all()
        now = _now()
        for row in rows:
            if row.id not in present:
                row.deleted_at = now


    def _reconcile_teams(self, data: dict[str, Any]) -> dict[str, str]:
        names = {
            str(record.get("team"))
            for collection in ("users", "leads", "deals")
            for record in data[collection]
            if record.get("team")
        }
        result: dict[str, str] = {}
        for name in sorted(names):
            team_id = _team_id(name)
            team = self.session.get(Team, team_id)
            if team is None:
                team = Team(id=team_id, workspace_id=self.workspace_id, name=name)
                self.session.add(team)
            else:
                team.name = name
            result[name] = team_id
        return result

    def _reconcile_users(self, records: list[dict[str, Any]], teams: dict[str, str]) -> None:
        present = {record["id"] for record in records}
        self._soft_delete_absent(CrmUser, present)
        for position, record in enumerate(records):
            row = self.session.get(CrmUser, record["id"])
            values = dict(
                workspace_id=self.workspace_id,
                team_id=teams.get(record.get("team")),
                name=record.get("name", ""),
                email=record.get("email", f"{record['id']}@smartcrm.local"),
                job_title=record.get("jobTitle", ""),
                role=record.get("role", "Vendedor"),
                status=record.get("status", "Ativo"),
                invited_at=_date(record.get("invitedAt")),
                payload=_packed(record, position),
                deleted_at=None,
            )
            if row is None:
                self.session.add(CrmUser(id=record["id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    def _reconcile_companies(self, records: list[dict[str, Any]], teams: dict[str, str]) -> None:
        del teams
        present = {record["id"] for record in records}
        self._soft_delete_absent(Company, present)
        for position, record in enumerate(records):
            row = self.session.get(Company, record["id"])
            values = dict(
                workspace_id=self.workspace_id,
                owner_id=record.get("ownerId"),
                name=record.get("name", ""),
                city=record.get("city", ""),
                segment=record.get("segment", ""),
                phone=record.get("phone", ""),
                bitrix_id=record.get("bitrixId"),
                payload=_packed(record, position),
                deleted_at=None,
            )
            if row is None:
                self.session.add(Company(id=record["id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    def _reconcile_contacts(self, records: list[dict[str, Any]]) -> None:
        company_names = self._unique_name_ids(Company)
        present = {record["id"] for record in records}
        self._soft_delete_absent(Contact, present)
        for position, record in enumerate(records):
            row = self.session.get(Contact, record["id"])
            company_text = record.get("company", "")
            values = dict(
                workspace_id=self.workspace_id,
                company_id=record.get("companyId") or company_names.get(company_text),
                name=record.get("name", ""),
                company_text=company_text,
                email=record.get("email", ""),
                phone=record.get("phone", ""),
                role=record.get("role", ""),
                bitrix_id=record.get("bitrixId"),
                payload=_packed(record, position),
                deleted_at=None,
            )
            if row is None:
                self.session.add(Contact(id=record["id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    def _reconcile_leads(self, records: list[dict[str, Any]], teams: dict[str, str]) -> None:
        present = {record["id"] for record in records}
        self._soft_delete_absent(Lead, present)
        for position, record in enumerate(records):
            row = self.session.get(Lead, record["id"])
            values = dict(
                workspace_id=self.workspace_id,
                responsible_id=record.get("responsibleId"),
                team_id=teams.get(record.get("team")),
                name=record.get("name", ""),
                company=record.get("company", ""),
                email=record.get("email", ""),
                phone=record.get("phone", ""),
                segment=record.get("segment", ""),
                source=record.get("source", ""),
                stage=record.get("stage", ""),
                discard_reason=record.get("discardReason"),
                bitrix_id=record.get("bitrixId"),
                payload=_packed(record, position),
                deleted_at=None,
            )
            if row is None:
                self.session.add(Lead(id=record["id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            self.session.execute(delete(LeadAssistant).where(LeadAssistant.lead_id == record["id"]))
            for assistant_position, user_id in enumerate(record.get("assistants") or []):
                self.session.add(LeadAssistant(lead_id=record["id"], user_id=user_id, position=assistant_position))

    def _reconcile_deals(self, records: list[dict[str, Any]], teams: dict[str, str]) -> None:
        company_names = self._unique_name_ids(Company)
        contact_names = self._unique_name_ids(Contact)
        present = {record["id"] for record in records}
        self._soft_delete_absent(Deal, present)
        for position, record in enumerate(records):
            row = self.session.get(Deal, record["id"])
            company_text = record.get("company", "")
            contact_text = record.get("contact", "")
            values = dict(
                workspace_id=self.workspace_id,
                company_id=record.get("companyId") or company_names.get(company_text),
                contact_id=record.get("contactId") or contact_names.get(contact_text),
                responsible_id=record.get("responsibleId"),
                team_id=teams.get(record.get("team")),
                title=record.get("title", ""),
                company_text=company_text,
                contact_text=contact_text,
                amount=Decimal(str(record.get("amount", 0))),
                stage=record.get("stage", ""),
                stage_changed_at=_date(record.get("stageChangedAt")),
                stage_changed_by_id=record.get("stageChangedById"),
                won_at=_date(record.get("wonAt")),
                bitrix_id=record.get("bitrixId"),
                payload=_packed(record, position),
                deleted_at=None,
            )
            if row is None:
                self.session.add(Deal(id=record["id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            self.session.flush()
            self.session.execute(delete(DealAssistant).where(DealAssistant.deal_id == record["id"]))
            for assistant_position, user_id in enumerate(record.get("assistants") or []):
                self.session.add(DealAssistant(deal_id=record["id"], user_id=user_id, position=assistant_position))
            self.session.execute(delete(DealStageHistory).where(DealStageHistory.deal_id == record["id"]))
            for history_position, history in enumerate(record.get("stageHistory") or []):
                self.session.add(DealStageHistory(deal_id=record["id"], position=history_position, from_stage=history.get("from"), to_stage=history.get("to", ""), changed_at=_date(history.get("at")) or _now(), changed_by_id=history.get("byId")))
            self._reconcile_quotes(record["id"], record.get("quotes") or [])

    def _reconcile_quotes(self, deal_id: str, records: list[dict[str, Any]]) -> None:
        present = {record["id"] for record in records}
        self._soft_delete_absent(Quote, present, (Quote.deal_id == deal_id,))
        for position, record in enumerate(records):
            row = self.session.get(Quote, record["id"])
            values = dict(deal_id=deal_id, position=position, description=record.get("description", ""), quantity=Decimal(str(record.get("quantity", 1))), unit_price=Decimal(str(record.get("unitPrice", 0))), discount=Decimal(str(record.get("discount", 0))), total=Decimal(str(record.get("total", 0))), valid_until=_date(record.get("validUntil")), state=record.get("state", "Rascunho"), pdf_name=record.get("pdf"), payload=_packed(record, position), deleted_at=None)
            if row is None:
                self.session.add(Quote(id=record["id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    def _reconcile_notifications(self, records: list[dict[str, Any]]) -> None:
        present = {record["id"] for record in records}
        self._soft_delete_absent(Notification, present)
        for position, record in enumerate(records):
            row = self.session.get(Notification, record["id"])
            values = dict(workspace_id=self.workspace_id, user_id=record.get("userId"), text=record.get("text", ""), detail=record.get("detail", ""), displayed_time=record.get("time", ""), is_read=bool(record.get("read", False)), payload=_packed(record, position), deleted_at=None)
            if row is None:
                self.session.add(Notification(id=record["id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    def _reconcile_definitions(self, schemas: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str], CustomFieldDefinition]:
        result: dict[tuple[str, str], CustomFieldDefinition] = {}
        active = self.session.scalars(select(CustomFieldDefinition).where(CustomFieldDefinition.workspace_id == self.workspace_id, CustomFieldDefinition.deleted_at.is_(None))).all()
        present = {(module, item["key"]) for module in MODULES for item in (schemas.get(module) or [])}
        for row in active:
            if (row.module, row.key) not in present:
                row.deleted_at = _now()
        for module in MODULES:
            for position, item in enumerate(schemas.get(module) or []):
                row = self.session.scalar(select(CustomFieldDefinition).where(CustomFieldDefinition.workspace_id == self.workspace_id, CustomFieldDefinition.module == module, CustomFieldDefinition.key == item["key"]))
                values = dict(label=item.get("label", item["key"]), field_type=item.get("type", "text"), options=item.get("options") or [], source=item.get("source", "custom"), source_name=item.get("sourceName"), source_occurrence=item.get("sourceOccurrence"), position=item.get("position", position), user_created=bool(item.get("userCreated", False)), deleted_at=None)
                if row is None:
                    row = CustomFieldDefinition(workspace_id=self.workspace_id, module=module, key=item["key"], **values)
                    self.session.add(row)
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
                result[(module, item["key"])] = row
        return result

    def _reconcile_record_fields(self, data: dict[str, Any], definitions: dict[tuple[str, str], CustomFieldDefinition]) -> None:
        for module in MODULES:
            for record in data[module]:
                filters = (CustomFieldValue.workspace_id == self.workspace_id, CustomFieldValue.module == module, CustomFieldValue.record_id == record["id"])
                self.session.execute(delete(CustomFieldValue).where(*filters))
                self.session.execute(delete(RecordVisibleCustomField).where(RecordVisibleCustomField.workspace_id == self.workspace_id, RecordVisibleCustomField.module == module, RecordVisibleCustomField.record_id == record["id"]))
                self.session.execute(delete(ExternalSourceField).where(ExternalSourceField.workspace_id == self.workspace_id, ExternalSourceField.module == module, ExternalSourceField.record_id == record["id"]))
                for position, item in enumerate(record.get("customFields") or []):
                    definition = definitions[(module, item["key"])]
                    self.session.add(CustomFieldValue(workspace_id=self.workspace_id, definition_id=definition.id, module=module, record_id=record["id"], field_key=item["key"], value=item.get("value"), position=position))
                for position, key in enumerate(record.get("visibleCustomFieldKeys") or []):
                    self.session.add(RecordVisibleCustomField(workspace_id=self.workspace_id, module=module, record_id=record["id"], field_key=key, position=position))
                for position, item in enumerate(record.get("bitrixFields") or []):
                    self.session.add(ExternalSourceField(workspace_id=self.workspace_id, module=module, record_id=record["id"], source="bitrix", name=item.get("name", ""), occurrence=item.get("occurrence", 1), position=item.get("position", position), value=item.get("value")))

    def _reconcile_module_settings(self, settings: dict[str, dict[str, Any]]) -> None:
        self.session.execute(delete(ModuleFieldSetting).where(ModuleFieldSetting.workspace_id == self.workspace_id))
        for module in MODULES:
            item = settings.get(module) or {}
            self.session.add(ModuleFieldSetting(workspace_id=self.workspace_id, module=module, hidden_standard_fields=item.get("hiddenStandardFields") or [], hidden_custom_field_keys=item.get("hiddenCustomFieldKeys") or []))

    def _reconcile_preferences(self, ui: dict[str, Any]) -> None:
        records = ui.get("savedFilters") or []
        present = {record["id"] for record in records}
        self._soft_delete_absent(SavedFilter, present)
        for position, record in enumerate(records):
            row = self.session.get(SavedFilter, record["id"])
            values = dict(workspace_id=self.workspace_id, user_id=record["userId"], scope=record["scope"], name=record["name"], filter={"value": record.get("filter") or {}, "__position": position}, updated_at=_date(record.get("updatedAt")) or _now(), deleted_at=None)
            if row is None:
                self.session.add(SavedFilter(id=record["id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        self.session.execute(delete(UserModulePreference).where(UserModulePreference.workspace_id == self.workspace_id))
        for user_id, modules in (ui.get("viewModesByUser") or {}).items():
            for module, view_mode in modules.items():
                self.session.add(UserModulePreference(workspace_id=self.workspace_id, user_id=user_id, module=module, view_mode=view_mode))
        self.session.execute(delete(UserDashboardPreference).where(UserDashboardPreference.workspace_id == self.workspace_id))
        for user_id, scope in (ui.get("dashboardScopeByUser") or {}).items():
            self.session.add(UserDashboardPreference(workspace_id=self.workspace_id, user_id=user_id, scope=scope))

    def _unique_name_ids(self, model) -> dict[str, str]:  # noqa: ANN001
        rows = self.session.scalars(select(model).where(model.workspace_id == self.workspace_id, model.deleted_at.is_(None))).all()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row.name, []).append(row.id)
        return {name: ids[0] for name, ids in grouped.items() if len(ids) == 1}
