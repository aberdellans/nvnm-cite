"""CourtListener bulk-data corpus extraction (plan task 2.1).

Streaming three-pass join over the quarterly bulk CSVs from
storage.courtlistener.com (S3 bucket com-courtlistener-storage, prefix
bulk-data/), producing corpus.sqlite for the census (task 2.2) and the
bulk load (tasks 2.4/2.6):

  pass 1  dockets-<date>.csv.bz2          -> {docket_id: court_id} for the
                                             wanted courts (in memory)
  pass 2  opinion-clusters-<date>.csv.bz2 -> clusters table
  pass 3  citations-<date>.csv.bz2        -> citations table (every type;
                                             the census decides the load set)

Format, MEASURED against the 2026-03-31 snapshot (do not trust docs or
first impressions here): PostgreSQL COPY csv with an UNQUOTED header row,
all non-NULL data values double-quoted (FORCE_QUOTE *), embedded quotes
BACKSLASH-ESCAPED (ESCAPE '\\' -- NOT csv-style doubled quotes), literal
newlines inside quoted values, NULL as a bare empty field. Parsing with
Python's default doublequote dialect silently DESYNCS at the first field
containing a quote character and shreds subsequent rows; the correct
reader is csv.reader(f, escapechar="\\", doublequote=False), verified to
yield uniform field counts across the snapshot. NULL and empty string both
surface as '' (the distinction does not matter for any column used here).
Columns are addressed by header name, never by position. Compressed files
are streamed; nothing is materialized uncompressed (the dockets file alone
is ~25 GB raw).

Run:  uv run python -m nvnm_cite.loader.courtlistener \
          --data-dir data --snapshot 2026-03-31 --db data/corpus.sqlite
"""

from __future__ import annotations

import argparse
import bz2
import csv
import sqlite3
import sys
import time
from array import array
from bisect import bisect_left
from collections.abc import Iterator
from pathlib import Path

from nvnm_cite.normalizer import canonical_from_parts

DEFAULT_COURTS = ("scotus", "ca11")
# --courts all: keep EVERY court (the Phase 7 full-scope corpus). The docket
# pass cannot hold all ~70M docket->court pairs, so an extra pass over the
# (much smaller) clusters file first collects the ~10M docket ids that
# clusters actually reference, and the docket pass keeps only those.
ALL_COURTS = "all"
BATCH_ROWS = 10_000

# Some cluster text columns (syllabus, headnotes) run to megabytes.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

SCHEMA = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE clusters (
    cluster_id          INTEGER PRIMARY KEY,
    docket_id           INTEGER NOT NULL,
    court_id            TEXT NOT NULL,
    case_name           TEXT NOT NULL DEFAULT '',
    date_filed          TEXT NOT NULL DEFAULT '',
    year                INTEGER,
    precedential_status TEXT NOT NULL DEFAULT '',
    slug                TEXT NOT NULL DEFAULT ''
);
CREATE TABLE citations (
    citation_id INTEGER PRIMARY KEY,
    cluster_id  INTEGER NOT NULL,
    volume      TEXT NOT NULL DEFAULT '',
    reporter    TEXT NOT NULL DEFAULT '',
    page        TEXT NOT NULL DEFAULT '',
    type        INTEGER,
    canonical   TEXT
);
"""

INDEXES = """
CREATE INDEX idx_clusters_court ON clusters(court_id);
CREATE INDEX idx_clusters_year ON clusters(court_id, year);
CREATE INDEX idx_citations_cluster ON citations(cluster_id);
CREATE INDEX idx_citations_canonical ON citations(canonical);
"""


def bulk_csv(path: Path) -> tuple[dict[str, int], Iterator[list[str]]]:
    """Open a bulk .csv.bz2 stream; return (header name -> index, row iterator)."""
    stream = bz2.open(path, "rt", encoding="utf-8", newline="")
    # The COPY dialect: backslash-escaped quotes, never doubled (see module
    # docstring; the default dialect desyncs and shreds rows).
    reader = csv.reader(stream, escapechar="\\", doublequote=False)
    header = {name: i for i, name in enumerate(next(reader))}
    return header, reader


def _progress(label: str, count: int, started: float) -> None:
    rate = count / max(time.monotonic() - started, 1e-9)
    print(f"  {label}: {count:,} rows ({rate:,.0f} rows/s)", flush=True)


class MalformedRows:
    """Counter for structurally short rows (a real, rare wart of the multi-GB
    dumps). They are skipped, counted, sampled in the log, and the count is
    recorded in the meta table -- lost rows are visible, never silent."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.count = 0

    def hit(self, row: list[str]) -> None:
        self.count += 1
        if self.count <= 3:
            print(f"  MALFORMED {self.label} row (skipped): {row!r:.200}", flush=True)


def pass_cluster_dockets(path: Path) -> tuple[array, int]:
    """Pass 0 (all-courts mode only): sorted docket ids referenced by clusters."""
    header, rows = bulk_csv(path)
    docket_col = header["docket_id"]
    malformed = MalformedRows("cluster(docket scan)")
    ids = array("q")
    started = time.monotonic()
    for n, row in enumerate(rows, 1):
        if len(row) <= docket_col:
            malformed.hit(row)
            continue
        raw = row[docket_col]
        if raw:
            ids.append(int(raw))
        if n % 1_000_000 == 0:
            _progress("clusters scanned for dockets", n, started)
    ids = array("q", sorted(ids))
    print(
        f"  pass 0 done: {len(ids):,} docket references kept, "
        f"{malformed.count} malformed rows skipped",
        flush=True,
    )
    return ids, malformed.count


def _in_sorted(ids: array, value: int) -> bool:
    i = bisect_left(ids, value)
    return i < len(ids) and ids[i] == value


def pass_dockets(
    path: Path, courts: frozenset[str], wanted_dockets: array | None = None
) -> tuple[dict[int, str], int]:
    """Pass 1: docket_id -> court_id for the wanted courts. In all-courts
    mode (wanted_dockets set) every court is kept, but only for docket ids
    that clusters reference; court strings are interned (a few thousand
    distinct values across ~10M entries)."""
    header, rows = bulk_csv(path)
    id_col, court_col = header["id"], header["court_id"]
    needed = max(id_col, court_col)
    malformed = MalformedRows("docket")
    docket_courts: dict[int, str] = {}
    started = time.monotonic()
    for n, row in enumerate(rows, 1):
        if len(row) <= needed:
            malformed.hit(row)
            continue
        if wanted_dockets is not None:
            court = row[court_col]
            if court:
                docket_id = int(row[id_col])
                if _in_sorted(wanted_dockets, docket_id):
                    docket_courts[docket_id] = sys.intern(court)
        elif row[court_col] in courts:
            docket_courts[int(row[id_col])] = row[court_col]
        if n % 5_000_000 == 0:
            _progress("dockets scanned", n, started)
    print(
        f"  pass 1 done: {len(docket_courts):,} dockets kept, "
        f"{malformed.count} malformed rows skipped",
        flush=True,
    )
    return docket_courts, malformed.count


def pass_clusters(
    path: Path, docket_courts: dict[int, str], db: sqlite3.Connection
) -> tuple[dict[int, str], int]:
    """Pass 2: clusters table for kept dockets; returns cluster_id -> court_id."""
    header, rows = bulk_csv(path)
    cols = {
        name: header[name]
        for name in (
            "id",
            "docket_id",
            "date_filed",
            "slug",
            "case_name_short",
            "case_name",
            "precedential_status",
        )
    }
    needed = max(cols.values())
    malformed = MalformedRows("cluster")
    cluster_courts: dict[int, str] = {}
    batch: list[tuple] = []
    started = time.monotonic()
    for n, row in enumerate(rows, 1):
        if len(row) <= needed:
            malformed.hit(row)
            continue
        raw_docket = row[cols["docket_id"]]
        if not raw_docket:
            continue
        court = docket_courts.get(int(raw_docket))
        if court is None:
            continue
        cluster_id = int(row[cols["id"]])
        date_filed = row[cols["date_filed"]]
        year = (
            int(date_filed[:4])
            if len(date_filed) >= 4 and date_filed[:4].isdigit()
            else None
        )
        # Metadata name rule from the record schema: case_name, falling
        # back to case_name_short.
        name = row[cols["case_name"]] or row[cols["case_name_short"]]
        cluster_courts[cluster_id] = court
        batch.append(
            (
                cluster_id,
                int(raw_docket),
                court,
                name,
                date_filed,
                year,
                row[cols["precedential_status"]],
                row[cols["slug"]],
            )
        )
        if len(batch) >= BATCH_ROWS:
            db.executemany("INSERT INTO clusters VALUES (?,?,?,?,?,?,?,?)", batch)
            db.commit()
            batch.clear()
        if n % 1_000_000 == 0:
            _progress("clusters scanned", n, started)
    if batch:
        db.executemany("INSERT INTO clusters VALUES (?,?,?,?,?,?,?,?)", batch)
        db.commit()
    print(
        f"  pass 2 done: {len(cluster_courts):,} clusters kept, "
        f"{malformed.count} malformed rows skipped",
        flush=True,
    )
    return cluster_courts, malformed.count


def pass_citations(
    path: Path, cluster_courts: dict[int, str], db: sqlite3.Connection
) -> tuple[int, int]:
    """Pass 3: citations table for kept clusters, with canonical keys."""
    header, rows = bulk_csv(path)
    cols = {name: header[name] for name in ("id", "volume", "reporter", "page", "type", "cluster_id")}
    needed = max(cols.values())
    malformed = MalformedRows("citation")
    kept = 0
    batch: list[tuple] = []
    started = time.monotonic()
    for n, row in enumerate(rows, 1):
        if len(row) <= needed:
            malformed.hit(row)
            continue
        raw_cluster = row[cols["cluster_id"]]
        if not raw_cluster or int(raw_cluster) not in cluster_courts:
            continue
        volume, reporter, page = row[cols["volume"]], row[cols["reporter"]], row[cols["page"]]
        kept += 1
        batch.append(
            (
                int(row[cols["id"]]),
                int(raw_cluster),
                volume,
                reporter,
                page,
                int(row[cols["type"]]) if row[cols["type"]] else None,
                canonical_from_parts(volume, reporter, page),
            )
        )
        if len(batch) >= BATCH_ROWS:
            db.executemany("INSERT INTO citations VALUES (?,?,?,?,?,?,?)", batch)
            db.commit()
            batch.clear()
        if n % 2_000_000 == 0:
            _progress("citations scanned", n, started)
    if batch:
        db.executemany("INSERT INTO citations VALUES (?,?,?,?,?,?,?)", batch)
        db.commit()
    print(
        f"  pass 3 done: {kept:,} citations kept, "
        f"{malformed.count} malformed rows skipped",
        flush=True,
    )
    return kept, malformed.count


def build_corpus(
    data_dir: Path,
    snapshot: str,
    db_path: Path,
    courts: tuple[str, ...] = DEFAULT_COURTS,
    force: bool = False,
) -> dict[str, str]:
    """Run all three passes; returns the stats written to the meta table."""
    files = {
        name: data_dir / f"{name}-{snapshot}.csv.bz2"
        for name in ("dockets", "opinion-clusters", "citations")
    }
    for name, path in files.items():
        if not path.is_file():
            raise FileNotFoundError(f"{name} bulk file missing: {path}")
    if db_path.exists():
        if not force:
            raise FileExistsError(f"{db_path} exists; pass --force to rebuild")
        db_path.unlink()

    db = sqlite3.connect(db_path)
    db.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
    db.executescript(SCHEMA)
    started = time.monotonic()

    all_courts = courts == (ALL_COURTS,)
    wanted_dockets: array | None = None
    if all_courts:
        print(f"pass 0/3: cluster docket ids ({files['opinion-clusters'].name})", flush=True)
        wanted_dockets, _ = pass_cluster_dockets(files["opinion-clusters"])
    print(f"pass 1/3: dockets ({files['dockets'].name})", flush=True)
    docket_courts, bad_dockets = pass_dockets(
        files["dockets"], frozenset(() if all_courts else courts), wanted_dockets
    )
    del wanted_dockets
    print(f"pass 2/3: opinion clusters ({files['opinion-clusters'].name})", flush=True)
    cluster_courts, bad_clusters = pass_clusters(files["opinion-clusters"], docket_courts, db)
    del docket_courts
    print(f"pass 3/3: citations ({files['citations'].name})", flush=True)
    n_citations, bad_citations = pass_citations(files["citations"], cluster_courts, db)

    db.executescript(INDEXES)
    stats = {
        "snapshot": snapshot,
        "courts": ",".join(courts),
        "clusters": str(len(cluster_courts)),
        "citations": str(n_citations),
        "malformed_rows": f"dockets={bad_dockets},clusters={bad_clusters},citations={bad_citations}",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_seconds": str(int(time.monotonic() - started)),
        "source": "CourtListener bulk data, Free Law Project (courtlistener.com)",
    }
    db.executemany("INSERT INTO meta VALUES (?,?)", sorted(stats.items()))
    db.commit()
    db.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--snapshot", required=True, help="bulk snapshot date, e.g. 2026-03-31")
    parser.add_argument("--db", type=Path, default=Path("data/corpus.sqlite"))
    parser.add_argument(
        "--courts",
        default=",".join(DEFAULT_COURTS),
        help="comma-separated courts-db ids, or 'all' for every court (full scope)",
    )
    parser.add_argument("--force", action="store_true", help="rebuild over an existing db")
    args = parser.parse_args(argv)

    courts = tuple(c.strip() for c in args.courts.split(",") if c.strip())
    stats = build_corpus(args.data_dir, args.snapshot, args.db, courts, args.force)
    print("\ncorpus built:")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
