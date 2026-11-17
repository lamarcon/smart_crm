"""CSV export of one CRM module, limited to what the user may see.

The state given here is already projected for the user (records outside their
read scope are gone, linked ones are name-only stubs), so the export can never
reveal more than the screen does.
"""

from __future__ import annotations

import csv
import io
from typing import Iterable

from app.i18n import translate
from app.schemas import WorkspaceState

# (record field, column title in Portuguese)
COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "leads": (
        ("id", "Identificador"), ("name", "Nome completo"), ("company", "Empresa"), ("email", "E-mail"),
        ("phone", "Telefone"), ("segment", "Segmento"), ("source", "Origem"), ("stage", "Etapa"),
        ("responsibleId", "Responsável"), ("assistants", "Assistentes"), ("team", "Equipe"),
        ("createdAt", "Data de criação"), ("updatedAt", "Data de atualização"),
    ),
    "contacts": (
        ("id", "Identificador"), ("name", "Nome completo"), ("company", "Empresa"), ("email", "E-mail"),
        ("phone", "Telefone"), ("role", "Cargo"), ("createdAt", "Data de criação"), ("updatedAt", "Data de atualização"),
    ),
    "companies": (
        ("id", "Identificador"), ("name", "Razão / nome da Empresa"), ("city", "Cidade / UF"), ("segment", "Segmento"),
        ("phone", "Telefone"), ("ownerId", "Responsável"), ("createdAt", "Data de criação"), ("updatedAt", "Data de atualização"),
    ),
    "deals": (
        ("id", "Identificador"), ("title", "Título do Negócio"), ("company", "Empresa"), ("contact", "Contato"),
        ("amount", "Valor"), ("currency", "Moeda"), ("stage", "Etapa"), ("responsibleId", "Responsável"),
        ("assistants", "Assistentes"), ("team", "Equipe"), ("createdAt", "Data de criação"), ("updatedAt", "Data de atualização"),
    ),
    "products": (
        ("id", "Identificador"), ("name", "Nome do produto"), ("sku", "Código / SKU"), ("category", "Categoria"),
        ("unit", "Unidade"), ("price", "Preço"), ("currency", "Moeda"), ("active", "Situação"), ("description", "Descrição"),
    ),
}
_USER_FIELDS = frozenset({"responsibleId", "ownerId"})
# Spreadsheets run cells that start with these as formulas.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_START) else value


def _cell(field: str, value: object, users: dict[str, str], locale: str) -> str:
    if value is None:
        return ""
    if field in _USER_FIELDS:
        return users.get(str(value), str(value))
    if field == "assistants" and isinstance(value, list):
        return ", ".join(users.get(str(item), str(item)) for item in value)
    if field == "active":
        return translate("Ativo" if value else "Inativo", locale)
    if isinstance(value, bool):
        return translate("Sim" if value else "Não", locale)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}: {item}" for key, item in value.items())
    return str(value)


def export_csv(state: WorkspaceState, module: str, ids: Iterable[str] | None, locale: str) -> tuple[bytes, int]:
    """Returns the CSV (UTF-8 with BOM, ``;``-separated) and how many rows it has."""

    data = state.model_dump(by_alias=True, exclude_none=True)
    users = {str(user.get("id")): str(user.get("name") or user.get("id")) for user in data.get("users") or []}
    wanted = None if ids is None else {str(item) for item in ids}
    records = [
        record
        for record in data.get(module) or []
        if not record.get("restricted") and (wanted is None or str(record.get("id")) in wanted)
    ]
    custom = [
        (field.get("key"), field.get("label") or field.get("key"))
        for field in (data.get("customFieldSchemas") or {}).get(module) or []
        if field.get("key")
    ]
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [translate(title, locale) for _field, title in COLUMNS[module]] + [str(label) for _key, label in custom]
    )
    for record in records:
        values = record.get("customFields") or {}
        writer.writerow(
            [_safe(_cell(field, record.get(field), users, locale)) for field, _title in COLUMNS[module]]
            + [_safe(_cell(key, values.get(key), users, locale)) for key, _label in custom]
        )
    return ("﻿" + output.getvalue()).encode("utf-8"), len(records)
