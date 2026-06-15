"""The shared verifier core: extract -> normalize -> LIVE chain read -> status.

Hermetic: the chain is a fake Resolver (canned records / canned errors), so
these pin the verification LOGIC without a network. The live testnet
round-trip is test_verifier_live.py; PDF extraction recall is
test_verifier_recall.py.
"""

from __future__ import annotations

import pytest

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import RpcError
from nvnm_cite.verifier.check import (
    CheckError,
    check_document,
    check_text,
    record_view,
)
from nvnm_cite.verifier.resolver import ChainResolver, Resolution, records_query


# ---------------------------------------------------------------- fakes


def _case_record(registry: str, checksum: str, metadata: str, uri: str = "https://cl/x/") -> pc.Record:
    return pc.Record(
        registry=registry, uri=uri, checksum=checksum, checksum_algo="cite-canonical-v1",
        metadata=metadata, timestamp="t", status="Active", record_id=1, index=1, is_latest=True,
    )


CHAIN_RECORDS = {
    ("us-scotus", "410 U.S. 113"): _case_record(
        "us-scotus", "410 U.S. 113", '{"cluster":108713,"name":"Roe v. Wade","year":1973}',
        "https://www.courtlistener.com/opinion/108713/roe-v-wade/",
    ),
    ("us-ca11", "950 F.3d 1000"): _case_record(
        "us-ca11", "950 F.3d 1000", '{"cluster":77001,"name":"Acme Corp. v. Zenith Ltd.","year":2020}',
    ),
    ("us-ca11", "111 F.3d 897"): _case_record(
        "us-ca11", "111 F.3d 897",
        '{"cases":[{"cluster":88001,"name":"First Order Co. v. Second Order Co.","year":1997},'
        '{"cluster":88002,"name":"Third Pet. v. Fourth Resp.","year":1997}],"omitted":3}',
    ),
}


class FakeResolver:
    def __init__(self, records=None):
        self.records = records or CHAIN_RECORDS
        self.calls: list[tuple[str, str]] = []

    def resolve(self, registry: str, checksum: str) -> Resolution:
        self.calls.append((registry, checksum))
        _, query = records_query(registry, checksum)
        return Resolution(record=self.records.get((registry, checksum)), query=query)


class RaisingResolver:
    """A chain that is down: every resolve raises a transport error."""

    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    def resolve(self, registry: str, checksum: str) -> Resolution:
        self.calls += 1
        raise self.error


BRIEF = """
Id. at 50. We begin elsewhere. The right was recognized in Roe v. Wade,
410 U. S. 113 (1973). Defendants rely on Varghese v. China Southern
Airlines Co., 925 F.3d 1339 (11th Cir. 2019), which does not exist. A
mislabeled but real citation appears as Totally Fabricated v. Name,
950 F.3d 1000 (11th Cir. 2020). Out of circuit, see Smith v. Doe,
100 F.3d 200 (2d Cir. 1996). And a court-less reporter cite, Foo v. Bar,
12 F.3d 34, ends it.
"""


# ---------------------------------------------------------------- statuses


def test_all_five_statuses_and_name_mismatch():
    resolver = FakeResolver()
    report = check_document(BRIEF.encode(), "brief.txt", resolver)

    by_key = {c["canonical"] or c["as_written"]: c for c in report["citations"]}
    assert by_key["410 U.S. 113"]["status"] == "VERIFIED"
    assert by_key["410 U.S. 113"]["name_check"] == "match"
    assert by_key["410 U.S. 113"]["record"]["cases"][0]["name"] == "Roe v. Wade"
    assert by_key["925 F.3d 1339"]["status"] == "NOT_FOUND"
    assert by_key["950 F.3d 1000"]["status"] == "VERIFIED"
    assert by_key["950 F.3d 1000"]["name_check"] == "mismatch"
    assert by_key["100 F.3d 200"]["status"] == "NOT_COVERED"
    assert by_key["12 F.3d 34"]["status"] == "AMBIGUOUS_JURISDICTION"
    unparseable = [c for c in report["citations"] if c["status"] == "UNPARSEABLE"]
    assert unparseable and "orphan short form" in (unparseable[0]["reason"] or "")

    counts = report["summary"]["by_status"]
    assert counts == {
        "VERIFIED": 2, "NOT_FOUND": 1, "NOT_COVERED": 1,
        "AMBIGUOUS_JURISDICTION": 1, "UNPARSEABLE": 1,
    }
    assert report["summary"]["name_mismatches"] == 1


def test_not_covered_never_hits_the_chain():
    # A registry outside the fixed covered list must NOT trigger a chain read
    # (it is NOT_COVERED by the built-in list, Albert's decision 2026-06-14).
    resolver = FakeResolver()
    check_document(BRIEF.encode(), "brief.txt", resolver)
    assert ("us-ca2", "100 F.3d 200") not in resolver.calls
    # only the two covered citations were resolved
    assert set(resolver.calls) == {("us-scotus", "410 U.S. 113"), ("us-ca11", "950 F.3d 1000"), ("us-ca11", "925 F.3d 1339")}


def test_keyed_results_carry_a_replayable_query():
    report = check_document(BRIEF.encode(), "brief.txt", FakeResolver())
    by_key = {c["canonical"] or c["as_written"]: c for c in report["citations"]}
    # VERIFIED and NOT_FOUND came from a live read -> the exact query travels back
    for k in ("410 U.S. 113", "925 F.3d 1339"):
        q = by_key[k]["query"]
        assert q["method"] == "eth_call"
        assert q["params"][0]["to"] == pc.PRECOMPILE_ADDRESS
        assert q["params"][0]["data"].startswith("0x")
    # statuses that need no chain read carry no query
    assert by_key["100 F.3d 200"]["query"] is None
    assert by_key["12 F.3d 34"]["query"] is None


def test_document_binds_sha256_and_privacy_note():
    report = check_document(BRIEF.encode(), "brief.txt", FakeResolver())
    import hashlib

    assert report["document"]["sha256"] == hashlib.sha256(BRIEF.encode()).hexdigest()
    assert report["privacy"]["persisted"] is False
    # the honest live-read note, NOT the old "no network request" claim
    assert "no network" not in report["privacy"]["note"].lower()
    assert "read" in report["privacy"]["note"].lower()


# ---------------------------------------------------------------- transport != NOT_FOUND


def test_transport_failure_propagates_not_treated_as_not_found():
    # The single most important invariant: a dead/erroring chain must raise,
    # NEVER silently classify the brief's citations as NOT_FOUND.
    for err in (ConnectionRefusedError("refused"), RpcError("eth_call", -32000, "execution reverted")):
        resolver = RaisingResolver(err)
        with pytest.raises(type(err)):
            check_text(BRIEF, resolver)
        assert resolver.calls >= 1  # it did attempt the read


def test_oversize_text_raises_checkerror():
    with pytest.raises(CheckError) as exc:
        check_text("x" * 2_000_001, FakeResolver())
    assert exc.value.http_status == 413


def test_empty_document_raises_checkerror():
    with pytest.raises(CheckError):
        check_document(b"", "empty.txt", FakeResolver())


def test_clean_document_has_no_findings():
    report = check_document(b"This brief cites no cases at all.", "x.txt", FakeResolver())
    assert report["citations"] == []
    assert report["summary"]["occurrences"] == 0


# ---------------------------------------------------------------- record_view


def test_record_view_single_and_collision():
    single = record_view(CHAIN_RECORDS[("us-scotus", "410 U.S. 113")])
    assert single["collision"] is False
    assert single["cases"][0]["name"] == "Roe v. Wade"
    assert single["more_cases"] == 0
    assert single["source"] == "chain (live)"

    coll = record_view(CHAIN_RECORDS[("us-ca11", "111 F.3d 897")])
    assert coll["collision"] is True
    assert len(coll["cases"]) == 2
    assert coll["more_cases"] == 3  # the metadata's "omitted" count is surfaced


# ---------------------------------------------------------------- ChainResolver error semantics


class _RpcStub:
    def __init__(self, error=None, result=b""):
        self.error = error
        self.result = result

    def eth_call(self, to, data, block="latest"):
        if self.error is not None:
            raise self.error
        return self.result


def test_chainresolver_keyed_miss_is_none():
    err = RpcError("eth_call", 3, "collections: not found: key 'us-scotus/999 U.S. 1'")
    resolver = ChainResolver(lambda: _RpcStub(error=err))
    res = resolver.resolve("us-scotus", "999 U.S. 1")
    assert res.record is None  # genuine absence -> NOT_FOUND upstream
    assert res.query["params"][0]["to"] == pc.PRECOMPILE_ADDRESS


def test_chainresolver_transport_error_propagates():
    resolver = ChainResolver(lambda: _RpcStub(error=ConnectionRefusedError("down")))
    with pytest.raises(ConnectionRefusedError):
        resolver.resolve("us-scotus", "410 U.S. 113")


def test_chainresolver_non_miss_rpc_error_propagates():
    err = RpcError("eth_call", -32000, "execution reverted")
    resolver = ChainResolver(lambda: _RpcStub(error=err))
    with pytest.raises(RpcError):
        resolver.resolve("us-scotus", "410 U.S. 113")


def test_is_keyed_miss_marker():
    assert pc.is_keyed_miss(RpcError("eth_call", 3, "collections: not found: key 'x'"))
    assert not pc.is_keyed_miss(RpcError("eth_call", 3, "execution reverted"))
    assert not pc.is_keyed_miss(ConnectionRefusedError("down"))
