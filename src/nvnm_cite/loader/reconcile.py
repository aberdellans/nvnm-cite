"""Corpus-vs-chain reconcile (plan task 2.5). A first-class CLI command and
demo artifact: the proof that what we said we loaded is what the chain holds.

Expected state = load_state (the schema-rendered rows the loader intended),
observed state = chain_index (is_latest=1 rows synced from the precompile).
Comparing against load_state rather than re-deriving from corpus.sqlite
means expectation and submission go through the same rendering code
(loader/records.py) and cannot drift apart silently.

Diff classes:
  missing-on-chain   a row the checkpoint says is confirmed, absent from the
                     synced index (also reported: pending/submitted backlog)
  extra-on-chain     a latest record in the registry the loader never planned
  drift              uri / metadata / checksumAlgo / status differ

Run:  uv run python -m nvnm_cite.loader.reconcile \
          --state data/load_state.sqlite --index data/chain_index.sqlite \
          --registries us-scotus,us-ca11
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from nvnm_cite.loader.records import CHECKSUM_ALGO


@dataclass
class Report:
    registries: list[str]
    confirmed_missing: list[tuple[str, str]] = field(default_factory=list)
    backlog: dict[str, int] = field(default_factory=dict)  # status -> count (not yet on chain by design)
    extra: list[tuple[str, str]] = field(default_factory=list)
    drift: list[tuple[str, str, str]] = field(default_factory=list)  # registry, checksum, field
    matched: int = 0

    @property
    def clean(self) -> bool:
        return not (self.confirmed_missing or self.extra or self.drift)


def reconcile(state_path: Path, index_path: Path, registries: list[str]) -> Report:
    db = sqlite3.connect(":memory:")
    db.execute("ATTACH DATABASE ? AS state", (str(state_path),))
    db.execute("ATTACH DATABASE ? AS idx", (str(index_path),))
    marks = ",".join("?" * len(registries))
    report = Report(registries=registries)

    report.confirmed_missing = db.execute(
        f"""
        SELECT s.registry, s.checksum
        FROM state.load_state s
        LEFT JOIN idx.records r
            ON r.registry = s.registry AND r.checksum = s.checksum AND r.is_latest = 1
        WHERE s.registry IN ({marks}) AND s.status = 'confirmed' AND r.checksum IS NULL
        ORDER BY s.registry, s.checksum
        """,
        registries,
    ).fetchall()

    report.backlog = dict(
        db.execute(
            f"""
            SELECT s.status, COUNT(*)
            FROM state.load_state s
            WHERE s.registry IN ({marks}) AND s.status != 'confirmed'
            GROUP BY s.status
            """,
            registries,
        ).fetchall()
    )

    report.extra = db.execute(
        f"""
        SELECT r.registry, r.checksum
        FROM idx.records r
        LEFT JOIN state.load_state s
            ON s.registry = r.registry AND s.checksum = r.checksum
        WHERE r.registry IN ({marks}) AND r.is_latest = 1 AND s.checksum IS NULL
        ORDER BY r.registry, r.checksum
        """,
        registries,
    ).fetchall()

    for registry, checksum, s_uri, s_meta, r_uri, r_meta, r_algo, r_status in db.execute(
        f"""
        SELECT s.registry, s.checksum, s.uri, s.metadata,
               r.uri, r.metadata, r.checksum_algo, r.status
        FROM state.load_state s
        JOIN idx.records r
            ON r.registry = s.registry AND r.checksum = s.checksum AND r.is_latest = 1
        WHERE s.registry IN ({marks})
        """,
        registries,
    ):
        fields = []
        if r_uri != s_uri:
            fields.append("uri")
        if r_meta != s_meta:
            fields.append("metadata")
        if r_algo != CHECKSUM_ALGO:
            fields.append("checksumAlgo")
        if r_status != "Active":
            fields.append("status")
        if fields:
            report.drift.append((registry, checksum, "+".join(fields)))
        else:
            report.matched += 1
    db.close()
    return report


def print_report(report: Report, sample: int = 10) -> None:
    print(f"reconcile over {', '.join(report.registries)}:")
    print(f"  matched exactly: {report.matched:,}")
    for status, count in sorted(report.backlog.items()):
        print(f"  backlog ({status}, not yet expected on chain): {count:,}")
    print(f"  confirmed-but-missing-on-chain: {len(report.confirmed_missing):,}")
    for registry, checksum in report.confirmed_missing[:sample]:
        print(f"    {registry}  {checksum}")
    print(f"  extra-on-chain: {len(report.extra):,}")
    for registry, checksum in report.extra[:sample]:
        print(f"    {registry}  {checksum}")
    print(f"  drift: {len(report.drift):,}")
    for registry, checksum, fields in report.drift[:sample]:
        print(f"    {registry}  {checksum}  ({fields})")
    print(f"  verdict: {'CLEAN' if report.clean else 'DIFFS FOUND'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff load_state against the synced chain index.")
    parser.add_argument("--state", type=Path, default=Path("data/load_state.sqlite"))
    parser.add_argument("--index", type=Path, default=Path("data/chain_index.sqlite"))
    parser.add_argument("--registries", required=True)
    parser.add_argument("--sample", type=int, default=10)
    args = parser.parse_args(argv)

    names = [n.strip() for n in args.registries.split(",") if n.strip()]
    report = reconcile(args.state, args.index, names)
    print_report(report, args.sample)
    return 0 if report.clean else 1


if __name__ == "__main__":
    sys.exit(main())
