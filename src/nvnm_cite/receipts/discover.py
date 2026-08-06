"""Chain-wide receipt discovery: which registries anchor a given SHA-256.

The chain has NO reverse index — the only existence read is the keyed
records(registry_id, checksum) call — so "is this document anchored
anywhere?" is answered by sweeping every registry with that keyed read.
Receipts live in per-firm-per-case registries (invariant 4); the court
citation registries hold citation keys, never document hashes, so callers
exclude them via the pinned manifest and the sweep checks everything else.

Cost: one eth_call per non-court registry, run in parallel — live reads,
consistent with item 0 (the chain answers, replayable per hit). Linear in
registry count; fine at today's scale. If receipts adoption ever makes the
sweep heavy, the fix is a rebuildable discovery index whose hits are STILL
confirmed by the live keyed read (the index must never become the
authority).

A transport failure during the sweep PROPAGATES: "could not check a
registry" must never read as "not anchored anywhere" — the same posture as
the verifier's NOT_FOUND rule.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

SWEEP_WORKERS = 8


def find_anchors(
    reader: Any,
    sha256: str,
    *,
    exclude_ids: set[int] | frozenset[int] = frozenset(),
    max_workers: int = SWEEP_WORKERS,
) -> dict[str, Any]:
    """Sweep every registry except ``exclude_ids`` for checksum == ``sha256``.

    ``reader`` duck-types receipts.chainio.ChainReader (and the webapp's
    ChainGateway): ``all_registries() -> [{id, name, creator, created_at}]``
    plus ``keyed_record(registry_id, checksum) -> Record | None`` (None means
    keyed miss; anything else raises). Returns hits ordered by registry id:

        {"hits": [{"registry": row, "record": Record}, ...],
         "registries_swept": int, "registries_excluded": int}
    """
    rows = reader.all_registries()
    targets = [r for r in rows if r["id"] not in exclude_ids]
    hits: list[dict[str, Any]] = []
    if targets:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(targets))) as pool:
            records = pool.map(lambda r: reader.keyed_record(r["id"], sha256), targets)
            for row, record in zip(targets, records):
                if record is not None:
                    hits.append({"registry": row, "record": record})
    hits.sort(key=lambda h: h["registry"]["id"])
    return {
        "hits": hits,
        "registries_swept": len(targets),
        "registries_excluded": len(rows) - len(targets),
    }
