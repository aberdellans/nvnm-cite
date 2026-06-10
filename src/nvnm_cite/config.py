"""Project configuration from .env and the process environment.

Values are loaded, never logged. Code in this package must not print
private keys or token values; callers get parsed values only.
"""

from __future__ import annotations

import os
from pathlib import Path

from nvnm_cite.chain.signer import parse_private_key

TESTNET_CHAIN_ID = 787111
TESTNET_EXPLORER = "https://explorer.evm.testnet.nvnmchain.io"


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
    return os.environ.get("NVNM_TESTNET_RPC", "https://evm.testnet.nvnmchain.io")


def testnet_private_key() -> int:
    raw = os.environ.get("NVNM_TESTNET_KEY", "")
    if not raw:
        raise RuntimeError(
            "NVNM_TESTNET_KEY is not set; copy .env.example to .env and fill it in"
        )
    return parse_private_key(raw)
