# NOTE: pre-v1.2.0 ABI (name-keyed records/registries/addRecord); historical
# record of the pilot probes/load — non-functional against current chains.
"""Phase 2 task 2.6 step 1: create the court registries on testnet.

Creation strings are FIXED in docs/record-schema.md section 2 (locked
2026-06-11); this script renders them mechanically from courts-db names and
refuses to improvise. Idempotent: a name-keyed registries() read first, and
addRegistry estimation rejects duplicates anyway (DECISIONS (c)).

Run:  uv run python scripts/phase2_create_registries.py          (pre-flight)
      uv run python scripts/phase2_create_registries.py --send   (2 txs)
"""

from __future__ import annotations

import sys

from nvnm_cite.loader.records import creation_strings

from nvnm_cite.chain.precompile import (
    PRECOMPILE_ADDRESS,
    build_add_registry,
    build_registries_query,
    decode_registries_result,
)
from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.chain.secp256k1 import address_from_private_key
from nvnm_cite.chain.signer import LegacyTransaction, sign_transaction
from nvnm_cite.config import (
    TESTNET_CHAIN_ID,
    TESTNET_EXPLORER,
    load_dotenv,
    testnet_private_key,
    testnet_rpc,
)

COURT_IDS = ("scotus", "ca11")
MIN_GAS_PRICE = 40_000_000_000


def find_registry(rpc: EvmRpc, name: str):
    try:
        registries, _ = decode_registries_result(
            rpc.eth_call(PRECOMPILE_ADDRESS, build_registries_query(name=name))
        )
    except RpcError as err:
        if "not found" in err.message:
            return None
        raise
    return next((r for r in registries if r.name == name), None)


def send_tx(rpc: EvmRpc, key: int, address: str, calldata: bytes, label: str) -> dict:
    gas_estimate = rpc.estimate_gas(address, PRECOMPILE_ADDRESS, calldata)
    gas_price = max(rpc.gas_price(), MIN_GAS_PRICE)
    tx = LegacyTransaction(
        nonce=rpc.get_transaction_count(address),
        gas_price=gas_price,
        gas_limit=gas_estimate + gas_estimate // 5,
        to=PRECOMPILE_ADDRESS,
        value=0,
        data=calldata,
    )
    signed = sign_transaction(tx, key, TESTNET_CHAIN_ID)
    tx_hash = rpc.send_raw_transaction(signed.raw)
    assert tx_hash == signed.hash_hex, "node-computed hash differs from ours"
    receipt = rpc.wait_for_receipt(tx_hash)
    status = int(receipt["status"], 16)
    print(
        f"  {label}: {'SUCCESS' if status == 1 else 'REVERTED'} in block "
        f"{int(receipt['blockNumber'], 16):,}, gas {int(receipt['gasUsed'], 16):,}"
    )
    print(f"    {TESTNET_EXPLORER}/tx/{tx_hash}")
    if status != 1:
        raise SystemExit(f"{label} reverted; stopping")
    return receipt


def main(send: bool) -> int:
    load_dotenv()
    rpc = EvmRpc(testnet_rpc())
    chain_id = rpc.chain_id()
    if chain_id != TESTNET_CHAIN_ID:
        print(f"chain id {chain_id} != {TESTNET_CHAIN_ID}; refusing")
        return 1
    key = testnet_private_key()
    address = address_from_private_key(key)
    print(f"wallet {address}, balance {rpc.get_balance(address) / 1e18:.3f} wmantraUSD\n")

    for court_id in COURT_IDS:
        name, description, metadata = creation_strings(court_id)
        existing = find_registry(rpc, name)
        if existing is not None:
            print(f"{name}: already exists (id {existing.id}, creator {existing.creator})")
            continue
        print(f"{name}: not on chain")
        print(f"  description: {description}")
        print(f"  metadata:    {metadata}")
        if send:
            send_tx(rpc, key, address, build_add_registry(name, description, metadata), name)
            created = find_registry(rpc, name)
            print(f"  read-back: id {created.id}" if created else "  READ-BACK FAILED")
        else:
            print("  (pre-flight only; rerun with --send)")
    return 0


if __name__ == "__main__":
    sys.exit(main(send="--send" in sys.argv[1:]))
