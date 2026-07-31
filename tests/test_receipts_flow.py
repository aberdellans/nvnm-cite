"""Anchor + verify flow, hermetic. The chain is faked via injected reader /
resolver and a fake RPC for the send path — no network, no writes.

v1.2.0 flow shape under test: reads/writes key on the numeric registryId; a
NEW registry's record calldata is built only after the create tx confirms
(the id comes from the AddRegistry event in the receipt logs).
"""

from __future__ import annotations

import hashlib

import pytest

from nvnm_cite.chain import abi
from nvnm_cite.chain import precompile as pc
from nvnm_cite.receipts.anchor import AnchorPlan, prepare_anchor, send
from nvnm_cite.receipts.schema import RECEIPT_CHECKSUM_ALGO, RECEIPT_URI, build_receipt, summary_tally
from nvnm_cite.receipts.verify import (
    FOUND,
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
CHAIN_ID = 787111  # fixtures live on the testnet ids
TEST_REGISTRY_IDS = {"us-scotus": 737, "us-ca11": 738}
TARGET_NAME = "inveniam--mata-v-avianca"
TARGET_ID = 900


def _rec(registry_id, checksum, metadata, algo="cite-canonical-v1", uri="https://cl/x/"):
    return pc.Record(
        uri=uri, checksum=checksum, checksum_algo=algo, metadata=metadata,
        timestamp="t", status="Active", record_id=1, index=1, is_latest=True,
        registry_id=registry_id,
    )


ROE = _rec(737, "410 U.S. 113", '{"cluster":108713,"name":"Roe v. Wade","year":1973}')


class FakeResolver:
    def resolve(self, registry_id, checksum, registry_name=None):
        _, query = records_query(registry_id, checksum)
        rec = ROE if (registry_id, checksum) == (737, "410 U.S. 113") else None
        return Resolution(record=rec, query=query)


class FakeReader:
    def __init__(self, registries, records=None, head=HEAD):
        self._registries = registries  # id -> facts dict
        self._records = records or {}  # (id, checksum) -> Record
        self._head = head

    def head_block(self):
        return self._head

    def registry(self, registry_id):
        return self._registries.get(registry_id)

    def keyed_record(self, registry_id, checksum, block="latest"):
        return self._records.get((registry_id, checksum))

    def registries_by_creator(self, creator):
        return [r for r in self._registries.values() if r["creator"] == creator]


COURTS = {
    737: {"id": 737, "name": "us-scotus", "creator": "nvnm1x", "created_at": "t"},
    738: {"id": 738, "name": "us-ca11", "creator": "nvnm1x", "created_at": "t"},
}


def _prepare(reader, registry_id=None):
    return prepare_anchor(
        BRIEF, "brief.txt", firm="Inveniam", case="Mata v. Avianca",
        agent_address=AGENT, chain_id=CHAIN_ID, registry_id=registry_id,
        reader=reader, resolver=FakeResolver(), registry_ids=TEST_REGISTRY_IDS,
    )


# ---------------------------------------------------------------- prepare


def test_prepare_anchor_new_registry_defers_record_calldata():
    reader = FakeReader(COURTS)  # target registry absent -> create path
    plan = _prepare(reader, registry_id=None)
    assert plan.registry == TARGET_NAME
    assert plan.registry_id is None
    assert plan.registry_exists is False and plan.create_registry is not None
    assert plan.create_calldata is not None
    # The id does not exist until addRegistry confirms, so there is NO
    # record calldata yet — send() builds it from the AddRegistry event.
    assert plan.record_calldata is None
    assert plan.already_anchored is False
    assert plan.document_sha256 == SHA
    assert plan.checked_at_block == HEAD
    assert plan.chain_id == CHAIN_ID
    assert plan.writes == 2  # create registry + anchor record


def test_registries_read_are_the_ones_actually_consulted():
    reader = FakeReader(COURTS)
    plan = _prepare(reader)
    # BRIEF resolves one VERIFIED (us-scotus) and one NOT_FOUND (us-ca11):
    # both were READ, so both appear, keyed by id, sorted.
    assert plan.registries_read == [
        {"head_block": HEAD, "id": 737, "name": "us-scotus"},
        {"head_block": HEAD, "id": 738, "name": "us-ca11"},
    ]
    assert plan.receipt["summary"]["verified"] == 1
    assert plan.receipt["summary"]["not_found"] == 1
    assert plan.receipt["chain_id"] == CHAIN_ID


def test_prepare_anchor_existing_registry_already_anchored():
    receipt, receipt_json = build_receipt(
        document_sha256=SHA, checked_at_block=HEAD,
        registries=[{"id": 737, "name": "us-scotus", "head_block": HEAD}],
        summary={"checked": 2, "verified": 1, "not_found": 1, "not_covered": 0,
                 "ambiguous": 0, "unparseable": 0, "name_mismatches": 0},
        agent_address=AGENT, timestamp="t", chain_id=CHAIN_ID,
    )
    reader = FakeReader(
        {**COURTS, TARGET_ID: {"id": TARGET_ID, "name": TARGET_NAME, "creator": "nvnm1x", "created_at": "t"}},
        records={(TARGET_ID, SHA): _rec(TARGET_ID, SHA, receipt_json, algo="sha256", uri=RECEIPT_URI)},
    )
    plan = _prepare(reader, registry_id=TARGET_ID)
    assert plan.registry_exists is True and plan.registry_id == TARGET_ID
    assert plan.name_matches is True
    assert plan.create_registry is None and plan.writes == 1
    assert plan.already_anchored is True
    # the record calldata is exactly an id-keyed addRecord of the receipt JSON
    expected = pc.build_add_record(TARGET_ID, RECEIPT_URI, SHA, RECEIPT_CHECKSUM_ALGO, plan.receipt_json)
    assert plan.record_calldata == expected


def test_prepare_anchor_warns_on_name_mismatch_never_blocks():
    reader = FakeReader(
        {**COURTS, TARGET_ID: {"id": TARGET_ID, "name": "some-other--matter", "creator": "nvnm1x", "created_at": "t"}},
    )
    plan = _prepare(reader, registry_id=TARGET_ID)
    assert plan.name_matches is False
    assert plan.record_calldata is not None  # warn-only


def test_prepare_anchor_unknown_registry_id_errors():
    from nvnm_cite.receipts.schema import ReceiptError

    reader = FakeReader(COURTS)
    with pytest.raises(ReceiptError, match="does not exist"):
        _prepare(reader, registry_id=4711)


# ---------------------------------------------------------------- send (writes)


def _add_registry_log(registry_id: int, name: str) -> dict:
    topic0 = next(t for t, n in pc.EVENT_TOPICS.items() if n == "AddRegistry")
    data = abi.encode_values(
        [{"name": "registryId", "type": "uint64"}, {"name": "name", "type": "string"}],
        [registry_id, name],
    )
    return {
        "address": pc.PRECOMPILE_ADDRESS.lower(),
        "topics": [topic0, "0x" + "00" * 12 + AGENT.removeprefix("0x")],
        "data": "0x" + data.hex(),
    }


class FakeRpc:
    def __init__(self, new_registry_id=TARGET_ID):
        self.sent = []
        self._nonce = 5
        self._new_registry_id = new_registry_id

    def chain_id(self):
        return CHAIN_ID

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
        receipt = {"status": "0x1", "blockNumber": "0x10", "gasUsed": "0x15f90", "logs": []}
        if len(self.sent) == 1 and self._new_registry_id is not None:
            receipt["logs"] = [_add_registry_log(self._new_registry_id, TARGET_NAME)]
        return receipt


def _plan(create: bool) -> AnchorPlan:
    return AnchorPlan(
        registry=TARGET_NAME,
        registry_id=None if create else TARGET_ID,
        registry_exists=not create,
        name_matches=None if create else True,
        document_sha256=SHA, checked_at_block=HEAD, chain_id=CHAIN_ID,
        registries_read=[], receipt={}, receipt_json='{"x":1}',
        record_calldata=(
            None if create
            else pc.build_add_record(TARGET_ID, RECEIPT_URI, SHA, "sha256", '{"x":1}')
        ),
        create_registry={"name": TARGET_NAME} if create else None,
        create_calldata=pc.build_add_registry(TARGET_NAME, "d", '{"k":1}') if create else None,
        already_anchored=False,
    )


def test_send_sequences_create_then_record_and_recovers_id():
    rpc = FakeRpc()
    plan = _plan(create=True)
    sent = send(plan, rpc, key=1, chain_id=CHAIN_ID)
    assert [s["label"] for s in sent] == ["create-registry", "anchor-receipt"]
    assert len(rpc.sent) == 2 and all(s["ok"] for s in sent)
    # the id was recovered from the AddRegistry event and used for addRecord
    assert plan.registry_id == TARGET_ID
    assert sent[0]["registry_id"] == TARGET_ID
    expected = pc.build_add_record(TARGET_ID, RECEIPT_URI, SHA, "sha256", '{"x":1}')
    assert plan.record_calldata == expected


def test_send_halts_when_create_confirms_without_event():
    rpc = FakeRpc(new_registry_id=None)  # confirmed receipt but no event log
    with pytest.raises(RuntimeError, match="AddRegistry event"):
        send(_plan(create=True), rpc, key=1, chain_id=CHAIN_ID)


def test_send_record_only_when_registry_exists():
    rpc = FakeRpc()
    sent = send(_plan(create=False), rpc, key=1, chain_id=CHAIN_ID)
    assert [s["label"] for s in sent] == ["anchor-receipt"]
    assert len(rpc.sent) == 1


def test_send_refuses_chain_mismatch():
    rpc = FakeRpc()
    with pytest.raises(RuntimeError, match="refusing to write"):
        send(_plan(create=False), rpc, key=1, chain_id=1611)


# ---------------------------------------------------------------- verify


def _receipt_record(summary):
    receipt, receipt_json = build_receipt(
        document_sha256=SHA, checked_at_block=HEAD,
        registries=[{"id": 737, "name": "us-scotus", "head_block": HEAD}],
        summary=summary, agent_address=AGENT, timestamp="2026-06-15T00:00:00Z",
        chain_id=CHAIN_ID,
    )
    return _rec(TARGET_ID, SHA, receipt_json, algo="sha256", uri=RECEIPT_URI)


TRUE_TALLY = summary_tally(
    check_document(BRIEF, "brief.txt", FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
)
TARGET_FACTS = {TARGET_ID: {"id": TARGET_ID, "name": TARGET_NAME, "creator": "nvnm1x", "created_at": "t"}}


def _verify(data, reader, **kw):
    return verify_document(
        data, "brief.txt", registry_id=TARGET_ID, reader=reader,
        resolver=FakeResolver(), registry_ids=TEST_REGISTRY_IDS, **kw
    )


def test_verify_verified():
    reader = FakeReader(TARGET_FACTS, records={(TARGET_ID, SHA): _receipt_record(TRUE_TALLY)})
    result = _verify(BRIEF, reader)
    assert result.verdict == VERIFIED
    assert result.found is True and result.summary_matches is True
    assert result.recomputed_summary == TRUE_TALLY
    assert result.registry_name == TARGET_NAME


def test_verify_tamper_is_not_found():
    reader = FakeReader(TARGET_FACTS, records={(TARGET_ID, SHA): _receipt_record(TRUE_TALLY)})
    tampered = BRIEF + b" "  # one byte changes the fingerprint
    result = _verify(tampered, reader)
    assert result.found is False and result.verdict == NOT_FOUND


def test_verify_registry_not_found():
    reader = FakeReader({})  # target registry absent
    result = _verify(BRIEF, reader)
    assert result.verdict == REGISTRY_NOT_FOUND and result.registry_exists is False


def test_verify_summary_drift():
    drifted = dict(TRUE_TALLY, verified=TRUE_TALLY["verified"] + 4)  # receipt claims more
    reader = FakeReader(TARGET_FACTS, records={(TARGET_ID, SHA): _receipt_record(drifted)})
    result = _verify(BRIEF, reader)
    assert result.verdict == SUMMARY_DRIFT and result.summary_matches is False


def test_verify_chain_mismatch_skips_recompute():
    reader = FakeReader(TARGET_FACTS, records={(TARGET_ID, SHA): _receipt_record(TRUE_TALLY)})
    result = _verify(BRIEF, reader, expected_chain_id=1611)  # receipt says 787111
    assert result.verdict == FOUND
    assert result.summary_matches is None
    assert any("anchored on chain 787111" in n for n in result.notes)
