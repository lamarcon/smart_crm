"""The permission matrix applied to the workspace snapshot: what is sent and what is accepted."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.schemas import WorkspaceState
from app.services.workspace import (
    WorkspaceAuthorizationError,
    merge_authorized_state,
    project_workspace_state,
)
from test_workspace_authorization import canonical_data, principal


def state(**changes) -> WorkspaceState:  # noqa: ANN003
    data = canonical_data()
    data["companies"] = [
        {"id": "E-1", "name": "Company", "ownerId": "u-seller"},
        {"id": "E-2", "name": "Other company", "ownerId": "u-manager"},
    ]
    data["contacts"] = [{"id": "C-1", "name": "Contact", "companyId": "E-2"}]
    data["products"] = [{"id": "P-1", "name": "License", "price": 10, "currency": "BRL"}]
    for deal in data["deals"]:
        if deal["id"] == "D-seller":
            deal.update({"companyId": "E-2", "contactId": "C-1", "quotes": [{"id": "Q-1", "productId": "P-1", "description": "License"}]})
    data.update(changes)
    return WorkspaceState.model_validate(data)


def seller(*cells: tuple[str, str, str]):  # noqa: ANN202
    return replace(principal("Vendedor"), permissions=tuple(cells))


def ids(records: list[dict]) -> set[str]:
    return {record["id"] for record in records}


# --- What is sent ----------------------------------------------------------------------

def test_default_projection_keeps_shared_modules_whole() -> None:
    projected = project_workspace_state(state(), principal("Vendedor"))
    assert ids(projected.companies) == {"E-1", "E-2"}
    assert ids(projected.contacts) == {"C-1"}
    assert ids(projected.products) == {"P-1"}
    assert not any(record.get("restricted") for record in projected.companies)


def test_module_without_read_is_not_sent_but_linked_names_are() -> None:
    subject = seller(("companies", "read", "none"), ("contacts", "read", "none"), ("products", "read", "none"))
    projected = project_workspace_state(state(), subject)
    # Only the records a visible deal points to come, and only with their name.
    assert projected.companies == [{"id": "E-2", "name": "Other company", "restricted": True}]
    assert projected.contacts == [{"id": "C-1", "name": "Contact", "restricted": True}]
    assert projected.products == [{"id": "P-1", "name": "License", "restricted": True}]


def test_company_scopes_follow_the_responsible_and_their_team() -> None:
    own = project_workspace_state(state(), seller(("companies", "read", "own")))
    assert {record["id"]: bool(record.get("restricted")) for record in own.companies} == {"E-1": False, "E-2": True}
    manager = replace(principal("Gestor"), permissions=(("companies", "read", "team"),))
    # E-2 belongs to the manager's team (Alpha); E-1's responsible is in Beta.
    assert ids(project_workspace_state(state(), manager).companies) == {"E-2"}


def test_wider_lead_scope_widens_what_is_sent() -> None:
    projected = project_workspace_state(state(), seller(("leads", "read", "team")))
    assert ids(projected.leads) == {"L-seller", "L-seller-assist", "L-assistant", "L-billing", "L-hidden"}
    assert ids(project_workspace_state(state(), seller(("leads", "read", "all"))).leads) == ids(state().leads)


# --- What is accepted ---------------------------------------------------------------------

def _submit(subject, mutate) -> WorkspaceState:  # noqa: ANN001
    canonical = state()
    submitted = project_workspace_state(canonical, subject)
    mutate(submitted)
    return merge_authorized_state(canonical, submitted, subject)


def test_unchanged_records_pass_without_edit_permission() -> None:
    subject = seller(("companies", "update", "none"), ("leads", "update", "none"))
    merged = _submit(subject, lambda submitted: None)
    assert ids(merged.companies) == {"E-1", "E-2"}
    assert ids(merged.leads) == ids(state().leads)


def test_changing_a_record_needs_edit_permission_in_scope() -> None:
    def rename(submitted: WorkspaceState) -> None:
        submitted.companies[0]["name"] = "Renamed"

    with pytest.raises(WorkspaceAuthorizationError):
        _submit(seller(("companies", "update", "none")), rename)
    with pytest.raises(WorkspaceAuthorizationError):
        _submit(seller(("companies", "update", "team")), lambda s: s.companies[1].update(name="Renamed"))
    merged = _submit(seller(("companies", "update", "own")), rename)
    assert merged.companies[0]["name"] == "Renamed"


def test_deleting_needs_delete_permission() -> None:
    def drop_lead(submitted: WorkspaceState) -> None:
        submitted.leads = [lead for lead in submitted.leads if lead["id"] != "L-seller"]

    with pytest.raises(WorkspaceAuthorizationError):
        _submit(seller(("leads", "delete", "none")), drop_lead)
    assert "L-seller" not in ids(_submit(seller(), drop_lead).leads)


def test_creating_needs_create_permission_and_a_record_the_user_can_see() -> None:
    def add_contact(submitted: WorkspaceState) -> None:
        submitted.contacts.append({"id": "C-new", "name": "New"})

    with pytest.raises(WorkspaceAuthorizationError):
        _submit(seller(("contacts", "create", "none")), add_contact)
    assert "C-new" in ids(_submit(seller(), add_contact).contacts)

    def add_foreign_lead(submitted: WorkspaceState) -> None:
        submitted.leads.append({"id": "L-new", "name": "New", "team": "Alpha", "responsibleId": "u-other", "assistants": []})

    with pytest.raises(WorkspaceAuthorizationError):
        _submit(seller(), add_foreign_lead)
    assert "L-new" in ids(_submit(seller(("leads", "read", "all")), add_foreign_lead).leads)


def test_imported_records_need_the_import_permission_of_their_module() -> None:
    def import_company(submitted: WorkspaceState) -> None:
        submitted.companies.append({"id": "E-bx", "name": "From Bitrix", "bitrixId": "77", "ownerId": "u-seller"})

    with pytest.raises(WorkspaceAuthorizationError):
        _submit(seller(), import_company)
    assert "E-bx" in ids(_submit(seller(("companies", "import", "all")), import_company).companies)
    with pytest.raises(WorkspaceAuthorizationError):
        _submit(seller(("deals", "import", "all")), import_company)


def test_name_only_stubs_never_overwrite_the_stored_record() -> None:
    subject = seller(("companies", "read", "none"))

    def tamper(submitted: WorkspaceState) -> None:
        submitted.companies[0]["name"] = "Hijacked"
        submitted.companies[0]["ownerId"] = "u-seller"

    merged = _submit(subject, tamper)
    stored = {record["id"]: record for record in merged.companies}
    assert stored["E-2"] == {"id": "E-2", "name": "Other company", "ownerId": "u-manager"}
    assert ids(merged.companies) == {"E-1", "E-2"}


def test_hidden_records_cannot_be_forged_as_stubs_or_edits() -> None:
    subject = seller(("companies", "read", "own"))

    def forge_stub(submitted: WorkspaceState) -> None:
        submitted.companies.append({"id": "E-1", "name": "x", "restricted": True})

    with pytest.raises(WorkspaceAuthorizationError):
        _submit(subject, forge_stub)  # E-1 is readable, so it is not a stub
    with pytest.raises(WorkspaceAuthorizationError):
        _submit(subject, lambda s: s.companies.append({"id": "E-missing", "name": "x", "restricted": True}))


def test_hidden_records_survive_a_save_untouched() -> None:
    subject = seller(("products", "read", "none"), ("contacts", "read", "none"))
    merged = _submit(subject, lambda submitted: None)
    assert ids(merged.products) == {"P-1"}
    assert merged.products[0] == state().products[0]
    assert ids(merged.contacts) == {"C-1"}


def test_taking_over_a_record_outside_the_edit_scope_is_rejected() -> None:
    # E-2 is readable (companies read "all") but belongs to someone else.
    def take_over(submitted: WorkspaceState) -> None:
        other = next(record for record in submitted.companies if record["id"] == "E-2")
        other.update(name="Mine now", ownerId="u-seller")

    with pytest.raises(WorkspaceAuthorizationError):
        _submit(seller(("companies", "update", "own")), take_over)


def test_records_outside_the_read_scope_cannot_be_edited_even_with_wide_edit_rights() -> None:
    subject = seller(("leads", "read", "own"), ("leads", "update", "all"))

    def forge(submitted: WorkspaceState) -> None:
        hidden = next(record for record in state().leads if record["id"] == "L-hidden")
        submitted.leads.append({**hidden, "name": "Stolen"})

    with pytest.raises(WorkspaceAuthorizationError):
        _submit(subject, forge)
