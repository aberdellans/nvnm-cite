"""Chain resolution for the verifier core: one keyed citation lookup.

The drafting-time check resolves each citation by a LIVE keyed
``records(registry, citation)`` ``eth_call`` against the NVNM-operated RPC
(item 0, DECISIONS 2026-06-13; supersedes the old local-index-only rule).
Two properties the core depends on and that every Resolver must honor:

1. A keyed MISS -- the precompile's ``collections: not found`` error --
   returns ``record=None`` (the citation is genuinely absent → NOT_FOUND).
   Every OTHER failure (transport, timeout, a non-miss RPC error)
   PROPAGATES unchanged. A dead or slow RPC must never be mistaken for
   "this citation does not exist" (plan task 3.2).
2. The exact, replayable query travels back with the answer, so the
   verdict is non-repudiable: any skeptic re-runs it against an
   independent node and gets the same result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import EvmRpc, RpcError


@dataclass(frozen=True)
class Resolution:
    """The chain's answer for one keyed lookup, plus the query to replay it."""

    record: pc.Record | None
    query: dict


def records_query(registry: str, checksum: str, block: str = "latest") -> tuple[bytes, dict]:
    """Calldata + a replayable eth_call description for one keyed read."""
    data = pc.build_records_query(registry=registry, checksum=checksum)
    replay = {
        "method": "eth_call",
        "params": [{"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + data.hex()}, block],
    }
    return data, replay


class Resolver(Protocol):
    """What the verifier core needs from the chain: resolve one citation."""

    def resolve(self, registry: str, checksum: str) -> Resolution: ...


class ChainResolver:
    """Live keyed ``records()`` reads against the NVNM-operated RPC.

    A fresh ``EvmRpc`` per call (via the factory) keeps this safe under the
    webapp's threaded server. The default RPC is fail-fast
    (``max_attempts=1``): the interactive verifier must surface a dead RPC
    immediately, not stall through retry backoff (DECISIONS 2026-06-13).
    """

    def __init__(self, rpc_factory: Callable[[], EvmRpc], block: str = "latest"):
        self._rpc_factory = rpc_factory
        self.block = block

    def resolve(self, registry: str, checksum: str) -> Resolution:
        data, replay = records_query(registry, checksum, self.block)
        try:
            raw = self._rpc_factory().eth_call(pc.PRECOMPILE_ADDRESS, data, block=self.block)
        except RpcError as err:
            if pc.is_keyed_miss(err):
                return Resolution(record=None, query=replay)
            raise  # transport / non-miss RPC error: NOT a NOT_FOUND signal
        records, _ = pc.decode_records_result(raw)
        return Resolution(record=records[0] if records else None, query=replay)
