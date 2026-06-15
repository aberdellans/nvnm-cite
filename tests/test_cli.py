"""CLI tests for ``nvnm-cite check``.

The chain is faked by swapping the resolver, so these run the REAL core and
renderer (no network). Error paths (missing file, dead chain) are checked
for the right exit code and message.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

import nvnm_cite.cli as cli
from nvnm_cite.chain import precompile as pc
from nvnm_cite.receipts.anchor import AnchorPlan
from nvnm_cite.receipts.schema import RECEIPT_CHECKSUM_ALGO, RECEIPT_URI, build_receipt, summary_tally
from nvnm_cite.receipts.verify import VerifyResult
from nvnm_cite.verifier.check import check_document
from nvnm_cite.verifier.resolver import Resolution, records_query


def _rec(registry: str, checksum: str, metadata: str) -> pc.Record:
    return pc.Record(
        registry=registry, uri="https://cl/x/", checksum=checksum, checksum_algo="cite-canonical-v1",
        metadata=metadata, timestamp="t", status="Active", record_id=1, index=1, is_latest=True,
    )


RECORDS = {
    ("us-scotus", "410 U.S. 113"): _rec(
        "us-scotus", "410 U.S. 113", '{"cluster":108713,"name":"Roe v. Wade","year":1973}'
    ),
}


class FakeResolver:
    def __init__(self, records):
        self.records = records

    def resolve(self, registry: str, checksum: str) -> Resolution:
        _, query = records_query(registry, checksum)
        return Resolution(record=self.records.get((registry, checksum)), query=query)


BRIEF = "Roe v. Wade, 410 U.S. 113 (1973). Varghese, 925 F.3d 1339 (11th Cir. 2019)."


@pytest.fixture()
def brief_file(tmp_path):
    f = tmp_path / "brief.txt"
    f.write_text(BRIEF)
    return f


def test_check_renders_table(brief_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ChainResolver", lambda *a, **k: FakeResolver(RECORDS))
    rc = cli.main(["check", str(brief_file)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "nvnm-cite check" in out
    assert "VERIFIED" in out and "Roe v. Wade" in out
    assert "NOT FOUND" in out  # the fabricated 925 F.3d 1339
    assert "Existence only" in out  # the honest disclaimer footer


def test_check_json_output(brief_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ChainResolver", lambda *a, **k: FakeResolver(RECORDS))
    rc = cli.main(["check", str(brief_file), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    report = json.loads(out)
    assert report["summary"]["by_status"]["VERIFIED"] == 1
    assert report["summary"]["by_status"]["NOT_FOUND"] == 1
    # a keyed result carries the replayable query
    verified = next(c for c in report["citations"] if c["status"] == "VERIFIED")
    assert verified["query"]["method"] == "eth_call"


def test_check_missing_file(capsys):
    rc = cli.main(["check", "/no/such/file.txt"])
    assert rc == 2
    assert "cannot read" in capsys.readouterr().err


def test_check_dead_rpc_exits_nonzero(brief_file, monkeypatch, capsys):
    class Down:
        def resolve(self, registry, checksum):
            raise ConnectionRefusedError("refused")

    monkeypatch.setattr(cli, "ChainResolver", lambda *a, **k: Down())
    rc = cli.main(["check", str(brief_file)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "could not reach" in err and "NVNM Chain" in err


def test_no_subcommand_errors(capsys):
    with pytest.raises(SystemExit):
        cli.main([])


# ---------------------------------------------------------------- anchor / verify


def _fake_plan():
    report = check_document(BRIEF.encode(), "brief.txt", FakeResolver(RECORDS))
    sha = report["document"]["sha256"]
    regs = [{"id": 737, "name": "us-scotus", "head_block": 1_700_000}]
    receipt, rj = build_receipt(
        document_sha256=sha, checked_at_block=1_700_000, registries=regs,
        summary=summary_tally(report), agent_address="0x" + "ab" * 20, timestamp="t",
    )
    reg = "inveniam--mata-v-avianca"
    return AnchorPlan(
        registry=reg, registry_exists=False, document_sha256=sha, checked_at_block=1_700_000,
        registries_read=regs, receipt=receipt, receipt_json=rj,
        record_calldata=pc.build_add_record(reg, RECEIPT_URI, sha, RECEIPT_CHECKSUM_ALGO, rj),
        create_registry={"name": reg}, create_calldata=pc.build_add_registry(reg, "d", '{"k":1}'),
        already_anchored=False, report=report,
    )


def test_anchor_dry_run_does_not_send(brief_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "prepare_anchor", lambda *a, **k: _fake_plan())
    # --agent avoids needing the signing key; no --anchor means dry run
    rc = cli.main(["anchor", str(brief_file), "--firm", "Inveniam", "--case", "Mata v. Avianca", "--agent", "0x" + "ab" * 20])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Dry run" in out and "Receipt to anchor" in out
    assert "inveniam--mata-v-avianca" in out
    assert "addRecord" in out and "VERIFIED" in out  # shows the check + the plan


def _verify_result(verdict, found=True):
    return VerifyResult(
        registry="inveniam--mata-v-avianca", registry_exists=True, document_sha256="a" * 64,
        found=found, verdict=verdict,
        receipt={"agent": {"address": "0x" + "ab" * 20}, "summary": {"checked": 2}, "timestamp": "t"} if found else None,
        recomputed_summary={"checked": 2} if found else None, summary_matches=(verdict == "verified") or None,
        checked_at_block=1_700_000 if found else None, normalizer_version_receipt="1.0.0",
        normalizer_version_now="1.0.0", notes=[], query={"method": "eth_call", "params": []},
    )


def test_verify_exit_code_verified(brief_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "verify_document", lambda *a, **k: _verify_result("verified"))
    rc = cli.main(["verify", str(brief_file), "--registry", "inveniam--mata-v-avianca"])
    assert rc == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_verify_exit_code_not_found(brief_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "verify_document", lambda *a, **k: _verify_result("not_found", found=False))
    rc = cli.main(["verify", str(brief_file), "--registry", "inveniam--mata-v-avianca"])
    assert rc == 1  # nonzero when not cleanly verified
    assert "NO RECEIPT" in capsys.readouterr().out


# ---------------------------------------------------------------- stats / delegation


def _seed_index(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE records (registry TEXT, checksum TEXT, record_id INTEGER, idx INTEGER,
            is_latest INTEGER, uri TEXT, checksum_algo TEXT, metadata TEXT, timestamp TEXT, status TEXT);
        CREATE TABLE sync_state (registry TEXT PRIMARY KEY, row_offset INTEGER, head_block INTEGER, synced_at TEXT);
        """
    )
    conn.execute("INSERT INTO records VALUES ('us-scotus','410 U.S. 113',1,1,1,'u','cite-canonical-v1','{}','t','Active')")
    conn.execute("INSERT INTO records VALUES ('us-ca11','950 F.3d 1000',2,1,1,'u','cite-canonical-v1','{}','t','Active')")
    conn.execute("INSERT INTO sync_state VALUES ('us-scotus',1,1693000,'2026-06-13T00:00:00Z')")
    conn.execute("INSERT INTO sync_state VALUES ('us-ca11',1,1693000,'2026-06-13T00:00:00Z')")
    conn.commit()
    conn.close()


def test_stats_reads_local_index(tmp_path, capsys):
    db = tmp_path / "chain_index.sqlite"
    _seed_index(db)
    rc = cli.main(["stats", "--db", str(db)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "us-scotus" in out and "us-ca11" in out
    assert "1,693,000" in out and "Total: 2 records" in out


def test_stats_missing_db(tmp_path, capsys):
    rc = cli.main(["stats", "--db", str(tmp_path / "nope.sqlite")])
    assert rc == 2
    assert "no chain index" in capsys.readouterr().err


def test_delegated_commands_route_to_module_mains(monkeypatch):
    import nvnm_cite.chain.indexer as indexer
    import nvnm_cite.loader.bulk_load as bulk_load
    import nvnm_cite.loader.reconcile as reconcile
    import nvnm_cite.loader.update as update

    calls: dict[str, list] = {}
    monkeypatch.setattr(indexer, "main", lambda argv: (calls.update(indexer=argv) or 0))
    monkeypatch.setattr(reconcile, "main", lambda argv: (calls.update(reconcile=argv) or 0))
    monkeypatch.setattr(bulk_load, "main", lambda argv: (calls.update(bulk_load=argv) or 0))
    monkeypatch.setattr(update, "main", lambda argv: (calls.update(update=argv) or 0))

    assert cli.main(["sync", "--registries", "us-scotus"]) == 0
    assert calls["indexer"] == ["sync", "--registries", "us-scotus"]
    assert cli.main(["rebuild-index", "--registries", "us-ca11"]) == 0
    assert calls["indexer"] == ["rebuild-index", "--registries", "us-ca11"]
    assert cli.main(["reconcile", "--registries", "us-scotus"]) == 0
    assert calls["reconcile"] == ["--registries", "us-scotus"]
    assert cli.main(["load", "status", "--offline"]) == 0
    assert calls["bulk_load"] == ["status", "--offline"]
    assert cli.main(["update", "--dry-run"]) == 0
    assert calls["update"] == ["--dry-run"]
