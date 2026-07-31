"""Network profiles and the mainnet signing guard."""

import pytest

from nvnm_cite import config


def test_profiles_pin_chain_constants():
    assert config.MAINNET.chain_id == 1611
    assert config.MAINNET.cosmos_chain_id == "nvnm-1"
    assert config.MAINNET.gas_token == "wmmUSD"
    assert config.TESTNET.chain_id == 787111
    assert config.TESTNET.cosmos_chain_id == "nvnm-testnet-1"
    assert config.TESTNET.gas_token == "wmantraUSD"


def test_get_network_precedence(monkeypatch):
    monkeypatch.delenv("NVNM_NETWORK", raising=False)
    assert config.get_network() is config.MAINNET
    assert config.get_network(default="testnet") is config.TESTNET
    monkeypatch.setenv("NVNM_NETWORK", "testnet")
    assert config.get_network() is config.TESTNET
    assert config.get_network("mainnet") is config.MAINNET  # explicit arg wins
    with pytest.raises(ValueError):
        config.get_network("devnet")


def test_rpc_env_override(monkeypatch):
    monkeypatch.setenv("NVNM_MAINNET_RPC", "http://localhost:9999")
    assert config.MAINNET.rpc_url() == "http://localhost:9999"
    monkeypatch.delenv("NVNM_MAINNET_RPC", raising=False)
    assert config.MAINNET.rpc_url() == "https://evm.nvnmchain.io"


def test_mainnet_signing_refused_without_optin(monkeypatch):
    monkeypatch.delenv("NVNM_MAINNET_WRITE_OK", raising=False)
    monkeypatch.delenv("NVNM_MAINNET_KEY", raising=False)
    # Even with the testnet key present, mainnet signing must refuse.
    monkeypatch.setenv("NVNM_TESTNET_KEY", "0x" + "11" * 32)
    with pytest.raises(RuntimeError, match="mainnet signing is disabled"):
        config.signing_context(config.MAINNET)


def test_mainnet_signing_requires_distinct_key(monkeypatch):
    monkeypatch.setenv("NVNM_MAINNET_WRITE_OK", "1")
    monkeypatch.delenv("NVNM_MAINNET_KEY", raising=False)
    monkeypatch.setenv("NVNM_TESTNET_KEY", "0x" + "11" * 32)
    with pytest.raises(RuntimeError, match="NVNM_MAINNET_KEY is not set"):
        config.signing_context(config.MAINNET)


def test_signing_context_testnet(monkeypatch):
    monkeypatch.setenv("NVNM_TESTNET_KEY", "0x" + "11" * 32)
    key, chain_id = config.signing_context(config.TESTNET)
    assert key == int("11" * 32, 16)
    assert chain_id == 787111


def test_signing_context_mainnet_optin(monkeypatch):
    monkeypatch.setenv("NVNM_MAINNET_WRITE_OK", "1")
    monkeypatch.setenv("NVNM_MAINNET_KEY", "0x" + "22" * 32)
    key, chain_id = config.signing_context(config.MAINNET)
    assert key == int("22" * 32, 16)
    assert chain_id == 1611
