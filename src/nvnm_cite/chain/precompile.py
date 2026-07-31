"""Typed wrappers for the NVNM anchoring precompile's seven methods.

Builds calldata and decodes eth_call results against the vendored ABI
(anchoring.json in this package). Vendored at anchoring-module v1.2.0
(2026-07-31, verified live against both networks): registry names are
NON-UNIQUE and every reference — reads and writes alike — keys on the
numeric registryId. The old name-keyed records()/registries()/addRecord
selectors return "unknown method id" on both networks.

No networking here: callers pair these with chain.rpc.EvmRpc.

Chain-set fields (timestamp, recordId, index, isLatest) are zeroed in
outbound addRecord calldata; the chain fills them. The records() query
supports the keyed existence read the whole design rests on:
records(registry_id, checksum, 0, 0, page).

The precompile emits events on normal transactions (only `caller` is
indexed); decode_event_logs recovers e.g. the new registryId from an
addRegistry receipt. Records loaded by the 2026-07-30 mainnet state
migration emitted NO events — log scans never see them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from nvnm_cite.chain import abi
from nvnm_cite.chain.keccak import keccak_256

PRECOMPILE_ADDRESS = "0x0000000000000000000000000000000000000A00"

DEFAULT_PAGE_LIMIT = 100


def _load_abi() -> tuple[dict[str, abi.Entry], dict[str, abi.Entry]]:
    raw = resources.files("nvnm_cite.chain").joinpath("anchoring.json").read_text()
    entries = json.loads(raw)
    functions = {e["name"]: e for e in entries if e["type"] == "function"}
    events = {e["name"]: e for e in entries if e["type"] == "event"}
    return functions, events


_FUNCTIONS, _EVENTS = _load_abi()

SELECTORS = {
    name: "0x" + abi.function_selector(fn).hex() for name, fn in _FUNCTIONS.items()
}

# Event topic0 is the FULL keccak-256 of the event signature (not a 4-byte
# selector). abi.function_signature works on event entries too: `indexed`
# is an extra key the canonical-type walk ignores.
EVENT_TOPICS = {
    "0x" + keccak_256(abi.function_signature(ev).encode()).hex(): name
    for name, ev in _EVENTS.items()
}

# Measured (DECISIONS 2026-06-10; re-verified under v1.2.0 2026-07-31): a keyed
# records()/registries() lookup that misses ERRORs through eth_call with this
# marker; an empty page is NOT the miss signal. The one place this string
# lives, so the verifier's NOT_FOUND path and the registry-existence probe
# agree with each other.
KEYED_MISS_MARKER = "collections: not found"


def is_keyed_miss(err: Exception) -> bool:
    """True when ``err`` is the precompile's keyed-miss error (record/registry
    absent). Duck-typed on ``.message`` so this stays decoupled from the RPC
    client. Callers map a miss to NOT_FOUND / registry-absent and let every
    other failure -- transport, timeout, a non-miss RPC error -- propagate;
    a transport failure must never be mistaken for a real chain answer."""
    return KEYED_MISS_MARKER in (getattr(err, "message", "") or "")


@dataclass(frozen=True)
class Record:
    uri: str
    checksum: str
    checksum_algo: str
    metadata: str
    timestamp: str
    status: str
    record_id: int
    index: int
    is_latest: bool
    registry_id: int


@dataclass(frozen=True)
class Registry:
    id: int
    name: str
    description: str
    creator: str
    created_at: str
    metadata: str


@dataclass(frozen=True)
class Page:
    next_key: bytes
    total: int


def _pagination(
    page_key: bytes, offset: int, limit: int, count_total: bool, reverse: bool
) -> list[Any]:
    return [page_key, offset, limit, count_total, reverse]


# --- calldata builders ---


def build_add_registry(name: str, description: str, metadata: str = "") -> bytes:
    if not name:
        raise ValueError("registry name is required")
    return abi.encode_call(_FUNCTIONS["addRegistry"], [name, description, metadata])


def build_add_record(
    registry_id: int,
    uri: str,
    checksum: str,
    checksum_algo: str,
    metadata: str = "",
    status: str = "Active",
) -> bytes:
    if registry_id < 1:
        raise ValueError("registry_id must be a positive id")
    if not checksum:
        raise ValueError("checksum is required")
    record = [uri, checksum, checksum_algo, metadata, "", status, 0, 0, False, registry_id]
    return abi.encode_call(_FUNCTIONS["addRecord"], [record])


def build_grant_role(
    registry_id: int, account: str, role: str, checksum: str = ""
) -> bytes:
    if role not in ("admin", "editor"):
        raise ValueError(f"role must be 'admin' or 'editor', got {role!r}")
    return abi.encode_call(
        _FUNCTIONS["grantRole"], [registry_id, checksum, account, role]
    )


def build_revoke_role(
    registry_id: int, account: str, role: str, checksum: str = ""
) -> bytes:
    if role not in ("admin", "editor"):
        raise ValueError(f"role must be 'admin' or 'editor', got {role!r}")
    return abi.encode_call(
        _FUNCTIONS["revokeRole"], [registry_id, checksum, account, role]
    )


def build_update_record_status(
    registry_id: int, record_id: int, index: int, status: str
) -> bytes:
    """In-place status write on an existing (registry, record, index). `status`
    is free-form on chain; the vocabulary is an application convention."""
    if not status:
        raise ValueError("status is required")
    return abi.encode_call(
        _FUNCTIONS["updateRecordStatus"], [registry_id, record_id, index, status]
    )


def build_records_query(
    registry_id: int = 0,
    checksum: str = "",
    record_id: int = 0,
    index: int = 0,
    page_key: bytes = b"",
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    count_total: bool = False,
    reverse: bool = False,
) -> bytes:
    return abi.encode_call(
        _FUNCTIONS["records"],
        [
            registry_id,
            checksum,
            record_id,
            index,
            _pagination(page_key, offset, limit, count_total, reverse),
        ],
    )


def build_registries_query(
    registry_id: int = 0,
    page_key: bytes = b"",
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    count_total: bool = False,
    reverse: bool = False,
) -> bytes:
    """registry_id=0 enumerates ALL registries (offset-paged). The v1.2.0
    interface has NO name filter: name -> id resolution happens off-chain
    against the pinned registry manifest, or by enumerating."""
    return abi.encode_call(
        _FUNCTIONS["registries"],
        [registry_id, _pagination(page_key, offset, limit, count_total, reverse)],
    )


# --- result decoders ---


def decode_add_registry_result(data: bytes) -> int:
    return abi.decode_result(_FUNCTIONS["addRegistry"], data)[0]


def decode_add_record_result(data: bytes) -> int:
    return abi.decode_result(_FUNCTIONS["addRecord"], data)[0]


def decode_records_result(data: bytes) -> tuple[list[Record], Page]:
    rows, page = abi.decode_result(_FUNCTIONS["records"], data)
    return [Record(*row) for row in rows], Page(*page)


def decode_registries_result(data: bytes) -> tuple[list[Registry], Page]:
    rows, page = abi.decode_result(_FUNCTIONS["registries"], data)
    return [Registry(*row) for row in rows], Page(*page)


# --- event log decoders ---


def decode_event_logs(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decode anchoring-precompile logs from an eth_getTransactionReceipt.

    Returns one dict per recognized log: {"event": <name>, "caller": 0x...,
    <non-indexed fields by ABI name>}. Unrecognized logs and logs from other
    addresses are skipped, never an error.
    """
    decoded: list[dict[str, Any]] = []
    for log in logs:
        if (log.get("address") or "").lower() != PRECOMPILE_ADDRESS.lower():
            continue
        topics = log.get("topics") or []
        if not topics:
            continue
        name = EVENT_TOPICS.get(topics[0].lower())
        if name is None:
            continue
        entry = _EVENTS[name]
        non_indexed = [p for p in entry["inputs"] if not p.get("indexed")]
        data_hex = (log.get("data") or "0x")[2:]
        values = abi.decode_values(non_indexed, bytes.fromhex(data_hex))
        out: dict[str, Any] = {"event": name}
        if len(topics) > 1:
            out["caller"] = "0x" + topics[1][-40:]
        out.update({p["name"]: v for p, v in zip(non_indexed, values)})
        decoded.append(out)
    return decoded


def decode_add_registry_log(logs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The registryId a confirmed addRegistry tx was assigned, from its
    receipt logs: {"registry_id": int, "name": str, "caller": 0x...} or None."""
    for ev in decode_event_logs(logs):
        if ev["event"] == "AddRegistry":
            return {
                "registry_id": ev["registryId"],
                "name": ev["name"],
                "caller": ev.get("caller", ""),
            }
    return None
