"""Mainnet read-only smoke: the production chain answers as the manifest pins.

STRICTLY READ-ONLY (eth_call / eth_chainId only — no key is loaded, no
transaction can be constructed here; sessions must never write mainnet).
Opt-in via NVNM_MAINNET_SMOKE=1 so the default suite stays offline-green:

    NVNM_MAINNET_SMOKE=1 uv run pytest tests/test_mainnet_smoke.py
"""

from __future__ import annotations

import os

import pytest

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.registrymap import load_manifest
from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.config import MAINNET

pytestmark = pytest.mark.skipif(
    os.environ.get("NVNM_MAINNET_SMOKE") != "1",
    reason="mainnet smoke is opt-in: set NVNM_MAINNET_SMOKE=1",
)

MANIFEST = load_manifest("mainnet")


@pytest.fixture(scope="module")
def rpc() -> EvmRpc:
    client = EvmRpc(MAINNET.rpc_url(), timeout=20)
    try:
        chain_id = client.chain_id()
    except Exception as exc:
        pytest.skip(f"mainnet RPC unreachable: {exc}")
    assert chain_id == 1611, f"RPC serves chain {chain_id}, not mainnet"
    return client


def test_scotus_registry_pinned_correctly(rpc: EvmRpc):
    raw = rpc.eth_call(
        pc.PRECOMPILE_ADDRESS, pc.build_registries_query(registry_id=82)
    )
    rows, _ = pc.decode_registries_result(raw)
    assert rows and rows[0].id == 82
    assert rows[0].name == "us-scotus"
    assert rows[0].creator == MANIFEST.creator


def test_roe_record_reads_back(rpc: EvmRpc):
    raw = rpc.eth_call(
        pc.PRECOMPILE_ADDRESS,
        pc.build_records_query(registry_id=82, checksum="410 U.S. 113"),
    )
    records, _ = pc.decode_records_result(raw)
    assert records
    roe = records[0]
    assert roe.record_id == 138702
    assert roe.checksum_algo == "cite-canonical-v1"
    assert roe.status == "Active" and roe.is_latest
    assert roe.registry_id == 82
    assert "Roe v. Wade" in roe.metadata


def test_keyed_miss_still_errors_with_marker(rpc: EvmRpc):
    with pytest.raises(RpcError) as exc:
        rpc.eth_call(
            pc.PRECOMPILE_ADDRESS,
            pc.build_records_query(registry_id=82, checksum="999 U.S. 999"),
        )
    assert pc.is_keyed_miss(exc.value)


def test_manifest_sentinels_match_chain(rpc: EvmRpc):
    # Spot-drift check on the id range endpoints + a mid sentinel.
    for rid, want_name in ((69, "us-ca1"), (71, "us-ca11"), (2182, "us-wyo")):
        raw = rpc.eth_call(
            pc.PRECOMPILE_ADDRESS, pc.build_registries_query(registry_id=rid)
        )
        rows, _ = pc.decode_registries_result(raw)
        assert rows and rows[0].name == want_name == MANIFEST.registry_name(rid)
        assert rows[0].creator == MANIFEST.creator


def test_paging_contract_holds_under_v120(rpc: EvmRpc):
    # 200-row server cap + short-page termination, on a small registry:
    # request 300, get at most 200; the manifest count is not trusted.
    raw = rpc.eth_call(
        pc.PRECOMPILE_ADDRESS,
        pc.build_records_query(registry_id=69, limit=300),
    )
    rows, _ = pc.decode_records_result(raw)
    assert 0 < len(rows) <= 200
