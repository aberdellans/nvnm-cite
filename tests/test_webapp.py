"""Webapp tests: extraction, local index, check pipeline, receipts, server.

Hermetic by construction: no network (chain access goes through a fake
gateway), no dependence on the gitignored data/ directory (indexes are
seeded into tmp_path with the production schemas).
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import sqlite3
import threading
import zipfile
from pathlib import Path

import pytest

from nvnm_cite.chain import abi
from nvnm_cite.chain import precompile as pc
from nvnm_cite.config import TESTNET
from nvnm_cite.loader.records import compact_json
from nvnm_cite.normalizer import NORMALIZER_VERSION
from nvnm_cite.receipts.anchor import AnchorPlan
from nvnm_cite.receipts.schema import RECEIPT_SCHEMA, RECEIPT_URI, receipt_registry_strings
from nvnm_cite.verifier.check import name_check
from nvnm_cite.verifier.extract import ExtractError, extract_text
from nvnm_cite.verifier.resolver import Resolution, records_query
from nvnm_cite.webapp import service as service_mod
from nvnm_cite.webapp.localindex import LocalIndex
from nvnm_cite.webapp.service import (
    CheckService,
    ReceiptService,
    TxService,
    WebAppError,
    decode_call,
)


class FakeResolver:
    """Duck-typed verifier Resolver: canned chain records, no network."""

    def __init__(self, records: dict[tuple[int, str], pc.Record]):
        self.records = records
        self.calls: list[tuple[int, str]] = []

    def resolve(self, registry_id: int, checksum: str, registry_name=None) -> Resolution:
        self.calls.append((registry_id, checksum))
        _, query = records_query(registry_id, checksum)
        return Resolution(record=self.records.get((registry_id, checksum)), query=query)


def _case_record(registry_id: int, checksum: str, metadata: str, uri: str = "https://cl/x/") -> pc.Record:
    return pc.Record(
        uri=uri, checksum=checksum, checksum_algo="cite-canonical-v1",
        metadata=metadata, timestamp="t", status="Active", record_id=1, index=1,
        is_latest=True, registry_id=registry_id,
    )


# Fixtures use the TESTNET pilot ids (flows are simulated where real anchors
# happen: the testnet).
TEST_REGISTRY_IDS = {"us-scotus": 737, "us-ca11": 738}

# Mirrors the corpus fixture rows, but as on-chain records the resolver returns.
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
        '{"cluster":88002,"name":"Third Pet. v. Fourth Resp.","year":1997}]}',
    ),
}

# ---------------------------------------------------------------- fixtures


def make_docx(paragraphs: list[str], footnotes: list[str] = ()) -> bytes:
    """Minimal but structurally honest .docx: document.xml + footnotes.xml."""

    def part(paras: list[str]) -> str:
        ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
        return f'<?xml version="1.0"?><w:document {ns}><w:body>{body}</w:body></w:document>'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", part(paragraphs))
        if footnotes:
            z.writestr("word/footnotes.xml", part(list(footnotes)))
    return buf.getvalue()


CORPUS_ROWS = [
    # cluster_id, court_id, case_name, year, slug
    (108713, "scotus", "Roe v. Wade", 1973, "roe-v-wade"),
    (77001, "ca11", "Acme Corp. v. Zenith Ltd.", 2020, "acme-v-zenith"),
    (88001, "ca11", "First Order Co. v. Second Order Co.", 1997, "first-v-second"),
    (88002, "ca11", "Third Pet. v. Fourth Resp.", 1997, "third-v-fourth"),
    (99001, "scotus", "Excluded Reporter Case", 1991, "excluded"),
]
CITATION_ROWS = [
    # citation_id, cluster_id, volume, reporter, page, canonical
    (1, 108713, "410", "U.S.", "113", "410 U.S. 113"),
    (2, 77001, "950", "F.3d", "1000", "950 F.3d 1000"),
    (3, 88001, "111", "F.3d", "897", "111 F.3d 897"),  # collision pair...
    (4, 88002, "111", "F.3d", "897", "111 F.3d 897"),  # ...same first page
    (5, 99001, "59", "U.S.L.W.", "4413", "59 U.S.L.W. 4413"),  # outside whitelist
]


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    corpus = sqlite3.connect(tmp_path / "corpus.sqlite")
    corpus.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE clusters (
            cluster_id INTEGER PRIMARY KEY, docket_id INTEGER NOT NULL,
            court_id TEXT NOT NULL, case_name TEXT NOT NULL DEFAULT '',
            date_filed TEXT NOT NULL DEFAULT '', year INTEGER,
            precedential_status TEXT NOT NULL DEFAULT '', slug TEXT NOT NULL DEFAULT '');
        CREATE TABLE citations (
            citation_id INTEGER PRIMARY KEY, cluster_id INTEGER NOT NULL,
            volume TEXT NOT NULL DEFAULT '', reporter TEXT NOT NULL DEFAULT '',
            page TEXT NOT NULL DEFAULT '', type INTEGER, canonical TEXT);
        """
    )
    corpus.executemany(
        "INSERT INTO clusters (cluster_id, docket_id, court_id, case_name, year, slug)"
        " VALUES (?, 1, ?, ?, ?, ?)",
        CORPUS_ROWS,
    )
    corpus.executemany(
        "INSERT INTO citations (citation_id, cluster_id, volume, reporter, page, canonical)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        CITATION_ROWS,
    )
    corpus.execute("INSERT INTO meta VALUES ('snapshot', '2026-03-31')")
    corpus.execute("INSERT INTO meta VALUES ('courts', 'scotus,ca11')")
    corpus.commit()
    corpus.close()
    return tmp_path


# ---------------------------------------------------------------- extract


def test_extract_txt_and_unknown_and_empty():
    out = extract_text("Roe v. Wade, 410 U.S. 113 (1973)".encode(), "brief.txt")
    assert "410 U.S. 113" in out.text and out.method.startswith("plain text")
    with pytest.raises(ExtractError):
        extract_text(b"GIF89a...", "brief.gif")
    with pytest.raises(ExtractError):
        extract_text(b"", "empty.txt")


def test_extract_docx_includes_footnotes():
    data = make_docx(
        ["Plaintiff relies on Roe v. Wade, 410 U.S. 113 (1973)."],
        footnotes=["See also Acme Corp. v. Zenith Ltd., 950 F.3d 1000 (11th Cir. 2020)."],
    )
    out = extract_text(data, "brief.docx")
    assert "410 U.S. 113" in out.text
    assert "950 F.3d 1000" in out.text  # footnote text must be read
    assert out.method == "docx"


# ---------------------------------------------------------------- local index


def test_localindex_corpus_lookup_collisions_and_whitelist(data_dir: Path):
    index = LocalIndex(data_dir)
    assert index.covered == {"us-scotus", "us-ca11"}
    hits = index.lookup_many(
        [
            ("us-scotus", "410 U.S. 113"),
            ("us-ca11", "111 F.3d 897"),
            ("us-ca11", "925 F.3d 1339"),  # absent: the Varghese gate
            ("us-scotus", "59 U.S.L.W. 4413"),  # excluded reporter: not loaded
        ]
    )
    roe = hits[("us-scotus", "410 U.S. 113")]
    assert roe.cases[0]["name"] == "Roe v. Wade" and roe.uri.endswith("/roe-v-wade/")
    collision = hits[("us-ca11", "111 F.3d 897")]
    assert collision.collision and len(collision.cases) == 2
    assert ("us-ca11", "925 F.3d 1339") not in hits
    assert ("us-scotus", "59 U.S.L.W. 4413") not in hits, "whitelist must mirror the load set"
    coverage = {row["registry"]: row for row in index.coverage()}
    assert coverage["us-scotus"]["source"] == "corpus-snapshot"
    assert coverage["us-scotus"]["records"] == 1  # only whitelisted distinct keys


def test_localindex_prefers_chain_index_when_synced(data_dir: Path):
    chain = sqlite3.connect(data_dir / "chain_index.sqlite")
    chain.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE records (
            registry_id INTEGER NOT NULL, registry_name TEXT NOT NULL,
            checksum TEXT NOT NULL, record_id INTEGER NOT NULL,
            idx INTEGER NOT NULL, is_latest INTEGER NOT NULL, uri TEXT NOT NULL,
            checksum_algo TEXT NOT NULL, metadata TEXT NOT NULL, timestamp TEXT NOT NULL,
            status TEXT NOT NULL, PRIMARY KEY (registry_id, checksum, idx));
        CREATE TABLE sync_state (
            registry_id INTEGER PRIMARY KEY, registry_name TEXT NOT NULL,
            row_offset INTEGER NOT NULL,
            head_block INTEGER NOT NULL, synced_at TEXT NOT NULL);
        """
    )
    chain.execute("INSERT INTO meta VALUES ('index_schema', '2')")
    chain.execute(
        "INSERT INTO records VALUES (738, 'us-ca11', '950 F.3d 1000', 9, 1, 1, "
        "'https://www.courtlistener.com/opinion/77001/acme-v-zenith/', 'cite-canonical-v1', "
        "'{\"cluster\":77001,\"name\":\"Acme Corp. v. Zenith Ltd.\",\"year\":2020}', 't', 'Active')"
    )
    chain.execute("INSERT INTO sync_state VALUES (738, 'us-ca11', 1, 1600000, '2026-06-12T00:00:00Z')")
    chain.commit()
    chain.close()

    index = LocalIndex(data_dir)
    coverage = {row["registry"]: row for row in index.coverage()}
    assert coverage["us-ca11"]["source"] == "chain-index"
    assert coverage["us-scotus"]["source"] == "corpus-snapshot"
    hits = index.lookup_many([("us-ca11", "950 F.3d 1000"), ("us-ca11", "111 F.3d 897")])
    assert hits[("us-ca11", "950 F.3d 1000")].source == "chain-index"
    # the chain index is authoritative once synced: corpus-only keys are not
    # consulted for that registry (chain state is what verification means)
    assert ("us-ca11", "111 F.3d 897") not in hits


# ---------------------------------------------------------------- name_check


def test_name_check_modes():
    assert name_check("Roe", "Wade", ["Roe v. Wade"]) == "match"
    assert name_check("Varghese", "China Southern Airlines", ["Acme Corp. v. Zenith Ltd."]) == "mismatch"
    assert name_check("Roe", None, ["Roe v. Wade"]) == "match"
    assert name_check(None, None, ["Roe v. Wade"]) == "unknown"
    assert name_check("Roe", "Wade", []) == "unknown"
    # vacuous parties (all stopwords) must not force a verdict
    assert name_check("United States", "The State", ["Nixon v. Fitzgerald"]) == "unknown"


# ---------------------------------------------------------------- check


BRIEF = """
Id. at 50. We begin elsewhere. The right was recognized in Roe v. Wade,
410 U. S. 113 (1973). Defendants rely on Varghese v. China Southern
Airlines Co., 925 F.3d 1339 (11th Cir. 2019), which does not exist. A
mislabeled but real citation appears as Totally Fabricated v. Name,
950 F.3d 1000 (11th Cir. 2020). Out of circuit, see Smith v. Doe,
100 F.3d 200 (2d Cir. 1996). And a court-less reporter cite, Foo v. Bar,
12 F.3d 34, ends it.
"""


def test_check_exercises_all_five_statuses():
    service = CheckService(FakeResolver(CHAIN_RECORDS), TEST_REGISTRY_IDS)
    report = service.check(BRIEF.encode(), "brief.txt")

    assert report["document"]["sha256"] == hashlib.sha256(BRIEF.encode()).hexdigest()
    assert report["privacy"]["persisted"] is False

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
    assert counts["VERIFIED"] == 2 and counts["NOT_FOUND"] == 1
    assert counts["NOT_COVERED"] == 1 and counts["AMBIGUOUS_JURISDICTION"] == 1
    assert counts["UNPARSEABLE"] >= 1
    assert report["summary"]["name_mismatches"] == 1


def test_check_canonicalizes_spacing_variant():
    # "410 U. S. 113" (line-broken/space-mangled form) must hit the registry key
    service = CheckService(FakeResolver(CHAIN_RECORDS), TEST_REGISTRY_IDS)
    report = service.check(b"Roe v. Wade, 410 U. S.\n113 (1973).", "x.txt")
    assert report["citations"][0]["canonical"] == "410 U.S. 113"
    assert report["citations"][0]["status"] == "VERIFIED"


# ---------------------------------------------------------------- receipts


FIRM = "Inveniam"
CASE = "Mata v. Avianca"
REG = "inveniam--mata-v-avianca"
DOC_SHA = "a" * 64
AGENT_ADDR = "0x" + "ab" * 20


REG_ID = 901


def fake_record(registry_id: int, checksum: str, metadata: str, index: int = 1, latest: bool = True) -> pc.Record:
    return pc.Record(
        uri=RECEIPT_URI, checksum=checksum, checksum_algo="sha256",
        metadata=metadata, timestamp="2026-06-15 15:00:00.000000001 +0000 UTC",
        status="Active", record_id=41, index=index, is_latest=latest,
        registry_id=registry_id,
    )


def minimal_receipt(sha: str, *, block: int = 1700, summary: dict | None = None) -> dict:
    """A locked v1 receipt object (non-enumerating)."""
    return {
        "agent": {"address": AGENT_ADDR},
        "chain_id": 787111,
        "checked_at_block": block,
        "document_sha256": sha,
        "normalizer_version": NORMALIZER_VERSION,
        "registries": [{"head_block": block, "id": 737, "name": "us-scotus"}],
        "schema": RECEIPT_SCHEMA,
        "summary": summary
        or {"checked": 3, "verified": 1, "not_found": 1, "not_covered": 1,
            "ambiguous": 0, "unparseable": 0, "name_mismatches": 0},
        "timestamp": "2026-06-15T00:00:00Z",
    }


class FakeGateway:
    """Duck-typed ChainGateway: canned registries and keyed records, no network.

    ``prepare_anchor`` is monkeypatched in the prepare tests, so the gateway is
    used only for the creator search, the write-probe estimate, and the lookup
    path's id-keyed reads.
    """

    def __init__(self, registries: dict | None = None, receipt_versions: dict | None = None,
                 estimate_result: dict | None = None, creator_registries: list | None = None):
        # registries: {id: name}. Default = the two court registries; there is
        # NO global receipts registry in the per-firm-per-case model.
        self._registries = registries if registries is not None else {737: "us-scotus", 738: "us-ca11"}
        self.receipt_versions = receipt_versions or {}  # {(registry_id, checksum): latest pc.Record}
        self.estimate_result = estimate_result or {"ok": True, "gas": 123456}
        self.estimates: list[bytes] = []
        self._creator_registries = creator_registries or []

    def head_block(self) -> int:
        return 1_700_000

    def chain_id(self) -> int:
        return 787111

    def registry(self, registry_id: int, max_age: float = 30.0):
        if registry_id not in self._registries:
            return None
        return {"id": registry_id, "name": self._registries[registry_id], "creator": "nvnm1fake",
                "created_at": "2026-06-15", "description": "", "metadata": ""}

    def all_registries(self, max_age: float = 60.0):
        return [
            {"id": rid, "name": name, "creator": "nvnm1fake", "created_at": "2026-06-15"}
            for rid, name in self._registries.items()
        ] + self._creator_registries

    def find_by_name(self, name: str):
        return [r for r in self.all_registries() if r["name"] == name]

    def registries_by_creator(self, creator: str):
        return list(self._creator_registries)

    def keyed_record(self, registry_id: int, checksum: str, block: str = "latest", index: int = 0):
        latest = self.receipt_versions.get((registry_id, checksum))
        if latest is None:
            return None
        if index == 0:
            return latest
        if 1 <= index < latest.index:
            return fake_record(registry_id, checksum, latest.metadata, index=index, latest=False)
        return None

    def estimate(self, from_addr: str, calldata: bytes) -> dict:
        self.estimates.append(calldata)
        return self.estimate_result

    @property
    def rpc_factory(self):
        return lambda: None  # prepare_anchor is monkeypatched, so this is never called


def make_service(gw: FakeGateway) -> ReceiptService:
    return ReceiptService(gw, TESTNET, TEST_REGISTRY_IDS)


def make_plan(*, registry_exists: bool = True, already_anchored: bool = False, create: bool = False) -> AnchorPlan:
    receipt = minimal_receipt(DOC_SHA, block=1_700_000)
    receipt_json = compact_json(receipt)
    record_calldata = None
    if not create:
        record_calldata = pc.build_add_record(
            registry_id=REG_ID, uri=RECEIPT_URI, checksum=DOC_SHA,
            checksum_algo="sha256", metadata=receipt_json,
        )
    create_registry = create_calldata = None
    if create:
        name, description, metadata = receipt_registry_strings(FIRM, CASE)
        create_registry = {"name": name, "description": description, "metadata": metadata}
        create_calldata = pc.build_add_registry(name, description, metadata)
    return AnchorPlan(
        registry=REG, registry_id=None if create else REG_ID,
        registry_exists=registry_exists,
        name_matches=None if create else True,
        document_sha256=DOC_SHA,
        checked_at_block=1_700_000, chain_id=787111,
        registries_read=receipt["registries"],
        receipt=receipt, receipt_json=receipt_json, record_calldata=record_calldata,
        create_registry=create_registry, create_calldata=create_calldata,
        already_anchored=already_anchored, report={},
    )


def test_receipt_prepare_builds_minimal_v1(monkeypatch):
    monkeypatch.setattr(service_mod, "prepare_anchor", lambda *a, **k: make_plan())
    gw = FakeGateway(
        creator_registries=[{"id": REG_ID, "name": REG, "creator": "nvnm1fake", "created_at": "t"}]
    )
    out = make_service(gw).prepare(b"%PDF-fake", "brief.pdf", firm=FIRM, case=CASE, agent_address=AGENT_ADDR)

    assert out["registry"] == REG
    assert out["registry_id"] == REG_ID
    assert out["registry_exists"] is True
    assert out["agent"] == {"address": AGENT_ADDR}
    assert f"registry #{REG_ID}" in out["registry_line"]
    assert out["chain"]["chain_id"] == 787111

    receipt = json.loads(out["receipt"]["json"])
    assert receipt["schema"] == "nvnm-cite-receipt/v1"  # LOCKED, not -draft
    assert receipt["document_sha256"] == DOC_SHA
    assert receipt["agent"] == {"address": AGENT_ADDR}
    # NON-ENUMERATING: no per-case list, and no kya_id anywhere
    assert "results" not in receipt
    assert "kya_id" not in out["receipt"]["json"]
    assert set(receipt["summary"]) == {
        "checked", "verified", "not_found", "not_covered", "ambiguous", "unparseable", "name_mismatches"
    }
    # canonical serialization + fits the cap with room to spare
    assert out["receipt"]["json"] == compact_json(receipt)
    assert out["receipt"]["bytes"] <= out["receipt"]["cap"]

    # the record calldata decodes straight back to the locked schema fields
    decoded = decode_call(bytes.fromhex(out["tx"]["data"][2:]))
    record = decoded["args"]["record"]
    assert decoded["function"] == "addRecord"
    assert record["registryId"] == REG_ID
    assert record["checksum"] == DOC_SHA
    assert record["checksumAlgo"] == "sha256"
    assert record["uri"] == RECEIPT_URI
    assert record["metadata"] == out["receipt"]["json"]
    assert out["write_probe"]["ok"] is True
    assert "setup" not in out


def test_receipt_prepare_offers_setup_when_registry_missing(monkeypatch):
    monkeypatch.setattr(service_mod, "prepare_anchor", lambda *a, **k: make_plan(registry_exists=False, create=True))
    out = make_service(FakeGateway()).prepare(b"%PDF", "brief.pdf", firm=FIRM, case=CASE, agent_address=AGENT_ADDR)

    assert out["registry_exists"] is False
    assert out["registry_id"] is None
    # v1.2.0: no record tx before the id exists — setup only
    assert "write_probe" not in out and "tx" not in out
    setup = out["setup"]
    assert setup["name"] == REG
    decoded = decode_call(bytes.fromhex(setup["tx"]["data"][2:]))
    assert decoded["function"] == "addRegistry"
    assert decoded["args"]["name"] == REG
    assert "filing receipts" in decoded["args"]["description"]
    assert setup["probe"]["ok"] is True


def test_receipt_prepare_surfaces_same_name_ambiguity():
    # Two same-name registries by the same wallet: the service must return
    # the candidate list, never pick one silently.
    gw = FakeGateway(creator_registries=[
        {"id": 901, "name": REG, "creator": "nvnm1fake", "created_at": "t1"},
        {"id": 902, "name": REG, "creator": "nvnm1fake", "created_at": "t2"},
    ])
    out = make_service(gw).prepare(b"%PDF", "brief.pdf", firm=FIRM, case=CASE, agent_address=AGENT_ADDR)
    assert out["ambiguous"] is True
    assert [c["id"] for c in out["candidates"]] == [901, 902]
    assert "tx" not in out and "setup" not in out


def test_receipt_prepare_validates_input():
    svc = make_service(FakeGateway())
    with pytest.raises(WebAppError):  # bad agent address
        svc.prepare(b"x", "f.pdf", firm=FIRM, case=CASE, agent_address="nope")
    with pytest.raises(WebAppError):  # missing firm
        svc.prepare(b"x", "f.pdf", firm="", case=CASE, agent_address=AGENT_ADDR)
    with pytest.raises(WebAppError):  # missing case
        svc.prepare(b"x", "f.pdf", firm=FIRM, case="", agent_address=AGENT_ADDR)


def test_receipt_prepare_maps_receipt_errors(monkeypatch):
    # A ReceiptError from the locked layer (e.g. un-sluggable firm/case) → a 422.
    from nvnm_cite.receipts.schema import ReceiptError

    def boom(*a, **k):
        raise ReceiptError("firm and case must each contain alphanumeric characters")

    monkeypatch.setattr(service_mod, "prepare_anchor", boom)
    with pytest.raises(WebAppError) as ei:
        make_service(FakeGateway()).prepare(b"x", "f.pdf", firm="a-firm", case="a-case", agent_address=AGENT_ADDR)
    assert ei.value.http_status == 422


def test_receipt_lookup_by_id_found_versions_and_missing():
    sha = "b" * 64
    receipt_meta = compact_json(minimal_receipt(sha, block=5))
    gw = FakeGateway(
        registries={737: "us-scotus", 738: "us-ca11", 901: REG},
        receipt_versions={(901, sha): fake_record(901, sha, receipt_meta, index=2)},
    )
    out = make_service(gw).lookup("#901", sha.upper())  # (id + hash), id from the filing line
    assert out["registry"] == REG
    assert out["found"] is True and out["registry_exists"] is True
    assert out["registry_id"] == 901 and out["registry_owner"] == "nvnm1fake"
    assert [v["index"] for v in out["versions"]] == [1, 2]
    assert out["versions"][-1]["receipt"]["schema"] == "nvnm-cite-receipt/v1"
    assert "results" not in out["versions"][-1]["receipt"]  # non-enumerating
    assert out["proof"]["request"]["method"] == "eth_call"

    # a whole pasted discovery line also works
    line = f"Citation verifications: NVNM Chain (chain 787111) registry #901 — {REG}"
    assert make_service(gw).lookup(line, sha)["found"] is True

    # registry exists but no receipt for this document → found False (the tamper signal)
    no_doc = make_service(FakeGateway(registries={901: REG})).lookup("901", "c" * 64)
    assert no_doc["registry_exists"] is True and no_doc["found"] is False

    # registry id absent → registry_exists False (bad/unknown discovery link)
    no_reg = make_service(FakeGateway(registries={})).lookup("4711", "c" * 64)
    assert no_reg["registry_exists"] is False and no_reg["found"] is False

    # bad inputs
    with pytest.raises(WebAppError):
        make_service(gw).lookup("901", "not-a-hash")
    with pytest.raises(WebAppError):
        make_service(gw).lookup("Bad Registry Name!!", sha)


def test_receipt_lookup_legacy_name_fallback():
    sha = "b" * 64
    receipt_meta = compact_json(minimal_receipt(sha, block=5))
    gw = FakeGateway(
        registries={901: REG},
        receipt_versions={(901, sha): fake_record(901, sha, receipt_meta)},
    )
    out = make_service(gw).lookup(REG, sha)  # legacy name, one match
    assert out["found"] is True and out["registry_id"] == 901
    assert "legacy" in out["note"]

    # two same-name registries: candidates surfaced, never first-row
    gw2 = FakeGateway(registries={901: REG, 902: REG})
    amb = make_service(gw2).lookup(REG, sha)
    assert amb["ambiguous"] is True
    assert sorted(c["id"] for c in amb["candidates"]) == [901, 902]

    # unknown name
    none = make_service(FakeGateway(registries={})).lookup("no--such", sha)
    assert none["registry_exists"] is False


# ---------------------------------------------------------------- decode


def test_decode_call_roundtrips_the_codec():
    calldata = pc.build_add_record(
        registry_id=82, uri="https://www.courtlistener.com/opinion/108713/roe-v-wade/",
        checksum="410 U.S. 113", checksum_algo="cite-canonical-v1",
        metadata='{"cluster":108713,"name":"Roe v. Wade","year":1973}',
    )
    decoded = decode_call(calldata)
    assert decoded["function"] == "addRecord"
    assert decoded["args"]["record"]["checksum"] == "410 U.S. 113"
    assert decoded["metadata_json"]["name"] == "Roe v. Wade"

    assert decode_call(b"\x01\x02\x03\x04garbage")["function"] is None
    assert decode_call(b"") is None


# ---------------------------------------------------------------- server


@pytest.fixture()
def live_server(data_dir: Path):
    from nvnm_cite.webapp.server import build_server

    server = build_server("127.0.0.1", 0, TESTNET, "http://127.0.0.1:9", data_dir)  # RPC unroutable on purpose
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address
    server.shutdown()


def _request(addr, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return res, data


def test_server_static_and_csp(live_server):
    res, data = _request(live_server, "GET", "/")
    assert res.status == 200 and b"NVNM" in data
    assert "default-src 'self'" in (res.getheader("Content-Security-Policy") or "")
    res, _ = _request(live_server, "GET", "/app.js")
    assert res.status == 200
    res, _ = _request(live_server, "GET", "/../pyproject.toml")
    assert res.status == 404
    res, _ = _request(live_server, "GET", "/nope.css")
    assert res.status == 404


def test_server_agent_docs(live_server):
    # The agent-facing artifacts (llms.txt convention + OpenAPI + tutorial)
    # serve from the static whitelist with the right content types.
    for path, ctype, needle in (
        ("/llms.txt", "text/plain", b"NVNM Cite"),
        ("/robots.txt", "text/plain", b"/llms.txt"),
        ("/agents.md", "text/markdown", b"/api/check"),
        ("/openapi.json", "application/json", b'"openapi"'),
    ):
        res, data = _request(live_server, "GET", path)
        assert res.status == 200, path
        assert (res.getheader("Content-Type") or "").startswith(ctype), path
        assert needle in data, path
    spec = json.loads(_request(live_server, "GET", "/openapi.json")[1])
    assert set(spec["paths"]) == {
        "/api/status", "/api/check", "/api/receipt/lookup",
        "/api/receipt/registries", "/api/tx", "/api/receipt/prepare",
    }


def test_server_check_surfaces_dead_rpc(live_server):
    # The check now reads the chain LIVE (item 0). The fixture's RPC is
    # unroutable, so the check must FAIL LOUDLY (502) — never silently report
    # the brief's citations as NOT_FOUND. This is the critical invariant:
    # a transport failure is not a chain answer.
    res, data = _request(
        live_server, "POST", "/api/check",
        body=BRIEF.encode(), headers={"X-Filename": "brief.txt", "Content-Length": str(len(BRIEF.encode()))},
    )
    assert res.status == 502
    assert b"NOT_FOUND" not in data and b"VERIFIED" not in data


def test_server_validation_errors(live_server):
    # lookup now needs a valid registry AND a 64-hex sha (registry + file, item 3)
    res, data = _request(live_server, "GET", "/api/receipt/lookup?registry=firm--case&sha256=zzz")
    assert res.status == 422 and b"SHA-256" in data
    res, data = _request(live_server, "GET", "/api/receipt/lookup?registry=Bad%20Name&sha256=" + "a" * 64)
    assert res.status == 422 and b"registry" in data
    res, data = _request(live_server, "GET", "/api/tx?hash=nope")
    assert res.status == 422
    # prepare takes a file + headers now; missing wallet/firm/case → 422 before any RPC
    res, _ = _request(live_server, "POST", "/api/receipt/prepare", body=b"hello",
                      headers={"Content-Length": "5"})
    assert res.status == 422


def test_server_status_fast_fails_on_dead_rpc(live_server):
    # The status probe runs through a SHORT-timeout gateway (task 4.5e): with an
    # unroutable RPC it must return promptly with rpc_ok False, not stall.
    import time as _time

    start = _time.monotonic()
    res, data = _request(live_server, "GET", "/api/status")
    elapsed = _time.monotonic() - start
    assert res.status == 200
    payload = json.loads(data)
    assert payload["chain"]["rpc_ok"] is False
    assert payload["telemetry"]["enabled"] is False
    assert "receipts-v1" not in data.decode()  # no global receipts registry anymore
    assert elapsed < 12, f"status probe stalled {elapsed:.1f}s — fast-fail timeout not applied"
