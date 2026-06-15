"""Receipt v1 + per-firm-per-case registry naming (Phase 4 task 4.1 lock).

Pure-module tests: no chain, no I/O. They pin the LOCKED shape — minimal,
non-enumerating, always under the 2048 B cap — and the filer-chosen readable
registry naming (Albert 2026-06-15).
"""

from __future__ import annotations

import json

import pytest

from nvnm_cite.loader.records import METADATA_CAP, compact_json
from nvnm_cite.normalizer import NORMALIZER_VERSION
from nvnm_cite.receipts.schema import (
    RECEIPT_SCHEMA,
    TALLY_KEYS,
    ReceiptError,
    build_receipt,
    receipt_registry_name,
    receipt_registry_strings,
    slugify,
    summary_tally,
)

DOC_SHA = "a1" * 32  # 64 hex
AGENT = "0x" + "ab" * 20
REGS = [
    {"id": 737, "name": "us-scotus", "head_block": 1670739},
    {"id": 738, "name": "us-ca11", "head_block": 1670739},
]
TALLY = {
    "checked": 6, "verified": 2, "not_found": 1, "not_covered": 1,
    "ambiguous": 1, "unparseable": 1, "name_mismatches": 1,
}


# ---------------------------------------------------------------- naming


def test_slugify():
    assert slugify("Inveniam LLP") == "inveniam-llp"
    assert slugify("Mata v. Avianca, Inc.") == "mata-v-avianca-inc"
    assert slugify("  --Trailing-- ") == "trailing"
    assert slugify("!!!") == ""


def test_receipt_registry_name_readable_double_hyphen():
    name = receipt_registry_name("Inveniam", "Mata v. Avianca")
    assert name == "inveniam--mata-v-avianca"
    # the "--" separates firm from case and never collides with a court id
    assert "--" in name and not name.startswith("us-")


def test_receipt_registry_name_rejects_empty_and_overlong():
    with pytest.raises(ReceiptError):
        receipt_registry_name("", "Case")
    with pytest.raises(ReceiptError):
        receipt_registry_name("Firm", "!!!")
    with pytest.raises(ReceiptError):
        receipt_registry_name("x" * 40, "y" * 40)  # > 64 byte name


def test_receipt_registry_strings_locked_shape():
    name, description, metadata = receipt_registry_strings("Inveniam", "Mata v. Avianca")
    assert name == "inveniam--mata-v-avianca"
    assert "filing receipts" in description and "Inveniam" in description
    parsed = json.loads(metadata)
    assert parsed["schema"] == RECEIPT_SCHEMA and parsed["kind"] == "receipts"
    assert parsed["firm"] == "Inveniam" and parsed["case"] == "Mata v. Avianca"
    assert metadata == compact_json(parsed)  # sorted, compact


# ---------------------------------------------------------------- tally


def test_summary_tally_from_report():
    report = {
        "summary": {
            "distinct": 6,
            "by_status": {
                "VERIFIED": 2, "NOT_FOUND": 1, "NOT_COVERED": 1,
                "AMBIGUOUS_JURISDICTION": 1, "UNPARSEABLE": 1,
            },
            "name_mismatches": 1,
        }
    }
    assert summary_tally(report) == TALLY
    assert set(summary_tally(report)) == set(TALLY_KEYS)


# ---------------------------------------------------------------- build_receipt


def test_build_receipt_shape_and_size():
    receipt, serialized = build_receipt(
        document_sha256=DOC_SHA.upper(),  # accepts/repairs case
        checked_at_block=1670739, registries=REGS, summary=TALLY,
        agent_address=AGENT, timestamp="2026-06-15T12:00:00Z",
    )
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["document_sha256"] == DOC_SHA  # lowercased
    assert receipt["agent"] == {"address": AGENT.lower()}
    assert receipt["normalizer_version"] == NORMALIZER_VERSION
    assert receipt["summary"] == TALLY
    assert [r["name"] for r in receipt["registries"]] == ["us-scotus", "us-ca11"]
    # NON-ENUMERATING: no per-case list anywhere
    assert "results" not in receipt and "cases" not in serialized
    assert "kya" not in serialized
    # canonical + always under cap, with comfortable margin
    assert serialized == compact_json(receipt)
    assert len(serialized.encode("utf-8")) <= METADATA_CAP
    assert len(serialized.encode("utf-8")) < 700


def test_build_receipt_validation():
    base = dict(
        document_sha256=DOC_SHA, checked_at_block=1, registries=REGS,
        summary=TALLY, agent_address=AGENT, timestamp="t",
    )
    with pytest.raises(ReceiptError):
        build_receipt(**{**base, "document_sha256": "xyz"})
    with pytest.raises(ReceiptError):
        build_receipt(**{**base, "agent_address": "nope"})
    with pytest.raises(ReceiptError):
        build_receipt(**{**base, "checked_at_block": -1})
    with pytest.raises(ReceiptError):
        build_receipt(**{**base, "summary": {"checked": 1}})  # wrong keys
    with pytest.raises(ReceiptError):
        build_receipt(**{**base, "registries": [{"name": "us-scotus"}]})  # missing id/head_block
