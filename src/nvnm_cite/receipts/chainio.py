"""Minimal chain reads for the receipts layer (registry facts, keyed records,
head block). Depends only on chain/, so receipts/ never imports webapp/.

This mirrors a few read methods of the webapp's ChainGateway; the duplication
is small and deliberate (clean layering). A future refactor could host one
shared read gateway in a lower layer — a dedup candidate, noted, not urgent.
"""

from __future__ import annotations

from typing import Callable

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import EvmRpc, RpcError


class ChainReader:
    """Read-only precompile access. A fresh EvmRpc per call (via the factory)
    keeps it safe under threaded callers; a keyed miss returns None, every
    other error propagates."""

    def __init__(self, rpc_factory: Callable[[], EvmRpc]):
        self._rpc_factory = rpc_factory

    def head_block(self) -> int:
        return self._rpc_factory().block_number()

    def registry(self, name: str) -> dict | None:
        """Registry facts by name, or None when it does not exist."""
        try:
            raw = self._rpc_factory().eth_call(
                pc.PRECOMPILE_ADDRESS, pc.build_registries_query(name=name)
            )
            reg = pc.decode_registries_result(raw)[0][0]
        except RpcError as err:
            if pc.is_keyed_miss(err):
                return None
            raise
        return {"id": reg.id, "name": reg.name, "creator": reg.creator, "created_at": reg.created_at}

    def keyed_record(self, registry: str, checksum: str, block: str = "latest") -> pc.Record | None:
        """Latest record for (registry, checksum), or None on a keyed miss."""
        try:
            raw = self._rpc_factory().eth_call(
                pc.PRECOMPILE_ADDRESS, pc.build_records_query(registry=registry, checksum=checksum), block=block
            )
        except RpcError as err:
            if pc.is_keyed_miss(err):
                return None
            raise
        records, _ = pc.decode_records_result(raw)
        return records[0] if records else None
