"""Expected result for every sample email. This is the eval: if a change breaks a row, the test says which."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from po_intake.pipeline import Pipeline

DATA = Path(__file__).resolve().parents[1] / "data"

EXPECTED = {
    "01_lacteos_OC-4501.eml": ("draft", "template", set()),
    "02_snacks_PO-8812.eml": ("exception", "csv", {"pack_multiple"}),
    "03_cafe_OC-0093.eml": ("exception", "template", {"price_matches"}),
    "04_nuevo_cliente.eml": ("exception", "none", {"extraction", "customer_known"}),
    "05_lacteos_OC-4501_reenvio.eml": ("exception", "template", {"not_duplicate"}),
    "06_snacks_consulta.eml": ("ignored", None, set()),
}


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("PO_LLM", "off")
    p = Pipeline(data_dir=DATA, staging_dir=tmp_path / "staging")
    p.process_inbox()
    return p


def by_file(p: Pipeline) -> dict[str, dict]:
    return {r["source_file"]: r for r in p.store.all()}


@pytest.mark.parametrize("file", sorted(EXPECTED))
def test_each_email(pipe, file):
    status, method, rules = EXPECTED[file]
    rec = by_file(pipe)[file]
    assert rec["status"] == status
    assert (rec.get("extraction") or {}).get("method") == method
    assert {i["rule"] for i in rec["issues"] if i["severity"] == "error"} == rules


def test_extracted_values(pipe):
    po = by_file(pipe)["01_lacteos_OC-4501.eml"]["po"]
    assert po["po_number"] == "OC-4501"
    assert po["delivery_date"] == "2026-12-10"
    assert [(l["sku"], l["quantity"], l["unit_price"]) for l in po["lines"]] == [
        ("BOB-1001", 1500.0, 4.8), ("TAP-4001", 200.0, 14.0)]
    assert po["stated_total"] == 10000.0


def test_reprocessing_is_idempotent(pipe):
    before = len(pipe.store.all())
    again = pipe.process_email("01_lacteos_OC-4501.eml")
    assert "already processed" in again["note"]
    assert len(pipe.store.all()) == before


def test_approve_writes_outbox_only_for_drafts(pipe, tmp_path):
    files = by_file(pipe)
    with pytest.raises(ValueError):
        pipe.approve(files["03_cafe_OC-0093.eml"]["order_id"], "Laura")
    oid = files["01_lacteos_OC-4501.eml"]["order_id"]
    out = pipe.approve(oid, "Laura", "ok")
    assert out["status"] == "approved"
    payload = json.loads((tmp_path / "staging" / "erp_outbox" / f"{oid}.json").read_text())
    assert payload["customer_po"] == "OC-4501" and payload["approved_by"] == "Laura"
    with pytest.raises(ValueError):
        pipe.approve(oid, "Laura")  # cannot approve twice


def test_person_fixes_exception_and_rules_run_again(pipe):
    rec = by_file(pipe)["02_snacks_PO-8812.eml"]
    po = rec["po"]
    po["lines"][2]["quantity"] = 20  # customer confirmed 20 millares
    out = pipe.revalidate(rec["order_id"], po)
    assert out["status"] == "draft" and out["errors"] == []
    assert pipe.metrics()["no_touch_rate"] == 0.2  # an edited order does not count as no-touch


def test_revalidate_cannot_sneak_in_bad_data(pipe):
    rec = by_file(pipe)["03_cafe_OC-0093.eml"]
    po = rec["po"]
    po["lines"][0]["sku"] = "XXX-999"
    out = pipe.revalidate(rec["order_id"], po)
    assert out["status"] == "exception"


def test_only_inbox_files_can_be_read(pipe):
    for bad in ("../master/items.csv", "/etc/passwd", "nope.eml"):
        with pytest.raises(ValueError):
            pipe.process_email(bad)
