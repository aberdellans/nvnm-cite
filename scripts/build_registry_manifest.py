"""Build the pinned registry-name -> registryId manifest for a network.

READ-ONLY: enumerates registries() (offset-paged), filters to the official
creator + the names in the bulk-load export, hard-verifies the result, and
writes src/nvnm_cite/chain/registry_manifest_<network>.json. Run after any
registry-set change on chain, review the diff, commit.

    uv run python scripts/build_registry_manifest.py --network mainnet

Verification is deliberately loud: any duplicate name within the creator
set, any export name missing (mainnet), or a failed record spot-check
aborts without writing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nvnm_cite import config
from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.registrymap import MANIFEST_SCHEMA
from nvnm_cite.chain.rpc import EvmRpc, RpcError

# The official attestor for the court registries on BOTH networks (verified
# live 2026-07-31; bech32 of the load key's address).
OFFICIAL_CREATOR = "nvnm14a3em3mr9mvta9ccgk80wn0dxgzt5lkt2r8trx"

REPO = Path(__file__).resolve().parent.parent
EXPORT_REGISTRIES = REPO / "data" / "mainnet-full-export" / "registries.json"

# Per-network hard expectations (live-verified 2026-07-31).
EXPECT = {
    "mainnet": {
        "count": 2114,
        "id_range": (69, 2182),
        "require_full_export": True,
        "spot_checks": [("us-scotus", "410 U.S. 113", 138702)],
    },
    "testnet": {
        "count": 2,
        "id_range": (737, 738),
        "require_full_export": False,
        "spot_checks": [("us-scotus", "410 U.S. 113", None)],
    },
}


def enumerate_registries(rpc: EvmRpc) -> list[pc.Registry]:
    out: list[pc.Registry] = []
    offset = 0
    while True:
        raw = rpc.eth_call(
            pc.PRECOMPILE_ADDRESS, pc.build_registries_query(offset=offset, limit=200)
        )
        rows, _ = pc.decode_registries_result(raw)
        if not rows:
            break
        out.extend(rows)
        offset += len(rows)
        if len(rows) < 200:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--network", choices=["mainnet", "testnet"], required=True)
    ap.add_argument("--rpc", help="override the network's default RPC URL")
    args = ap.parse_args()

    network = config.get_network(args.network)
    expect = EXPECT[network.key]
    rpc = EvmRpc(args.rpc or network.rpc_url(), timeout=30)

    chain_id = rpc.chain_id()
    if chain_id != network.chain_id:
        print(f"FATAL: RPC chain id {chain_id} != {network.chain_id}", file=sys.stderr)
        return 1
    block = rpc.block_number()

    export_names = {
        entry["name"] for entry in json.loads(EXPORT_REGISTRIES.read_text())
    }
    print(f"{network.key}: export lists {len(export_names)} court registries")

    all_regs = enumerate_registries(rpc)
    print(f"{network.key}: enumerated {len(all_regs)} registries at block {block}")

    matched = [
        r
        for r in all_regs
        if r.creator == OFFICIAL_CREATOR and r.name in export_names
    ]

    # --- hard verification, abort on any violation ---
    errors: list[str] = []
    names_seen: dict[str, list[int]] = {}
    for r in matched:
        names_seen.setdefault(r.name, []).append(r.id)
    dupes = {n: ids for n, ids in names_seen.items() if len(ids) > 1}
    if dupes:
        errors.append(f"duplicate names within the creator set: {dupes}")

    if len(matched) != expect["count"]:
        errors.append(f"expected {expect['count']} registries, matched {len(matched)}")
    lo, hi = expect["id_range"]
    ids = sorted(r.id for r in matched)
    if ids and (ids[0] < lo or ids[-1] > hi):
        errors.append(f"ids outside expected range {lo}-{hi}: {ids[0]}..{ids[-1]}")
    if expect["require_full_export"]:
        missing = export_names - set(names_seen)
        if missing:
            errors.append(f"{len(missing)} export names missing on chain: {sorted(missing)[:5]}...")
        if len(ids) == expect["count"] and ids != list(range(ids[0], ids[0] + len(ids))):
            errors.append("ids are not contiguous")

    by_name = {r.name: r.id for r in matched}
    for name, checksum, want_record_id in expect["spot_checks"]:
        rid = by_name.get(name)
        if rid is None:
            errors.append(f"spot check: {name} not in matched set")
            continue
        try:
            raw = rpc.eth_call(
                pc.PRECOMPILE_ADDRESS,
                pc.build_records_query(registry_id=rid, checksum=checksum),
            )
            recs, _ = pc.decode_records_result(raw)
        except RpcError as err:
            errors.append(f"spot check {name}/{checksum}: {err}")
            continue
        if not recs:
            errors.append(f"spot check {name}/{checksum}: empty result")
        elif want_record_id is not None and recs[0].record_id != want_record_id:
            errors.append(
                f"spot check {name}/{checksum}: recordId {recs[0].record_id} != {want_record_id}"
            )

    if errors:
        for e in errors:
            print(f"FATAL: {e}", file=sys.stderr)
        return 1

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "network": network.key,
        "chain_id": network.chain_id,
        "creator": OFFICIAL_CREATOR,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at_block": block,
        "registries": {
            name: {"id": rid} for name, rid in sorted(by_name.items())
        },
    }
    out_path = REPO / "src" / "nvnm_cite" / "chain" / f"registry_manifest_{network.key}.json"
    out_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out_path.relative_to(REPO)}: {len(by_name)} registries, block {block}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
