"""Chain index: offset-paged records() reads into chain_index.sqlite (task 2.3).

rebuild-index is the public-auditability story made executable: anyone with
an RPC URL can reconstruct a registry's contents without trusting us. sync
continues from the stored row offset.

Measured precompile behavior this module is built around (DECISIONS
2026-06-10, experiments (g)/(h)):
- every page is capped at 200 rows server-side regardless of the requested
  limit; end of data is detected by a SHORT page, never by countTotal or
  nextKey (both unreliable, totals must be counted client-side);
- list views return only the LATEST version per record, so the index stores
  the latest version observed at sync time (idx + is_latest kept so
  superseded observations remain distinguishable; reconcile reads
  is_latest=1);
- the public RPC serves archive state, so a whole sync is pinned to one
  block height and the index is a consistent snapshot "as of block H".

Incremental sync assumes the registries are append-mostly (true for the
bulk load): a new VERSION of an already-synced record changes a list row
behind the stored offset and is only caught by re-fetching one overlap page
and, ultimately, by rebuild-index. Reconcile against a fresh rebuild is the
audit path.

Run:  uv run python -m nvnm_cite.chain.indexer sync --registries us-scotus,us-ca11
      uv run python -m nvnm_cite.chain.indexer rebuild-index --registries us-scotus
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections.abc import Callable
from pathlib import Path

from nvnm_cite.chain.precompile import (
    PRECOMPILE_ADDRESS,
    Record,
    build_records_query,
    build_registries_query,
    decode_records_result,
    decode_registries_result,
)
from nvnm_cite.chain.rpc import EvmRpc, RpcError

PAGE_LIMIT = 200  # measured server cap; larger requests still return 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    registry      TEXT NOT NULL,
    checksum      TEXT NOT NULL,
    record_id     INTEGER NOT NULL,
    idx           INTEGER NOT NULL,
    is_latest     INTEGER NOT NULL,
    uri           TEXT NOT NULL,
    checksum_algo TEXT NOT NULL,
    metadata      TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    status        TEXT NOT NULL,
    PRIMARY KEY (registry, checksum, idx)
);
CREATE INDEX IF NOT EXISTS idx_records_latest
    ON records(registry, is_latest, checksum);
CREATE TABLE IF NOT EXISTS sync_state (
    registry   TEXT PRIMARY KEY,
    row_offset INTEGER NOT NULL,
    head_block INTEGER NOT NULL,
    synced_at  TEXT NOT NULL
);
"""

# fetch_page(registry, offset, limit) -> list of Record (chain order)
FetchPage = Callable[[str, int, int], list[Record]]


def open_index(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    return db


def upsert_records(db: sqlite3.Connection, rows: list[Record]) -> None:
    """Store the rows as the latest observed versions of their keys."""
    for rec in rows:
        db.execute(
            "UPDATE records SET is_latest = 0 WHERE registry = ? AND checksum = ?",
            (rec.registry, rec.checksum),
        )
        db.execute(
            "INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                rec.registry,
                rec.checksum,
                rec.record_id,
                rec.index,
                1 if rec.is_latest else 0,
                rec.uri,
                rec.checksum_algo,
                rec.metadata,
                rec.timestamp,
                rec.status,
            ),
        )


def sync_registry(
    db: sqlite3.Connection,
    registry: str,
    fetch_page: FetchPage,
    head_block: int,
    from_offset: int | None = None,
    log: Callable[[str], None] = lambda s: print(s, flush=True),
) -> int:
    """Page one registry from from_offset (default: stored, minus one overlap
    page) until a short page. Returns rows fetched."""
    if from_offset is None:
        row = db.execute(
            "SELECT row_offset FROM sync_state WHERE registry = ?", (registry,)
        ).fetchone()
        # Re-fetch one full page behind the stored cursor: cheap insurance
        # against versions/boundary movement just behind the high-water mark.
        from_offset = max(0, (row[0] if row else 0) - PAGE_LIMIT)

    offset = from_offset
    fetched = 0
    started = time.monotonic()
    while True:
        rows = fetch_page(registry, offset, PAGE_LIMIT)
        upsert_records(db, rows)
        offset += len(rows)
        fetched += len(rows)
        db.execute(
            "INSERT OR REPLACE INTO sync_state VALUES (?,?,?,?)",
            (registry, offset, head_block, time.strftime("%Y-%m-%dT%H:%M:%S%z")),
        )
        db.commit()
        if fetched and fetched % 10_000 == 0:
            rate = fetched / max(time.monotonic() - started, 1e-9)
            log(f"  {registry}: {offset:,} rows ({rate:,.0f} rows/s)")
        if len(rows) < PAGE_LIMIT:
            break
    log(f"  {registry}: synced to offset {offset:,} at block {head_block:,}")
    return fetched


def rpc_fetch_page(rpc: EvmRpc, block_tag: str) -> FetchPage:
    """The production fetcher: records() eth_call pinned to one block."""

    def fetch(registry: str, offset: int, limit: int) -> list[Record]:
        calldata = build_records_query(registry=registry, offset=offset, limit=limit)
        try:
            raw = rpc.eth_call(PRECOMPILE_ADDRESS, calldata, block=block_tag)
        except RpcError as err:
            # Keyed-miss semantics: an empty/missing collection ERRORS, it
            # never returns an empty page (DECISIONS 2026-06-10). Registry
            # existence is checked separately before paging.
            if "not found" in err.message:
                return []
            raise
        rows, _page = decode_records_result(raw)
        return rows

    return fetch


def registry_exists(rpc: EvmRpc, name: str) -> bool:
    try:
        registries, _ = decode_registries_result(
            rpc.eth_call(PRECOMPILE_ADDRESS, build_registries_query(name=name))
        )
    except RpcError as err:
        if "not found" in err.message:
            return False
        raise
    return any(r.name == name for r in registries)


def index_stats(db: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    """registry -> (latest rows, total rows, sync head block)."""
    stats: dict[str, tuple[int, int, int]] = {}
    for registry, head in db.execute("SELECT registry, head_block FROM sync_state"):
        latest, total = db.execute(
            "SELECT SUM(is_latest), COUNT(*) FROM records WHERE registry = ?",
            (registry,),
        ).fetchone()
        stats[registry] = (latest or 0, total or 0, head)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync NVNM registries into a local index.")
    parser.add_argument("command", choices=["sync", "rebuild-index"])
    parser.add_argument("--db", type=Path, default=Path("data/chain_index.sqlite"))
    parser.add_argument("--registries", required=True, help="comma-separated registry names")
    parser.add_argument("--rpc", default=None, help="RPC URL (default: testnet from config)")
    args = parser.parse_args(argv)

    from nvnm_cite.config import load_dotenv, testnet_rpc

    load_dotenv()
    rpc = EvmRpc(args.rpc or testnet_rpc())
    head = rpc.block_number()
    block_tag = hex(head)
    fetch = rpc_fetch_page(rpc, block_tag)
    db = open_index(args.db)

    names = [n.strip() for n in args.registries.split(",") if n.strip()]
    for name in names:
        if not registry_exists(rpc, name):
            print(f"  {name}: registry does not exist on chain; skipping")
            continue
        if args.command == "rebuild-index":
            db.execute("DELETE FROM records WHERE registry = ?", (name,))
            db.execute("DELETE FROM sync_state WHERE registry = ?", (name,))
            db.commit()
            sync_registry(db, name, fetch, head, from_offset=0)
        else:
            sync_registry(db, name, fetch, head)

    print(f"\nindex stats ({args.db}):")
    for registry, (latest, total, head_block) in sorted(index_stats(db).items()):
        print(f"  {registry}: {latest:,} records ({total:,} versions) as of block {head_block:,}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
