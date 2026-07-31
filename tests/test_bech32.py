"""Bech32 conversion: pinned against the live-verified admin address pair."""

import pytest

from nvnm_cite.chain.bech32 import bech32_to_eth, eth_to_bech32

# Verified live 2026-07-31: the creator of all 2,114 mainnet court registries.
ADMIN_BECH32 = "nvnm14a3em3mr9mvta9ccgk80wn0dxgzt5lkt2r8trx"
ADMIN_ETH = "0xaf639dc7632ed8be9718458ef74ded3204ba7ecb"


def test_bech32_to_eth_known_pair():
    assert bech32_to_eth(ADMIN_BECH32) == ADMIN_ETH


def test_eth_to_bech32_known_pair():
    assert eth_to_bech32(ADMIN_ETH) == ADMIN_BECH32
    assert eth_to_bech32(ADMIN_ETH.upper().replace("0X", "0x")) == ADMIN_BECH32


def test_roundtrip():
    assert bech32_to_eth(eth_to_bech32(ADMIN_ETH)) == ADMIN_ETH


def test_bad_checksum_rejected():
    corrupted = ADMIN_BECH32[:-1] + ("q" if ADMIN_BECH32[-1] != "q" else "p")
    with pytest.raises(ValueError):
        bech32_to_eth(corrupted)


def test_wrong_hrp_rejected():
    with pytest.raises(ValueError):
        bech32_to_eth(ADMIN_BECH32, hrp="cosmos")


def test_bad_eth_length_rejected():
    with pytest.raises(ValueError):
        eth_to_bech32("0x1234")
