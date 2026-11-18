"""Deal value = items + additional value; item prices need the price permission."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, inspect, text

from app.schemas import WorkspaceState
from app.services.deal_amounts import ItemPriceNotAllowed, enforce_item_prices, normalize_deal_amounts
from test_migrations import isolated_migration  # noqa: F401 - fixture
from test_workspace_authorization import canonical_data, principal


def deal_state(deal: dict, products: list[dict] | None = None) -> WorkspaceState:
    data = canonical_data()
    data["deals"] = [{"id": "N-1", "title": "Negócio", "responsibleId": "u-seller", "assistants": [], "team": "Beta", **deal}]
    data["products"] = products or []
    return WorkspaceState.model_validate(data)


def item(item_id: str, **values) -> dict:  # noqa: ANN003
    return {"id": item_id, "description": "Item", "quantity": 1, "unitPrice": 0, "discount": 0, **values}


def normalized(deal: dict) -> dict:
    return normalize_deal_amounts(deal_state(deal)).deals[0]


# --- Value ------------------------------------------------------------------------------------

def test_value_is_the_sum_of_items_plus_the_additional_value() -> None:
    deal = normalized({
        "amount": 1,
        "additionalAmount": 250.5,
        "additionalReason": "Orçamento externo em PDF",
        "quotes": [item("Q-1", quantity=2, unitPrice=100, discount=10), item("Q-2", quantity=3, unitPrice=33.333)],
    })
    assert [quote["total"] for quote in deal["quotes"]] == [190, 99.99]
    assert deal["additionalAmount"] == 250.5
    assert deal["additionalReason"] == "Orçamento externo em PDF"
    assert deal["amount"] == 540.49


def test_items_never_go_negative_and_additional_value_is_not_negative() -> None:
    deal = normalized({"additionalAmount": -50, "quotes": [item("Q-1", unitPrice=10, discount=99)]})
    assert deal["quotes"][0]["total"] == 0
    assert deal["additionalAmount"] == 0
    assert deal["amount"] == 0


@pytest.mark.parametrize(
    ("deal", "additional", "amount"),
    [
        ({"amount": 150000, "quotes": []}, 150000, 150000),  # typed value, no items: kept as additional
        ({"amount": 6000, "quotes": [item("Q-1", unitPrice=6000)]}, 0, 6000),  # value replaced by the items
    ],
)
def test_clients_without_the_additional_field_keep_the_old_meaning(deal, additional, amount) -> None:  # noqa: ANN001
    result = normalized(deal)
    assert (result["additionalAmount"], result["amount"]) == (additional, amount)


# --- Price permission ----------------------------------------------------------------------

PRODUCTS = [{"id": "P-1", "name": "Licença", "price": 100, "currency": "BRL"}, {"id": "P-2", "name": "Euro", "price": 10, "currency": "EUR"}]


def check(before: list[dict], after: list[dict], subject) -> None:  # noqa: ANN001
    canonical = normalize_deal_amounts(deal_state({"quotes": before}, PRODUCTS))
    merged = normalize_deal_amounts(deal_state({"quotes": after}, PRODUCTS))
    enforce_item_prices(canonical, merged, subject)


def test_without_permission_catalog_items_keep_their_price_and_no_discount() -> None:
    seller = principal("Vendedor")
    check([], [item("Q-1", productId="P-1", unitPrice=100, quantity=3)], seller)
    check([], [item("Q-1", description="Serviço avulso", unitPrice=777)], seller)  # free item
    check([], [item("Q-1", productId="P-2", unitPrice=61.7)], seller)  # converted from EUR
    with pytest.raises(ItemPriceNotAllowed):
        check([], [item("Q-1", productId="P-1", unitPrice=90)], seller)
    with pytest.raises(ItemPriceNotAllowed):
        check([], [item("Q-1", description="Serviço avulso", unitPrice=500, discount=5)], seller)
    existing = [item("Q-1", productId="P-1", unitPrice=100)]
    check(existing, [item("Q-1", productId="P-1", unitPrice=100, quantity=5)], seller)  # quantity is free
    with pytest.raises(ItemPriceNotAllowed):
        check(existing, [item("Q-1", productId="P-1", unitPrice=80)], seller)
    # A discount given earlier by someone allowed may stay.
    check([item("Q-1", productId="P-1", unitPrice=100, discount=5)], [item("Q-1", productId="P-1", unitPrice=100, discount=5, quantity=2)], seller)


def test_with_permission_prices_and_discounts_are_free() -> None:
    check([], [item("Q-1", productId="P-1", unitPrice=70, discount=10)], principal("Gestor"))
    check([], [item("Q-1", productId="P-1", unitPrice=70, discount=10)], principal("Administrador"))
    granted = replace(principal("Vendedor"), permissions=(("deals", "price", "all"),))
    check([item("Q-1", productId="P-1", unitPrice=100)], [item("Q-1", productId="P-1", unitPrice=50)], granted)


# --- Migration of existing deals -------------------------------------------------------------

def test_migration_converts_existing_deals_once(isolated_migration) -> None:  # noqa: ANN001
    from alembic import command

    connection, schema, config = isolated_migration
    command.upgrade(config, "c4e8a2f6b9d1")
    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
    pipeline = connection.execute(text("SELECT id, default_stage_id FROM deal_pipelines LIMIT 1")).first()
    if pipeline is None:
        pytest.skip("no default pipeline in the isolated schema")
    connection.execute(text("INSERT INTO workspaces (id, version) VALUES ('default', 1) ON CONFLICT DO NOTHING"))
    for deal_id, amount in (("N-typed", 150000), ("N-quoted", 6000)):
        connection.execute(
            text(
                "INSERT INTO deals (id, workspace_id, title, company_text, contact_text, amount, stage, pipeline_id, stage_id, payload, created_at, updated_at) "
                "VALUES (:id, 'default', :id, '', '', :amount, 'Em Contato', :pipeline, :stage, "
                "CAST(:payload AS jsonb), now(), now())"
            ),
            {
                "id": deal_id, "amount": amount, "pipeline": pipeline.id, "stage": pipeline.default_stage_id,
                "payload": json.dumps({"position": 0, "record": {"id": deal_id, "amount": amount}}),
            },
        )
    for quote_id, total in (("Q-1", 6000), ("Q-2", 1500)):
        connection.execute(
            text(
                "INSERT INTO quotes (id, workspace_id, deal_id, position, description, quantity, unit_price, discount, total, state, payload, created_at, updated_at) "
                "VALUES (:id, 'default', 'N-quoted', 0, '', 1, :total, 0, :total, 'Rascunho', '{}'::jsonb, now(), now())"
            ),
            {"id": quote_id, "total": total},
        )

    command.upgrade(config, "head")
    connection.execute(text("SELECT set_config('smartcrm.workspace_id', 'default', true)"))
    rows = {
        row.id: (float(row.amount), row.record)
        for row in connection.execute(text("SELECT id, amount, payload -> 'record' AS record FROM deals ORDER BY id"))
    }
    assert rows["N-typed"][0] == 150000
    assert rows["N-typed"][1]["additionalAmount"] == 150000
    assert rows["N-quoted"][0] == 7500
    assert rows["N-quoted"][1]["additionalAmount"] == 0
    assert rows["N-quoted"][1]["amount"] == 7500
    checks = {item["name"]: item["sqltext"] for item in inspect(connection).get_check_constraints("role_permissions", schema=schema)}
    assert "price" in checks["ck_role_permissions_valid_action"]
