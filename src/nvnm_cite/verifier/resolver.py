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
from nvnm_cite.verifier.telemetry import NullTelemetry, TelemetrySink


@dataclass(frozen=True)
class Resolution:
    """The chain's answer for one keyed lookup, plus the query to replay it."""

    record: pc.Record | None
    query: dict


def records_query(registry_id: int, checksum: str, block: str = "latest") -> tuple[bytes, dict]:
    """Calldata + a replayable eth_call description for one keyed read.

    Id-keyed under anchoring v1.2.0: the calldata carries the numeric
    registryId (names are non-unique on chain and cannot key a read)."""
    data = pc.build_records_query(registry_id=registry_id, checksum=checksum)
    replay = {
        "method": "eth_call",
        "params": [{"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + data.hex()}, block],
    }
    return data, replay


class Resolver(Protocol):
    """What the verifier core needs from the chain: resolve one citation.

    ``registry_name`` rides along for telemetry/reporting only; the chain
    call keys on ``registry_id``."""

    def resolve(
        self, registry_id: int, checksum: str, registry_name: str | None = None
    ) -> Resolution: ...


class ChainResolver:
    """Live keyed ``records()`` reads against the NVNM-operated RPC.

    A fresh ``EvmRpc`` per call (via the factory) keeps this safe under the
    webapp's threaded server. The default RPC is fail-fast
    (``max_attempts=1``): the interactive verifier must surface a dead RPC
    immediately, not stall through retry backoff (DECISIONS 2026-06-13).
    """

    def __init__(
        self,
        rpc_factory: Callable[[], EvmRpc],
        block: str = "latest",
        telemetry: TelemetrySink | None = None,
    ):
        self._rpc_factory = rpc_factory
        self.block = block
        # Opt-in aggregate analytics (task 4.6); off unless an operator attaches a sink.
        self.telemetry = telemetry or NullTelemetry()

    def resolve(
        self, registry_id: int, checksum: str, registry_name: str | None = None
    ) -> Resolution:
        # Telemetry stays keyed by NAME (analytics continuity across the
        # v1.2.0 id migration); the chain call keys on the id.
        tel_key = registry_name or f"#{registry_id}"
        data, replay = records_query(registry_id, checksum, self.block)
        try:
            raw = self._rpc_factory().eth_call(pc.PRECOMPILE_ADDRESS, data, block=self.block)
        except RpcError as err:
            if pc.is_keyed_miss(err):
                self.telemetry.record(tel_key, checksum, False)
                return Resolution(record=None, query=replay)
            raise  # transport / non-miss RPC error: NOT a NOT_FOUND signal, and not telemetry
        records, _ = pc.decode_records_result(raw)
        record = records[0] if records else None
        self.telemetry.record(tel_key, checksum, record is not None)
        return Resolution(record=record, query=replay)
