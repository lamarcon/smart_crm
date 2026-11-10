from __future__ import annotations

import uuid
from copy import deepcopy

import pytest

from app.policies import PrincipalScope
from app.schemas import WorkspaceReferenceError, WorkspaceState
from app.services.crm_integrity import enforce_crm_integrity, normalized_name


def principal(role: str = "Administrador") -> PrincipalScope:
    return PrincipalScope(
        tenant_id=uuid.uuid4(),
        workspace_id="default",
        user_id="u-1",
        role=role,
        team_id=None,
        auth_version=1,
    )


ADMIN = principal()
SELLER = principal("Vendedor")


def base() -> dict:
    return {
        "users": [{"id": "u-1", "name": "Ana", "email": "ana@test", "jobTitle": "Admin", "role": "Administrador", "team": "Gestão", "status": "Ativo", "invitedAt": None}],
        "leads": [],
        "companies": [
            {"id": "E-1", "name": "Jack Daniels", "city": "SP", "segment": "", "phone": "", "ownerId": "u-1"},
            {"id": "E-2", "name": "ALS Pharma", "city": "RJ", "segment": "", "phone": "", "ownerId": "u-1"},
        ],
        "contacts": [
            {"id": "C-1", "name": "Maria", "company": "Jack Daniels", "companyId": "E-1", "email": "maria@jd.test", "phone": "", "role": ""},
            {"id": "C-2", "name": "João", "company": "ALS Pharma", "companyId": "E-2", "email": "joao@als.test", "phone": "", "role": ""},
            {"id": "C-3", "name": "Pedro", "company": "Jack Daniels", "email": "", "phone": "", "role": ""},
        ],
        "deals": [
            {"id": "N-1", "title": "Ligado", "company": "Jack Daniels", "companyId": "E-1", "contact": "Maria", "contactId": "C-1", "amount": 10, "stage": "Em Contato", "responsibleId": "u-1"},
            {"id": "N-OLD", "title": "Antigo", "company": "Empresa Livre Antiga", "contact": "Alguém", "amount": 5, "stage": "Em Contato", "responsibleId": "u-1"},
        ],
        "notifications": [],
    }


def ws(data: dict) -> WorkspaceState:
    return WorkspaceState.model_validate(data)


def check(after: dict, before: dict | None = None, who: PrincipalScope = ADMIN) -> None:
    enforce_crm_integrity(ws(before or base()), ws(after), who)


def rejected(after: dict, path: str, message_part: str, who: PrincipalScope = ADMIN) -> None:
    with pytest.raises(WorkspaceReferenceError) as caught:
        check(after, who=who)
    assert caught.value.path == path
    assert message_part in caught.value.message


def new_deal(**fields) -> dict:
    deal = {"id": "N-NEW", "title": "Novo", "amount": 1, "stage": "Em Contato", "responsibleId": "u-1"}
    deal.update(fields)
    return deal


def test_normalized_name_matches_the_screen_rule() -> None:
    assert normalized_name("  Açaí   Ltda ") == normalized_name("acai ltda")
    assert normalized_name(None) == ""


def test_unchanged_snapshot_with_legacy_free_text_is_accepted() -> None:
    check(base())


def test_editing_other_fields_of_a_legacy_deal_is_accepted() -> None:
    after = base()
    after["deals"][1]["title"] = "Antigo renomeado"
    after["deals"][1]["amount"] = 50
    check(after)


def test_new_deal_with_registered_company_and_contact_is_accepted() -> None:
    after = base()
    after["deals"].append(new_deal(company="ALS Pharma", companyId="E-2", contact="João", contactId="C-2"))
    check(after)


def test_new_deal_without_contact_is_accepted() -> None:
    after = base()
    after["deals"].append(new_deal(company="ALS Pharma", companyId="E-2", contact=""))
    check(after)


def test_new_deal_with_free_text_company_is_rejected() -> None:
    after = base()
    after["deals"].append(new_deal(company="Empresa Que Nao Existe"))
    rejected(after, "deals[2].companyId", "Selecione uma empresa cadastrada")


def test_new_deal_with_unknown_company_id_is_rejected() -> None:
    after = base()
    after["deals"].append(new_deal(company="Fantasma", companyId="E-404"))
    rejected(after, "deals[2].companyId", "Selecione uma empresa cadastrada")


def test_company_text_must_match_the_linked_company() -> None:
    after = base()
    after["deals"].append(new_deal(company="Outra Empresa", companyId="E-2"))
    rejected(after, "deals[2].company", "não confere")


def test_company_text_comparison_ignores_case_and_accents() -> None:
    after = base()
    after["deals"].append(new_deal(company="  als   PHARMA ", companyId="E-2"))
    check(after)


def test_new_deal_with_free_text_contact_is_rejected() -> None:
    after = base()
    after["deals"].append(new_deal(company="ALS Pharma", companyId="E-2", contact="Desconhecido"))
    rejected(after, "deals[2].contactId", "Selecione um contato cadastrado")


def test_contact_of_another_company_is_rejected() -> None:
    after = base()
    after["deals"].append(new_deal(company="ALS Pharma", companyId="E-2", contact="Maria", contactId="C-1"))
    rejected(after, "deals[2].contactId", "não pertence à empresa ALS Pharma")


def test_contact_linked_only_by_company_name_belongs_to_it() -> None:
    after = base()
    after["deals"].append(new_deal(company="Jack Daniels", companyId="E-1", contact="Pedro", contactId="C-3"))
    check(after)


def test_contact_text_must_match_the_linked_contact() -> None:
    after = base()
    after["deals"].append(new_deal(company="ALS Pharma", companyId="E-2", contact="Outro Nome", contactId="C-2"))
    rejected(after, "deals[2].contact", "não confere")


def test_changing_a_legacy_deal_company_to_free_text_is_rejected() -> None:
    after = base()
    after["deals"][1]["company"] = "Outra Livre"
    rejected(after, "deals[1].companyId", "Selecione uma empresa cadastrada")


def test_linking_a_legacy_deal_keeps_its_untouched_free_contact() -> None:
    after = base()
    after["deals"][1].update(company="ALS Pharma", companyId="E-2")
    check(after)


def test_changing_company_keeps_no_contact_from_the_old_company() -> None:
    after = base()
    after["deals"][0].update(company="ALS Pharma", companyId="E-2")
    rejected(after, "deals[0].contactId", "não pertence à empresa ALS Pharma")


def test_non_admin_is_held_to_the_same_rule() -> None:
    after = base()
    after["deals"].append(new_deal(company="Livre", responsibleId="u-1"))
    rejected(after, "deals[2].companyId", "Selecione uma empresa cadastrada", who=SELLER)


def test_new_company_with_duplicate_name_is_rejected() -> None:
    after = base()
    after["companies"].append({"id": "E-3", "name": " jack  DANIELS ", "city": "", "segment": "", "phone": "", "ownerId": "u-1"})
    rejected(after, "companies[2].name", "Já existe uma empresa cadastrada como Jack Daniels.")


def test_renaming_a_company_onto_another_name_is_rejected() -> None:
    after = base()
    after["companies"][1]["name"] = "Jack Daniels"
    rejected(after, "companies[1].name", "Já existe uma empresa")


def test_legacy_duplicate_companies_keep_saving_until_renamed() -> None:
    before = base()
    before["companies"].append({"id": "E-3", "name": "Jack Daniels", "city": "", "segment": "", "phone": "", "ownerId": "u-1"})
    after = deepcopy(before)
    after["companies"][2]["city"] = "BH"
    check(after, before)


def test_new_contact_with_duplicate_email_is_rejected() -> None:
    after = base()
    after["contacts"].append({"id": "C-4", "name": "Outra Maria", "company": "ALS Pharma", "companyId": "E-2", "email": " MARIA@jd.test ", "phone": "", "role": ""})
    rejected(after, "contacts[3].email", "Já existe um contato com o e-mail maria@jd.test (Maria).")


def test_contacts_without_email_are_never_duplicates() -> None:
    after = base()
    after["contacts"].append({"id": "C-4", "name": "Sem Email", "company": "ALS Pharma", "companyId": "E-2", "email": "", "phone": "", "role": ""})
    check(after)


def test_lead_conversion_creating_company_contact_and_deal_together_is_accepted() -> None:
    after = base()
    after["companies"].append({"id": "E-9", "name": "Nova Ltda", "city": "", "segment": "", "phone": "", "ownerId": "u-1"})
    after["contacts"].append({"id": "C-9", "name": "Lia", "company": "Nova Ltda", "companyId": "E-9", "email": "lia@nova.test", "phone": "", "role": ""})
    after["deals"].append(new_deal(company="Nova Ltda", companyId="E-9", contact="Lia", contactId="C-9"))
    check(after)


def new_contact(**fields) -> dict:
    contact = {"id": "C-NEW", "name": "Nova Pessoa", "email": "", "phone": "", "role": ""}
    contact.update(fields)
    return contact


def test_new_contact_with_registered_company_is_accepted() -> None:
    after = base()
    after["contacts"].append(new_contact(company=" als pharma ", companyId="E-2"))
    check(after)


def test_new_contact_without_company_is_accepted() -> None:
    after = base()
    after["contacts"].append(new_contact(company=""))
    check(after)


def test_new_contact_with_free_text_company_is_rejected() -> None:
    after = base()
    after["contacts"].append(new_contact(company="Empresa Livre"))
    rejected(after, "contacts[3].companyId", "Selecione uma empresa cadastrada")


def test_new_contact_with_unknown_company_id_is_rejected() -> None:
    after = base()
    after["contacts"].append(new_contact(company="Fantasma", companyId="E-404"))
    rejected(after, "contacts[3].companyId", "Selecione uma empresa cadastrada")


def test_contact_company_text_must_match_the_linked_company() -> None:
    after = base()
    after["contacts"].append(new_contact(company="Outra", companyId="E-2"))
    rejected(after, "contacts[3].company", "não confere")


def test_legacy_free_text_contact_keeps_saving_other_changes() -> None:
    before = base()
    before["contacts"][2]["company"] = "Livre Antiga"
    after = deepcopy(before)
    after["contacts"][2]["phone"] = "1199"
    check(after, before)


def test_changing_a_contact_company_to_free_text_is_rejected() -> None:
    after = base()
    after["contacts"][0].pop("companyId")
    after["contacts"][0]["company"] = "Livre Nova"
    rejected(after, "contacts[0].companyId", "Selecione uma empresa cadastrada")


def test_non_admin_contact_follows_the_same_rule() -> None:
    after = base()
    after["contacts"].append(new_contact(company="Livre", bitrixId="9", bitrixFields={"ID": "9"}))
    rejected(after, "contacts[3].companyId", "Selecione uma empresa cadastrada", who=SELLER)


def bitrix_deal(**fields) -> dict:
    return new_deal(id="BX-DEAL-7", bitrixId="7", bitrixEntity="deal", bitrixFields={"ID": "7", "Empresa": "Livre Bitrix"}, company="Livre Bitrix", contact="Fulano", **fields)


def test_admin_bitrix_import_keeps_free_text_names() -> None:
    after = base()
    after["deals"].append(bitrix_deal())
    after["companies"].append({"id": "BX-COMPANY-1", "name": "Jack Daniels", "bitrixId": "1", "bitrixEntity": "company", "bitrixFields": {"ID": "1"}, "city": "", "segment": "", "phone": "", "ownerId": "u-1"})
    check(after)


def test_non_admin_cannot_use_the_bitrix_exemption() -> None:
    after = base()
    after["deals"].append(bitrix_deal())
    rejected(after, "deals[2].companyId", "Selecione uma empresa cadastrada", who=SELLER)


def test_editing_an_imported_deal_without_reimport_follows_the_rule() -> None:
    before = base()
    before["deals"].append(bitrix_deal())
    after = deepcopy(before)
    after["deals"][2]["company"] = "Outra Livre"
    with pytest.raises(WorkspaceReferenceError):
        check(after, before)
