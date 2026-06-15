"""CLI tests for ``nvnm-cite check``.

The chain is faked by swapping the resolver, so these run the REAL core and
renderer (no network). Error paths (missing file, dead chain) are checked
for the right exit code and message.
"""

from __future__ import annotations

import json

import pytest

import nvnm_cite.cli as cli
from nvnm_cite.chain import precompile as pc
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
