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
from nvnm_cite.loader.records import compact_json
from nvnm_cite.webapp.extract import ExtractError, extract_text
from nvnm_cite.webapp.localindex import LocalIndex
from nvnm_cite.webapp.service import (
    CheckService,
    ReceiptService,
    ReceiptTooLarge,
    TxService,
    WebAppError,
    build_receipt,
    decode_call,
    name_check,
)

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
            registry TEXT NOT NULL, checksum TEXT NOT NULL, record_id INTEGER NOT NULL,
            idx INTEGER NOT NULL, is_latest INTEGER NOT NULL, uri TEXT NOT NULL,
            checksum_algo TEXT NOT NULL, metadata TEXT NOT NULL, timestamp TEXT NOT NULL,
            status TEXT NOT NULL, PRIMARY KEY (registry, checksum, idx));
        CREATE TABLE sync_state (
            registry TEXT PRIMARY KEY, row_offset INTEGER NOT NULL,
            head_block INTEGER NOT NULL, synced_at TEXT NOT NULL);
        """
    )
    chain.execute(
        "INSERT INTO records VALUES ('us-ca11', '950 F.3d 1000', 9, 1, 1, "
        "'https://www.courtlistener.com/opinion/77001/acme-v-zenith/', 'cite-canonical-v1', "
        "'{\"cluster\":77001,\"name\":\"Acme Corp. v. Zenith Ltd.\",\"year\":2020}', 't', 'Active')"
    )
    chain.execute("INSERT INTO sync_state VALUES ('us-ca11', 1, 1600000, '2026-06-12T00:00:00Z')")
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


def test_check_exercises_all_five_statuses(data_dir: Path):
    service = CheckService(LocalIndex(data_dir))
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


def test_check_canonicalizes_spacing_variant(data_dir: Path):
    # "410 U. S. 113" (line-broken/space-mangled form) must hit the registry key
    service = CheckService(LocalIndex(data_dir))
    report = service.check(b"Roe v. Wade, 410 U. S.\n113 (1973).", "x.txt")
    assert report["citations"][0]["canonical"] == "410 U.S. 113"
    assert report["citations"][0]["status"] == "VERIFIED"


# ---------------------------------------------------------------- receipts


def fake_record(registry: str, checksum: str, metadata: str, index: int = 1, latest: bool = True) -> pc.Record:
    return pc.Record(
        registry=registry, uri="urn:nvnm-cite:receipt:v1" if registry == "receipts-v1" else "https://example",
        checksum=checksum, checksum_algo="sha256" if registry == "receipts-v1" else "cite-canonical-v1",
        metadata=metadata, timestamp="2026-06-12 15:00:00.000000001 +0000 UTC",
        status="Active", record_id=41, index=index, is_latest=latest,
    )


class FakeGateway:
    """Duck-typed ChainGateway: canned registries and keyed records."""

    def __init__(self, receipts_exists: bool = True, receipt_versions: dict | None = None):
        self.receipts_exists = receipts_exists
        self.receipt_versions = receipt_versions or {}
        self.estimates: list[bytes] = []

    def head_block(self) -> int:
        return 1_700_000

    def chain_id(self) -> int:
        return 787111

    def registry(self, name: str, max_age: float = 30.0):
        table = {"us-scotus": 737, "us-ca11": 738, "receipts-v1": 900}
        if name == "receipts-v1" and not self.receipts_exists:
            return None
        if name not in table:
            return None
        return {"id": table[name], "name": name, "creator": "nvnm1fake", "created_at": "t", "description": "", "metadata": ""}

    def keyed_record(self, registry: str, checksum: str, block: str = "latest", index: int = 0):
        if registry == "us-scotus" and checksum == "410 U.S. 113":
            return fake_record(registry, checksum, '{"cluster":108713,"name":"Roe v. Wade","year":1973}')
        if registry == "receipts-v1" and checksum in self.receipt_versions:
            latest = self.receipt_versions[checksum]
            if index == 0:
                return latest
            if 1 <= index < latest.index:
                return fake_record(registry, checksum, latest.metadata, index=index, latest=False)
        return None

    def estimate(self, from_addr: str, calldata: bytes) -> dict:
        self.estimates.append(calldata)
        return {"ok": True, "gas": 123456}


DOC_SHA = "a" * 64
AGENT = {"address": "0x" + "ab" * 20, "kya_id": "kya:test-agent"}


def prepare_payload() -> dict:
    return {
        "document_sha256": DOC_SHA,
        "agent": AGENT,
        "results": [
            {"registry": "us-scotus", "canonical": "410 U.S. 113", "as_written": "410 U. S. 113",
             "occurrences": 3, "plaintiff": "Roe", "defendant": "Wade", "status": "VERIFIED"},
            {"registry": "us-ca11", "canonical": "925 F.3d 1339", "as_written": "925 F.3d 1339",
             "occurrences": 1, "plaintiff": "Varghese", "defendant": "China Southern Airlines",
             "status": "VERIFIED"},  # client lies; the chain re-check must override
            {"registry": "us-ca2", "canonical": "100 F.3d 200", "as_written": "100 F.3d 200",
             "occurrences": 1, "status": "NOT_COVERED"},
            {"registry": None, "canonical": "12 F.3d 34", "as_written": "12 F.3d 34",
             "occurrences": 1, "status": "AMBIGUOUS_JURISDICTION"},
            {"registry": None, "canonical": None, "as_written": "Id.", "occurrences": 2,
             "status": "UNPARSEABLE"},
        ],
    }


def test_receipt_prepare_rechecks_against_chain():
    service = ReceiptService(FakeGateway())
    out = service.prepare(prepare_payload())

    receipt = json.loads(out["receipt"]["json"])
    assert receipt["schema"] == "nvnm-cite-receipt/v1-draft"
    assert receipt["document_sha256"] == DOC_SHA
    assert receipt["checked_at_block"] == 1_700_000
    assert receipt["agent"] == {"address": AGENT["address"], "kya_id": "kya:test-agent"}
    names = [r["name"] for r in receipt["registries"]]
    assert names == ["us-scotus", "us-ca11"]

    by_c = {r.get("c", r.get("w")): r for r in receipt["results"]}
    roe = by_c["410 U.S. 113"]
    assert roe["s"] == "V" and roe["k"] == 108713 and roe["n"] == "m" and roe["o"] == 3
    assert roe["g"] == 0 and roe["w"] == "410 U. S. 113"
    assert by_c["925 F.3d 1339"]["s"] == "N", "client-claimed VERIFIED must not survive a chain miss"
    assert by_c["100 F.3d 200"]["g"] == "us-ca2" and by_c["100 F.3d 200"]["s"] == "C"
    assert by_c["12 F.3d 34"]["s"] == "A"
    assert by_c["Id."]["s"] == "U"

    # canonical serialization: sorted keys, no whitespace
    assert out["receipt"]["json"] == compact_json(receipt)
    assert out["receipt"]["bytes"] <= out["receipt"]["cap"]

    # the prepared calldata must decode straight back to the schema fields
    data = bytes.fromhex(out["tx"]["data"][2:])
    decoded = decode_call(data)
    record = decoded["args"]["record"]
    assert decoded["function"] == "addRecord"
    assert record["registry"] == "receipts-v1"
    assert record["checksum"] == DOC_SHA
    assert record["checksumAlgo"] == "sha256"
    assert record["uri"] == "urn:nvnm-cite:receipt:v1"
    assert record["metadata"] == out["receipt"]["json"]
    assert record["status"] == "Active"
    assert out["write_probe"]["ok"] is True


def test_receipt_prepare_offers_setup_when_registry_missing():
    service = ReceiptService(FakeGateway(receipts_exists=False))
    out = service.prepare(prepare_payload())
    assert out["receipts_registry"]["exists"] is False
    setup = out["setup"]
    assert setup["registry"] == "receipts-v1"
    assert setup["metadata"] == '{"schema":"nvnm-cite-receipt/v1","spec":"cite-canonical-v1"}'
    decoded = decode_call(bytes.fromhex(setup["tx"]["data"][2:]))
    assert decoded["function"] == "addRegistry"
    assert decoded["args"]["name"] == "receipts-v1"
    assert "filing receipts" in decoded["args"]["description"]


def test_receipt_prepare_rejects_bad_input():
    service = ReceiptService(FakeGateway())
    with pytest.raises(WebAppError):
        service.prepare({"document_sha256": "xyz", "agent": AGENT, "results": [{}]})
    with pytest.raises(WebAppError):
        service.prepare({"document_sha256": DOC_SHA, "agent": {"address": "nope"}, "results": [{}]})
    with pytest.raises(WebAppError):
        service.prepare({"document_sha256": DOC_SHA, "agent": AGENT, "results": []})


def test_receipt_compaction_ladder_and_overflow():
    registries = [{"head_block": 1, "id": 737, "name": "us-scotus"}]
    verified = [
        {"c": f"{v} U.S. {v}", "g": 0, "k": v, "n": "m", "s": "V", "w": f"{v} U. S. {v}"}
        for v in range(100, 160)
    ]
    receipt_json, compactions = build_receipt(
        document_sha256=DOC_SHA, checked_at_block=1, registries=registries,
        results=verified, agent={"address": "0x" + "ab" * 20}, timestamp="2026-06-12T00:00:00Z",
    )
    assert compactions, "sixty verified entries cannot fit uncompacted"
    parsed = json.loads(receipt_json)
    assert parsed["verified_omitted"] == 60
    assert len(receipt_json.encode()) <= 2048

    # NOT_FOUND entries are never collapsed: overflow must raise, not lie
    not_found = [{"c": f"{v} F.3d {v}", "g": 0, "s": "N"} for v in range(100, 200)]
    with pytest.raises(ReceiptTooLarge):
        build_receipt(
            document_sha256=DOC_SHA, checked_at_block=1, registries=registries,
            results=not_found, agent={"address": "0x" + "ab" * 20}, timestamp="2026-06-12T00:00:00Z",
        )


def test_receipt_lookup_versions_and_missing_registry():
    sha = "b" * 64
    receipt_meta = compact_json(
        {"schema": "nvnm-cite-receipt/v1-draft", "document_sha256": sha,
         "checked_at_block": 5, "results": [{"c": "410 U.S. 113", "g": 0, "s": "V"}],
         "registries": [{"head_block": 5, "id": 737, "name": "us-scotus"}],
         "agent": {"address": "0x" + "ab" * 20}, "chain_id": 787111,
         "normalizer_version": "1.0.0", "timestamp": "t"}
    )
    gw = FakeGateway(receipt_versions={sha: fake_record("receipts-v1", sha, receipt_meta, index=2)})
    service = ReceiptService(gw)
    out = service.lookup(sha.upper())  # case-insensitive input
    assert out["found"] is True and out["registry_exists"] is True
    assert [v["index"] for v in out["versions"]] == [1, 2]
    assert out["versions"][-1]["receipt"]["schema"] == "nvnm-cite-receipt/v1-draft"
    assert out["proof"]["request"]["method"] == "eth_call"

    missing = ReceiptService(FakeGateway()).lookup("c" * 64)
    assert missing["found"] is False and missing["registry_exists"] is True

    no_registry = ReceiptService(FakeGateway(receipts_exists=False)).lookup("c" * 64)
    assert no_registry["found"] is False and no_registry["registry_exists"] is False

    with pytest.raises(WebAppError):
        service.lookup("not-a-hash")


# ---------------------------------------------------------------- decode


def test_decode_call_roundtrips_the_codec():
    calldata = pc.build_add_record(
        registry="us-scotus", uri="https://www.courtlistener.com/opinion/108713/roe-v-wade/",
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

    server = build_server("127.0.0.1", 0, "http://127.0.0.1:9", data_dir)  # RPC unroutable on purpose
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


def test_server_check_endpoint_is_local_only(live_server):
    # RPC is unroutable in this fixture: a passing check proves no RPC call.
    res, data = _request(
        live_server, "POST", "/api/check",
        body=BRIEF.encode(), headers={"X-Filename": "brief.txt", "Content-Length": str(len(BRIEF.encode()))},
    )
    assert res.status == 200
    report = json.loads(data)
    assert report["summary"]["by_status"]["VERIFIED"] == 2
    assert report["privacy"]["persisted"] is False


def test_server_validation_errors(live_server):
    res, data = _request(live_server, "GET", "/api/receipt/lookup?sha256=zzz")
    assert res.status == 422 and b"SHA-256" in data
    res, data = _request(live_server, "GET", "/api/tx?hash=nope")
    assert res.status == 422
    res, _ = _request(live_server, "POST", "/api/receipt/prepare", body=b"{not json",
                      headers={"Content-Length": "9"})
    assert res.status == 400
