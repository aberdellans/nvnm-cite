"""Phase 0 task 0.7: empirical experiment matrix against NVNM testnet.

Groups (run separately so a failure doesn't lose earlier results):
  quick       (a) duplicates, (b) metadata size/gas curve, (c) registry
              name uniqueness, (d) write permissions + grantRole
  throughput  (e) sustained tx/s at pipeline depths 1 / 5 / 20
  post        (g) pagination, (h) archive depth, (i) budget report

Every conclusion-bearing line is prefixed FINDING: for collection into
DECISIONS.md. Spends only what the user approved (~1 wmantraUSD total).

Run:  uv run python scripts/phase0_experiments.py quick|throughput|post
"""

from __future__ import annotations

import json
import sys
import time

from nvnm_cite.chain.keccak import keccak_256
from nvnm_cite.chain.precompile import (
    PRECOMPILE_ADDRESS,
    build_add_record,
    build_add_registry,
    build_grant_role,
    build_records_query,
    build_registries_query,
    decode_records_result,
    decode_registries_result,
)
from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.chain.secp256k1 import SECP256K1, address_from_private_key
from nvnm_cite.chain.signer import LegacyTransaction, sign_transaction
from nvnm_cite.config import TESTNET_CHAIN_ID, load_dotenv, testnet_private_key, testnet_rpc

REGISTRY = "dev-probe"
PROBE_URI = "nvnm-cite://probe"
MIN_GAS_PRICE = 40_000_000_000
ROUNDTRIP_CHECKSUM = "TEST 1573499 NVNM 1"  # written by task 0.6


class Sender:
    """Single-owner nonce manager; everything stateful goes through here."""

    def __init__(self, rpc: EvmRpc, key: int):
        self.rpc = rpc
        self.key = key
        self.address = address_from_private_key(key)
        self.nonce = rpc.get_transaction_count(self.address)
        self.gas_price = max(rpc.gas_price(), MIN_GAS_PRICE)
        self.spent_gas = 0

    def estimate(self, calldata: bytes, from_addr: str | None = None) -> int | str:
        """Gas estimate, or the error message string if estimation reverts."""
        try:
            return self.rpc.estimate_gas(from_addr or self.address, PRECOMPILE_ADDRESS, calldata)
        except RpcError as err:
            return err.message

    def send_async(self, calldata: bytes, gas_limit: int) -> str:
        tx = LegacyTransaction(self.nonce, self.gas_price, gas_limit,
                               PRECOMPILE_ADDRESS, 0, calldata)
        signed = sign_transaction(tx, self.key, TESTNET_CHAIN_ID)
        tx_hash = self.rpc.send_raw_transaction(signed.raw)
        self.nonce += 1
        return tx_hash

    def send_wait(self, calldata: bytes, label: str) -> dict | str:
        """Estimate, send, wait. Returns receipt dict, or error string on revert."""
        estimate = self.estimate(calldata)
        if isinstance(estimate, str):
            return f"estimateGas reverted: {estimate}"
        tx_hash = self.send_async(calldata, estimate + estimate // 5)
        receipt = self.rpc.wait_for_receipt(tx_hash)
        gas_used = int(receipt["gasUsed"], 16)
        self.spent_gas += gas_used
        status = "ok" if int(receipt["status"], 16) == 1 else "REVERTED"
        print(f"    {label}: {status}, gas {gas_used:,}, tx {tx_hash[:18]}...")
        return receipt


def read_records(rpc: EvmRpc, **kwargs):
    return decode_records_result(
        rpc.eth_call(PRECOMPILE_ADDRESS, build_records_query(**kwargs))
    )


def exp_a_duplicates(s: Sender) -> None:
    print("\n[a] duplicate (registry, checksum) behavior")
    dup = build_add_record(REGISTRY, "https://github.com/aberdellans/nvnm-cite",
                           ROUNDTRIP_CHECKSUM, "cite-canonical-v1",
                           '{"name":"Round-trip probe (not a real case)","task":"0.6"}')
    estimate = s.estimate(dup)
    if isinstance(estimate, str):
        print(f"FINDING (a): duplicates REJECT at estimateGas: {estimate!r}")
        print("FINDING (a): loader idempotency is free (estimate-probe skips already-loaded)")
        return
    print(f"    identical duplicate estimates {estimate:,} gas; sending to observe semantics")
    result = s.send_wait(dup, "identical duplicate")
    if isinstance(result, str):
        print(f"FINDING (a): duplicate send failed late: {result}")
        return
    rows, _ = read_records(s.rpc, registry=REGISTRY, checksum=ROUNDTRIP_CHECKSUM, limit=10)
    print(f"FINDING (a): duplicates create VERSIONS: {len(rows)} row(s) for the checksum; "
          + "; ".join(f"recordId={r.record_id} index={r.index} isLatest={r.is_latest}" for r in rows))
    diff = build_add_record(REGISTRY, PROBE_URI, ROUNDTRIP_CHECKSUM, "cite-canonical-v1",
                            '{"note":"different metadata, same checksum"}')
    result = s.send_wait(diff, "same checksum, new metadata")
    if not isinstance(result, str):
        rows, _ = read_records(s.rpc, registry=REGISTRY, checksum=ROUNDTRIP_CHECKSUM, limit=10)
        latest = [r for r in rows if r.is_latest]
        print(f"FINDING (a): after metadata change: {len(rows)} row(s), "
              f"latest index={latest[0].index if latest else '?'} "
              f"metadata={latest[0].metadata[:60] if latest else '?'!r}")


def exp_b_metadata_sizes(s: Sender, head: int) -> None:
    print("\n[b] metadata size ceiling + gas curve")
    sizes = [256, 1024, 4096, 8192, 16384, 32768, 65536, 131072]
    estimates: dict[int, int] = {}
    for size in sizes:
        calldata = build_add_record(REGISTRY, PROBE_URI, f"TEST META {size} {head}",
                                    "cite-canonical-v1", "m" * size)
        result = s.estimate(calldata)
        if isinstance(result, str):
            print(f"FINDING (b): metadata {size:>7,} B: estimation FAILS: {result[:90]!r}")
        else:
            estimates[size] = result
            print(f"    metadata {size:>7,} B: estimates {result:,} gas "
                  f"(~{result * s.gas_price / 10**18:.4f} wmantraUSD)")
    if len(estimates) >= 2:
        lo, hi = min(estimates), max(estimates)
        per_byte = (estimates[hi] - estimates[lo]) / (hi - lo)
        print(f"FINDING (b): estimable up to {hi:,} B; marginal cost ~{per_byte:.1f} gas/byte "
              f"(fixed ~{estimates[lo] - int(per_byte * lo):,} gas)")
    if not estimates:
        print("FINDING (b): no size estimable; ceiling probe inconclusive")
        return
    biggest = max(estimates)
    for size in sorted({1024, 16384, biggest} & set(estimates)):
        s.send_wait(
            build_add_record(REGISTRY, PROBE_URI, f"TEST META CONFIRM {size} {head}",
                             "cite-canonical-v1", "m" * size),
            f"confirm {size:,} B metadata")
    try:
        rows, _ = read_records(s.rpc, registry=REGISTRY,
                               checksum=f"TEST META CONFIRM {biggest} {head}")
        if rows:
            print(f"FINDING (b): largest confirmed metadata ({biggest:,} B) read back intact: "
                  f"{len(rows[0].metadata):,} chars")
    except RpcError as err:
        print(f"FINDING (b): read-back of largest confirm failed: {err.message[:80]!r}")

    # which record fields does the module actually require?
    cases = {"empty checksumAlgo": (PROBE_URI, "TEST VALID ALGO", "", "{}"),
             "empty metadata": (PROBE_URI, "TEST VALID META", "cite-canonical-v1", ""),
             "empty uri": ("", "TEST VALID URI", "cite-canonical-v1", '{"p":1}')}
    for label, (uri, checksum, algo, metadata) in cases.items():
        result = s.estimate(build_add_record(REGISTRY, uri, checksum, algo, metadata))
        verdict = f"REQUIRED ({result[:60]!r})" if isinstance(result, str) else "optional"
        print(f"FINDING (b-validation): {label}: {verdict}")


def exp_c_registry_uniqueness(s: Sender) -> None:
    print("\n[c] addRegistry name uniqueness")
    calldata = build_add_registry(REGISTRY, "duplicate-name probe", "")
    result = s.estimate(calldata)
    if isinstance(result, str):
        print(f"FINDING (c): duplicate registry name REJECTED at estimation: {result[:90]!r}")
        return
    print(f"    duplicate name estimates {result:,} gas; sending to observe")
    s.send_wait(calldata, "duplicate addRegistry(dev-probe)")
    regs, _ = decode_registries_result(
        s.rpc.eth_call(PRECOMPILE_ADDRESS, build_registries_query(name=REGISTRY)))
    print(f"FINDING (c): duplicate names ALLOWED; name query now returns {len(regs)} "
          f"registr{'y' if len(regs) == 1 else 'ies'}: ids {[r.id for r in regs]} "
          "(name-keyed lookups must disambiguate!)")


def exp_d_permissions(s: Sender) -> None:
    print("\n[d] write permissions + grantRole (third-party-attestor proof)")
    key2 = int.from_bytes(keccak_256(b"nvnm-cite phase0 throwaway key2"), "big") % SECP256K1.n
    addr2 = address_from_private_key(key2)
    print(f"    second (unfunded) address: {addr2}")
    probe = build_add_record(REGISTRY, PROBE_URI, "TEST PERMS NVNM", "cite-canonical-v1", '{"p":1}')
    before = s.estimate(probe, from_addr=addr2)
    print("FINDING (d): foreign addRecord before grant: "
          + (f"DENIED: {before[:90]!r}" if isinstance(before, str) else f"ALLOWED?! ({before:,} gas)"))
    regs, _ = decode_registries_result(
        s.rpc.eth_call(PRECOMPILE_ADDRESS, build_registries_query(name=REGISTRY)))
    registry_id = regs[0].id
    s.send_wait(build_grant_role(registry_id, addr2, "editor"), f"grantRole(editor, id={registry_id})")
    after = s.estimate(probe, from_addr=addr2)
    print("FINDING (d): foreign addRecord after editor grant: "
          + (f"still blocked: {after[:90]!r}" if isinstance(after, str)
             else f"ALLOWED ({after:,} gas) — third-party attestors work via grantRole"))


def exp_e_throughput(s: Sender, head: int) -> None:
    print("\n[e] throughput at pipeline depths 1 / 5 / 20")
    base = build_add_record(REGISTRY, PROBE_URI, f"TEST TPUT SIZER {head}", "cite-canonical-v1", '{"p":1}')
    estimate = s.estimate(base)
    if isinstance(estimate, str):
        raise SystemExit(f"sizer estimation failed: {estimate}")
    gas_limit = estimate + estimate // 5
    counter = 0
    for depth, total in ((1, 20), (5, 60), (20, 120)):
        hashes: list[str] = []
        start = time.monotonic()
        pending: list[str] = []
        for i in range(total):
            calldata = build_add_record(REGISTRY, PROBE_URI, f"TEST TPUT {head} {counter}",
                                        "cite-canonical-v1", '{"p":1}')
            counter += 1
            pending.append(s.send_async(calldata, gas_limit))
            if len(pending) >= depth:
                for tx_hash in pending:
                    receipt = s.rpc.wait_for_receipt(tx_hash)
                    s.spent_gas += int(receipt["gasUsed"], 16)
                    if int(receipt["status"], 16) != 1:
                        print(f"    UNEXPECTED revert at depth {depth}: {tx_hash}")
                hashes.extend(pending)
                pending.clear()
        for tx_hash in pending:
            receipt = s.rpc.wait_for_receipt(tx_hash)
            s.spent_gas += int(receipt["gasUsed"], 16)
            hashes.extend([tx_hash])
        elapsed = time.monotonic() - start
        print(f"FINDING (e): depth {depth:>2}: {total} txs confirmed in {elapsed:.1f}s "
              f"= {total / elapsed:.2f} tx/s sustained")
    print(f"FINDING (e): no mempool rejections of sequential-nonce bursts up to depth 20")


def exp_g_pagination(s: Sender) -> None:
    print("\n[g] pagination stability + page limits")
    seen: dict[str, int] = {}
    pages = 0
    key = b""
    total_reported = None
    while True:
        rows, page = read_records(s.rpc, registry=REGISTRY, page_key=key,
                                  limit=50, count_total=(pages == 0))
        if pages == 0:
            total_reported = page.total
        pages += 1
        for r in rows:
            seen[f"{r.checksum}#{r.index}"] = seen.get(f"{r.checksum}#{r.index}", 0) + 1
        if pages == 1:
            # stability probe: write 2 records mid-pagination
            for j in range(2):
                s.send_wait(build_add_record(REGISTRY, PROBE_URI, f"TEST PAGESTAB {j} {pages}",
                                             "cite-canonical-v1", '{"p":1}'), f"mid-pagination write {j}")
        if not page.next_key or not rows:
            break
        key = page.next_key
        if pages > 50:
            print("    stopping after 50 pages (safety)")
            break
    dupes = {k: c for k, c in seen.items() if c > 1}
    print(f"FINDING (g): paged {pages} pages, {len(seen)} distinct rows, "
          f"{len(dupes)} duplicates across pages, countTotal first-page={total_reported}")
    rows, page = read_records(s.rpc, registry=REGISTRY, limit=10_000, count_total=True)
    print(f"FINDING (g): single limit=10000 query returned {len(rows)} rows "
          f"(total={page.total}); large pages "
          + ("work at this scale" if len(rows) >= len(seen) - 5 else "are CAPPED below the row count"))


def exp_h_archive(s: Sender, head: int) -> None:
    print("\n[h] historical state depth (archive node?)")
    for depth in (1_000, 100_000, 1_000_000, head - 1):
        block = hex(head - depth)
        try:
            bal = s.rpc.call("eth_getBalance", [s.address, block])
            print(f"FINDING (h): state at head-{depth:,}: served (balance {int(bal, 16) / 10**18:.4f})")
        except RpcError as err:
            print(f"FINDING (h): state at head-{depth:,}: NOT served: {err.message[:80]!r}")
    try:
        s.rpc.eth_call(PRECOMPILE_ADDRESS, build_registries_query(name=REGISTRY),
                       block=hex(head - 100_000))
        print("FINDING (h): historical precompile eth_call: served (registry visible pre-creation?!)")
    except RpcError as err:
        msg = err.message[:80]
        kind = "historical precompile call works (name not yet created at that height)" \
            if "not found" in err.message else f"historical precompile call FAILS: {msg!r}"
        print(f"FINDING (h): {kind}")


def main() -> int:
    group = sys.argv[1] if len(sys.argv) > 1 else "quick"
    load_dotenv()
    rpc = EvmRpc(testnet_rpc())
    if rpc.chain_id() != TESTNET_CHAIN_ID:
        raise SystemExit("wrong chain; refusing")
    s = Sender(rpc, testnet_private_key())
    head = rpc.block_number()
    start_balance = rpc.get_balance(s.address)
    print(f"wallet {s.address}, balance {start_balance / 10**18:.4f} wmantraUSD, "
          f"head {head:,}, gas price {s.gas_price / 10**9:.0f} gwei")

    if group == "quick":
        exp_a_duplicates(s)
        exp_b_metadata_sizes(s, head)
        exp_c_registry_uniqueness(s)
        exp_d_permissions(s)
    elif group == "throughput":
        exp_e_throughput(s, head)
    elif group == "post":
        exp_g_pagination(s)
        exp_h_archive(s, head)
    else:
        raise SystemExit(f"unknown group {group!r}")

    end_balance = rpc.get_balance(s.address)
    print(f"\nFINDING (i): this run spent {(start_balance - end_balance) / 10**18:.4f} wmantraUSD "
          f"({s.spent_gas:,} gas); balance now {end_balance / 10**18:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
