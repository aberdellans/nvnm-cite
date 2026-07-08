"""Typed wrappers for the NVNM anchoring precompile's seven methods.

Builds calldata and decodes eth_call results against the vendored ABI
(anchoring.json in this package; originally copied from the NVNM_MCP_Server
project, extended 2026-07-07 with updateRecordStatus + revokeRole and
cross-checked against MANTRA's anchoring-abi.sol and the deployed binary).
No networking here: the RPC client and the live round-trip arrive with plan
task 0.6.

Key asymmetry (measured 2026-07-07): READS key on registry name + checksum
string; WRITES that target an existing record (updateRecordStatus,
role grants/revokes) key on numeric ids (registryId/recordId/index).

Chain-set fields (timestamp, recordId, index, isLatest) are zeroed in
outbound addRecord calldata; the chain fills them. The records() query
supports the keyed existence read the whole design rests on:
records(registry_name, checksum, 0, 0, page).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from nvnm_cite.chain import abi

PRECOMPILE_ADDRESS = "0x0000000000000000000000000000000000000A00"

DEFAULT_PAGE_LIMIT = 100


def _load_abi() -> dict[str, abi.Entry]:
    raw = resources.files("nvnm_cite.chain").joinpath("anchoring.json").read_text()
    return {fn["name"]: fn for fn in json.loads(raw)}


_FUNCTIONS = _load_abi()

SELECTORS = {
    name: "0x" + abi.function_selector(fn).hex() for name, fn in _FUNCTIONS.items()
}

# Measured (DECISIONS 2026-06-10): a keyed records()/registries() lookup that
# misses ERRORs through eth_call with this marker; an empty page is NOT the
# miss signal. The one place this string lives, so the verifier's NOT_FOUND
# path and the registry-existence probe agree with each other.
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
    registry: str
    uri: str
    checksum: str
    checksum_algo: str
    metadata: str
    timestamp: str
    status: str
    record_id: int
    index: int
    is_latest: bool


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
    registry: str,
    uri: str,
    checksum: str,
    checksum_algo: str,
    metadata: str = "",
    status: str = "Active",
) -> bytes:
    if not registry:
        raise ValueError("registry is required")
    if not checksum:
        raise ValueError("checksum is required")
    record = [registry, uri, checksum, checksum_algo, metadata, "", status, 0, 0, False]
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
    """In-place status write on an existing (registry, record, index) — the
    write side is id-keyed, unlike the name+checksum-keyed reads. `status`
    is free-form on chain; the vocabulary is an application convention."""
    if not status:
        raise ValueError("status is required")
    return abi.encode_call(
        _FUNCTIONS["updateRecordStatus"], [registry_id, record_id, index, status]
    )


def build_records_query(
    registry: str = "",
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
            registry,
            checksum,
            record_id,
            index,
            _pagination(page_key, offset, limit, count_total, reverse),
        ],
    )


def build_registries_query(
    registry_id: int = 0,
    name: str = "",
    page_key: bytes = b"",
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    count_total: bool = False,
    reverse: bool = False,
) -> bytes:
    return abi.encode_call(
        _FUNCTIONS["registries"],
        [registry_id, name, _pagination(page_key, offset, limit, count_total, reverse)],
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
