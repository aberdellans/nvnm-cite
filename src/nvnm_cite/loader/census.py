"""Corpus census (plan task 2.2). Runs BEFORE any chain write; the numbers
go to DECISIONS.md and gate the tranches and the demo.

Answers, per court:
- cluster and citation-row counts; canonical-keyed citation counts
- precedential_status split (the scotus tranche boundary)
- citation type x reporter distribution (the load-set decision input)
- first-page collisions: distinct clusters sharing one canonical key
- demo gates: `925 F.3d 1339` must be ABSENT; ca11 2019 F.3d coverage

Run:  uv run python -m nvnm_cite.loader.census --corpus data/corpus.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

VARGHESE_KEY = "925 F.3d 1339"  # the Mata v. Avianca fabricated cite


def census(corpus_path: Path) -> dict:
    db = sqlite3.connect(corpus_path)
    out: dict = {"meta": dict(db.execute("SELECT key, value FROM meta"))}

    out["clusters_by_court"] = dict(
        db.execute("SELECT court_id, COUNT(*) FROM clusters GROUP BY court_id")
    )
    out["citations_by_court"] = dict(
        db.execute(
            """SELECT cl.court_id, COUNT(*) FROM citations ci
               JOIN clusters cl USING (cluster_id) GROUP BY cl.court_id"""
        )
    )
    out["keyed_citations_by_court"] = dict(
        db.execute(
            """SELECT cl.court_id, COUNT(*) FROM citations ci
               JOIN clusters cl USING (cluster_id)
               WHERE ci.canonical IS NOT NULL GROUP BY cl.court_id"""
        )
    )
    out["precedential_by_court"] = {
        (court, status or "<empty>"): n
        for court, status, n in db.execute(
            "SELECT court_id, precedential_status, COUNT(*) FROM clusters GROUP BY 1, 2"
        )
    }
    out["type_reporter_by_court"] = [
        row
        for row in db.execute(
            """SELECT cl.court_id, ci.type, ci.reporter, COUNT(*) AS n
               FROM citations ci JOIN clusters cl USING (cluster_id)
               WHERE ci.canonical IS NOT NULL
               GROUP BY 1, 2, 3 ORDER BY cl.court_id, n DESC"""
        )
    ]
    out["clusters_no_year"] = dict(
        db.execute("SELECT court_id, COUNT(*) FROM clusters WHERE year IS NULL GROUP BY court_id")
    )

    # Collisions: one canonical key denoting multiple distinct clusters
    # (within one court registry). These take the metadata collision form.
    out["collisions_by_court"] = dict(
        db.execute(
            """SELECT court_id, COUNT(*) FROM (
                 SELECT cl.court_id AS court_id, ci.canonical
                 FROM citations ci JOIN clusters cl USING (cluster_id)
                 WHERE ci.canonical IS NOT NULL
                 GROUP BY cl.court_id, ci.canonical
                 HAVING COUNT(DISTINCT ci.cluster_id) > 1
               ) GROUP BY court_id"""
        )
    )
    out["distinct_keys_by_court"] = dict(
        db.execute(
            """SELECT cl.court_id, COUNT(DISTINCT ci.canonical)
               FROM citations ci JOIN clusters cl USING (cluster_id)
               WHERE ci.canonical IS NOT NULL GROUP BY cl.court_id"""
        )
    )

    # Demo gates.
    out["varghese_rows"] = db.execute(
        "SELECT COUNT(*) FROM citations WHERE canonical = ?", (VARGHESE_KEY,)
    ).fetchone()[0]
    out["ca11_2019_f3d"] = db.execute(
        """SELECT COUNT(DISTINCT ci.cluster_id) FROM citations ci
           JOIN clusters cl USING (cluster_id)
           WHERE cl.court_id = 'ca11' AND cl.year = 2019 AND ci.reporter = 'F.3d'"""
    ).fetchone()[0]
    db.close()
    return out


def print_census(out: dict) -> None:
    meta = out["meta"]
    print(f"census of corpus.sqlite (snapshot {meta.get('snapshot')}, built {meta.get('built_at')}):\n")
    for court in sorted(out["clusters_by_court"]):
        print(
            f"  {court}: {out['clusters_by_court'][court]:,} clusters, "
            f"{out['citations_by_court'].get(court, 0):,} citation rows, "
            f"{out['keyed_citations_by_court'].get(court, 0):,} keyed, "
            f"{out['distinct_keys_by_court'].get(court, 0):,} distinct keys, "
            f"{out['collisions_by_court'].get(court, 0):,} collision keys, "
            f"{out['clusters_no_year'].get(court, 0):,} clusters without year"
        )
    print("\n  precedential_status:")
    for (court, status), n in sorted(out["precedential_by_court"].items()):
        print(f"    {court:8s} {status:15s} {n:,}")
    print("\n  citation type x reporter (keyed rows):")
    for court, ctype, reporter, n in out["type_reporter_by_court"]:
        print(f"    {court:8s} type={ctype} {reporter!r:20s} {n:,}")
    print(
        f"\n  demo gates: '{VARGHESE_KEY}' rows = {out['varghese_rows']}"
        f" (MUST be 0); ca11 2019 F.3d clusters = {out['ca11_2019_f3d']:,} (must be > 0)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus census (pre-chain-write).")
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus.sqlite"))
    args = parser.parse_args(argv)
    print_census(census(args.corpus))
    return 0


if __name__ == "__main__":
    sys.exit(main())
