# NOTE: pre-v1.2.0 ABI (name-keyed records/registries/addRecord); historical
# record of the pilot probes/load — non-functional against current chains.
"""Backfill real reporter citations that CourtListener is MISSING — TEST PILOT ONLY.

CourtListener holds some Published opinion clusters with NO reporter citation
attached (e.g. Muransky v. Godiva, 979 F.3d 917 (11th Cir. 2020) (en banc) —
cluster present, cite absent in CL bulk AND live; citation-lookup 404). Our
CL-derived registry is keyed by reporter citation, so those real cases come back
NOT_FOUND. This tool writes a curated, schema-conformant record for each such
cite into the existing us-* registry on TESTNET, signed by the registry's admin
(the load key), so a live check finds the case.

It is deliberately minimal and honest:
- Only the missing cite->cluster LINK is supplied. The case name / year / slug /
  uri come from the cluster we already hold in corpus.sqlite (CL's own data),
  rendered through the LOCKED record schema (loader/records.render_record).
- Idempotent: a cite already on chain is skipped.
- Keeps the local index consistent (chain_index.records + corpus.citations) so
  `stats` / `reconcile` stay accurate. The CSV is the auditable list of what we
  added beyond CL, re-appliable after a corpus rebuild.

NOT a mainnet path. The principled fix for production is Phase 7 task 7.1.

    uv run python scripts/backfill_supplemental.py --dry-run   # preview, no write
    uv run python scripts/backfill_supplemental.py             # write to testnet
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import EvmRpc
from nvnm_cite.chain.secp256k1 import address_from_private_key
from nvnm_cite.chain.signer import LegacyTransaction, sign_transaction
from nvnm_cite.config import TESTNET_CHAIN_ID, load_dotenv, testnet_private_key, testnet_rpc
from nvnm_cite.loader.records import CHECKSUM_ALGO, CaseRow, render_record
from nvnm_cite.receipts.chainio import ChainReader

GAS_FLOOR = 40_000_000_000  # 40 gwei chain floor (DECISIONS 2026-06-10)
GAS_HEADROOM_PCT = 25
DEFAULT_CSV = Path(__file__).with_name("supplemental_citations.csv")


def _split_canonical(canonical: str) -> tuple[str, str, str]:
    """`<volume> <reporter...> <page>` -> (volume, reporter, page)."""
    parts = canonical.split()
    if len(parts) < 3:
        raise ValueError(f"cannot split canonical citation {canonical!r}")
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def _send(rpc: EvmRpc, key: int, calldata: bytes) -> dict:
    """Sign + send one addRecord with the load key; wait for the receipt."""
    address = address_from_private_key(key)
    nonce = rpc.get_transaction_count(address, "pending")
    gas_price = max(rpc.gas_price(), GAS_FLOOR)
    gas = rpc.estimate_gas(address, pc.PRECOMPILE_ADDRESS, calldata)
    tx = LegacyTransaction(
        nonce=nonce,
        gas_price=gas_price,
        gas_limit=gas + gas * GAS_HEADROOM_PCT // 100,
        to=pc.PRECOMPILE_ADDRESS,
        value=0,
        data=calldata,
    )
    signed = sign_transaction(tx, key, TESTNET_CHAIN_ID)
    tx_hash = rpc.send_raw_transaction(signed.raw)
    receipt = rpc.wait_for_receipt(tx_hash)
    return {
        "tx_hash": tx_hash,
        "block": int(receipt.get("blockNumber", "0x0"), 16),
        "gas_used": int(receipt.get("gasUsed", "0x0"), 16),
        "ok": int(receipt.get("status", "0x0"), 16) == 1,
    }


def _read_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


def _index_record(index: sqlite3.Connection, rec: pc.Record) -> None:
    """Upsert the on-chain record into chain_index so stats/reconcile stay accurate."""
    index.execute(
        """INSERT OR REPLACE INTO records
               (registry, checksum, record_id, idx, is_latest, uri, checksum_algo, metadata, timestamp, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (rec.registry, rec.checksum, rec.record_id, rec.index, 1 if rec.is_latest else 0,
         rec.uri, rec.checksum_algo, rec.metadata, rec.timestamp, rec.status),
    )
    index.commit()


def _index_corpus(corpus: sqlite3.Connection, cluster_id: int, canonical: str) -> None:
    """Insert the cite into the corpus so corpus-vs-chain reconcile stays clean."""
    vol, rep, page = _split_canonical(canonical)
    next_id = (corpus.execute("SELECT COALESCE(MAX(citation_id), 0) + 1 FROM citations").fetchone()[0])
    corpus.execute(
        "INSERT INTO citations (citation_id, cluster_id, volume, reporter, page, type, canonical) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (next_id, cluster_id, vol, rep, page, 1, canonical),
    )
    corpus.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill CL-missing reporter cites into testnet us-* registries (test pilot)")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--rpc", default=None)
    parser.add_argument("--dry-run", action="store_true", help="preview the records; send nothing")
    args = parser.parse_args(argv)

    load_dotenv()
    rpc_url = args.rpc or testnet_rpc()
    reader = ChainReader(lambda: EvmRpc(rpc_url))
    corpus = sqlite3.connect(args.data_dir / "corpus.sqlite")
    index = sqlite3.connect(args.data_dir / "chain_index.sqlite")
    key = None if args.dry_run else testnet_private_key()
    if not args.dry_run:
        print(f"Signing wallet: {address_from_private_key(key)}")

    added = skipped = failed = 0
    for row in _read_rows(args.csv):
        registry, canonical, cluster_id = row["registry"].strip(), row["canonical"].strip(), int(row["cluster_id"])
        cluster = corpus.execute(
            "SELECT case_name, year, slug FROM clusters WHERE cluster_id=?", (cluster_id,)
        ).fetchone()
        if cluster is None:
            print(f"  SKIP {registry} {canonical!r}: cluster {cluster_id} not in corpus"); failed += 1; continue
        name, year, slug = cluster
        rendered = render_record(registry, canonical, [CaseRow(cluster_id, name, year, slug or "")])
        calldata = pc.build_add_record(
            registry=rendered.registry, uri=rendered.uri, checksum=rendered.checksum,
            checksum_algo=CHECKSUM_ALGO, metadata=rendered.metadata,
        )
        existing = reader.keyed_record(registry, canonical)
        print(f"\n{registry}  {canonical!r}  (cluster {cluster_id})")
        print(f"  uri      : {rendered.uri}")
        print(f"  metadata : {rendered.metadata}")
        if existing is not None:
            print("  -> already on chain; ensuring local index, skipping write")
            _index_record(index, existing)
            skipped += 1
            continue
        if args.dry_run:
            print("  -> DRY RUN: would addRecord (not sent)")
            continue
        result = _send(EvmRpc(rpc_url), key, calldata)
        if not result["ok"]:
            print(f"  -> FAILED: tx {result['tx_hash']} reverted"); failed += 1; continue
        record = reader.keyed_record(registry, canonical)
        if record is not None:
            _index_record(index, record)
        _index_corpus(corpus, cluster_id, canonical)
        print(f"  -> ANCHORED: tx {result['tx_hash']} block {result['block']:,} gas {result['gas_used']:,}")
        added += 1

    print(f"\n{'DRY RUN ' if args.dry_run else ''}done: {added} added, {skipped} already-present, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
