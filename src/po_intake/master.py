"""Master data (customers, items). In production this is a read-only view of the ERP or Fabric."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Customer:
    customer_id: str
    name: str
    email_domain: str
    currency: str
    lead_time_days: int


@dataclass
class Item:
    sku: str
    description: str
    unit: str
    list_price: float
    pack_multiple: float
    min_quantity: float


@dataclass
class MasterData:
    customers: dict[str, Customer]
    items: dict[str, Item]

    def customer_by_domain(self, sender: str) -> Customer | None:
        domain = sender.rsplit("@", 1)[-1].strip(" >").lower()
        for c in self.customers.values():
            if c.email_domain.lower() == domain:
                return c
        return None


def load_master(master_dir: Path) -> MasterData:
    with open(master_dir / "customers.csv", newline="", encoding="utf-8") as f:
        customers = {
            r["customer_id"]: Customer(
                customer_id=r["customer_id"],
                name=r["name"],
                email_domain=r["email_domain"],
                currency=r["currency"],
                lead_time_days=int(r["lead_time_days"]),
            )
            for r in csv.DictReader(f)
        }
    with open(master_dir / "items.csv", newline="", encoding="utf-8") as f:
        items = {
            r["sku"]: Item(
                sku=r["sku"],
                description=r["description"],
                unit=r["unit"],
                list_price=float(r["list_price"]),
                pack_multiple=float(r["pack_multiple"]),
                min_quantity=float(r["min_quantity"]),
            )
            for r in csv.DictReader(f)
        }
    return MasterData(customers=customers, items=items)
