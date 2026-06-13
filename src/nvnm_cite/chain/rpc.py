"""Minimal Ethereum JSON-RPC client. Stdlib only (urllib).

Exactly the calls the project needs; no provider abstraction. All ints
are Python ints; hex conversion happens at the boundary.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.request
from typing import Any

# Transient TRANSPORT failures: the request never produced a JSON-RPC reply.
# All are safe to retry because eth_call/reads are idempotent and a resent
# raw tx keeps the same hash. urllib.error.URLError subclasses OSError;
# socket timeouts surface as OSError; a response truncated mid-stream raises
# http.client.IncompleteRead (an HTTPException). A JSON-RPC RpcError is NOT
# in here: it means the node answered, so it is never retried.
_TRANSPORT_ERRORS = (OSError, http.client.HTTPException)


class RpcError(RuntimeError):
    """A JSON-RPC level error response from the node."""

    def __init__(self, method: str, code: int, message: str, data: Any = None):
        super().__init__(f"{method}: [{code}] {message}")
        self.method = method
        self.code = code
        self.message = message
        self.data = data


def _to_int(hex_value: str) -> int:
    return int(hex_value, 16)


class EvmRpc:
    """JSON-RPC client with OPT-IN transport-level retry.

    Retry lives in the client (not scattered across callers) so the bulk
    pullers -- the indexer, the loader, and any third party running
    rebuild-index -- can ride out the public RPC's Cloudflare truncations
    and timeouts over a quarter-million-row pull. But it is OPT-IN: the
    default is a single attempt (fail fast), because interactive callers
    (the webapp, the Phase 3 verifier's receipt read) must surface a dead
    or slow RPC immediately rather than stall through 30s of backoff. Long-
    running consumers pass max_attempts explicitly. A JSON-RPC RpcError is
    never retried at any setting -- it means the node answered.
    """

    def __init__(
        self,
        url: str,
        timeout: float = 30.0,
        max_attempts: int = 1,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
        on_retry: Any = None,
    ):
        self.url = url
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        # Optional callback(method, attempt, exc) for progress visibility.
        self.on_retry = on_retry
        self._next_id = 1

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or [],
        }
        self._next_id += 1
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # The public RPC sits behind Cloudflare, which rejects the
                # default Python-urllib user agent (error 1010).
                "User-Agent": "nvnm-cite/0.1.0",
            },
        )
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except _TRANSPORT_ERRORS as err:
                if attempt >= self.max_attempts:
                    raise
                if self.on_retry is not None:
                    self.on_retry(method, attempt, err)
                time.sleep(min(self.backoff_base * 2 ** (attempt - 1), self.backoff_cap))
        if "error" in body:
            err = body["error"]
            raise RpcError(method, err.get("code", 0), err.get("message", ""), err.get("data"))
        return body["result"]

    # --- typed conveniences ---

    def chain_id(self) -> int:
        return _to_int(self.call("eth_chainId"))

    def block_number(self) -> int:
        return _to_int(self.call("eth_blockNumber"))

    def get_balance(self, address: str) -> int:
        return _to_int(self.call("eth_getBalance", [address, "latest"]))

    def get_transaction_count(self, address: str, tag: str = "pending") -> int:
        return _to_int(self.call("eth_getTransactionCount", [address, tag]))

    def gas_price(self) -> int:
        return _to_int(self.call("eth_gasPrice"))

    def estimate_gas(self, from_addr: str, to: str, data: bytes, value: int = 0) -> int:
        tx = {
            "from": from_addr,
            "to": to,
            "data": "0x" + data.hex(),
            "value": hex(value),
        }
        return _to_int(self.call("eth_estimateGas", [tx]))

    def send_raw_transaction(self, raw: bytes) -> str:
        return self.call("eth_sendRawTransaction", ["0x" + raw.hex()])

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        return self.call("eth_getTransactionReceipt", [tx_hash])

    def eth_call(self, to: str, data: bytes, block: str = "latest") -> bytes:
        result = self.call("eth_call", [{"to": to, "data": "0x" + data.hex()}, block])
        return bytes.fromhex(result.removeprefix("0x"))

    def wait_for_receipt(
        self, tx_hash: str, timeout: float = 120.0, poll_seconds: float = 2.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            receipt = self.get_transaction_receipt(tx_hash)
            if receipt is not None:
                return receipt
            time.sleep(poll_seconds)
        raise TimeoutError(f"no receipt for {tx_hash} after {timeout:.0f}s")
