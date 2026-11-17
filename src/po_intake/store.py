"""Staging store laid out like OneLake medallion layers, on the local filesystem.

  bronze/      original .eml, untouched, named by SHA-256
  silver/      one JSON per order: extraction, method, model, every rule result
  gold/        approved orders only
  erp_outbox/  payloads an ERP adapter would send; nothing here talks to an ERP
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, root: Path):
        self.root = root
        for layer in ("bronze", "silver", "gold", "erp_outbox"):
            (root / layer).mkdir(parents=True, exist_ok=True)

    # bronze
    def keep_original(self, eml_path: Path) -> str:
        digest = hashlib.sha256(eml_path.read_bytes()).hexdigest()
        target = self.root / "bronze" / f"{digest}.eml"
        if not target.exists():
            shutil.copyfile(eml_path, target)
        return digest

    # silver
    def save(self, record: dict[str, Any]) -> None:
        record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path = self.root / "silver" / f"{record['order_id']}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, order_id: str) -> dict[str, Any] | None:
        path = self.root / "silver" / f"{order_id}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def all(self) -> list[dict[str, Any]]:
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.root / "silver").glob("*.json"))]

    def seen_po_numbers(self, exclude_order: str | None = None) -> set[str]:
        return {
            f"{r['po']['customer_id']}:{r['po']['po_number']}"
            for r in self.all()
            if r.get("po") and r["status"] in ("draft", "approved") and r["order_id"] != exclude_order
        }

    def processed_sources(self) -> set[str]:
        return {r["source_sha256"] for r in self.all()}

    # gold + outbox
    def publish_approved(self, record: dict[str, Any], erp_payload: dict[str, Any]) -> None:
        oid = record["order_id"]
        (self.root / "gold" / f"{oid}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        (self.root / "erp_outbox" / f"{oid}.json").write_text(
            json.dumps(erp_payload, indent=2, ensure_ascii=False), encoding="utf-8")
