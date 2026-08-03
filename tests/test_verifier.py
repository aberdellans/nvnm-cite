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


def _case_record(registry_id: int, checksum: str, metadata: str, uri: str = "https://cl/x/") -> pc.Record:
    return pc.Record(
        uri=uri, checksum=checksum, checksum_algo="cite-canonical-v1",
        metadata=metadata, timestamp="t", status="Active", record_id=1, index=1,
        is_latest=True, registry_id=registry_id,
    )


# Coverage map for these hermetic tests: the TESTNET pilot ids.
TEST_REGISTRY_IDS = {"us-scotus": 737, "us-ca11": 738}

CHAIN_RECORDS = {
    (737, "410 U.S. 113"): _case_record(
        737, "410 U.S. 113", '{"cluster":108713,"name":"Roe v. Wade","year":1973}',
        "https://www.courtlistener.com/opinion/108713/roe-v-wade/",
    ),
    (738, "950 F.3d 1000"): _case_record(
        738, "950 F.3d 1000", '{"cluster":77001,"name":"Acme Corp. v. Zenith Ltd.","year":2020}',
    ),
    (738, "111 F.3d 897"): _case_record(
        738, "111 F.3d 897",
        '{"cases":[{"cluster":88001,"name":"First Order Co. v. Second Order Co.","year":1997},'
        '{"cluster":88002,"name":"Third Pet. v. Fourth Resp.","year":1997}],"omitted":3}',
    ),
}


class FakeResolver:
    def __init__(self, records=None):
        self.records = records or CHAIN_RECORDS
        self.calls: list[tuple[int, str]] = []

    def resolve(self, registry_id: int, checksum: str, registry_name=None) -> Resolution:
        self.calls.append((registry_id, checksum))
        _, query = records_query(registry_id, checksum)
        return Resolution(record=self.records.get((registry_id, checksum)), query=query)


class RaisingResolver:
    """A chain that is down: every resolve raises a transport error."""

    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    def resolve(self, registry_id: int, checksum: str, registry_name=None) -> Resolution:
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
    report = check_document(BRIEF.encode(), "brief.txt", resolver, registry_ids=TEST_REGISTRY_IDS)

    by_key = {c["canonical"] or c["as_written"]: c for c in report["citations"]}
    assert by_key["410 U.S. 113"]["status"] == "VERIFIED"
    assert by_key["410 U.S. 113"]["name_check"] == "match"
    assert by_key["410 U.S. 113"]["record"]["cases"][0]["name"] == "Roe v. Wade"
    assert by_key["925 F.3d 1339"]["status"] == "NOT_FOUND"
    assert by_key["950 F.3d 1000"]["status"] == "VERIFIED"
    assert by_key["950 F.3d 1000"]["name_check"] == "mismatch"
    assert by_key["100 F.3d 200"]["status"] == "NOT_COVERED"
    assert by_key["12 F.3d 34"]["status"] == "AMBIGUOUS_JURISDICTION"
    # 1.2.0: the document-opening orphan "Id." is accounted for in the
    # unresolved-references block, no longer an UNPARSEABLE table row.
    refs = report["unresolved_references"]
    assert refs["count"] == 1
    assert refs["forms"][0]["as_written"].lower().startswith("id.")
    assert not any(c["status"] == "UNPARSEABLE" for c in report["citations"])

    counts = report["summary"]["by_status"]
    assert counts == {
        "VERIFIED": 2, "NOT_FOUND": 1, "NOT_COVERED": 1,
        "AMBIGUOUS_JURISDICTION": 1, "UNPARSEABLE": 0,
    }
    assert report["summary"]["name_mismatches"] == 1


def test_parallel_citations_cluster_into_one_authority():
    # "410 U.S. 113, 93 S. Ct. 705 (1973)" is ONE authority cited by two
    # reporters. The strongest member (VERIFIED official cite) is the row;
    # the S. Ct. parallel stays visible under "parallels".
    text = "Roe v. Wade, 410 U.S. 113, 93 S. Ct. 705 (1973), controls."
    report = check_text(text, FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
    assert len(report["citations"]) == 1
    row = report["citations"][0]
    assert row["canonical"] == "410 U.S. 113" and row["status"] == "VERIFIED"
    assert [p["canonical"] for p in row["parallels"]] == ["93 S. Ct. 705"]
    assert row["parallels"][0]["status"] == "NOT_FOUND"
    # Authority-level tally: one VERIFIED, nothing else.
    assert report["summary"]["by_status"]["VERIFIED"] == 1
    assert report["summary"]["by_status"]["NOT_FOUND"] == 0


def test_parallel_run_with_pin_page_between_members_clusters():
    # Bluebook style interleaves a pin page before the parallel reporter:
    # "58 Ohio St.2d 108, 110, 388 N.E.2d 1370". Still one authority.
    text = "Counsel v. Pub. Util. Comm., 58 Ohio St.2d 108, 110, 388 N.E.2d 1370 (1979)."
    report = check_text(text, FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
    assert len(report["citations"]) == 1
    assert len(report["citations"][0]["parallels"]) == 1


def test_string_cites_with_semicolons_do_not_cluster():
    text = (
        "See Roe v. Wade, 410 U.S. 113 (1973); Acme Corp. v. Zenith Ltd., "
        "950 F.3d 1000 (11th Cir. 2020)."
    )
    report = check_text(text, FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
    assert len(report["citations"]) == 2
    assert all(c["parallels"] == [] for c in report["citations"])


def test_law_section_tokens_are_accounted_not_unparseable():
    text = "The Act, §2000d, applies. See Roe v. Wade, 410 U.S. 113 (1973)."
    report = check_text(text, FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
    assert report["summary"]["law_sections_out_of_scope"]["count"] == 1
    assert "§2000d" in report["summary"]["law_sections_out_of_scope"]["examples"][0]
    assert not any(c["status"] == "UNPARSEABLE" for c in report["citations"])


def test_scotus_not_found_notes_parallel_reporter_lag():
    text = "Fulton v. City of Philadelphia, 141 S. Ct. 1868 (2021)."
    report = check_text(text, FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
    row = report["citations"][0]
    assert row["status"] == "NOT_FOUND"
    assert "parallel U.S. / S. Ct." in row["reason"]


def test_not_covered_never_hits_the_chain():
    # A registry outside the coverage map must NOT trigger a chain read
    # (NOT_COVERED comes from the pinned manifest, no RPC).
    resolver = FakeResolver()
    check_document(BRIEF.encode(), "brief.txt", resolver, registry_ids=TEST_REGISTRY_IDS)
    assert all("100 F.3d 200" != checksum for _, checksum in resolver.calls)
    # only the two covered citations were resolved
    assert set(resolver.calls) == {(737, "410 U.S. 113"), (738, "950 F.3d 1000"), (738, "925 F.3d 1339")}


def test_registry_id_travels_with_resolved_citations():
    report = check_document(BRIEF.encode(), "brief.txt", FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
    by_key = {c["canonical"] or c["as_written"]: c for c in report["citations"]}
    assert by_key["410 U.S. 113"]["registry_id"] == 737
    assert by_key["925 F.3d 1339"]["registry_id"] == 738
    assert by_key["100 F.3d 200"]["registry_id"] is None  # NOT_COVERED, no id


def test_expanded_coverage_not_found_carries_caution():
    # A NOT_FOUND outside the proven federal-appellate set (here a district
    # court) is flagged expanded-coverage: a signal to verify, never proof of
    # fabrication. Federal-appellate NOT_FOUNDs carry no such marker.
    text = (
        "See Foo v. Bar, 100 F. Supp. 2d 500 (S.D.N.Y. 2000). "
        "Also Varghese v. China Southern Airlines Co., 925 F.3d 1339 (11th Cir. 2019)."
    )
    ids = dict(TEST_REGISTRY_IDS, **{"us-nysd": 1500})
    report = check_text(text, FakeResolver(), registry_ids=ids)
    by_key = {c["canonical"]: c for c in report["citations"]}
    district = by_key["100 F. Supp. 2d 500"]
    assert district["status"] == "NOT_FOUND"
    assert district["confidence"] == "expanded-coverage"
    assert "never" in district["caution"]
    appellate = by_key["925 F.3d 1339"]
    assert appellate["status"] == "NOT_FOUND"
    assert appellate["confidence"] is None
    assert appellate["caution"] is None


def test_keyed_results_carry_a_replayable_query():
    report = check_document(BRIEF.encode(), "brief.txt", FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
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
    report = check_document(BRIEF.encode(), "brief.txt", FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
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
            check_text(BRIEF, resolver, registry_ids=TEST_REGISTRY_IDS)
        assert resolver.calls >= 1  # it did attempt the read


def test_oversize_text_raises_checkerror():
    with pytest.raises(CheckError) as exc:
        check_text("x" * 2_000_001, FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
    assert exc.value.http_status == 413


def test_empty_document_raises_checkerror():
    with pytest.raises(CheckError):
        check_document(b"", "empty.txt", FakeResolver(), registry_ids=TEST_REGISTRY_IDS)


def test_clean_document_has_no_findings():
    report = check_document(b"This brief cites no cases at all.", "x.txt", FakeResolver(), registry_ids=TEST_REGISTRY_IDS)
    assert report["citations"] == []
    assert report["summary"]["occurrences"] == 0


# ---------------------------------------------------------------- record_view


def test_record_view_single_and_collision():
    single = record_view(CHAIN_RECORDS[(737, "410 U.S. 113")])
    assert single["collision"] is False
    assert single["cases"][0]["name"] == "Roe v. Wade"
    assert single["more_cases"] == 0
    assert single["source"] == "chain (live)"

    coll = record_view(CHAIN_RECORDS[(738, "111 F.3d 897")])
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
    res = resolver.resolve(737, "999 U.S. 1")
    assert res.record is None  # genuine absence -> NOT_FOUND upstream
    assert res.query["params"][0]["to"] == pc.PRECOMPILE_ADDRESS


def test_chainresolver_transport_error_propagates():
    resolver = ChainResolver(lambda: _RpcStub(error=ConnectionRefusedError("down")))
    with pytest.raises(ConnectionRefusedError):
        resolver.resolve(737, "410 U.S. 113")


def test_chainresolver_non_miss_rpc_error_propagates():
    err = RpcError("eth_call", -32000, "execution reverted")
    resolver = ChainResolver(lambda: _RpcStub(error=err))
    with pytest.raises(RpcError):
        resolver.resolve(737, "410 U.S. 113")


def test_is_keyed_miss_marker():
    assert pc.is_keyed_miss(RpcError("eth_call", 3, "collections: not found: key 'x'"))
    assert not pc.is_keyed_miss(RpcError("eth_call", 3, "execution reverted"))
    assert not pc.is_keyed_miss(ConnectionRefusedError("down"))
