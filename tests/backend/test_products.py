"""Product catalog: rules, persistence, quote link, recycle bin and permissions."""

from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from sqlalchemy import select, text

from app.models import Product, Quote
from app.policies import PrincipalScope
from app.repositories.workspace import team_id_for_name
from app.schemas import WorkspaceReferenceError, WorkspaceState
from app.services.crm_integrity import enforce_crm_integrity
from app.services.workspace import WorkspaceAuthorizationError, WorkspaceService
from tests.backend.test_workspace_service import TEST_PRINCIPAL, service, state_data  # noqa: F401


def product(**fields) -> dict:
    base = {
        "id": "P-1", "name": "Licença Anual", "sku": "LIC-01", "description": "Plano anual",
        "category": "Software", "price": 1200, "currency": "BRL", "unit": "licença", "active": True,
        "metadata": [{"key": "ncm", "value": "8523.80"}, {"key": "garantia", "value": "12 meses"}],
    }
    base.update(fields)
    return base


def catalog_state(*products: dict) -> dict:
    data = state_data()
    data["products"] = list(products)
    return data


def guard(after: dict, before: dict | None = None) -> None:
    enforce_crm_integrity(
        WorkspaceState.model_validate(before or catalog_state()),
        WorkspaceState.model_validate(after),
        TEST_PRINCIPAL,
    )


def refused(after: dict, path: str, fragment: str, before: dict | None = None) -> None:
    with pytest.raises(WorkspaceReferenceError) as error:
        guard(after, before)
    assert error.value.path == path
    assert fragment in error.value.message


# --- Rules ------------------------------------------------------------------------------


def test_a_complete_product_is_accepted() -> None:
    guard(catalog_state(product()))


@pytest.mark.parametrize(
    ("fields", "path", "fragment"),
    [
        ({"name": "  "}, "products[0].name", "Informe o nome"),
        ({"price": -1}, "products[0].price", "maior ou igual a zero"),
        ({"price": "caro"}, "products[0].price", "maior ou igual a zero"),
        ({"currency": "GBP"}, "products[0].currency", "Moeda não suportada"),
        ({"metadata": {"ncm": "1"}}, "products[0].metadata", "lista"),
        ({"metadata": [{"key": " ", "value": "x"}]}, "products[0].metadata", "chave"),
        ({"metadata": [{"key": "k" * 65, "value": "x"}]}, "products[0].metadata", "chave"),
        ({"metadata": [{"key": "a", "value": "v" * 1001}]}, "products[0].metadata", "valor"),
        ({"metadata": [{"key": "Peso", "value": "1"}, {"key": "peso", "value": "2"}]}, "products[0].metadata", "repetida: peso"),
        ({"metadata": [{"key": f"k{i}", "value": "1"} for i in range(51)]}, "products[0].metadata", "até 50"),
    ],
)
def test_invalid_products_are_refused(fields, path, fragment) -> None:  # noqa: ANN001
    refused(catalog_state(product(**fields)), path, fragment)


def test_duplicate_sku_is_refused_ignoring_case_and_spaces() -> None:
    after = catalog_state(product(), product(id="P-2", name="Outra", sku=" lic-01 "))
    refused(after, "products[1].sku", "Já existe um produto com o código lic-01 (Licença Anual).", before=catalog_state(product()))


def test_products_without_sku_never_clash_and_legacy_duplicates_keep_saving() -> None:
    guard(catalog_state(product(sku=""), product(id="P-2", sku="")))
    legacy = catalog_state(product(), product(id="P-2", sku="LIC-01"))
    edited = deepcopy(legacy)
    edited["products"][1]["price"] = 99
    guard(edited, legacy)


# --- Persistence ---------------------------------------------------------------------------


def test_products_round_trip_with_metadata_and_columns(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(catalog_state(product(currency="usd", price="49.9"))))
    loaded = workspace.load().state.products
    assert loaded[0]["metadata"] == [{"key": "ncm", "value": "8523.80"}, {"key": "garantia", "value": "12 meses"}]
    with database.session_scope() as session:
        row = session.get(Product, "P-1")
        assert (row.name, row.sku, row.currency, str(row.price), row.unit, row.active) == ("Licença Anual", "LIC-01", "USD", "49.90", "licença", True)
        assert row.product_metadata == [{"key": "ncm", "value": "8523.80"}, {"key": "garantia", "value": "12 meses"}]


def test_quote_keeps_its_product_and_unknown_products_are_refused(service) -> None:  # noqa: F811
    workspace, database = service
    data = catalog_state(product())
    data["deals"][0]["quotes"][0]["productId"] = "P-1"
    workspace.bootstrap(WorkspaceState.model_validate(data))
    with database.session_scope() as session:
        assert session.scalar(select(Quote.product_id).where(Quote.id == "Q-1")) == "P-1"

    broken = workspace.load().state.model_dump(by_alias=True, exclude_none=True)
    broken["deals"][0]["quotes"][0]["productId"] = "P-404"
    with pytest.raises(WorkspaceReferenceError) as error:
        workspace.save(workspace.load().version, WorkspaceState.model_validate(broken))
    assert error.value.path == "deals[0].quotes[0].productId"


def test_removed_products_go_to_the_recycle_bin_and_come_back(service) -> None:  # noqa: F811
    workspace, _database = service
    workspace.bootstrap(WorkspaceState.model_validate(catalog_state(product(), product(id="P-2", name="Suporte", sku="SUP"))))
    removed = workspace.load().state.model_dump(by_alias=True, exclude_none=True)
    removed["products"] = [item for item in removed["products"] if item["id"] != "P-2"]
    saved = workspace.save(1, WorkspaceState.model_validate(removed))
    assert [item["id"] for item in saved.state.products] == ["P-1"]
    assert [item["id"] for item in workspace.list_deleted("products")] == ["P-2"]
    restored = workspace.restore(saved.version, "products", "P-2")
    assert sorted(item["id"] for item in restored.state.products) == ["P-1", "P-2"]


# --- Permissions ---------------------------------------------------------------------------


def principal(role: str, user_id: str = "u-2") -> PrincipalScope:
    return PrincipalScope(
        tenant_id=TEST_PRINCIPAL.tenant_id, workspace_id="default", user_id=user_id,
        role=role, team_id=team_id_for_name("Vendas"), auth_version=1,
    )


def save_as(database, who: PrincipalScope, mutate):  # noqa: ANN001, ANN201
    core = WorkspaceService()
    with database.session_scope() as session:
        loaded = core.load(session, who)
        data = loaded.state.model_dump(by_alias=True, exclude_none=True)
        mutate(data)
        return core.save(session, who, loaded.version, WorkspaceState.model_validate(data))


@pytest.mark.parametrize("role", ["Vendedor", "Assistente", "Faturamento"])
def test_other_roles_see_products_but_cannot_change_them(service, role) -> None:  # noqa: F811, ANN001
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(catalog_state(product())))
    who = principal(role)
    with database.session_scope() as session:
        assert [item["id"] for item in WorkspaceService().load(session, who).state.products] == ["P-1"]
    # An ordinary save that keeps the catalog untouched works.
    assert save_as(database, who, lambda data: None).version == 2
    for change in (
        lambda data: data["products"][0].update(price=1),
        lambda data: data["products"].append(product(id="P-9", sku="NOVO")),
        lambda data: data["products"].clear(),
    ):
        with pytest.raises(WorkspaceAuthorizationError):
            save_as(database, who, change)
    assert workspace.load().state.products[0]["price"] == 1200


def test_manager_can_change_the_catalog(service) -> None:  # noqa: F811
    workspace, database = service
    workspace.bootstrap(WorkspaceState.model_validate(catalog_state(product())))
    saved = save_as(database, principal("Gestor"), lambda data: data["products"].append(product(id="P-2", name="Treinamento", sku="TRN")))
    assert sorted(item["id"] for item in saved.state.products) == ["P-1", "P-2"]
