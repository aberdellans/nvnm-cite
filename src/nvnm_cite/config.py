"""Project configuration from .env and the process environment.

Values are loaded, never logged. Code in this package must not print
private keys or token values; callers get parsed values only.

Network selection: every chain-facing entry point resolves a Network
profile via get_network(). Reads may target either network; SIGNING is
network-gated through signing_context() — mainnet signing requires an
explicit opt-in pair of environment variables that never appear in .env,
so the ambient testnet key can never sign chain 1611.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from nvnm_cite.chain.signer import parse_private_key


@dataclass(frozen=True)
class Network:
    key: str  # "mainnet" | "testnet"
    chain_id: int
    cosmos_chain_id: str
    rpc_default: str
    rpc_env: str  # env var that overrides rpc_default
    explorer: str
    gas_token: str
    label: str

    def rpc_url(self) -> str:
        return os.environ.get(self.rpc_env, self.rpc_default)


MAINNET = Network(
    key="mainnet",
    chain_id=1611,
    cosmos_chain_id="nvnm-1",
    rpc_default="https://evm.nvnmchain.io",
    rpc_env="NVNM_MAINNET_RPC",
    explorer="https://evm.explorer.nvnmchain.io",
    gas_token="wmmUSD",
    label="NVNM Chain mainnet (nvnm-1)",
)

TESTNET = Network(
    key="testnet",
    chain_id=787111,
    cosmos_chain_id="nvnm-testnet-1",
    rpc_default="https://evm.testnet.nvnmchain.io",
    rpc_env="NVNM_TESTNET_RPC",
    explorer="https://explorer.evm.testnet.nvnmchain.io",
    gas_token="wmantraUSD",
    label="NVNM Chain testnet (nvnm-testnet-1)",
)

NETWORKS: dict[str, Network] = {"mainnet": MAINNET, "testnet": TESTNET}

# Deprecated aliases; migration-era call sites only. New code takes a Network.
TESTNET_CHAIN_ID = TESTNET.chain_id
TESTNET_EXPLORER = TESTNET.explorer


def get_network(name: str | None = None, *, default: str = "mainnet") -> Network:
    """Resolve a Network: explicit arg > NVNM_NETWORK env > caller default."""
    chosen = name or os.environ.get("NVNM_NETWORK") or default
    try:
        return NETWORKS[chosen]
    except KeyError:
        raise ValueError(
            f"unknown network {chosen!r}; expected one of {sorted(NETWORKS)}"
        ) from None


def load_dotenv(path: Path | None = None) -> None:
    """Overlay .env values into os.environ (existing variables win)."""
    env_path = path or Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def testnet_rpc() -> str:
    return TESTNET.rpc_url()


def testnet_private_key() -> int:
    raw = os.environ.get("NVNM_TESTNET_KEY", "")
    if not raw:
        raise RuntimeError(
            "NVNM_TESTNET_KEY is not set; copy .env.example to .env and fill it in"
        )
    return parse_private_key(raw)


def signing_context(network: Network) -> tuple[int, int]:
    """The single gate for transaction signing: returns (private_key, chain_id).

    Testnet reads NVNM_TESTNET_KEY (the .env dev key). Mainnet refuses
    unless BOTH NVNM_MAINNET_WRITE_OK=1 and NVNM_MAINNET_KEY are set —
    deliberately distinct variables that are never placed in .env, so a
    session or a misconfigured tool cannot sign chain 1611 with the
    ambient dev key. Mainnet writes are a human-gated ops action.
    """
    if network.key == "testnet":
        return testnet_private_key(), network.chain_id
    if network.key == "mainnet":
        if os.environ.get("NVNM_MAINNET_WRITE_OK") != "1":
            raise RuntimeError(
                "mainnet signing is disabled: set NVNM_MAINNET_WRITE_OK=1 and "
                "NVNM_MAINNET_KEY explicitly (ops only; never in .env, never "
                "in a Claude Code session)"
            )
        raw = os.environ.get("NVNM_MAINNET_KEY", "")
        if not raw:
            raise RuntimeError(
                "NVNM_MAINNET_WRITE_OK=1 but NVNM_MAINNET_KEY is not set; the "
                "testnet key is never used for mainnet"
            )
        return parse_private_key(raw), network.chain_id
    raise ValueError(f"no signing policy for network {network.key!r}")
