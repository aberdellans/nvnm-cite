# NOTE: pre-v1.2.0 ABI (name-keyed records/registries/addRecord); historical
# record of the pilot probes/load — non-functional against current chains.
"""Phase 0 task 0.6: first live round-trip on NVNM testnet.

Pre-flight (read-only, free): verify chain id 787111, derive the wallet
address, check the balance, look for the dev-probe registry, estimate gas.
With --send: create the dev-probe registry if missing, anchor one clearly
labeled test record, read both back via keyed eth_call queries, and print
explorer links.

Run:  uv run python scripts/phase0_roundtrip.py          (pre-flight only)
      uv run python scripts/phase0_roundtrip.py --send   (the real thing)
"""

from __future__ import annotations

import json
import sys

from nvnm_cite.chain.precompile import (
    PRECOMPILE_ADDRESS,
    build_add_record,
    build_add_registry,
    build_records_query,
    build_registries_query,
    decode_records_result,
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

REGISTRY_NAME = "dev-probe"
MIN_GAS_PRICE = 40_000_000_000  # chain floor: 40 gwei


def wmantra(wei: int) -> str:
    return f"{wei / 10**18:.6f} wmantraUSD"


def send_tx(rpc: EvmRpc, key: int, address: str, calldata: bytes, label: str) -> dict:
    gas_estimate = rpc.estimate_gas(address, PRECOMPILE_ADDRESS, calldata)
    gas_limit = gas_estimate + gas_estimate // 5  # +20% headroom
    gas_price = max(rpc.gas_price(), MIN_GAS_PRICE)
    print(f"  {label}: estimated {gas_estimate:,} gas, "
          f"max cost {wmantra(gas_limit * gas_price)}")
    tx = LegacyTransaction(
        nonce=rpc.get_transaction_count(address),
        gas_price=gas_price,
        gas_limit=gas_limit,
        to=PRECOMPILE_ADDRESS,
        value=0,
        data=calldata,
    )
    signed = sign_transaction(tx, key, TESTNET_CHAIN_ID)
    tx_hash = rpc.send_raw_transaction(signed.raw)
    assert tx_hash == signed.hash_hex, "node-computed hash differs from ours"
    receipt = rpc.wait_for_receipt(tx_hash)
    status = int(receipt["status"], 16)
    gas_used = int(receipt["gasUsed"], 16)
    block = int(receipt["blockNumber"], 16)
    print(f"  {label}: {'SUCCESS' if status == 1 else 'REVERTED'} "
          f"in block {block:,}, gas used {gas_used:,} ({wmantra(gas_used * gas_price)})")
    print(f"  {TESTNET_EXPLORER}/tx/{tx_hash}")
    if status != 1:
        raise SystemExit(f"{label} reverted; stopping")
    return receipt


def main(send: bool) -> int:
    load_dotenv()
    rpc = EvmRpc(testnet_rpc())

    print("== pre-flight (read-only) ==")
    chain_id = rpc.chain_id()
    print(f"  chain id: {chain_id} ({'OK' if chain_id == TESTNET_CHAIN_ID else 'WRONG CHAIN'})")
    if chain_id != TESTNET_CHAIN_ID:
        print(f"  expected {TESTNET_CHAIN_ID}; refusing to continue against an unknown chain")
        return 1

    key = testnet_private_key()
    address = address_from_private_key(key)
    balance = rpc.get_balance(address)
    head = rpc.block_number()
    print(f"  wallet: {address}")
    print(f"  balance: {wmantra(balance)}")
    print(f"  head block: {head:,}")
    if balance == 0:
        print("  balance is zero; fund the wallet before --send (see nvnm-tutorial README)")
        return 1

    try:
        registries, _ = decode_registries_result(
            rpc.eth_call(PRECOMPILE_ADDRESS, build_registries_query(name=REGISTRY_NAME))
        )
        registry = next((r for r in registries if r.name == REGISTRY_NAME), None)
    except RpcError as err:
        if "not found" not in err.message:
            raise
        # Empirical finding (2026-06-10): a name-keyed registries() query for a
        # missing name errors at the precompile instead of returning an empty page.
        registry = None
    print(f"  registry '{REGISTRY_NAME}': "
          + (f"exists (id {registry.id}, creator {registry.creator})" if registry else "not found"))

    if not send:
        print("\npre-flight only; rerun with --send to write")
        return 0

    print("\n== writes ==")
    if registry is None:
        send_tx(
            rpc, key, address,
            build_add_registry(
                REGISTRY_NAME,
                "Throwaway probe registry for nvnm-cite Phase 0 chain characterization.",
                json.dumps({"project": "nvnm-cite", "purpose": "phase-0 probe"},
                           separators=(",", ":"), sort_keys=True),
            ),
            "addRegistry(dev-probe)",
        )

    test_checksum = f"TEST {head} NVNM 1"  # unique per run; clearly not a real citation
    send_tx(
        rpc, key, address,
        build_add_record(
            registry=REGISTRY_NAME,
            uri="https://github.com/aberdellans/nvnm-cite",
            checksum=test_checksum,
            checksum_algo="cite-canonical-v1",
            metadata=json.dumps(
                {"name": "Round-trip probe (not a real case)", "task": "0.6"},
                separators=(",", ":"), sort_keys=True),
        ),
        f"addRecord({test_checksum!r})",
    )

    print("\n== read-back (keyed eth_call) ==")
    registries, _ = decode_registries_result(
        rpc.eth_call(PRECOMPILE_ADDRESS, build_registries_query(name=REGISTRY_NAME))
    )
    registry = next((r for r in registries if r.name == REGISTRY_NAME), None)
    if registry is None:
        raise SystemExit("registry not visible after write")
    print(f"  registry: id={registry.id} name={registry.name!r} creator={registry.creator}")

    records, page = decode_records_result(
        rpc.eth_call(
            PRECOMPILE_ADDRESS,
            build_records_query(registry=REGISTRY_NAME, checksum=test_checksum, count_total=True),
        )
    )
    if not records:
        raise SystemExit("record not found by keyed (registry, checksum) query")
    rec = records[0]
    print(f"  record: checksum={rec.checksum!r} recordId={rec.record_id} index={rec.index} "
          f"isLatest={rec.is_latest} timestamp={rec.timestamp!r}")
    print(f"  metadata: {rec.metadata}")
    print(f"  query total={page.total}")

    # The core verifier operation, probed while we're here: keyed lookup of a
    # checksum that does NOT exist in a registry that does. Empty page or error?
    try:
        missing, _ = decode_records_result(
            rpc.eth_call(
                PRECOMPILE_ADDRESS,
                build_records_query(registry=REGISTRY_NAME, checksum="TEST NONEXISTENT NVNM"),
            )
        )
        print("  absent-checksum probe: "
              + ("returns an EMPTY page (clean NOT_FOUND path)" if not missing
                 else f"UNEXPECTED: {len(missing)} rows"))
    except RpcError as err:
        print(f"  absent-checksum probe: precompile ERRORS: {err.message!r} "
              "(NOT_FOUND must be detected via this error)")

    print(f"\n  address activity: {TESTNET_EXPLORER}/address/{address}")
    print("round-trip COMPLETE: plaintext record written and read back by key")
    return 0


if __name__ == "__main__":
    sys.exit(main(send="--send" in sys.argv[1:]))
