"""EvmRpc transport-retry tests.

Pins the behavior that fixed the task-2.6 sync crash: a response truncated
mid-stream (http.client.IncompleteRead) is retried, a socket timeout is
retried, but a JSON-RPC error reply (the node answered) is NOT -- so the
keyed-miss NOT_FOUND path and other semantic errors surface immediately.
"""

from __future__ import annotations

import http.client
import json

import pytest

from nvnm_cite.chain import rpc as rpc_module
from nvnm_cite.chain.rpc import EvmRpc, RpcError


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self._raw = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._raw


def patch_urlopen(monkeypatch, behaviors):
    """behaviors: list of either an Exception instance (raise) or dict (reply)."""
    calls = {"n": 0}

    def fake_urlopen(_request, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        step = behaviors[i]
        if isinstance(step, Exception):
            raise step
        return FakeResponse(step)

    monkeypatch.setattr(rpc_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(rpc_module.time, "sleep", lambda _s: None)
    return calls


def test_retries_incomplete_read_then_succeeds(monkeypatch) -> None:
    calls = patch_urlopen(
        monkeypatch,
        [
            http.client.IncompleteRead(b"partial"),
            http.client.IncompleteRead(b"partial"),
            {"jsonrpc": "2.0", "id": 1, "result": "0xc0ffee"},
        ],
    )
    rpc = EvmRpc("http://node.test", max_attempts=6, backoff_base=0)
    assert rpc.call("eth_blockNumber") == "0xc0ffee"
    assert calls["n"] == 3


def test_retries_socket_timeout(monkeypatch) -> None:
    calls = patch_urlopen(
        monkeypatch,
        [TimeoutError("read timed out"), {"jsonrpc": "2.0", "id": 1, "result": "0x1"}],
    )
    rpc = EvmRpc("http://node.test", max_attempts=6, backoff_base=0)
    assert rpc.call("eth_chainId") == "0x1"
    assert calls["n"] == 2


def test_rpc_error_is_not_retried(monkeypatch) -> None:
    # A JSON-RPC error means the node answered; the keyed-miss NOT_FOUND path
    # depends on this surfacing immediately, not being retried away.
    calls = patch_urlopen(
        monkeypatch,
        [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "collections: not found: key"}}],
    )
    # Even with retry budget available, a semantic error is not retried.
    rpc = EvmRpc("http://node.test", max_attempts=6, backoff_base=0)
    with pytest.raises(RpcError) as excinfo:
        rpc.call("eth_call")
    assert "not found" in excinfo.value.message
    assert calls["n"] == 1


def test_gives_up_after_max_attempts(monkeypatch) -> None:
    calls = patch_urlopen(monkeypatch, [http.client.IncompleteRead(b"") for _ in range(4)])
    rpc = EvmRpc("http://node.test", max_attempts=4, backoff_base=0)
    with pytest.raises(http.client.IncompleteRead):
        rpc.call("eth_blockNumber")
    assert calls["n"] == 4


def test_on_retry_callback_fires(monkeypatch) -> None:
    patch_urlopen(
        monkeypatch,
        [http.client.IncompleteRead(b""), {"jsonrpc": "2.0", "id": 1, "result": "0x1"}],
    )
    seen = []
    rpc = EvmRpc(
        "http://node.test", max_attempts=6, backoff_base=0, on_retry=lambda m, a, e: seen.append((m, a))
    )
    rpc.call("eth_blockNumber")
    assert seen == [("eth_blockNumber", 1)]
