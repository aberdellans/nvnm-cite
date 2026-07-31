"""Checkpointed single-key bulk writer (plan task 2.4; key strategy per
DECISIONS 2026-06-11: one funded key, Albert's call, doubling as a
sustained-load stress test of the chain).

Subcommands:
  prepare  corpus.sqlite -> load_state rows (pure local; inspect before
           sending anything). Renders records through loader/records.py
           against the locked schema, validates caps, groups collisions,
           and excludes non-loadable rows with stored reasons.
  run      submit pending rows from the checkpoint DB. Single-key,
           strictly serialized nonces (the chain rejects gapped nonces
           outright), pipelined to depth ~50 (measured single-sender
           plateau is ~1.1 confirmed tx/s from depth 20 up).
  status   checkpoint counters, throughput, balance, ETA.

Idempotency doctrine (DECISIONS (a)): duplicates create VERSIONS and
estimateGas does not flag them, so the checkpoint DB is the ONLY guard.
Never blind-resubmit. On resume, wait for the mempool to drain (pending
nonce == latest nonce), then re-verify ONLY the rows left 'submitted' via
keyed records() reads, treating the keyed-miss RpcError ("collections: not
found") as not-loaded. Steady state never pre-checks existence per record
(that would double RPC traffic for nothing).

Failure doctrine: a failed send halts everything queued behind it (nonce
serialization); a stuck nonce is re-sent as the SAME nonce at +25% gas; an
on-chain revert or unexplained RPC state halts the loader for reconcile
rather than guessing.
"""

from __future__ import annotations

import argparse
import http.client
import signal
import sqlite3
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from nvnm_cite.chain.precompile import (
    PRECOMPILE_ADDRESS,
    build_add_record,
    build_records_query,
    decode_records_result,
)
from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.chain.secp256k1 import address_from_private_key
from nvnm_cite.chain.signer import LegacyTransaction, sign_transaction
from nvnm_cite.config import get_network, load_dotenv, signing_context
from nvnm_cite.loader.records import CaseRow, RecordError, render_record

GAS_FLOOR = 40_000_000_000  # 40 gwei chain floor
STUCK_SECONDS = 180.0  # account nonce not advancing -> re-send head at +25%
DEFAULT_DEPTH = 50
BALANCE_HALT_WEI = 10**18  # halt cleanly below 1 wmantraUSD

# Gas limit from the measured curve instead of a per-record estimateGas
# round-trip (2026-06-11 optimization, Albert's call: the first live run
# confirmed at ~0.76 tx/s with estimate+send+receipt per record all serial
# HTTP). Phase 0 measured ~70k intercept + ~76 gas per payload-string byte,
# exact to the unit at 256 B and 1,024 B; the live load's 89,526 average
# sits on the same line. 75k + 80/byte plus 30% headroom clears the worst
# 2048 B metadata row with margin; unused limit is refunded, and reconcile
# is the ground truth for anything gas can get wrong.
GAS_BASE = 75_000
GAS_PER_BYTE = 80
GAS_HEADROOM_PCT = 30
RECEIPT_SAMPLE = 50  # receipt-check every Nth nonce: revert detection

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS load_state (
    position   INTEGER PRIMARY KEY AUTOINCREMENT,
    registry   TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    uri        TEXT NOT NULL,
    metadata   TEXT NOT NULL,
    tranche    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    nonce      INTEGER,
    tx_hash    TEXT,
    gas_used   INTEGER,
    block      INTEGER,
    updated_at TEXT,
    UNIQUE (registry, checksum)
);
CREATE INDEX IF NOT EXISTS idx_load_status ON load_state(status, position);
CREATE TABLE IF NOT EXISTS excluded (
    registry  TEXT NOT NULL,
    canonical TEXT NOT NULL,
    reason    TEXT NOT NULL,
    PRIMARY KEY (registry, canonical)
);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


T = TypeVar("T")

# Transport-level failures are retried (the operation either never reached
# the node or is idempotent to repeat); RpcError is SEMANTIC (the node
# answered) and is never retried here -- the caller decides what it means.
_TRANSPORT_ERRORS = (OSError, http.client.HTTPException, ValueError)
_RETRY_SCHEDULE = (1, 2, 5, 15, 30)


def rpc_retry(log: Callable[[str], None], label: str, call: Callable[[], T]) -> T:
    """Run an idempotent RPC call, riding out transient transport failures.

    A 75-hour unattended load must survive Cloudflare hiccups and timeouts;
    every call routed through here is safe to repeat: reads trivially, and
    re-sending the SAME raw tx bytes yields the same hash."""
    for delay in _RETRY_SCHEDULE:
        try:
            return call()
        except RpcError:
            raise
        except _TRANSPORT_ERRORS as err:
            log(f"transient RPC failure on {label}: {type(err).__name__}: {err}; retry in {delay}s")
            time.sleep(delay)
    return call()  # last attempt surfaces the real exception


def open_state(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(db_path)
    db.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
    db.executescript(SCHEMA)
    return db


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------


def known_editions() -> frozenset[str]:
    """Every edition string in reporters-db (the cite-canonical/v1 key space)."""
    from reporters_db import REPORTERS

    return frozenset(
        edition
        for variants in REPORTERS.values()
        for variant in variants
        for edition in variant.get("editions", {})
    )


def prepare(
    corpus_path: Path,
    state_path: Path,
    court: str,
    reporters: tuple[str, ...],
    tranche: str,
    precedential_only: bool = False,
) -> dict[str, int]:
    """Render every loadable (registry, canonical) for one court into
    load_state. Re-running upserts nothing: existing keys are left alone.

    reporters is the census-informed whitelist of exact CL reporter strings
    (which are reporters-db edition strings for everything we load): the
    verifier-reachable key space, decided in DECISIONS 2026-06-11. The
    precedential_status field cannot define tranches (the census measured
    scotus as ~all 'Published', cert denials included), so the whitelist IS
    the load-set rule."""
    if not reporters:
        raise ValueError("an explicit reporter whitelist is required")
    corpus = sqlite3.connect(corpus_path)
    state = open_state(state_path)
    editions = known_editions()
    registry = f"us-{court}"

    where = ["cl.court_id = ?", "ci.canonical IS NOT NULL"]
    params: list = [court]
    where.append(f"ci.reporter IN ({','.join('?' * len(reporters))})")
    params.extend(reporters)
    if precedential_only:
        where.append("cl.precedential_status = 'Published'")

    rows = corpus.execute(
        f"""
        SELECT ci.canonical, ci.reporter, cl.cluster_id, cl.case_name, cl.year, cl.slug
        FROM citations ci JOIN clusters cl USING (cluster_id)
        WHERE {' AND '.join(where)}
        ORDER BY ci.canonical, cl.cluster_id
        """,
        params,
    )

    # Group by canonical; dedupe clusters (parallel rows of the same cluster
    # under one key happen when CL stores duplicate citation rows).
    stats = {"rendered": 0, "collisions": 0, "excluded_reporter": 0, "excluded_caps": 0, "existing": 0}
    batch: list[tuple] = []
    excluded: list[tuple] = []

    def flush_group(canonical: str | None, group: dict[int, CaseRow], reporter_ok: bool) -> None:
        if canonical is None or not group:
            return
        if not reporter_ok:
            stats["excluded_reporter"] += 1
            excluded.append((registry, canonical, "reporter not a reporters-db edition"))
            return
        cases = list(group.values())
        try:
            rec = render_record(registry, canonical, cases)
        except RecordError as err:
            stats["excluded_caps"] += 1
            excluded.append((registry, canonical, str(err)))
            return
        if len(cases) > 1:
            stats["collisions"] += 1
        batch.append((rec.registry, rec.checksum, rec.uri, rec.metadata, tranche, _now()))

    current: str | None = None
    group: dict[int, CaseRow] = {}
    reporter_ok = True
    for canonical, reporter, cluster_id, name, year, slug in rows:
        if canonical != current:
            flush_group(current, group, reporter_ok)
            current, group, reporter_ok = canonical, {}, reporter in editions
        group.setdefault(cluster_id, CaseRow(cluster_id, name, year, slug))
        if len(batch) >= 5_000:
            _insert_prepared(state, batch, stats)
    flush_group(current, group, reporter_ok)
    _insert_prepared(state, batch, stats)
    state.executemany("INSERT OR REPLACE INTO excluded VALUES (?,?,?)", excluded)
    state.execute(
        "INSERT OR REPLACE INTO meta VALUES (?,?)",
        (
            f"prepare:{tranche}",
            f"court={court} reporters={reporters} precedential_only={precedential_only} at={_now()}",
        ),
    )
    state.commit()
    corpus.close()
    state.close()
    return stats


def _insert_prepared(state: sqlite3.Connection, batch: list[tuple], stats: dict[str, int]) -> None:
    if not batch:
        return
    before = state.total_changes
    state.executemany(
        "INSERT OR IGNORE INTO load_state"
        " (registry, checksum, uri, metadata, tranche, updated_at)"
        " VALUES (?,?,?,?,?,?)",
        batch,
    )
    inserted = state.total_changes - before
    stats["rendered"] += inserted
    stats["existing"] += len(batch) - inserted
    state.commit()
    batch.clear()


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


@dataclass
class InFlight:
    nonce: int
    position: int
    tx_hash: str
    raw: bytes
    gas_price: int
    sent_at: float


class Halt(RuntimeError):
    """Stop submitting; checkpoint stays consistent for the next resume."""


def chain_has_key(
    rpc: EvmRpc, registry_id: int, checksum: str, log=lambda s: None
) -> bool:
    """Keyed existence read (id-keyed under v1.2.0); the miss signal is the
    RpcError, never an empty page (DECISIONS 2026-06-10)."""
    calldata = build_records_query(registry_id=registry_id, checksum=checksum)
    try:
        rows, _ = decode_records_result(
            rpc_retry(log, "records()", lambda: rpc.eth_call(PRECOMPILE_ADDRESS, calldata))
        )
    except RpcError as err:
        if "not found" in err.message:
            return False
        raise
    return bool(rows)


def _registry_id_or_halt(registry_ids, registry: str) -> int:
    rid = registry_ids.get(registry)
    if rid is None:
        raise Halt(f"{registry} is not in the registry manifest; refusing to guess an id")
    return rid


def recover_submitted(
    db: sqlite3.Connection, rpc: EvmRpc, address: str, registry_ids, log
) -> None:
    """Resume protocol: drain the mempool, then settle every 'submitted' row
    by a keyed read. Only the in-flight window can be in this state."""
    rows = db.execute(
        "SELECT position, registry, checksum FROM load_state WHERE status = 'submitted' ORDER BY position"
    ).fetchall()
    if not rows:
        return
    log(f"recovery: {len(rows)} rows left 'submitted' by a previous run")
    while True:
        pending = rpc_retry(log, "nonce(pending)", lambda: rpc.get_transaction_count(address, "pending"))
        latest = rpc_retry(log, "nonce(latest)", lambda: rpc.get_transaction_count(address, "latest"))
        if pending == latest:
            break
        log(f"recovery: mempool still draining (pending {pending} > latest {latest}); waiting")
        time.sleep(5)
    confirmed = reset = 0
    for position, registry, checksum in rows:
        if chain_has_key(rpc, _registry_id_or_halt(registry_ids, registry), checksum, log):
            db.execute(
                "UPDATE load_state SET status='confirmed', updated_at=? WHERE position=?",
                (_now(), position),
            )
            confirmed += 1
        else:
            db.execute(
                "UPDATE load_state SET status='pending', nonce=NULL, tx_hash=NULL, updated_at=?"
                " WHERE position=?",
                (_now(), position),
            )
            reset += 1
    db.commit()
    log(f"recovery: {confirmed} confirmed on chain, {reset} reset to pending")


def run_load(
    db: sqlite3.Connection,
    rpc: EvmRpc,
    key: int,
    chain_id: int,
    registry_ids,
    depth: int = DEFAULT_DEPTH,
    log=lambda s: print(s, flush=True),
    max_records: int | None = None,
) -> dict[str, int]:
    """``key``/``chain_id`` come from config.signing_context (the one signing
    gate); ``registry_ids`` is the pinned manifest's name -> id map."""
    address = address_from_private_key(key)
    live_chain = rpc.chain_id()
    if live_chain != chain_id:
        raise Halt(f"chain id {live_chain} != {chain_id}; refusing to write")

    recover_submitted(db, rpc, address, registry_ids, log)

    stop = {"flag": False}

    def _signal(_sig, _frame):
        stop["flag"] = True
        log("signal received: finishing in-flight window, then checkpoint-exit")

    signal.signal(signal.SIGINT, _signal)
    signal.signal(signal.SIGTERM, _signal)

    nonce = rpc.get_transaction_count(address, "pending")
    gas_price = max(rpc.gas_price(), GAS_FLOOR)
    inflight: deque[InFlight] = deque()
    counters = {"confirmed": 0, "resent": 0}
    started = time.monotonic()
    last_log = started
    submitted_since_refresh = 0

    def fetch_pending(limit: int) -> list[tuple]:
        return db.execute(
            "SELECT position, registry, checksum, uri, metadata FROM load_state"
            " WHERE status = 'pending' ORDER BY position LIMIT ?",
            (limit,),
        ).fetchall()

    def submit(row: tuple, use_nonce: int) -> InFlight:
        position, registry, checksum, uri, metadata = row
        calldata = build_add_record(
            registry_id=_registry_id_or_halt(registry_ids, registry),
            uri=uri,
            checksum=checksum,
            checksum_algo="cite-canonical-v1",
            metadata=metadata,
        )
        # Analytic gas limit (see GAS_BASE note): caps were validated at
        # prepare, auth is proven by the running load, duplicates never
        # revert -- nothing a per-record estimate would catch is left.
        # (v1.2.0: the registry name left the payload; the uint64 id is in
        # the static tuple head and is covered by GAS_BASE.)
        payload_bytes = len(
            (uri + checksum + "cite-canonical-v1" + metadata).encode("utf-8")
        )
        gas = GAS_BASE + GAS_PER_BYTE * payload_bytes
        tx = LegacyTransaction(
            nonce=use_nonce,
            gas_price=gas_price,
            gas_limit=gas + gas * GAS_HEADROOM_PCT // 100,
            to=PRECOMPILE_ADDRESS,
            value=0,
            data=calldata,
        )
        signed = sign_transaction(tx, key, chain_id)
        try:
            tx_hash = rpc_retry(
                log, "sendRawTransaction", lambda: rpc.send_raw_transaction(signed.raw)
            )
        except RpcError as err:
            # A transport retry can race a send that actually landed: the
            # repeat then sees the node's duplicate/consumed-nonce response.
            # Our hash is deterministic, so check whether the consumed slot
            # is OURS before treating it as fatal.
            message = err.message.lower()
            if "already known" in message or "already in mempool" in message:
                tx_hash = signed.hash_hex
            elif "nonce" in message:
                tx_hash = None
                for _ in range(10):
                    if rpc.get_transaction_receipt(signed.hash_hex) is not None:
                        tx_hash = signed.hash_hex
                        break
                    time.sleep(3)
                if tx_hash is None:
                    raise
            else:
                raise
        db.execute(
            "UPDATE load_state SET status='submitted', nonce=?, tx_hash=?, updated_at=?"
            " WHERE position=?",
            (use_nonce, tx_hash, _now(), position),
        )
        db.commit()
        return InFlight(use_nonce, position, tx_hash, signed.raw, gas_price, time.monotonic())

    remaining = max_records
    try:
        while not (stop["flag"] and not inflight):
            # Fill the pipeline.
            if not stop["flag"]:
                want = depth - len(inflight)
                if remaining is not None:
                    want = min(want, remaining)
                if want > 0:
                    rows = fetch_pending(want)
                    if not rows and not inflight:
                        break
                    for row in rows:
                        inflight.append(submit(row, nonce))
                        nonce += 1
                        submitted_since_refresh += 1
                        if remaining is not None:
                            remaining -= 1
                    if submitted_since_refresh >= 500:
                        gas_price = max(rpc_retry(log, "gasPrice", rpc.gas_price), GAS_FLOOR)
                        submitted_since_refresh = 0
                        balance = rpc_retry(log, "balance", lambda: rpc.get_balance(address))
                        if balance < BALANCE_HALT_WEI:
                            raise Halt(f"balance {balance / 1e18:.3f} below halt floor")
            if not inflight:
                if stop["flag"] or (remaining is not None and remaining <= 0):
                    break
                time.sleep(0.2)
                continue

            # Confirmation by account-nonce advance: one read settles every
            # in-flight tx below it. Nonce advance proves INCLUSION, not
            # success; sampled receipts catch reverts fast and reconcile is
            # the ground truth for everything.
            latest = rpc_retry(
                log, "nonce(latest)", lambda: rpc.get_transaction_count(address, "latest")
            )
            drained: list[tuple] = []
            while inflight and inflight[0].nonce < latest:
                done = inflight.popleft()
                gas_used = block = None
                if done.nonce % RECEIPT_SAMPLE == 0:
                    receipt = rpc_retry(
                        log, "getReceipt", lambda: rpc.get_transaction_receipt(done.tx_hash)
                    )
                    if receipt is None:
                        # Nonce consumed but our hash has no receipt: a
                        # replacement raced it. The keyed read settles
                        # whether OUR record landed.
                        reg, ck = db.execute(
                            "SELECT registry, checksum FROM load_state WHERE position=?",
                            (done.position,),
                        ).fetchone()
                        if not chain_has_key(rpc, _registry_id_or_halt(registry_ids, reg), ck, log):
                            db.execute(
                                "UPDATE load_state SET status='failed', updated_at=? WHERE position=?",
                                (_now(), done.position),
                            )
                            db.commit()
                            raise Halt(
                                f"nonce {done.nonce} consumed by an unknown tx and key absent; reconcile"
                            )
                    elif int(receipt["status"], 16) != 1:
                        db.execute(
                            "UPDATE load_state SET status='failed', updated_at=? WHERE position=?",
                            (_now(), done.position),
                        )
                        db.commit()
                        raise Halt(
                            f"on-chain REVERT at nonce {done.nonce} tx {done.tx_hash}; reconcile before resuming"
                        )
                    else:
                        gas_used = int(receipt["gasUsed"], 16)
                        block = int(receipt["blockNumber"], 16)
                drained.append((gas_used, block, _now(), done.position))
                counters["confirmed"] += 1
            if drained:
                db.executemany(
                    "UPDATE load_state SET status='confirmed', gas_used=?, block=?, updated_at=?"
                    " WHERE position=?",
                    drained,
                )
                db.commit()
            elif inflight:
                head = inflight[0]
                if time.monotonic() - head.sent_at > STUCK_SECONDS:
                    # Same nonce, +25% gas: replacement, never a gap.
                    new_price = head.gas_price + head.gas_price // 4
                    log(f"stuck nonce {head.nonce}: re-sending at {new_price / 1e9:.0f} gwei")
                    row = db.execute(
                        "SELECT position, registry, checksum, uri, metadata FROM load_state WHERE position=?",
                        (head.position,),
                    ).fetchone()
                    saved_price = gas_price
                    gas_price = new_price
                    try:
                        replacement = submit(row, head.nonce)
                    finally:
                        gas_price = saved_price
                    inflight[0] = replacement
                    counters["resent"] += 1
                else:
                    time.sleep(0.5)

            now = time.monotonic()
            if now - last_log >= 60:
                rate = counters["confirmed"] / max(now - started, 1e-9)
                left = db.execute(
                    "SELECT COUNT(*) FROM load_state WHERE status='pending'"
                ).fetchone()[0]
                eta_h = (left / rate / 3600) if rate > 0 else float("inf")
                log(
                    f"confirmed {counters['confirmed']:,} ({rate:.2f} tx/s overall), "
                    f"in-flight {len(inflight)}, pending {left:,}, eta {eta_h:.1f} h"
                )
                last_log = now
    except Halt as err:
        log(f"HALT: {err}")
    except RpcError as err:
        log(f"HALT on RPC error (state ambiguous, reconcile before resuming): {err}")
    finally:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    rate = counters["confirmed"] / max(time.monotonic() - started, 1e-9)
    log(
        f"run ends: {counters['confirmed']:,} confirmed this run at {rate:.2f} tx/s, "
        f"{counters['resent']} re-sends; in-flight left 'submitted': {len(inflight)}"
    )
    return counters


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


def print_status(
    db: sqlite3.Connection,
    rpc: EvmRpc | None,
    address: str | None,
    token: str = "wmantraUSD",
) -> None:
    print("load_state:")
    for status, count in db.execute(
        "SELECT status, COUNT(*) FROM load_state GROUP BY status ORDER BY status"
    ):
        print(f"  {status}: {count:,}")
    for registry, count in db.execute(
        "SELECT registry, COUNT(*) FROM load_state GROUP BY registry ORDER BY registry"
    ):
        print(f"  {registry}: {count:,} rows")
    excluded = db.execute("SELECT COUNT(*) FROM excluded").fetchone()[0]
    print(f"  excluded at prepare: {excluded:,}")
    gas = db.execute(
        "SELECT COUNT(*), SUM(gas_used), AVG(gas_used) FROM load_state WHERE gas_used IS NOT NULL"
    ).fetchone()
    if gas[0]:
        print(f"  measured: {gas[0]:,} records, avg {gas[2]:,.0f} gas")
    if rpc is not None and address is not None:
        balance = rpc.get_balance(address)
        print(f"  balance: {balance / 1e18:.3f} {token} ({address})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Checkpointed bulk loader.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prep = sub.add_parser("prepare", help="render corpus rows into load_state (local only)")
    p_prep.add_argument("--corpus", type=Path, default=Path("data/corpus.sqlite"))
    p_prep.add_argument("--state", type=Path, default=Path("data/load_state.sqlite"))
    p_prep.add_argument("--court", required=True, help="courts-db id, e.g. ca11")
    p_prep.add_argument(
        "--reporters",
        required=True,
        help="comma-separated exact reporter whitelist (census-informed), e.g. 'F.2d,F.3d,F.4th,F. App'\\''x'",
    )
    p_prep.add_argument("--tranche", required=True, help="label, e.g. tranche1-ca11")
    p_prep.add_argument("--precedential-only", action="store_true")

    p_run = sub.add_parser("run", help="submit pending rows (single key, serialized nonces)")
    p_run.add_argument("--state", type=Path, default=Path("data/load_state.sqlite"))
    p_run.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    p_run.add_argument("--max-records", type=int, default=None, help="stop after N submissions (probe runs)")
    p_run.add_argument("--network", choices=["mainnet", "testnet"], default=None)

    p_stat = sub.add_parser("status", help="checkpoint counters and balance")
    p_stat.add_argument("--state", type=Path, default=Path("data/load_state.sqlite"))
    p_stat.add_argument("--offline", action="store_true", help="skip RPC reads")
    p_stat.add_argument("--network", choices=["mainnet", "testnet"], default=None)

    args = parser.parse_args(argv)
    load_dotenv()

    if args.command == "prepare":
        reporters = tuple(r.strip() for r in args.reporters.split(",") if r.strip())
        stats = prepare(
            args.corpus, args.state, args.court, reporters, args.tranche, args.precedential_only
        )
        print(f"prepare {args.tranche}: " + ", ".join(f"{k}={v:,}" for k, v in stats.items()))
        return 0

    from nvnm_cite.chain.registrymap import load_manifest

    if args.command == "run":
        # Writes default to testnet; mainnet requires the signing_context
        # opt-in pair (never set in .env or sessions).
        network = get_network(args.network, default="testnet")
        db = open_state(args.state)
        rpc = EvmRpc(network.rpc_url())
        key, chain_id = signing_context(network)
        registry_ids = load_manifest(network.key).all_registries()
        run_load(db, rpc, key, chain_id, registry_ids, depth=args.depth, max_records=args.max_records)
        print_status(db, rpc, address_from_private_key(key), token=network.gas_token)
        db.close()
        return 0

    network = get_network(args.network, default="testnet")
    db = open_state(args.state)
    if args.offline:
        print_status(db, None, None)
    else:
        rpc = EvmRpc(network.rpc_url())
        key, _ = signing_context(network)
        print_status(db, rpc, address_from_private_key(key), token=network.gas_token)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
