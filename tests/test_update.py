"""Incremental updater tests (task 2.7): render, append, idempotency, cursor.

A FakeClient replaces the network, honoring the same iter_clusters contract
the real CourtListenerClient promises (filter by modified-since, ascending
date_modified, respect max_clusters). No live API calls.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nvnm_cite.loader.bulk_load import open_state
from nvnm_cite.loader.update import (
    cluster_to_records,
    normalize_since,
    parse_cl_datetime,
    update_court,
)


def cluster(cid, modified, cites, name="A v. B", date_filed="2026-04-01", slug="a-v-b"):
    return {
        "id": cid,
        "date_modified": modified,
        "date_filed": date_filed,
        "case_name": name,
        "case_name_short": "",
        "slug": slug,
        "citations": [
            {"volume": v, "reporter": r, "page": p, "type": t} for (v, r, p, t) in cites
        ],
    }


class FakeClient:
    def __init__(self, by_court: dict[str, list[dict]]):
        self.by_court = by_court

    def iter_clusters(self, court, modified_since_iso, max_clusters=None):
        since = parse_cl_datetime(modified_since_iso)
        rows = sorted(self.by_court.get(court, []), key=lambda c: parse_cl_datetime(c["date_modified"]))
        n = 0
        for c in rows:
            if parse_cl_datetime(c["date_modified"]) >= since:
                yield c
                n += 1
                if max_clusters is not None and n >= max_clusters:
                    return


# ---- rendering ------------------------------------------------------------


def test_render_filters_to_whitelist():
    c = cluster(1, "2026-05-01T00:00:00Z", [("925", "F.3d", "1339", 1), ("2019", "WL", "5", 7)])
    recs, skipped = cluster_to_records(c, frozenset({"F.2d", "F.3d", "F.4th", "F. App'x"}), "us-ca11")
    assert [r.checksum for r in recs] == ["925 F.3d 1339"]  # WL dropped
    assert skipped == 0
    assert '"cluster":1' in recs[0].metadata


def test_render_parallel_citations_make_multiple_records():
    c = cluster(
        2,
        "2026-05-01T00:00:00Z",
        [("558", "U.S.", "310", 1), ("130", "S. Ct.", "876", 1), ("175", "L. Ed. 2d", "753", 1)],
        name="Citizens United v. FEC",
    )
    recs, _ = cluster_to_records(c, frozenset({"U.S.", "S. Ct.", "L. Ed.", "L. Ed. 2d"}), "us-scotus")
    assert {r.checksum for r in recs} == {"558 U.S. 310", "130 S. Ct. 876", "175 L. Ed. 2d 753"}
    assert all('"cluster":2' in r.metadata for r in recs)  # share the cluster


def test_render_citationless_cluster_is_empty():
    c = cluster(3, "2026-06-12T00:00:00Z", [])  # freshly published, no cite yet
    recs, skipped = cluster_to_records(c, frozenset({"F.3d"}), "us-ca11")
    assert recs == [] and skipped == 0


def test_render_skips_unkeyable_citation():
    c = cluster(4, "2026-05-01T00:00:00Z", [("", "F.3d", "", 1)])  # no volume/page
    recs, _ = cluster_to_records(c, frozenset({"F.3d"}), "us-ca11")
    assert recs == []


# ---- the update pass ------------------------------------------------------


def test_append_then_idempotent_rerun(tmp_path: Path):
    db = open_state(tmp_path / "state.sqlite")
    client = FakeClient(
        {
            "ca11": [
                cluster(10, "2026-04-02T10:00:00Z", [("1", "F.4th", "100", 1)]),
                cluster(11, "2026-04-03T10:00:00Z", [("1", "F.4th", "200", 1)]),
            ]
        }
    )
    s1 = update_court("ca11", client, db, dry_run=False, since="2026-04-01")
    assert s1.appended == 2 and s1.clusters_with_new == 2
    assert s1.cursor_to == parse_cl_datetime("2026-04-03T10:00:00Z").isoformat()
    assert db.execute("SELECT COUNT(*) FROM load_state").fetchone()[0] == 2

    # Re-run with no --since: reads the stored cursor, re-includes the
    # boundary, appends nothing.
    s2 = update_court("ca11", client, db, dry_run=False)
    assert s2.appended == 0
    assert db.execute("SELECT COUNT(*) FROM load_state").fetchone()[0] == 2


def test_cursor_catches_late_added_citation(tmp_path: Path):
    db = open_state(tmp_path / "state.sqlite")
    # First sweep: cluster 20 exists but has no cite yet.
    early = [cluster(20, "2026-04-02T00:00:00Z", [])]
    update_court("ca11", FakeClient({"ca11": early}), db, dry_run=False, since="2026-04-01")
    assert db.execute("SELECT COUNT(*) FROM load_state").fetchone()[0] == 0

    # Later: the F.4th cite is added (a modification bumps date_modified
    # past the stored cursor) -> the daily run now appends it.
    later = [cluster(20, "2026-05-10T00:00:00Z", [("2", "F.4th", "55", 1)])]
    s = update_court("ca11", FakeClient({"ca11": later}), db, dry_run=False)
    assert s.appended == 1
    assert db.execute("SELECT checksum FROM load_state").fetchone()[0] == "2 F.4th 55"


def test_dry_run_writes_nothing(tmp_path: Path):
    db = open_state(tmp_path / "state.sqlite")
    client = FakeClient({"ca11": [cluster(30, "2026-04-02T00:00:00Z", [("3", "F.3d", "9", 1)])]})
    s = update_court("ca11", client, db, dry_run=True, since="2026-04-01")
    assert s.appended == 1  # would append
    assert db.execute("SELECT COUNT(*) FROM load_state").fetchone()[0] == 0  # but didn't
    assert db.execute("SELECT value FROM meta WHERE key='update_cursor:us-ca11'").fetchone() is None


def test_max_clusters_caps_and_advances_cursor(tmp_path: Path):
    db = open_state(tmp_path / "state.sqlite")
    client = FakeClient(
        {
            "ca11": [
                cluster(40, "2026-04-02T00:00:00Z", [("4", "F.4th", "1", 1)]),
                cluster(41, "2026-04-03T00:00:00Z", [("4", "F.4th", "2", 1)]),
                cluster(42, "2026-04-04T00:00:00Z", [("4", "F.4th", "3", 1)]),
            ]
        }
    )
    s = update_court("ca11", client, db, dry_run=False, since="2026-04-01", max_clusters=2)
    assert s.examined == 2 and s.capped is True and s.appended == 2
    # cursor advanced to the 2nd cluster; the 3rd is picked up next run
    assert s.cursor_to == parse_cl_datetime("2026-04-03T00:00:00Z").isoformat()
    s2 = update_court("ca11", client, db, dry_run=False, max_clusters=2)
    assert s2.appended == 1  # only cluster 42 remained new


def test_default_since_used_when_no_cursor(tmp_path: Path):
    db = open_state(tmp_path / "state.sqlite")
    client = FakeClient({"ca11": [cluster(50, "2026-04-02T00:00:00Z", [("5", "F.4th", "1", 1)])]})
    s = update_court("ca11", client, db, dry_run=False, default_since="2026-04-01T00:00:00+00:00")
    assert s.appended == 1


def test_normalize_since_forms():
    assert normalize_since("2026-03-31") == "2026-03-31T00:00:00+00:00"
    # offset-aware input normalizes to UTC
    assert normalize_since("2026-03-31T19:00:00-05:00") == "2026-04-01T00:00:00+00:00"
