"""Plain data shapes shared by every step. JSON-friendly on purpose."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Attachment:
    name: str
    content_type: str
    data: bytes


@dataclass
class Email:
    path: str
    message_id: str
    sender: str
    subject: str
    received: str  # ISO date (YYYY-MM-DD)
    body: str
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class POLine:
    sku: str
    quantity: float
    unit: str
    unit_price: float
    description: str = ""


@dataclass
class PurchaseOrder:
    po_number: str
    customer_id: str | None
    customer_name: str | None
    delivery_date: str | None  # ISO date
    currency: str
    lines: list[POLine]
    stated_total: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PurchaseOrder":
        return cls(
            po_number=str(d.get("po_number") or ""),
            customer_id=d.get("customer_id"),
            customer_name=d.get("customer_name"),
            delivery_date=d.get("delivery_date"),
            currency=d.get("currency") or "USD",
            lines=[POLine(**ln) for ln in d.get("lines", [])],
            stated_total=d.get("stated_total"),
        )


@dataclass
class Issue:
    rule: str
    severity: str  # "error" blocks the draft, "warning" is shown to the approver
    message: str
    line: int | None = None
