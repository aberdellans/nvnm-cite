"""Web demo services: check, receipt, lookup, decode, status.

Trust boundaries, restated where the code lives:

- ``CheckService`` (drafting time): local index only. It performs no RPC
  and never persists the document; bytes live in this call frame and are
  garbage the moment the report is returned.
- ``ReceiptService`` (filing time): re-verifies every keyed citation via
  ``records()`` eth_calls pinned to one block, so the anchored receipt
  claims chain state at a stated height (plan task 3.2 semantics). The
  server prepares calldata with the golden-tested codec but signs
  nothing; the user's wallet does.
- Receipt object: the receipt schema locks at Phase 4 task 4.1. Until
  then this module writes schema string ``nvnm-cite-receipt/v1-draft``
  (a deliberate marker: testnet demo receipts must not masquerade as
  the locked v1). Field sketch follows plan 4.1; compaction follows the
  4.3 hints (single-char statuses, registry index table, omit
  ``as_written`` when redundant, omit unknown name_checks).

Status vocabulary is the locked five-status enum (DECISIONS 2026-06-10):
VERIFIED / NOT_FOUND / NOT_COVERED / AMBIGUOUS_JURISDICTION /
UNPARSEABLE, plus the orthogonal name_check field. The normalizer's
UNRESOLVED disposition (orphan short forms) reports as UNPARSEABLE with
the normalizer's reason carried through.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from nvnm_cite.chain import abi
from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.config import TESTNET_CHAIN_ID, TESTNET_EXPLORER
from nvnm_cite.loader.records import METADATA_CAP, compact_json
from nvnm_cite.normalizer import CANONICAL_SPEC, NORMALIZER_VERSION, Disposition, normalize
from nvnm_cite.webapp.extract import ExtractError, extract_text
from nvnm_cite.webapp.localindex import IndexHit, LocalIndex

WEBAPP_VERSION = "0.1.0"
RECEIPT_SCHEMA = "nvnm-cite-receipt/v1-draft"
RECEIPT_URI = "urn:nvnm-cite:receipt:v1"
RECEIPTS_REGISTRY = "receipts-v1"
# Locked creation strings, docs/record-schema.md section 2 (rendered, not improvised).
RECEIPTS_REGISTRY_DESCRIPTION = (
    "nvnm-cite filing receipts: SHA-256-keyed records of citation checks "
    "performed against the us-* registries. nvnm-cite."
)
RECEIPTS_REGISTRY_METADATA = compact_json(
    {"schema": "nvnm-cite-receipt/v1", "spec": "cite-canonical-v1"}
)

COURT_REGISTRIES = ("us-scotus", "us-ca11")

VERIFIED = "VERIFIED"
NOT_FOUND = "NOT_FOUND"
NOT_COVERED = "NOT_COVERED"
AMBIGUOUS = "AMBIGUOUS_JURISDICTION"
UNPARSEABLE = "UNPARSEABLE"
STATUS_CHARS = {VERIFIED: "V", NOT_FOUND: "N", NOT_COVERED: "C", AMBIGUOUS: "A", UNPARSEABLE: "U"}

MAX_TEXT_CHARS = 2_000_000
MAX_RECEIPT_ENTRIES = 500

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TXHASH_RE = re.compile(r"^0x[0-9a-f]{64}$")


class WebAppError(ValueError):
    """User-facing request error; http_status picks the response code."""

    def __init__(self, message: str, http_status: int = 422):
        super().__init__(message)
        self.http_status = http_status


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_keyed_miss(err: RpcError) -> bool:
    # Measured (DECISIONS 2026-06-10): keyed misses ERROR with this marker;
    # an empty page is NOT the miss signal. Anything else is transport.
    return "collections: not found" in (err.message or "")


def _clean_str(value: Any, cap: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(ch for ch in value if ch >= " " or ch == "\t").strip()
    return cleaned[:cap] if cleaned else None


# --- name_check heuristic (conservative preview of plan task 3.3) ---

_NAME_STOPWORDS = frozenset(
    "v vs in re ex parte et al the of and on a an matter state states united"
    " people commonwealth city county town u s inc llc co corp ltd".split()
)


def _name_tokens(name: str) -> set[str]:
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    return {w for w in words if w not in _NAME_STOPWORDS and len(w) > 1}


def name_check(plaintiff: str | None, defendant: str | None, record_names: list[str]) -> str:
    """match | mismatch | unknown. Mismatch only when both brief parties are
    present and neither shares a single significant token with any record
    name: the heuristic flags the invented-name failure mode and stays
    silent when it cannot be sure."""
    parties = [_name_tokens(p) for p in (plaintiff, defendant) if p]
    parties = [p for p in parties if p]  # drop vacuous ("United States" alone)
    candidates = [_name_tokens(n) for n in record_names if n]
    if not parties or not candidates:
        return "unknown"
    for cand in candidates:
        if all(p & cand for p in parties):
            return "match"
    if len(parties) == 2 and not any(p & cand for p in parties for cand in candidates):
        return "mismatch"
    return "unknown"


# =====================================================================
# Drafting-time check (local only)
# =====================================================================


class CheckService:
    def __init__(self, index: LocalIndex):
        self.index = index

    def check(self, data: bytes, filename: str) -> dict:
        started = time.monotonic()
        try:
            extraction = extract_text(data, filename)
        except ExtractError as exc:
            raise WebAppError(str(exc)) from exc
        sha256 = hashlib.sha256(data).hexdigest()
        if len(extraction.text) > MAX_TEXT_CHARS:
            raise WebAppError(
                f"document text exceeds {MAX_TEXT_CHARS:,} characters", http_status=413
            )

        result = normalize(extraction.text)
        covered = self.index.covered

        entries: dict[tuple, dict] = {}
        for occ in result.citations:
            if occ.disposition is Disposition.OK:
                key = ("ok", occ.registry, occ.canonical)
            elif occ.disposition is Disposition.AMBIGUOUS_JURISDICTION:
                key = ("ambiguous", occ.canonical or occ.as_written)
            else:
                key = ("unresolved", occ.as_written.strip().lower())
            entry = entries.get(key)
            if entry is None:
                entry = entries[key] = {
                    "registry": occ.registry,
                    "canonical": occ.canonical,
                    "as_written": occ.as_written,
                    "variants": [],
                    "occurrences": 0,
                    "kinds": set(),
                    "court": occ.court,
                    "year": occ.year,
                    "plaintiff": occ.plaintiff,
                    "defendant": occ.defendant,
                    "reason": occ.reason,
                    "first_span": list(occ.span),
                    "spans": [],
                }
            entry["occurrences"] += 1
            entry["kinds"].add(occ.kind)
            entry["spans"].append({"span": list(occ.span), "kind": occ.kind, "as_written": occ.as_written, "pin_cite": occ.pin_cite})
            if occ.as_written not in entry["variants"]:
                entry["variants"].append(occ.as_written)
            for field_name in ("plaintiff", "defendant", "court"):
                if entry[field_name] is None:
                    entry[field_name] = getattr(occ, field_name)
            if entry["year"] is None:
                entry["year"] = occ.year

        keyed = [
            (e["registry"], e["canonical"])
            for (kind, *_), e in entries.items()
            if kind == "ok" and e["registry"] in covered
        ]
        hits = self.index.lookup_many(keyed)

        citations: list[dict] = []
        counts = {s: 0 for s in (VERIFIED, NOT_FOUND, NOT_COVERED, AMBIGUOUS, UNPARSEABLE)}
        mismatches = 0
        for (kind, *_), entry in entries.items():
            hit: IndexHit | None = None
            if kind == "ok":
                if entry["registry"] in covered:
                    hit = hits.get((entry["registry"], entry["canonical"]))
                    status = VERIFIED if hit else NOT_FOUND
                    reason = None if hit else (
                        "no record for this citation in the "
                        f"{entry['registry']} registry (first-page canonical keys)"
                    )
                else:
                    status = NOT_COVERED
                    reason = (
                        f"{entry['registry']} is outside pilot coverage "
                        f"({', '.join(COURT_REGISTRIES)})"
                    )
            elif kind == "ambiguous":
                status, reason = AMBIGUOUS, entry["reason"]
            else:
                status, reason = UNPARSEABLE, entry["reason"]
            counts[status] += 1

            record_names = [c.get("name", "") for c in hit.cases] if hit else []
            check = name_check(entry["plaintiff"], entry["defendant"], record_names)
            if check == "mismatch":
                mismatches += 1

            citations.append(
                {
                    "registry": entry["registry"],
                    "canonical": entry["canonical"],
                    "as_written": entry["as_written"],
                    "variants": entry["variants"],
                    "occurrences": entry["occurrences"],
                    "kinds": sorted(entry["kinds"]),
                    "status": status,
                    "name_check": check,
                    "reason": reason,
                    "court": entry["court"],
                    "year": entry["year"],
                    "plaintiff": entry["plaintiff"],
                    "defendant": entry["defendant"],
                    "first_span": entry["first_span"],
                    "spans": entry["spans"][:50],
                    "record": (
                        {
                            "uri": hit.uri,
                            "cases": hit.cases[:5],
                            "more_cases": max(0, len(hit.cases) - 5),
                            "collision": hit.collision,
                            "source": hit.source,
                        }
                        if hit
                        else None
                    ),
                }
            )
        citations.sort(key=lambda c: c["first_span"])

        return {
            "document": {
                "filename": filename,
                "sha256": sha256,
                "bytes": len(data),
                "extraction": {
                    "method": extraction.method,
                    "chars": len(extraction.text),
                    "warning": extraction.warning,
                },
            },
            "normalizer": {"version": NORMALIZER_VERSION, "spec": CANONICAL_SPEC},
            "index": {"registries": self.index.coverage(), "covered": sorted(covered)},
            "summary": {
                "occurrences": len(result.citations),
                "distinct": len(citations),
                "by_status": counts,
                "name_mismatches": mismatches,
            },
            "citations": citations,
            "privacy": {
                "persisted": False,
                "note": (
                    "Processed in memory and discarded with this response; "
                    "nothing was written to disk and no chain or network "
                    "request was made during this check."
                ),
            },
            "generated_at": _utc_now(),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }


# =====================================================================
# Chain gateway (all RPC in one place)
# =====================================================================


class ChainGateway:
    def __init__(self, rpc_factory: Callable[[], EvmRpc]):
        self._rpc_factory = rpc_factory
        self._registry_cache: dict[str, tuple[float, dict | None]] = {}

    @property
    def rpc(self) -> EvmRpc:
        return self._rpc_factory()

    def head_block(self) -> int:
        return self.rpc.block_number()

    def chain_id(self) -> int:
        return self.rpc.chain_id()

    def registry(self, name: str, max_age: float = 30.0) -> dict | None:
        """Registry facts by name, None when it does not exist; cached."""
        cached = self._registry_cache.get(name)
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]
        try:
            raw = self.rpc.eth_call(pc.PRECOMPILE_ADDRESS, pc.build_registries_query(name=name))
            reg = pc.decode_registries_result(raw)[0][0]
            value = {
                "id": reg.id,
                "name": reg.name,
                "creator": reg.creator,
                "created_at": reg.created_at,
                "description": reg.description,
                "metadata": reg.metadata,
            }
        except RpcError as err:
            if not _is_keyed_miss(err):
                raise
            value = None
        self._registry_cache[name] = (time.monotonic(), value)
        return value

    def keyed_record(
        self, registry: str, checksum: str, block: str = "latest", index: int = 0
    ) -> pc.Record | None:
        """Latest (or a specific version of) a record, None on keyed miss."""
        query = pc.build_records_query(registry=registry, checksum=checksum, index=index)
        try:
            raw = self.rpc.eth_call(pc.PRECOMPILE_ADDRESS, query, block=block)
        except RpcError as err:
            if _is_keyed_miss(err):
                return None
            raise
        records, _ = pc.decode_records_result(raw)
        return records[0] if records else None

    def estimate(self, from_addr: str, calldata: bytes) -> dict:
        """eth_estimateGas as a permission probe: deny-by-default writes mean
        a clean estimate implies this address may send the call."""
        try:
            gas = self.rpc.estimate_gas(from_addr, pc.PRECOMPILE_ADDRESS, calldata)
            return {"ok": True, "gas": gas}
        except RpcError as err:
            message = err.message or str(err)
            if "unauthorized" in message.lower():
                kind = "unauthorized"
            elif _is_keyed_miss(err):
                kind = "registry-missing"
            else:
                kind = "other"
            return {"ok": False, "kind": kind, "message": message}

    def transaction(self, tx_hash: str) -> tuple[dict | None, dict | None, dict | None]:
        rpc = self.rpc
        tx = rpc.call("eth_getTransactionByHash", [tx_hash])
        if tx is None:
            return None, None, None
        receipt = rpc.get_transaction_receipt(tx_hash)
        block = None
        if tx.get("blockNumber"):
            block = rpc.call("eth_getBlockByNumber", [tx["blockNumber"], False])
        return tx, receipt, block


# =====================================================================
# Calldata decoding (the readable view Blockscout's UTF-8 mode is not)
# =====================================================================


def _label_value(entry: dict, value: Any) -> Any:
    kind = entry["type"]
    if kind.startswith("tuple") and kind.endswith("[]"):
        element = dict(entry, type=kind[:-2])
        return [_label_value(element, v) for v in value]
    if kind.startswith("tuple"):
        return {
            c["name"] or f"field{i}": _label_value(c, v)
            for i, (c, v) in enumerate(zip(entry["components"], value))
        }
    if kind == "bytes":
        return "0x" + value.hex() if isinstance(value, (bytes, bytearray)) else value
    return value


def decode_call(data: bytes) -> dict | None:
    """Decode anchoring-precompile calldata into named, plaintext fields."""
    if len(data) < 4:
        return None
    selector = "0x" + data[:4].hex()
    fn_name = next((n for n, s in pc.SELECTORS.items() if s == selector), None)
    if fn_name is None:
        return {"selector": selector, "function": None}
    fn = pc._FUNCTIONS[fn_name]
    try:
        values = abi.decode_values(fn["inputs"], data[4:])
    except (ValueError, IndexError, UnicodeDecodeError):
        return {"selector": selector, "function": fn_name, "error": "calldata does not decode against the vendored ABI"}
    args = {
        inp["name"] or f"arg{i}": _label_value(inp, v)
        for i, (inp, v) in enumerate(zip(fn["inputs"], values))
    }
    decoded: dict[str, Any] = {"selector": selector, "function": fn_name, "args": args}
    if fn_name == "addRecord":
        record = args.get("record", {})
        metadata = record.get("metadata")
        decoded["metadata_json"] = _try_json(metadata)
    if fn_name == "addRegistry":
        decoded["metadata_json"] = _try_json(args.get("metadata"))
    return decoded


def _try_json(raw: Any) -> Any:
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# =====================================================================
# Filing-time receipt (chain reads pinned to one block)
# =====================================================================


class ReceiptTooLarge(WebAppError):
    pass


def build_receipt(
    *,
    document_sha256: str,
    checked_at_block: int,
    registries: list[dict],
    results: list[dict],
    agent: dict,
    timestamp: str,
    chain_id: int = TESTNET_CHAIN_ID,
) -> tuple[str, list[str]]:
    """Serialize the draft receipt, applying the deterministic compaction
    ladder until it fits the measured 2048 B metadata cap.

    Result entry keys (compact by design, documented in docs/web-demo.md):
    c=canonical, w=as_written (omitted when equal to c), g=registry (int =
    index into the receipt's registries table; string = registry outside
    pilot coverage), s=status char (V/N/C/A/U), n=name_check (m/x; unknown
    omitted), k=cluster id, o=occurrence count (omitted when 1).

    Ladder: (1) drop w everywhere; (2) collapse VERIFIED+match entries
    into a top-level verified_omitted count; (3) give up (chunked receipts
    are Phase 4 task 4.3).
    """
    compactions: list[str] = []

    def serialize(entries: list[dict], verified_omitted: int) -> str:
        obj: dict[str, Any] = {
            "agent": agent,
            "chain_id": chain_id,
            "checked_at_block": checked_at_block,
            "document_sha256": document_sha256,
            "normalizer_version": NORMALIZER_VERSION,
            "registries": registries,
            "results": entries,
            "schema": RECEIPT_SCHEMA,
            "timestamp": timestamp,
        }
        if verified_omitted:
            obj["verified_omitted"] = verified_omitted
        return compact_json(obj)

    entries = [dict(e) for e in results]
    serialized = serialize(entries, 0)
    if len(serialized.encode("utf-8")) <= METADATA_CAP:
        return serialized, compactions

    compactions.append("dropped as-written variants (w)")
    for e in entries:
        e.pop("w", None)
    serialized = serialize(entries, 0)
    if len(serialized.encode("utf-8")) <= METADATA_CAP:
        return serialized, compactions

    keep = [e for e in entries if not (e["s"] == "V" and e.get("n") != "x")]
    omitted = len(entries) - len(keep)
    compactions.append(f"collapsed {omitted} verified results into verified_omitted")
    serialized = serialize(keep, omitted)
    if len(serialized.encode("utf-8")) <= METADATA_CAP:
        return serialized, compactions

    raise ReceiptTooLarge(
        "the receipt does not fit the 2048-byte on-chain metadata cap even "
        "after compaction; chunked receipts arrive with Phase 4"
    )


class ReceiptService:
    def __init__(self, gateway: ChainGateway):
        self.gateway = gateway

    # --- prepare ---

    def prepare(self, payload: dict) -> dict:
        sha = str(payload.get("document_sha256", "")).lower()
        if not _SHA256_RE.match(sha):
            raise WebAppError("document_sha256 must be 64 lowercase hex characters")
        agent_addr = payload.get("agent", {}).get("address", "")
        if not _ADDRESS_RE.match(agent_addr or ""):
            raise WebAppError("agent.address must be a 0x-prefixed 20-byte address")
        agent: dict[str, Any] = {"address": agent_addr.lower()}
        kya = _clean_str(payload.get("agent", {}).get("kya_id"), 120)
        if kya:
            agent["kya_id"] = kya

        raw_entries = payload.get("results")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise WebAppError("results must be a non-empty list (run a check first)")
        if len(raw_entries) > MAX_RECEIPT_ENTRIES:
            raise WebAppError(f"too many results (max {MAX_RECEIPT_ENTRIES})")

        registries_table: list[dict] = []
        registry_index: dict[str, int] = {}
        head = self.gateway.head_block()
        block_tag = hex(head)
        for name in COURT_REGISTRIES:
            reg = self.gateway.registry(name)
            if reg is not None:
                registry_index[name] = len(registries_table)
                registries_table.append({"head_block": head, "id": reg["id"], "name": name})

        results: list[dict] = []
        detail: list[dict] = []
        for raw in raw_entries:
            if not isinstance(raw, dict):
                raise WebAppError("each result must be an object")
            registry = _clean_str(raw.get("registry"), 64)
            canonical = _clean_str(raw.get("canonical"), 64)
            as_written = _clean_str(raw.get("as_written"), 200)
            plaintiff = _clean_str(raw.get("plaintiff"), 200)
            defendant = _clean_str(raw.get("defendant"), 200)
            occurrences = raw.get("occurrences")
            occurrences = occurrences if isinstance(occurrences, int) and 1 <= occurrences <= 10000 else 1
            claimed = str(raw.get("status", ""))

            entry: dict[str, Any] = {}
            row: dict[str, Any] = {
                "registry": registry,
                "canonical": canonical,
                "as_written": as_written,
                "local_status": claimed,
            }
            if canonical and registry in registry_index:
                # The receipt path: a live keyed read pinned at `head`.
                record = self.gateway.keyed_record(registry, canonical, block=block_tag)
                if record is not None:
                    status = VERIFIED
                    names = _record_names(record.metadata)
                    check = name_check(plaintiff, defendant, names)
                    cluster = _record_cluster(record.metadata)
                    if cluster is not None:
                        entry["k"] = cluster
                    if check == "match":
                        entry["n"] = "m"
                    elif check == "mismatch":
                        entry["n"] = "x"
                    row["name_check"] = check
                else:
                    status = NOT_FOUND
                entry["g"] = registry_index[registry]
                entry["c"] = canonical
            elif canonical and registry:
                status = NOT_COVERED
                entry["g"] = registry
                entry["c"] = canonical
            elif claimed == AMBIGUOUS and (canonical or as_written):
                status = AMBIGUOUS
                if canonical:
                    entry["c"] = canonical
            else:
                status = UNPARSEABLE
            entry["s"] = STATUS_CHARS[status]
            if as_written and as_written != canonical:
                entry["w"] = as_written
            if occurrences > 1:
                entry["o"] = occurrences
            results.append(entry)
            row["chain_status"] = status
            detail.append(row)

        timestamp = _utc_now()
        receipt_json, compactions = build_receipt(
            document_sha256=sha,
            checked_at_block=head,
            registries=registries_table,
            results=results,
            agent=agent,
            timestamp=timestamp,
        )

        calldata = pc.build_add_record(
            registry=RECEIPTS_REGISTRY,
            uri=RECEIPT_URI,
            checksum=sha,
            checksum_algo="sha256",
            metadata=receipt_json,
        )
        receipts_reg = self.gateway.registry(RECEIPTS_REGISTRY)
        response: dict[str, Any] = {
            "receipt": {
                "schema": RECEIPT_SCHEMA,
                "json": receipt_json,
                "bytes": len(receipt_json.encode("utf-8")),
                "cap": METADATA_CAP,
                "compactions": compactions,
                "timestamp": timestamp,
            },
            "chain": {
                "chain_id": TESTNET_CHAIN_ID,
                "checked_at_block": head,
                "registries": registries_table,
            },
            "results": detail,
            "tx": {
                "to": pc.PRECOMPILE_ADDRESS,
                "data": "0x" + calldata.hex(),
                "value": "0x0",
            },
            "receipts_registry": {"exists": receipts_reg is not None}
            | ({"id": receipts_reg["id"], "creator": receipts_reg["creator"]} if receipts_reg else {}),
        }
        if receipts_reg is not None:
            response["write_probe"] = self.gateway.estimate(agent_addr, calldata)
        else:
            response["setup"] = self.registry_setup(agent_addr)
        return response

    def registry_setup(self, from_addr: str | None = None) -> dict:
        """Everything a wallet needs to create receipts-v1 with the LOCKED
        creation strings (schema doc section 2): shown only while the
        registry does not exist; the creator becomes its admin."""
        calldata = pc.build_add_registry(
            RECEIPTS_REGISTRY, RECEIPTS_REGISTRY_DESCRIPTION, RECEIPTS_REGISTRY_METADATA
        )
        setup = {
            "registry": RECEIPTS_REGISTRY,
            "description": RECEIPTS_REGISTRY_DESCRIPTION,
            "metadata": RECEIPTS_REGISTRY_METADATA,
            "tx": {"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + calldata.hex(), "value": "0x0"},
            "note": (
                "receipts-v1 does not exist on this chain yet. Creating it is a "
                "one-time setup transaction; the creating wallet becomes its admin."
            ),
        }
        if from_addr and _ADDRESS_RE.match(from_addr):
            setup["probe"] = self.gateway.estimate(from_addr, calldata)
        return setup

    # --- lookup (free, read-only) ---

    def lookup(self, sha256: str) -> dict:
        sha = sha256.strip().lower()
        if not _SHA256_RE.match(sha):
            raise WebAppError("expected a 64-character hex SHA-256")
        registry = self.gateway.registry(RECEIPTS_REGISTRY)
        head = self.gateway.head_block()
        if registry is None:
            return {
                "sha256": sha,
                "registry_exists": False,
                "found": False,
                "head_block": head,
                "note": "the receipts-v1 registry has not been created on this chain yet",
            }
        query = pc.build_records_query(registry=RECEIPTS_REGISTRY, checksum=sha)
        record = self.gateway.keyed_record(RECEIPTS_REGISTRY, sha)
        versions: list[dict] = []
        if record is not None:
            versions.append(_render_receipt_record(record))
            for index in range(1, record.index):  # earlier versions, capped
                if len(versions) >= 10:
                    break
                try:
                    earlier = self.gateway.keyed_record(RECEIPTS_REGISTRY, sha, index=index)
                except RpcError:
                    break
                if earlier is not None:
                    versions.append(_render_receipt_record(earlier))
            versions.sort(key=lambda v: v["index"])
        return {
            "sha256": sha,
            "registry_exists": True,
            "registry": {"id": registry["id"], "creator": registry["creator"]},
            "found": record is not None,
            "head_block": head,
            "versions": versions,
            "proof": {
                "note": "replayable against any NVNM testnet RPC, no trust in this server required",
                "request": {
                    "method": "eth_call",
                    "params": [
                        {"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + query.hex()},
                        "latest",
                    ],
                },
            },
        }


def _record_names(metadata: str) -> list[str]:
    parsed = _try_json(metadata)
    if not isinstance(parsed, dict):
        return []
    if isinstance(parsed.get("cases"), list):
        return [c.get("name", "") for c in parsed["cases"] if isinstance(c, dict)]
    name = parsed.get("name")
    return [name] if isinstance(name, str) else []


def _record_cluster(metadata: str) -> int | None:
    parsed = _try_json(metadata)
    if isinstance(parsed, dict) and isinstance(parsed.get("cluster"), int):
        return parsed["cluster"]
    return None


def _render_receipt_record(record: pc.Record) -> dict:
    return {
        "index": record.index,
        "is_latest": record.is_latest,
        "record_id": record.record_id,
        "chain_timestamp": record.timestamp,
        "status": record.status,
        "uri": record.uri,
        "checksum_algo": record.checksum_algo,
        "metadata_bytes": len(record.metadata.encode("utf-8")),
        "receipt": _try_json(record.metadata),
        "metadata_raw": record.metadata,
    }


# =====================================================================
# Transaction inspector
# =====================================================================


class TxService:
    def __init__(self, gateway: ChainGateway):
        self.gateway = gateway

    def inspect(self, tx_hash: str) -> dict:
        tx_hash = tx_hash.strip().lower()
        if not _TXHASH_RE.match(tx_hash):
            raise WebAppError("expected a 0x-prefixed 32-byte transaction hash")
        tx, receipt, block = self.gateway.transaction(tx_hash)
        if tx is None:
            return {"hash": tx_hash, "found": False}
        data = bytes.fromhex(tx.get("input", "0x")[2:] or "")
        decoded = decode_call(data) if data else None
        block_time = None
        if block and block.get("timestamp"):
            block_time = datetime.fromtimestamp(
                int(block["timestamp"], 16), tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "hash": tx_hash,
            "found": True,
            "pending": receipt is None,
            "success": (int(receipt["status"], 16) == 1) if receipt and receipt.get("status") else None,
            "from": tx.get("from"),
            "to": tx.get("to"),
            "block": int(tx["blockNumber"], 16) if tx.get("blockNumber") else None,
            "block_time": block_time,
            "gas_used": int(receipt["gasUsed"], 16) if receipt and receipt.get("gasUsed") else None,
            "gas_price_gwei": round(int(tx["gasPrice"], 16) / 1e9, 3) if tx.get("gasPrice") else None,
            "is_anchoring_precompile": (tx.get("to") or "").lower() == pc.PRECOMPILE_ADDRESS.lower(),
            "decoded": decoded,
            "explorer": f"{TESTNET_EXPLORER}/tx/{tx_hash}",
        }


# =====================================================================
# Status
# =====================================================================


class StatusService:
    def __init__(self, gateway: ChainGateway, index: LocalIndex, data_dir: Path):
        self.gateway = gateway
        self.index = index
        self.data_dir = Path(data_dir)
        self._cache: tuple[float, dict] | None = None

    def status(self) -> dict:
        if self._cache and time.monotonic() - self._cache[0] < 10:
            return self._cache[1]
        chain: dict[str, Any] = {"rpc_ok": False}
        registries: dict[str, Any] = {}
        try:
            chain = {
                "rpc_ok": True,
                "chain_id": self.gateway.chain_id(),
                "expected_chain_id": TESTNET_CHAIN_ID,
                "head_block": self.gateway.head_block(),
            }
            chain["chain_id_ok"] = chain["chain_id"] == TESTNET_CHAIN_ID
            for name in (*COURT_REGISTRIES, RECEIPTS_REGISTRY):
                reg = self.gateway.registry(name)
                registries[name] = (
                    {"exists": True, "id": reg["id"], "created_at": reg["created_at"]}
                    if reg
                    else {"exists": False}
                )
        except (RpcError, OSError, TimeoutError) as err:
            chain["error"] = str(err)
        result = {
            "app": {"name": "nvnm-cite web demo", "version": WEBAPP_VERSION, "network": "NVNM testnet (nvnm-testnet-1)"},
            "chain": chain,
            "registries": registries,
            "index": {"registries": self.index.coverage()},
            "loader": {"bulk_load_running": self._loader_running()},
            "versions": {
                "normalizer": NORMALIZER_VERSION,
                "citation_spec": CANONICAL_SPEC,
                "receipt_schema": RECEIPT_SCHEMA,
                "record_schema": "nvnm-cite-record/v1",
            },
            "constants": {
                "precompile": pc.PRECOMPILE_ADDRESS,
                "chain_id": TESTNET_CHAIN_ID,
                "explorer": TESTNET_EXPLORER,
                "receipts_registry": RECEIPTS_REGISTRY,
                "receipt_uri": RECEIPT_URI,
            },
            "attribution": (
                "Case data: CourtListener bulk data, Free Law Project "
                "(courtlistener.com). Citation parsing: eyecite / reporters-db / "
                "courts-db, Free Law Project."
            ),
        }
        self._cache = (time.monotonic(), result)
        return result

    def _loader_running(self) -> bool:
        pid_file = self.data_dir / "load.pid"
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False
