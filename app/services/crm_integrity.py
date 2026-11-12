"""Server-side guard for company/contact links and duplicates on workspace saves.

Contacts and deals may only name registered companies (and deals registered
contacts of that company). The screen already enforces these rules; this module
makes the API enforce them too, so a direct request cannot bypass them. Only
records that are new or whose
guarded fields changed are checked, so legacy data saved before these rules
keeps loading and saving untouched. Bitrix imports performed by a user allowed
to import data are exempt, as they carry free-text names from the export.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from app.policies import Action, PrincipalScope, can_perform_action
from app.schemas import WorkspaceReferenceError, WorkspaceState
from app.services.exchange_rates import SUPPORTED_CURRENCIES


def normalized_name(value: Any) -> str:
    """Same normalization as the screen: no accents, no case, collapsed spaces."""

    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.split()).lower()


def normalized_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise WorkspaceReferenceError(path, message)


def _changed(record: dict, previous: dict | None, fields: tuple[str, ...]) -> bool:
    return previous is None or any(record.get(field) != previous.get(field) for field in fields)


def _is_import(record: dict, previous: dict | None, principal: PrincipalScope) -> bool:
    return (
        bool(record.get("bitrixId"))
        and can_perform_action(principal, Action.IMPORT_DATA)
        and (previous is None or record.get("bitrixFields") != previous.get("bitrixFields"))
    )


def _contact_belongs_to(contact: dict, company: dict) -> bool:
    if contact.get("companyId"):
        return contact["companyId"] == company.get("id")
    return normalized_name(contact.get("company")) == normalized_name(company.get("name"))


def _by_id(records: list[dict]) -> dict[str, dict]:
    return {str(record.get("id")): record for record in records}


def _check_company_duplicates(companies: list[dict], previous: dict[str, dict], principal: PrincipalScope) -> None:
    owners: dict[str, list[dict]] = {}
    for company in companies:
        key = normalized_name(company.get("name"))
        if key:
            owners.setdefault(key, []).append(company)
    for index, company in enumerate(companies):
        old = previous.get(str(company.get("id")))
        key = normalized_name(company.get("name"))
        if not key or _is_import(company, old, principal):
            continue
        if old is not None and normalized_name(old.get("name")) == key:
            continue
        clash = next((other for other in owners[key] if other.get("id") != company.get("id")), None)
        _require(
            clash is None,
            f"companies[{index}].name",
            f"Já existe uma empresa cadastrada como {clash.get('name') if clash else ''}.",
        )


def _check_contact_duplicates(contacts: list[dict], previous: dict[str, dict], principal: PrincipalScope) -> None:
    owners: dict[str, list[dict]] = {}
    for contact in contacts:
        key = normalized_email(contact.get("email"))
        if key:
            owners.setdefault(key, []).append(contact)
    for index, contact in enumerate(contacts):
        old = previous.get(str(contact.get("id")))
        key = normalized_email(contact.get("email"))
        if not key or _is_import(contact, old, principal):
            continue
        if old is not None and normalized_email(old.get("email")) == key:
            continue
        clash = next((other for other in owners[key] if other.get("id") != contact.get("id")), None)
        _require(
            clash is None,
            f"contacts[{index}].email",
            f"Já existe um contato com o e-mail {key} ({clash.get('name') if clash else ''}).",
        )


def _check_deal_currencies(deals: list[dict]) -> None:
    for index, deal in enumerate(deals):
        currency = deal.get("currency")
        _require(
            currency in (None, "") or str(currency).upper() in SUPPORTED_CURRENCIES,
            f"deals[{index}].currency",
            "Moeda não suportada. Use BRL, USD ou EUR.",
        )


def _check_contact_links(
    contacts: list[dict],
    previous: dict[str, dict],
    companies: dict[str, dict],
    principal: PrincipalScope,
) -> None:
    for index, contact in enumerate(contacts):
        old = previous.get(str(contact.get("id")))
        if _is_import(contact, old, principal) or not _changed(contact, old, ("company", "companyId")):
            continue
        company = companies.get(str(contact.get("companyId") or ""))
        if not str(contact.get("company") or "").strip() and not contact.get("companyId"):
            continue
        _require(company is not None, f"contacts[{index}].companyId", "Selecione uma empresa cadastrada na lista.")
        _require(
            normalized_name(contact.get("company")) == normalized_name(company.get("name")),
            f"contacts[{index}].company",
            "A empresa do Contato não confere com o cadastro.",
        )


def _check_deal_links(
    deals: list[dict],
    previous: dict[str, dict],
    companies: dict[str, dict],
    contacts: dict[str, dict],
    principal: PrincipalScope,
) -> None:
    for index, deal in enumerate(deals):
        old = previous.get(str(deal.get("id")))
        if _is_import(deal, old, principal):
            continue
        company = companies.get(str(deal.get("companyId") or ""))
        linked_contact = contacts.get(str(deal.get("contactId") or ""))
        # A name that only follows a rename of the linked record is not a change.
        company_changed = _changed(deal, old, ("companyId",)) or (
            _changed(deal, old, ("company",))
            and not (company and normalized_name(deal.get("company")) == normalized_name(company.get("name")))
        )
        contact_changed = _changed(deal, old, ("contactId",)) or (
            _changed(deal, old, ("contact",))
            and not (linked_contact and normalized_name(deal.get("contact")) == normalized_name(linked_contact.get("name")))
        )
        if company_changed:
            _require(company is not None, f"deals[{index}].companyId", "Selecione uma empresa cadastrada na lista.")
            _require(
                normalized_name(deal.get("company")) == normalized_name(company.get("name")),
                f"deals[{index}].company",
                "A empresa do Negócio não confere com o cadastro.",
            )
        if not (contact_changed or (company_changed and deal.get("contactId"))):
            continue
        contact_id = str(deal.get("contactId") or "")
        if not contact_id:
            _require(
                not str(deal.get("contact") or "").strip(),
                f"deals[{index}].contactId",
                "Selecione um contato cadastrado na lista.",
            )
            continue
        contact = contacts.get(contact_id)
        _require(contact is not None, f"deals[{index}].contactId", "Selecione um contato cadastrado na lista.")
        _require(
            normalized_name(deal.get("contact")) == normalized_name(contact.get("name")),
            f"deals[{index}].contact",
            "O contato do Negócio não confere com o cadastro.",
        )
        if company is not None:
            _require(
                _contact_belongs_to(contact, company),
                f"deals[{index}].contactId",
                f"Este contato não pertence à empresa {company.get('name')}.",
            )


def propagate_renames(canonical: WorkspaceState, merged: WorkspaceState) -> WorkspaceState:
    """Copy renamed company/contact names into every record linked by id.

    Deals and contacts keep the name as text next to the id, and records of
    other users are not sent by a non-admin client, so the server keeps every
    linked copy in step with the renamed company or contact.
    """

    before = canonical.model_dump(by_alias=True, exclude_none=True)
    after = merged.model_dump(by_alias=True, exclude_none=True)

    def renames(module: str) -> dict[str, str]:
        old_names = {str(item.get("id")): item.get("name") for item in before[module]}
        return {
            str(item.get("id")): item.get("name")
            for item in after[module]
            if str(item.get("id")) in old_names
            and item.get("name")
            and old_names[str(item.get("id"))] != item.get("name")
        }

    company_names = renames("companies")
    contact_names = renames("contacts")
    if not company_names and not contact_names:
        return merged
    for contact in after["contacts"]:
        new_name = company_names.get(str(contact.get("companyId") or ""))
        if new_name:
            contact["company"] = new_name
    for deal in after["deals"]:
        new_company = company_names.get(str(deal.get("companyId") or ""))
        if new_company:
            deal["company"] = new_company
        new_contact = contact_names.get(str(deal.get("contactId") or ""))
        if new_contact:
            deal["contact"] = new_contact
    return WorkspaceState.model_validate(after)


def enforce_crm_integrity(
    canonical: WorkspaceState,
    merged: WorkspaceState,
    principal: PrincipalScope,
) -> None:
    """Reject new or changed records that break the link and duplicate rules."""

    before = canonical.model_dump(by_alias=True, exclude_none=True)
    after = merged.model_dump(by_alias=True, exclude_none=True)
    _check_company_duplicates(after["companies"], _by_id(before["companies"]), principal)
    _check_contact_duplicates(after["contacts"], _by_id(before["contacts"]), principal)
    _check_contact_links(after["contacts"], _by_id(before["contacts"]), _by_id(after["companies"]), principal)
    _check_deal_currencies(after["deals"])
    _check_deal_links(
        after["deals"],
        _by_id(before["deals"]),
        _by_id(after["companies"]),
        _by_id(after["contacts"]),
        principal,
    )
