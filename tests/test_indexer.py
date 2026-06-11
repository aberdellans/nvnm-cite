"""Indexer tests (task 2.3): paging, short-page end, overlap re-fetch, versions.

The chain is faked with an in-memory list per registry; the production
fetcher's RPC behavior (keyed-miss errors, 200-row cap, block pinning) is
characterized in DECISIONS and exercised live in Phase 2.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nvnm_cite.chain.indexer import (
    PAGE_LIMIT,
    index_stats,
    open_index,
    sync_registry,
)
from nvnm_cite.chain.precompile import Record


def make_record(registry: str, n: int, idx: int = 1, is_latest: bool = True) -> Record:
    return Record(
        registry=registry,
        uri=f"https://example.test/{n}",
        checksum=f"{n} U.S. {n + 7}",
        checksum_algo="cite-canonical-v1",
        metadata=f'{{"cluster":{n}}}',
        timestamp="2026-06-11 00:00:00 +0000 UTC",
        status="Active",
        record_id=n,
        index=idx,
        is_latest=is_latest,
    )


class FakeChain:
    """List view per registry: latest version per record, insertion order."""

    def __init__(self) -> None:
        self.rows: dict[str, list[Record]] = {}
        self.calls = 0

    def fetch(self, registry: str, offset: int, limit: int) -> list[Record]:
        self.calls += 1
        # The server never returns more than PAGE_LIMIT rows per call.
        limit = min(limit, PAGE_LIMIT)
        return self.rows.get(registry, [])[offset : offset + limit]


def latest_checksums(db: sqlite3.Connection, registry: str) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            "SELECT checksum FROM records WHERE registry = ? AND is_latest = 1",
            (registry,),
        )
    }


def test_multi_page_sync_ends_on_short_page(tmp_path: Path) -> None:
    chain = FakeChain()
    chain.rows["us-test"] = [make_record("us-test", n) for n in range(450)]
    db = open_index(tmp_path / "idx.sqlite")

    fetched = sync_registry(db, "us-test", chain.fetch, head_block=100, log=lambda s: None)
    assert fetched == 450
    assert chain.calls == 3  # 200 + 200 + 50 (short page stops the loop)
    assert index_stats(db) == {"us-test": (450, 450, 100)}


def test_empty_registry_syncs_zero(tmp_path: Path) -> None:
    chain = FakeChain()
    db = open_index(tmp_path / "idx.sqlite")
    fetched = sync_registry(db, "us-empty", chain.fetch, head_block=5, log=lambda s: None)
    assert fetched == 0
    assert index_stats(db) == {"us-empty": (0, 0, 5)}


def test_incremental_sync_with_overlap(tmp_path: Path) -> None:
    chain = FakeChain()
    chain.rows["us-test"] = [make_record("us-test", n) for n in range(300)]
    db = open_index(tmp_path / "idx.sqlite")
    sync_registry(db, "us-test", chain.fetch, head_block=1, log=lambda s: None)

    # 150 new records appended on chain; resync starts one page behind the
    # stored offset (300 - 200 = 100) and walks to the new end.
    chain.rows["us-test"] += [make_record("us-test", n) for n in range(300, 450)]
    fetched = sync_registry(db, "us-test", chain.fetch, head_block=2, log=lambda s: None)
    assert fetched == 350  # overlap (200) + new rows (150)
    assert index_stats(db) == {"us-test": (450, 450, 2)}
    assert len(latest_checksums(db, "us-test")) == 450


def test_version_update_keeps_one_latest(tmp_path: Path) -> None:
    chain = FakeChain()
    chain.rows["us-test"] = [make_record("us-test", n) for n in range(10)]
    db = open_index(tmp_path / "idx.sqlite")
    sync_registry(db, "us-test", chain.fetch, head_block=1, log=lambda s: None)

    # Record 3 is superseded: same checksum and recordId, idx bumps to 2
    # (duplicates VERSION, never revert -- DECISIONS (a)).
    chain.rows["us-test"][3] = make_record("us-test", 3, idx=2)
    sync_registry(db, "us-test", chain.fetch, head_block=2, from_offset=0, log=lambda s: None)

    versions = db.execute(
        "SELECT idx, is_latest FROM records WHERE checksum = '3 U.S. 10' ORDER BY idx"
    ).fetchall()
    assert versions == [(1, 0), (2, 1)]  # both observations kept, one latest
    latest, total, _ = index_stats(db)["us-test"]
    assert latest == 10
    assert total == 11


def test_registries_isolated(tmp_path: Path) -> None:
    chain = FakeChain()
    chain.rows["us-a"] = [make_record("us-a", n) for n in range(5)]
    chain.rows["us-b"] = [make_record("us-b", n) for n in range(7)]
    db = open_index(tmp_path / "idx.sqlite")
    sync_registry(db, "us-a", chain.fetch, head_block=1, log=lambda s: None)
    sync_registry(db, "us-b", chain.fetch, head_block=1, log=lambda s: None)
    assert index_stats(db) == {"us-a": (5, 5, 1), "us-b": (7, 7, 1)}
