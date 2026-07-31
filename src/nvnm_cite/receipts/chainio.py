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

    def registry(self, registry_id: int) -> dict | None:
        """Registry facts by id, or None when it does not exist. Names are
        non-unique under v1.2.0, so the id is the only keyed lookup."""
        try:
            raw = self._rpc_factory().eth_call(
                pc.PRECOMPILE_ADDRESS, pc.build_registries_query(registry_id=registry_id)
            )
            rows = pc.decode_registries_result(raw)[0]
        except RpcError as err:
            if pc.is_keyed_miss(err):
                return None
            raise
        if not rows:
            return None
        reg = rows[0]
        return {"id": reg.id, "name": reg.name, "creator": reg.creator, "created_at": reg.created_at}

    def registries_by_creator(self, creator: str) -> list[dict]:
        """All registries created by ``creator`` (bech32 nvnm1... string), via
        a full offset-paged enumeration — the only name/owner search v1.2.0
        allows. Same-named duplicates are all returned; callers must surface
        ambiguity, never pick a row silently."""
        rpc = self._rpc_factory()
        out: list[dict] = []
        offset = 0
        while True:
            raw = rpc.eth_call(
                pc.PRECOMPILE_ADDRESS,
                pc.build_registries_query(offset=offset, limit=200),
            )
            rows, _ = pc.decode_registries_result(raw)
            if not rows:
                break
            for reg in rows:
                if reg.creator == creator:
                    out.append(
                        {
                            "id": reg.id,
                            "name": reg.name,
                            "creator": reg.creator,
                            "created_at": reg.created_at,
                        }
                    )
            offset += len(rows)
            if len(rows) < 200:
                break
        return out

    def keyed_record(self, registry_id: int, checksum: str, block: str = "latest") -> pc.Record | None:
        """Latest record for (registry_id, checksum), or None on a keyed miss."""
        try:
            raw = self._rpc_factory().eth_call(
                pc.PRECOMPILE_ADDRESS,
                pc.build_records_query(registry_id=registry_id, checksum=checksum),
                block=block,
            )
        except RpcError as err:
            if pc.is_keyed_miss(err):
                return None
            raise
        records, _ = pc.decode_records_result(raw)
        return records[0] if records else None
