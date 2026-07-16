"""Mainnet export tests (Phase 7): scope-v2 filter, tranche layout, submit
shape, collision grouping, manifest/registries integrity, determinism."""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from nvnm_cite.loader.courtlistener import SCHEMA
from nvnm_cite.loader.export import classify_court, export, _courts_db_index
from nvnm_cite.loader.records import creation_strings

SUBMIT_KEYS = ["checksum", "checksumAlgo", "metadata", "registry", "status", "uri"]


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """A tiny full-scope corpus: one court per tranche + an unknown court."""
    db_path = tmp_path / "corpus.sqlite"
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    clusters = [
        # cluster_id, docket_id, court_id, case_name, date_filed, year, prec, slug
        (11, 101, "scotus", "Roe v. Wade", "1973-01-22", 1973, "Published", "roe-v-wade"),
        (12, 102, "flsd", "United States v. Example", "1990-01-01", 1990, "Published", "us-v-example"),
        (21, 103, "cal", "People v. Anderson", "1972-02-18", 1972, "Published", "people-v-anderson"),
        (22, 104, "cal", "People v. Rival", "1972-03-01", 1972, "Published", "people-v-rival"),
        (31, 105, "nj", "State v. Kelly", "1984-07-24", 1984, "Published", "state-v-kelly"),
        (41, 106, "zzfake", "Ghost v. Court", "2000-01-01", 2000, "Published", ""),
    ]
    db.executemany("INSERT INTO clusters VALUES (?,?,?,?,?,?,?,?)", clusters)
    citations = [
        # citation_id, cluster_id, volume, reporter, page, type, canonical
        (1, 11, "410", "U.S.", "113", 1, "410 U.S. 113"),
        (2, 11, "93", "S. Ct.", "705", 1, "93 S. Ct. 705"),
        (3, 12, "700", "F. Supp.", "100", 1, "700 F. Supp. 100"),
        # cal: two distinct clusters on ONE canonical key -> collision form
        (4, 21, "6", "Cal. 3d", "628", 2, "6 Cal. 3d 628"),
        (5, 22, "6", "Cal. 3d", "628", 2, "6 Cal. 3d 628"),
        # cal: vendor cite (type 7 = West) -> excluded by the type filter
        (6, 21, "1972", "WL", "999", 7, "1972 WL 999"),
        # cal: eligible type but a reporter that is NOT a reporters-db
        # edition -> excluded_reporter
        (7, 21, "1", "Bogus Rptr.", "1", 2, "1 Bogus Rptr. 1"),
        (8, 31, "97", "N.J.", "178", 2, "97 N.J. 178"),
        (9, 41, "1", "U.S.", "999", 1, "1 U.S. 999"),
        # unkeyed row (canonical NULL) -> never eligible
        (10, 11, "", "U.S.", "9", 1, None),
    ]
    db.executemany("INSERT INTO citations VALUES (?,?,?,?,?,?,?)", citations)
    db.executemany(
        "INSERT INTO meta VALUES (?,?)",
        [("snapshot", "2099-01-01"), ("built_at", "2099-01-02T00:00:00")],
    )
    db.commit()
    db.close()
    return db_path


def _read_jsonl_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def test_classify_court_tranches() -> None:
    by_id = _courts_db_index()
    assert classify_court("scotus", by_id).tranche == 1
    assert classify_court("cafc", by_id).tranche == 1
    assert classify_court("flsd", by_id).tranche == 2
    assert classify_court("cal", by_id).tranche == 3
    assert classify_court("nj", by_id).tranche == 4
    ghost = classify_court("zzfake", by_id)
    assert ghost.tranche == 4 and not ghost.in_courts_db


def test_export_layout_shape_and_manifest(corpus: Path, tmp_path: Path) -> None:
    out = tmp_path / "export"
    manifest = export(corpus, out)

    # Tranche layout: one file per court with >= 1 eligible record.
    paths = {
        "us-scotus": out / "tranche-1-federal-appellate/us-scotus.jsonl.gz",
        "us-flsd": out / "tranche-2-federal-complete/us-flsd.jsonl.gz",
        "us-cal": out / "tranche-3-state-pilot/us-cal.jsonl.gz",
        "us-nj": out / "tranche-4-state-remainder/us-nj.jsonl.gz",
        "us-zzfake": out / "tranche-4-state-remainder/us-zzfake.jsonl.gz",
    }
    for path in paths.values():
        assert path.is_file(), path

    # Submit shape: exactly the six writer fields, fixed algo/status, and
    # the registry field matching the file.
    for registry, path in paths.items():
        for rec in _read_jsonl_gz(path):
            assert sorted(rec) == SUBMIT_KEYS
            assert rec["registry"] == registry
            assert rec["checksumAlgo"] == "cite-canonical-v1"
            assert rec["status"] == "Active"
            assert len(rec["checksum"].encode()) <= 64
            assert len(rec["metadata"].encode()) <= 2048

    scotus = _read_jsonl_gz(paths["us-scotus"])
    assert [r["checksum"] for r in scotus] == ["410 U.S. 113", "93 S. Ct. 705"]
    assert json.loads(scotus[0]["metadata"]) == {
        "cluster": 11,
        "name": "Roe v. Wade",
        "year": 1973,
    }
    assert scotus[0]["uri"] == "https://www.courtlistener.com/opinion/11/roe-v-wade/"

    # Collision form: two cal clusters under one key -> one record.
    cal = _read_jsonl_gz(paths["us-cal"])
    assert len(cal) == 1
    meta = json.loads(cal[0]["metadata"])
    assert [c["cluster"] for c in meta["cases"]] == [21, 22]

    files = {f["registry"]: f for f in manifest["files"]}
    assert files["us-cal"]["records"] == 1
    assert files["us-cal"]["collisions"] == 1
    assert files["us-cal"]["excluded_reporter"] == 1  # Bogus Rptr.
    assert files["us-scotus"]["tranche"] == 1
    assert files["us-zzfake"]["in_courts_db"] is False
    assert manifest["totals"]["records"] == sum(f["records"] for f in files.values())
    assert manifest["snapshot"] == "2099-01-01"

    # The WL row is gone entirely (type 7): no "1972 WL 999" anywhere.
    assert all(r["checksum"] != "1972 WL 999" for r in cal)

    # sha256 in the manifest matches the file as shipped.
    gz = paths["us-scotus"].read_bytes()
    assert files["us-scotus"]["sha256_gz"] == hashlib.sha256(gz).hexdigest()

    # registries.json: creation strings match the locked-schema renderer.
    registries = json.loads((out / "registries.json").read_text())
    by_name = {r["name"]: r for r in registries}
    assert set(by_name) == set(paths)
    name, description, reg_meta = creation_strings("scotus")
    assert by_name["us-scotus"]["description"] == description
    assert by_name["us-scotus"]["metadata"] == reg_meta
    assert by_name["us-nj"]["tranche"] == 4

    # README renders with the manifest's own figures.
    readme = (out / "README.md").read_text()
    assert f"{manifest['totals']['records']:,} records" in readme
    assert "2099-01-01" in readme


def test_export_is_deterministic(corpus: Path, tmp_path: Path) -> None:
    m1 = export(corpus, tmp_path / "a")
    m2 = export(corpus, tmp_path / "b")
    sha1 = {f["registry"]: f["sha256_gz"] for f in m1["files"]}
    sha2 = {f["registry"]: f["sha256_gz"] for f in m2["files"]}
    assert sha1 == sha2
