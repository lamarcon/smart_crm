"""A deal's value: the sum of its quote items plus an additional value.

Every saved snapshot goes through ``normalize_deal_amounts`` so the stored
value can never disagree with the items, whatever a client sends. Changing the
price of a catalog item or giving a discount needs the "price" permission.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.policies import PrincipalScope, allowed
from app.schemas import WorkspaceState

_CENT = Decimal("0.01")


class ItemPriceNotAllowed(PermissionError):
    """The user may not change item prices or give discounts."""


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError):
        amount = Decimal(0)
    if not amount.is_finite():
        amount = Decimal(0)
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _number(amount: Decimal) -> float | int:
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def item_total(item: dict[str, Any]) -> Decimal:
    quantity = _money(item.get("quantity", 1))
    return max(Decimal(0), (quantity * _money(item.get("unitPrice")) - _money(item.get("discount"))).quantize(_CENT))


def _normalize_deal(deal: dict[str, Any]) -> None:
    items = deal.get("quotes") or []
    items_sum = Decimal(0)
    for item in items:
        total = item_total(item)
        item["total"] = _number(total)
        items_sum += total
    if "additionalAmount" in deal:
        additional = max(Decimal(0), _money(deal.get("additionalAmount")))
    else:
        # A client that predates items (or an import) sends only the value:
        # without items it is all additional value; with items it is replaced.
        additional = max(Decimal(0), _money(deal.get("amount"))) if not items else Decimal(0)
    deal["additionalAmount"] = _number(additional)
    deal["additionalReason"] = str(deal.get("additionalReason") or "")[:1000]
    deal["amount"] = _number(items_sum + additional)


def normalize_deal_amounts(state: WorkspaceState) -> WorkspaceState:
    data = state.model_dump(by_alias=True, exclude_none=True)
    for deal in data.get("deals") or []:
        _normalize_deal(deal)
    return WorkspaceState.model_validate(data)


def enforce_item_prices(canonical: WorkspaceState, merged: WorkspaceState, principal: PrincipalScope) -> None:
    """Without the price permission, items keep the catalog price and no discount.

    Free-text items (no product) are priced freely. A catalog item priced in
    another currency was converted by the client at the day's rate, so only
    same-currency items are compared with the catalog.
    """

    if allowed(principal, "deals", "price"):
        return
    before = canonical.model_dump(by_alias=True, exclude_none=True)
    after = merged.model_dump(by_alias=True, exclude_none=True)
    products = {product.get("id"): product for product in after.get("products") or []}
    old_items = {
        (deal.get("id"), item.get("id")): item
        for deal in before.get("deals") or []
        for item in deal.get("quotes") or []
    }
    for deal in after.get("deals") or []:
        currency = deal.get("currency") or "BRL"
        for item in deal.get("quotes") or []:
            old = old_items.get((deal.get("id"), item.get("id")))
            discount = _money(item.get("discount"))
            if discount > 0 and (old is None or _money(old.get("discount")) != discount):
                raise ItemPriceNotAllowed("discount")
            same_product = old is not None and old.get("productId") == item.get("productId")
            if same_product:
                if _money(old.get("unitPrice")) != _money(item.get("unitPrice")):
                    raise ItemPriceNotAllowed("unit price")
                continue
            product = products.get(item.get("productId"))
            if product is None or (product.get("currency") or "BRL") != currency:
                continue
            if _money(product.get("price")) != _money(item.get("unitPrice")):
                raise ItemPriceNotAllowed("catalog price")
