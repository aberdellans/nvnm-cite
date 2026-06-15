"""Anchor + verify flow, hermetic. The chain is faked via injected reader /
resolver and a fake RPC for the send path — no network, no writes.
"""

from __future__ import annotations

import hashlib

import pytest

from nvnm_cite.chain import precompile as pc
from nvnm_cite.receipts import anchor as anchor_mod
from nvnm_cite.receipts.anchor import AnchorPlan, prepare_anchor, send
from nvnm_cite.receipts.schema import RECEIPT_CHECKSUM_ALGO, RECEIPT_URI, build_receipt, summary_tally
from nvnm_cite.receipts.verify import (
    NOT_FOUND,
    REGISTRY_NOT_FOUND,
    SUMMARY_DRIFT,
    VERIFIED,
    verify_document,
)
from nvnm_cite.verifier.check import check_document
from nvnm_cite.verifier.resolver import Resolution, records_query

BRIEF = b"Roe v. Wade, 410 U.S. 113 (1973). Varghese, 925 F.3d 1339 (11th Cir. 2019)."
SHA = hashlib.sha256(BRIEF).hexdigest()
AGENT = "0x" + "ab" * 20
HEAD = 1_700_000


def _rec(registry, checksum, metadata, algo="cite-canonical-v1", uri="https://cl/x/"):
    return pc.Record(
        registry=registry, uri=uri, checksum=checksum, checksum_algo=algo, metadata=metadata,
        timestamp="t", status="Active", record_id=1, index=1, is_latest=True,
    )


ROE = _rec("us-scotus", "410 U.S. 113", '{"cluster":108713,"name":"Roe v. Wade","year":1973}')


class FakeResolver:
    def resolve(self, registry, checksum):
        _, query = records_query(registry, checksum)
        rec = ROE if (registry, checksum) == ("us-scotus", "410 U.S. 113") else None
        return Resolution(record=rec, query=query)


class FakeReader:
    def __init__(self, registries, records=None, head=HEAD):
        self._registries = registries
        self._records = records or {}
        self._head = head

    def head_block(self):
        return self._head

    def registry(self, name):
        return self._registries.get(name)

    def keyed_record(self, registry, checksum, block="latest"):
        return self._records.get((registry, checksum))


COURTS = {
    "us-scotus": {"id": 737, "name": "us-scotus", "creator": "nvnm1x", "created_at": "t"},
    "us-ca11": {"id": 738, "name": "us-ca11", "creator": "nvnm1x", "created_at": "t"},
}


# ---------------------------------------------------------------- prepare


def test_prepare_anchor_new_registry():
    reader = FakeReader(COURTS)  # target registry absent
    plan = prepare_anchor(
        BRIEF, "brief.txt", firm="Inveniam", case="Mata v. Avianca",
        agent_address=AGENT, reader=reader, resolver=FakeResolver(),
    )
    assert plan.registry == "inveniam--mata-v-avianca"
    assert plan.registry_exists is False and plan.create_registry is not None
    assert plan.already_anchored is False
    assert plan.document_sha256 == SHA
    assert plan.checked_at_block == HEAD
    assert [r["name"] for r in plan.registries_read] == ["us-scotus", "us-ca11"]
    # receipt reflects the live check tally
    assert plan.receipt["summary"]["verified"] == 1
    assert plan.receipt["summary"]["not_found"] == 1
    assert plan.writes == 2  # create registry + anchor record
    # the record calldata is exactly an addRecord of the receipt JSON
    expected = pc.build_add_record(plan.registry, RECEIPT_URI, SHA, RECEIPT_CHECKSUM_ALGO, plan.receipt_json)
    assert plan.record_calldata == expected


def test_prepare_anchor_existing_registry_already_anchored():
    receipt, receipt_json = build_receipt(
        document_sha256=SHA, checked_at_block=HEAD,
        registries=[{"id": 737, "name": "us-scotus", "head_block": HEAD}],
        summary={"checked": 2, "verified": 1, "not_found": 1, "not_covered": 0,
                 "ambiguous": 0, "unparseable": 0, "name_mismatches": 0},
        agent_address=AGENT, timestamp="t",
    )
    target = "inveniam--mata-v-avianca"
    reader = FakeReader(
        {**COURTS, target: {"id": 900, "name": target, "creator": "nvnm1x", "created_at": "t"}},
        records={(target, SHA): _rec(target, SHA, receipt_json, algo="sha256", uri=RECEIPT_URI)},
    )
    plan = prepare_anchor(
        BRIEF, "brief.txt", firm="Inveniam", case="Mata v. Avianca",
        agent_address=AGENT, reader=reader, resolver=FakeResolver(),
    )
    assert plan.registry_exists is True
    assert plan.create_registry is None and plan.writes == 1
    assert plan.already_anchored is True


# ---------------------------------------------------------------- send (writes)


class FakeRpc:
    def __init__(self):
        self.sent = []
        self._nonce = 5

    def get_transaction_count(self, address, tag="pending"):
        return self._nonce

    def gas_price(self):
        return 45_000_000_000

    def estimate_gas(self, frm, to, data):
        return 90_000

    def send_raw_transaction(self, raw):
        self._nonce += 1
        self.sent.append(raw)
        return "0x" + f"{len(self.sent):064x}"

    def wait_for_receipt(self, tx_hash, **kw):
        return {"status": "0x1", "blockNumber": "0x10", "gasUsed": "0x15f90"}


def _plan(create: bool) -> AnchorPlan:
    reg = "inveniam--mata-v-avianca"
    return AnchorPlan(
        registry=reg, registry_exists=not create, document_sha256=SHA, checked_at_block=HEAD,
        registries_read=[], receipt={}, receipt_json='{"x":1}',
        record_calldata=pc.build_add_record(reg, RECEIPT_URI, SHA, "sha256", '{"x":1}'),
        create_registry={"name": reg} if create else None,
        create_calldata=pc.build_add_registry(reg, "d", '{"k":1}') if create else None,
        already_anchored=False,
    )


def test_send_sequences_create_then_record():
    rpc = FakeRpc()
    sent = send(_plan(create=True), rpc, key=1)
    assert [s["label"] for s in sent] == ["create-registry", "anchor-receipt"]
    assert len(rpc.sent) == 2 and all(s["ok"] for s in sent)


def test_send_record_only_when_registry_exists():
    rpc = FakeRpc()
    sent = send(_plan(create=False), rpc, key=1)
    assert [s["label"] for s in sent] == ["anchor-receipt"]
    assert len(rpc.sent) == 1


# ---------------------------------------------------------------- verify


def _receipt_record(summary):
    receipt, receipt_json = build_receipt(
        document_sha256=SHA, checked_at_block=HEAD,
        registries=[{"id": 737, "name": "us-scotus", "head_block": HEAD}],
        summary=summary, agent_address=AGENT, timestamp="2026-06-15T00:00:00Z",
    )
    return _rec("inveniam--mata-v-avianca", SHA, receipt_json, algo="sha256", uri=RECEIPT_URI)


TRUE_TALLY = summary_tally(check_document(BRIEF, "brief.txt", FakeResolver()))
TARGET = "inveniam--mata-v-avianca"


def test_verify_verified():
    reader = FakeReader(
        {TARGET: {"id": 900, "name": TARGET, "creator": "nvnm1x", "created_at": "t"}},
        records={(TARGET, SHA): _receipt_record(TRUE_TALLY)},
    )
    result = verify_document(BRIEF, "brief.txt", registry=TARGET, reader=reader, resolver=FakeResolver())
    assert result.verdict == VERIFIED
    assert result.found is True and result.summary_matches is True
    assert result.recomputed_summary == TRUE_TALLY


def test_verify_tamper_is_not_found():
    reader = FakeReader(
        {TARGET: {"id": 900, "name": TARGET, "creator": "nvnm1x", "created_at": "t"}},
        records={(TARGET, SHA): _receipt_record(TRUE_TALLY)},
    )
    tampered = BRIEF + b" "  # one byte changes the fingerprint
    result = verify_document(tampered, "brief.txt", registry=TARGET, reader=reader, resolver=FakeResolver())
    assert result.found is False and result.verdict == NOT_FOUND


def test_verify_registry_not_found():
    reader = FakeReader({})  # target registry absent
    result = verify_document(BRIEF, "brief.txt", registry=TARGET, reader=reader, resolver=FakeResolver())
    assert result.verdict == REGISTRY_NOT_FOUND and result.registry_exists is False


def test_verify_summary_drift():
    drifted = dict(TRUE_TALLY, verified=TRUE_TALLY["verified"] + 4)  # receipt claims more
    reader = FakeReader(
        {TARGET: {"id": 900, "name": TARGET, "creator": "nvnm1x", "created_at": "t"}},
        records={(TARGET, SHA): _receipt_record(drifted)},
    )
    result = verify_document(BRIEF, "brief.txt", registry=TARGET, reader=reader, resolver=FakeResolver())
    assert result.verdict == SUMMARY_DRIFT and result.summary_matches is False
