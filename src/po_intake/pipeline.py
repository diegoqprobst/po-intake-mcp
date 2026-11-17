"""The whole flow, as plain functions. The MCP server is a thin layer on top."""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .extract import classify, extract
from .mail import read_eml
from .master import MasterData, load_master
from .models import PurchaseOrder
from .store import Store
from .validate import validate

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Pipeline:
    def __init__(self, data_dir: Path | None = None, staging_dir: Path | None = None):
        self.data_dir = Path(data_dir or os.environ.get("PO_DATA_DIR", PROJECT_ROOT / "data"))
        self.inbox = self.data_dir / "inbox"
        self.master: MasterData = load_master(self.data_dir / "master")
        self.store = Store(Path(staging_dir or os.environ.get("PO_STAGING_DIR", PROJECT_ROOT / "staging")))

    # ---- inbox ----
    def list_inbox(self) -> list[dict[str, Any]]:
        done = self.store.processed_sources()
        out = []
        for p in sorted(self.inbox.glob("*.eml")):
            m = read_eml(p)
            sha = self.store.keep_original(p)
            out.append({
                "file": p.name, "from": m.sender, "subject": m.subject, "received": m.received,
                "attachments": [a.name for a in m.attachments], "already_processed": sha in done,
            })
        return out

    def _resolve(self, file: str) -> Path:
        path = (self.inbox / file).resolve()
        if path.parent != self.inbox.resolve() or path.suffix != ".eml" or not path.exists():
            raise ValueError(f"{file!r} is not an .eml file in the inbox")
        return path

    # ---- one email ----
    def process_email(self, file: str) -> dict[str, Any]:
        path = self._resolve(file)
        sha = self.store.keep_original(path)
        existing = next((r for r in self.store.all() if r["source_sha256"] == sha), None)
        if existing:
            return {**self.summary(existing), "note": "already processed; returning the stored result"}

        mail = read_eml(path)
        cls = classify(mail, self.master)
        record: dict[str, Any] = {
            "order_id": f"ORD-{sha[:10]}",
            "source_file": path.name,
            "source_sha256": sha,
            "email": {"from": mail.sender, "subject": mail.subject, "received": mail.received,
                      "message_id": mail.message_id},
            "classification": asdict(cls),
            "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if not cls.is_po:
            record.update(status="ignored", po=None, issues=[], extraction=None)
            self.store.save(record)
            return self.summary(record)

        try:
            ex = extract(mail, cls, self.master)
        except Exception as e:  # a broken file is an exception for a person, not a crash
            record.update(status="exception", po=None, extraction={"method": "error", "detail": str(e)},
                          issues=[{"rule": "extraction", "severity": "error", "message": str(e), "line": None}])
            self.store.save(record)
            return self.summary(record)

        record["extraction"] = {"method": ex.method, "model": ex.model, "detail": ex.detail}
        if ex.po is None:
            record.update(status="exception", po=None, issues=[
                {"rule": "extraction", "severity": "error", "message": ex.detail, "line": None}])
            if cls.customer_id is None:
                record["issues"].append({"rule": "customer_known", "severity": "error",
                                         "message": "Sender is not a known customer", "line": None})
        else:
            issues = validate(ex.po, self.master, mail.received, self.store.seen_po_numbers())
            record["po"] = ex.po.to_dict()
            record["issues"] = [asdict(i) for i in issues]
            record["status"] = "exception" if any(i.severity == "error" for i in issues) else "draft"
        self.store.save(record)
        return self.summary(record)

    def process_inbox(self) -> dict[str, Any]:
        results = [self.process_email(p.name) for p in sorted(self.inbox.glob("*.eml"))]
        return {"processed": len(results), "results": results, "metrics": self.metrics()}

    # ---- tools for a person ----
    def revalidate(self, order_id: str, po_json: dict[str, Any]) -> dict[str, Any]:
        """A person fixes fields (e.g. after calling the customer); rules run again."""
        rec = self._require(order_id, allowed=("exception", "draft"))
        po = PurchaseOrder.from_dict(po_json)
        issues = validate(po, self.master, rec["email"]["received"], self.store.seen_po_numbers(order_id))
        rec["po"] = po.to_dict()
        rec["issues"] = [asdict(i) for i in issues]
        rec["status"] = "exception" if any(i.severity == "error" for i in issues) else "draft"
        rec.setdefault("history", []).append({"action": "revalidated", "at": _now()})
        self.store.save(rec)
        return self.summary(rec)

    def approve(self, order_id: str, approver: str, note: str = "") -> dict[str, Any]:
        rec = self._require(order_id, allowed=("draft",))
        rec["status"] = "approved"
        rec.setdefault("history", []).append({"action": "approved", "by": approver, "note": note, "at": _now()})
        self.store.save(rec)
        payload = erp_payload(rec)
        self.store.publish_approved(rec, payload)
        return {**self.summary(rec), "erp_payload": payload,
                "note": "Written to erp_outbox/. No ERP was called; an adapter sends this in production."}

    def reject(self, order_id: str, approver: str, reason: str) -> dict[str, Any]:
        rec = self._require(order_id, allowed=("draft", "exception"))
        rec["status"] = "rejected"
        rec.setdefault("history", []).append({"action": "rejected", "by": approver, "note": reason, "at": _now()})
        self.store.save(rec)
        return self.summary(rec)

    def list_orders(self, status: str | None = None) -> list[dict[str, Any]]:
        return [self.summary(r) for r in self.store.all() if status in (None, r["status"])]

    def get(self, order_id: str) -> dict[str, Any]:
        rec = self.store.get(order_id)
        if rec is None:
            raise ValueError(f"No order {order_id}")
        return rec

    def metrics(self) -> dict[str, Any]:
        recs = self.store.all()
        pos = [r for r in recs if r["status"] != "ignored"]
        by_status: dict[str, int] = {}
        by_method: dict[str, int] = {}
        by_rule: dict[str, int] = {}
        for r in recs:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        for r in pos:
            m = (r.get("extraction") or {}).get("method", "none")
            by_method[m] = by_method.get(m, 0) + 1
            for i in r.get("issues", []):
                if i["severity"] == "error":
                    by_rule[i["rule"]] = by_rule.get(i["rule"], 0) + 1
        # "no touch": reached draft/approved without a person editing fields
        straight = sum(1 for r in pos if r["status"] in ("draft", "approved")
                       and all(h["action"] != "revalidated" for h in r.get("history", [])))
        return {
            "emails": len(recs),
            "purchase_orders": len(pos),
            "by_status": by_status,
            "extraction_method": by_method,
            "llm_calls": by_method.get("llm", 0),
            "no_touch_rate": round(straight / len(pos), 3) if pos else None,
            "exceptions_by_rule": dict(sorted(by_rule.items(), key=lambda kv: -kv[1])),
        }

    # ---- helpers ----
    def _require(self, order_id: str, allowed: tuple[str, ...]) -> dict[str, Any]:
        rec = self.get(order_id)
        if rec["status"] not in allowed:
            raise ValueError(f"{order_id} is {rec['status']}; this action needs status {' or '.join(allowed)}")
        return rec

    @staticmethod
    def summary(rec: dict[str, Any]) -> dict[str, Any]:
        po = rec.get("po") or {}
        return {
            "order_id": rec["order_id"],
            "status": rec["status"],
            "source_file": rec["source_file"],
            "customer": po.get("customer_name") or rec["email"]["from"],
            "po_number": po.get("po_number"),
            "lines": len(po.get("lines", [])),
            "method": (rec.get("extraction") or {}).get("method"),
            "errors": [i["message"] for i in rec.get("issues", []) if i["severity"] == "error"],
            "warnings": [i["message"] for i in rec.get("issues", []) if i["severity"] == "warning"],
        }


def erp_payload(rec: dict[str, Any]) -> dict[str, Any]:
    """Neutral sales-order shape. A NetSuite or SAP adapter maps this; it is the only piece that changes."""
    po = rec["po"]
    return {
        "type": "sales_order_draft",
        "external_id": rec["order_id"],
        "customer_id": po["customer_id"],
        "customer_po": po["po_number"],
        "currency": po["currency"],
        "requested_date": po["delivery_date"],
        "lines": [{"sku": ln["sku"], "quantity": ln["quantity"], "unit": ln["unit"], "unit_price": ln["unit_price"]}
                  for ln in po["lines"]],
        "source": {"email_sha256": rec["source_sha256"], "extraction": rec["extraction"]["method"]},
        "approved_by": rec["history"][-1]["by"],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
