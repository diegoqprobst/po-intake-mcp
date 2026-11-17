"""Business rules in code. The model never decides whether an order is valid."""

from __future__ import annotations

from datetime import date, timedelta

from .master import MasterData
from .models import Issue, PurchaseOrder

PRICE_TOLERANCE = 0.02  # 2 % against list price


def validate(po: PurchaseOrder, master: MasterData, received: str, seen_po_numbers: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    cust = master.customers.get(po.customer_id) if po.customer_id else None

    if not po.po_number:
        issues.append(Issue("po_number_present", "error", "No PO number found"))
    if cust is None:
        issues.append(Issue("customer_known", "error", "Sender is not a known customer"))
    if po.customer_id and f"{po.customer_id}:{po.po_number}" in seen_po_numbers:
        issues.append(Issue("not_duplicate", "error", f"PO {po.po_number} was already received"))
    if cust and po.currency != cust.currency:
        issues.append(Issue("currency_matches", "error",
                            f"Currency {po.currency} differs from customer currency {cust.currency}"))

    if not po.delivery_date:
        issues.append(Issue("delivery_date_present", "warning", "No delivery date; approver must set one"))
    elif cust and received:
        earliest = date.fromisoformat(received) + timedelta(days=cust.lead_time_days)
        if date.fromisoformat(po.delivery_date) < earliest:
            issues.append(Issue("lead_time", "error",
                                f"Delivery {po.delivery_date} is before the earliest possible date {earliest}"))

    if not po.lines:
        issues.append(Issue("has_lines", "error", "No order lines found"))

    computed = 0.0
    for i, ln in enumerate(po.lines, start=1):
        computed += ln.quantity * ln.unit_price
        item = master.items.get(ln.sku)
        if item is None:
            issues.append(Issue("sku_known", "error", f"SKU {ln.sku} is not in the item master", i))
            continue
        if ln.unit.lower() != item.unit.lower():
            issues.append(Issue("unit_matches", "error", f"Unit {ln.unit} but item is sold in {item.unit}", i))
        if ln.quantity < item.min_quantity:
            issues.append(Issue("min_quantity", "error",
                                f"{ln.quantity:g} {item.unit} is below the minimum of {item.min_quantity:g}", i))
        if item.pack_multiple and round(ln.quantity / item.pack_multiple, 6) % 1:
            issues.append(Issue("pack_multiple", "error",
                                f"{ln.quantity:g} is not a multiple of {item.pack_multiple:g} {item.unit}", i))
        diff = (ln.unit_price - item.list_price) / item.list_price
        if abs(diff) > PRICE_TOLERANCE:
            issues.append(Issue("price_matches", "error",
                                f"Price {ln.unit_price:g} is {diff:+.1%} vs list {item.list_price:g}", i))

    if po.stated_total is not None and abs(po.stated_total - computed) > 0.01 * max(computed, 1):
        issues.append(Issue("total_matches", "error",
                            f"Stated total {po.stated_total:,.2f} differs from lines {computed:,.2f}"))
    return issues
