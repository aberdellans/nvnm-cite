"""Web app services: check, receipt, lookup, decode, status.

Trust boundaries, restated where the code lives:

- ``CheckService`` (drafting time): a thin wrapper over the shared
  verifier core (``nvnm_cite.verifier``), which reads NVNM Chain LIVE via
  keyed ``records()`` reads (item 0, DECISIONS 2026-06-13). It never
  persists the document; bytes live in this call frame and are garbage the
  moment the report is returned. The same core powers ``nvnm-cite check``.
- ``ReceiptService`` (filing time): delegates to the LOCKED receipts layer
  (``nvnm_cite.receipts``) — ``prepare_anchor`` pins the check to one block
  and assembles the minimal receipt + exact calldata, so the webapp receipt
  is byte-identical to the ``nvnm-cite anchor`` CLI's. The server prepares
  calldata with the golden-tested codec but signs nothing; the user's
  wallet does. Lookup is a keyed ``records(registry_id, hash)`` read.
- Receipt object: the LOCKED receipt v1 (``nvnm-cite-receipt/v1``,
  DECISIONS 2026-06-15) — MINIMAL and NON-ENUMERATING (document SHA-256 +
  provenance + a non-identifying status tally, never the list of cited
  cases; items 2/2b). Receipts live in a PER-FIRM-PER-CASE registry owned
  by the filing party's wallet (item 3), not a global one.

Anchoring v1.2.0 (2026-07-31): registry names are NON-UNIQUE; every chain
call keys on the numeric registryId. The discovery line on a filing carries
``registry #<id>``; a NEW registry's id exists only after its addRegistry
tx confirms (recovered from the AddRegistry event via /api/tx), so the
record flow is two-step: setup tx -> confirmed id -> re-prepare -> anchor.

Status vocabulary is the locked five-status enum (DECISIONS 2026-06-10):
VERIFIED / NOT_FOUND / NOT_COVERED / AMBIGUOUS_JURISDICTION /
UNPARSEABLE, plus the orthogonal name_check field.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from nvnm_cite.chain import abi
from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.bech32 import eth_to_bech32
from nvnm_cite.chain.registrymap import RegistryManifest
from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.config import Network
from nvnm_cite.loader.records import METADATA_CAP
from nvnm_cite.normalizer import CANONICAL_SPEC, NORMALIZER_VERSION
from nvnm_cite.receipts.anchor import prepare_anchor, registry_line
from nvnm_cite.receipts.schema import (
    RECEIPT_SCHEMA,
    RECEIPT_URI,
    ReceiptError,
    receipt_registry_name,
)
from nvnm_cite.verifier.check import CheckError, check_document
from nvnm_cite.verifier.extract import ExtractError, extract_text
from nvnm_cite.verifier.resolver import Resolver
from nvnm_cite.webapp.localindex import LocalIndex

WEBAPP_VERSION = "0.2.0"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TXHASH_RE = re.compile(r"^0x[0-9a-f]{64}$")
# Receipt registry names are <firm-slug>--<case-slug>, lowercase [a-z0-9-],
# <=64 B (receipts/schema.py::receipt_registry_name). Used only by the
# legacy name fallback in lookup; the canonical reference is the #id.
_REGISTRY_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_REGISTRY_REF_RE = re.compile(r"registry\s+#(\d+)", re.IGNORECASE)


class WebAppError(ValueError):
    """User-facing request error; http_status picks the response code."""

    def __init__(self, message: str, http_status: int = 422):
        super().__init__(message)
        self.http_status = http_status


def parse_registry_ref(ref: str) -> int | None:
    """A registry reference: '4711', '#4711', or a pasted discovery line."""
    token = (ref or "").strip()
    if token.startswith("#"):
        token = token[1:]
    if token.isdigit():
        return int(token)
    m = _REGISTRY_REF_RE.search(ref or "")
    return int(m.group(1)) if m else None


# =====================================================================
# Drafting-time check (delegates to the shared verifier core)
# =====================================================================


class CheckService:
    """Drafting-time citation check. A thin wrapper over the shared verifier
    core (``nvnm_cite.verifier``), which reads NVNM Chain LIVE via keyed
    ``records()`` reads (item 0, DECISIONS 2026-06-13) — the same core powers
    ``nvnm-cite check``. Coverage is the pinned per-network manifest's
    name -> id map. Transport / RPC failures propagate out of the core and
    surface to the client (a 502) rather than masquerading as NOT_FOUND."""

    def __init__(self, resolver: Resolver, registry_ids: Mapping[str, int]):
        self.resolver = resolver
        self.registry_ids = registry_ids

    def check(self, data: bytes, filename: str) -> dict:
        try:
            return check_document(
                data, filename, self.resolver, registry_ids=self.registry_ids
            )
        except CheckError as exc:
            raise WebAppError(str(exc), exc.http_status) from exc


# =====================================================================
# Chain gateway (all RPC in one place)
# =====================================================================


class ChainGateway:
    def __init__(self, rpc_factory: Callable[[], EvmRpc]):
        self._rpc_factory = rpc_factory
        self._registry_cache: dict[int, tuple[float, dict | None]] = {}
        self._enumeration_cache: tuple[float, list[dict]] | None = None

    @property
    def rpc(self) -> EvmRpc:
        return self._rpc_factory()

    @property
    def rpc_factory(self) -> Callable[[], EvmRpc]:
        """The underlying factory, for handing to the receipts layer
        (``prepare_anchor`` builds its own reader/resolver from it)."""
        return self._rpc_factory

    def head_block(self) -> int:
        return self.rpc.block_number()

    def chain_id(self) -> int:
        return self.rpc.chain_id()

    def gas_price(self) -> int:
        return self.rpc.gas_price()

    def registry(self, registry_id: int, max_age: float = 30.0) -> dict | None:
        """Registry facts by id, None when it does not exist; cached."""
        cached = self._registry_cache.get(registry_id)
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]
        try:
            raw = self.rpc.eth_call(
                pc.PRECOMPILE_ADDRESS, pc.build_registries_query(registry_id=registry_id)
            )
            rows = pc.decode_registries_result(raw)[0]
            value = None
            if rows:
                reg = rows[0]
                value = {
                    "id": reg.id,
                    "name": reg.name,
                    "creator": reg.creator,
                    "created_at": reg.created_at,
                    "description": reg.description,
                    "metadata": reg.metadata,
                }
        except RpcError as err:
            if not pc.is_keyed_miss(err):
                raise
            value = None
        self._registry_cache[registry_id] = (time.monotonic(), value)
        return value

    def all_registries(self, max_age: float = 60.0) -> list[dict]:
        """A cached full enumeration snapshot (v1.2.0 has no name filter, so
        name/creator searches must enumerate — ~13 pages today). Serves the
        legacy-name lookup fallback and the creator listing."""
        cached = self._enumeration_cache
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]
        rpc = self.rpc
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
            out.extend(
                {
                    "id": r.id,
                    "name": r.name,
                    "creator": r.creator,
                    "created_at": r.created_at,
                }
                for r in rows
            )
            offset += len(rows)
            if len(rows) < 200:
                break
        self._enumeration_cache = (time.monotonic(), out)
        return out

    def find_by_name(self, name: str) -> list[dict]:
        """ALL registries with this exact name (names are not unique)."""
        return [r for r in self.all_registries() if r["name"] == name]

    def registries_by_creator(self, creator_bech32: str) -> list[dict]:
        return [r for r in self.all_registries() if r["creator"] == creator_bech32]

    def keyed_record(
        self, registry_id: int, checksum: str, block: str = "latest", index: int = 0
    ) -> pc.Record | None:
        """Latest (or a specific version of) a record, None on keyed miss."""
        query = pc.build_records_query(
            registry_id=registry_id, checksum=checksum, index=index
        )
        try:
            raw = self.rpc.eth_call(pc.PRECOMPILE_ADDRESS, query, block=block)
        except RpcError as err:
            if pc.is_keyed_miss(err):
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
            elif pc.is_keyed_miss(err):
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


class ReceiptService:
    """Filing-time receipts, delegating to the LOCKED receipts layer.

    ``prepare`` re-checks the uploaded document pinned to one block and
    assembles the minimal receipt via ``receipts.anchor.prepare_anchor`` —
    byte-identical to ``nvnm-cite anchor``'s. The receipt lives in a
    PER-FIRM-PER-CASE registry named ``<firm>--<case>`` and owned by the
    filing wallet (item 3). Under v1.2.0 the flow is id-keyed:

    - existing registry: resolved by an explicit ``registry_id`` (the
      client's X-Registry-Id) or by a creator+name search; multiple
      same-name matches are SURFACED, never auto-picked;
    - new registry: ``prepare`` returns only the setup (addRegistry) tx —
      the record calldata cannot exist before the chain assigns the id.
      After the setup tx confirms, /api/tx decodes the AddRegistry event
      and the client re-prepares with the id.

    ``lookup`` is a keyed ``records(registry_id, hash)`` read against the
    #id printed on the filing. The server signs nothing; the user's
    wallet does.
    """

    def __init__(self, gateway: ChainGateway, network: Network, registry_ids: Mapping[str, int]):
        self.gateway = gateway
        self.network = network
        self.registry_ids = registry_ids

    # --- prepare (read-only: pins a re-check, builds calldata, sends nothing) ---

    def prepare(
        self,
        data: bytes,
        filename: str,
        *,
        firm: str,
        case: str,
        agent_address: str,
        registry_id: int | None = None,
    ) -> dict:
        if not _ADDRESS_RE.match(agent_address or ""):
            raise WebAppError(
                "connect a wallet first — the receipt records the attesting 0x address"
            )
        firm = (firm or "").strip()
        case = (case or "").strip()
        if not firm or not case:
            raise WebAppError(
                "name the filer/firm and the case/matter — together they name the "
                "per-case receipt registry your wallet will own"
            )

        # Resolve the target registry id when the client did not pin one:
        # search this wallet's own registries for the derived name. Names are
        # NOT unique on chain — multiple matches are returned to the client
        # to choose from, never silently resolved.
        if registry_id is None:
            try:
                derived = receipt_registry_name(firm, case)
            except ReceiptError as exc:
                raise WebAppError(str(exc)) from exc
            matches = [
                r
                for r in self.gateway.registries_by_creator(eth_to_bech32(agent_address))
                if r["name"] == derived
            ]
            if len(matches) == 1:
                registry_id = matches[0]["id"]
            elif len(matches) > 1:
                return {
                    "ambiguous": True,
                    "registry": derived,
                    "candidates": matches,
                    "note": (
                        f"this wallet created {len(matches)} registries named "
                        f"{derived!r}; pick the #id printed on this matter's filings "
                        "and re-prepare with it"
                    ),
                }

        try:
            plan = prepare_anchor(
                data,
                filename,
                firm=firm,
                case=case,
                agent_address=agent_address,
                chain_id=self.network.chain_id,
                registry_id=registry_id,
                rpc_factory=self.gateway.rpc_factory,
                registry_ids=self.registry_ids,
            )
        except ReceiptError as exc:
            raise WebAppError(str(exc)) from exc
        except CheckError as exc:
            raise WebAppError(str(exc), exc.http_status) from exc

        response: dict[str, Any] = {
            "registry": plan.registry,
            "registry_id": plan.registry_id,
            "registry_exists": plan.registry_exists,
            "name_matches": plan.name_matches,
            "already_anchored": plan.already_anchored,
            "agent": {"address": agent_address.lower()},
            "document_sha256": plan.document_sha256,
            "checked_at_block": plan.checked_at_block,
            "registries_read": plan.registries_read,
            "receipt": {
                "schema": RECEIPT_SCHEMA,
                "json": plan.receipt_json,
                "object": plan.receipt,
                "summary": plan.receipt["summary"],
                "timestamp": plan.receipt["timestamp"],
                "bytes": len(plan.receipt_json.encode("utf-8")),
                "cap": METADATA_CAP,
            },
            "chain": {
                "chain_id": self.network.chain_id,
                "checked_at_block": plan.checked_at_block,
            },
            "writes": plan.writes,
        }
        if plan.registry_id is not None and plan.record_calldata is not None:
            response["registry_line"] = registry_line(
                plan.registry_id, plan.registry, self.network.chain_id
            )
            # Discovery ordering (item 3): the registry line (with its #id)
            # must be ON the filing before its bytes are anchored, or
            # verification of the filed document misses. Re-extracts the text
            # (the plan does not carry it); the UI warns but never blocks.
            response["registry_line_found"] = _registry_line_found(
                data, filename, plan.registry_id, plan.registry
            )
            response["tx"] = {
                "to": pc.PRECOMPILE_ADDRESS,
                "data": "0x" + plan.record_calldata.hex(),
                "value": "0x0",
            }
            response["write_probe"] = self.gateway.estimate(
                agent_address, plan.record_calldata
            )
        if plan.create_registry is not None and plan.create_calldata is not None:
            response["setup"] = dict(
                plan.create_registry,
                tx={
                    "to": pc.PRECOMPILE_ADDRESS,
                    "data": "0x" + plan.create_calldata.hex(),
                    "value": "0x0",
                },
                note=(
                    f"no {plan.registry} registry owned by this wallet exists on "
                    "this chain yet. Creating it is a one-time setup transaction; "
                    "the creating wallet becomes its admin — self-sovereign, no "
                    "NVNM gatekeeper. The chain assigns its #id on confirmation; "
                    "that id goes on the filing."
                ),
                probe=self.gateway.estimate(agent_address, plan.create_calldata),
            )
        return response

    # --- creator listing (read-only; the record tab's registry picker) ---

    def registries_for_creator(self, address: str) -> dict:
        if not _ADDRESS_RE.match(address or ""):
            raise WebAppError("expected a 0x wallet address")
        creator = eth_to_bech32(address)
        registries = self.gateway.registries_by_creator(creator)
        return {
            "creator": {"address": address.lower(), "bech32": creator},
            "registries": registries,
        }

    # --- lookup (free, read-only; registry ref + hash) ---

    def lookup(self, registry_ref: str, sha256: str) -> dict:
        """Keyed ``records(registry_id, hash)`` read. The #id comes from the
        filing's discovery line; the hash is computed in the visitor's browser
        (item 4), so the document itself never reaches us here. A legacy NAME
        is accepted as a fallback: it is matched against a cached enumeration,
        and multiple same-name matches are surfaced for the visitor to pick —
        never silently resolved."""
        sha = sha256.strip().lower()
        if not _SHA256_RE.match(sha):
            raise WebAppError("expected a 64-character hex SHA-256")

        ref = (registry_ref or "").strip()
        registry_id = parse_registry_ref(ref)
        legacy_note = None
        if registry_id is None:
            name = ref.lower()
            if not _REGISTRY_NAME_RE.match(name):
                raise WebAppError(
                    "expected the registry #id from the filing's verification line "
                    "(e.g. '#4711' or the whole line), or a legacy registry name"
                )
            matches = self.gateway.find_by_name(name)
            if not matches:
                return {
                    "registry": name,
                    "sha256": sha,
                    "registry_exists": False,
                    "found": False,
                    "head_block": self.gateway.head_block(),
                    "note": (
                        f"no registry named {name!r} exists on this chain — check "
                        "the verification line printed on the filing (it carries "
                        "the registry #id)"
                    ),
                }
            if len(matches) > 1:
                return {
                    "registry": name,
                    "sha256": sha,
                    "ambiguous": True,
                    "candidates": matches,
                    "note": (
                        f"{len(matches)} registries are named {name!r} (names are "
                        "not unique on this chain). Use the #id from the filing's "
                        "verification line."
                    ),
                }
            registry_id = matches[0]["id"]
            legacy_note = (
                f"resolved legacy name {name!r} to registry #{registry_id} by "
                "enumeration; filings should carry the #id"
            )

        facts = self.gateway.registry(registry_id)
        head = self.gateway.head_block()
        if facts is None:
            return {
                "registry_id": registry_id,
                "sha256": sha,
                "registry_exists": False,
                "found": False,
                "head_block": head,
                "note": (
                    f"registry #{registry_id} does not exist on this chain — check "
                    "the verification line printed on the filing"
                ),
            }
        query = pc.build_records_query(registry_id=registry_id, checksum=sha)
        record = self.gateway.keyed_record(registry_id, sha)
        versions: list[dict] = []
        if record is not None:
            versions.append(_render_receipt_record(record))
            for index in range(1, record.index):  # earlier versions, capped
                if len(versions) >= 10:
                    break
                try:
                    earlier = self.gateway.keyed_record(registry_id, sha, index=index)
                except RpcError:
                    break
                if earlier is not None:
                    versions.append(_render_receipt_record(earlier))
            versions.sort(key=lambda v: v["index"])
        result = {
            "registry": facts["name"],
            "registry_id": registry_id,
            "registry_owner": facts["creator"],
            "sha256": sha,
            "registry_exists": True,
            "found": record is not None,
            "head_block": head,
            "versions": versions,
            "proof": {
                "note": (
                    f"replayable against any {self.network.label} RPC, "
                    "no trust in this server required"
                ),
                "request": {
                    "method": "eth_call",
                    "params": [
                        {"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + query.hex()},
                        "latest",
                    ],
                },
            },
        }
        if legacy_note:
            result["note"] = legacy_note
        return result


def _registry_line_found(
    data: bytes, filename: str, registry_id: int, registry_name: str
) -> str:
    """How the document's extracted text references its receipt registry:
    'id' (the canonical '#<id>' is present), 'name' (only the name — a weak
    pointer under non-unique names), or 'none'."""
    try:
        text = extract_text(data, filename).text.lower()
    except ExtractError:
        return "none"
    if f"#{registry_id}" in text:
        return "id"
    if registry_name.lower() in text:
        return "name"
    return "none"


def _render_receipt_record(record: pc.Record) -> dict:
    return {
        "index": record.index,
        "is_latest": record.is_latest,
        "record_id": record.record_id,
        "registry_id": record.registry_id,
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
    def __init__(self, gateway: ChainGateway, network: Network):
        self.gateway = gateway
        self.network = network

    def inspect(self, tx_hash: str) -> dict:
        tx_hash = tx_hash.strip().lower()
        if not _TXHASH_RE.match(tx_hash):
            raise WebAppError("expected a 0x-prefixed 32-byte transaction hash")
        tx, receipt, block = self.gateway.transaction(tx_hash)
        if tx is None:
            return {"hash": tx_hash, "found": False}
        data = bytes.fromhex(tx.get("input", "0x")[2:] or "")
        decoded = decode_call(data) if data else None
        input_preview = None
        if decoded is not None and not decoded.get("function"):
            raw = tx.get("input", "")
            input_preview = raw[:200] + ("…" if len(raw) > 200 else "")
        block_time = None
        if block and block.get("timestamp"):
            block_time = datetime.fromtimestamp(
                int(block["timestamp"], 16), tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Precompile events from the receipt logs: the AddRegistry event is
        # how a newly created receipts registry's #id is recovered, and the
        # AddRecord event carries an anchor's assigned recordId.
        events = pc.decode_event_logs(receipt.get("logs", [])) if receipt else []
        registry_id = next(
            (e["registryId"] for e in events if e["event"] == "AddRegistry"), None
        )
        record_id = next(
            (e["recordId"] for e in events if e["event"] == "AddRecord"), None
        )
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
            "events": events,
            "registry_id": registry_id,
            "record_id": record_id,
            "input_preview": input_preview,
            "explorer": f"{self.network.explorer}/tx/{tx_hash}",
        }


# =====================================================================
# Status
# =====================================================================


class StatusService:
    """Live status for the header + About panel. The probe is lazy (only on
    the first ``/api/status`` after the 10 s cache lapses) and runs through a
    SHORT-timeout gateway (wired in server.py), so a slow or dead RPC fails
    fast and never stalls the page (task 4.5e). Coverage counts come from
    the pinned manifest — never a per-registry probe of 2,114 registries;
    only a couple of sentinel registries are read live."""

    # Live sentinels: pilot-proven registries probed each refresh as a
    # sanity check on the manifest's ids.
    SENTINELS = ("us-scotus", "us-ca11")

    def __init__(
        self,
        gateway: ChainGateway,
        index: LocalIndex,
        data_dir: Path,
        network: Network,
        manifest: RegistryManifest,
        rpc_url: str = "",
        telemetry_enabled: bool = False,
    ):
        self.gateway = gateway
        self.index = index
        self.data_dir = Path(data_dir)
        self.network = network
        self.manifest = manifest
        self.rpc_url = rpc_url
        self.telemetry_enabled = telemetry_enabled
        self._cache: tuple[float, dict] | None = None

    def status(self) -> dict:
        if self._cache and time.monotonic() - self._cache[0] < 10:
            return self._cache[1]
        chain: dict[str, Any] = {"rpc_ok": False}
        registries: dict[str, Any] = {}
        gas_price_gwei: float | None = None
        try:
            chain = {
                "rpc_ok": True,
                "chain_id": self.gateway.chain_id(),
                "expected_chain_id": self.network.chain_id,
                "head_block": self.gateway.head_block(),
            }
            chain["chain_id_ok"] = chain["chain_id"] == self.network.chain_id
            gas_price_gwei = round(self.gateway.gas_price() / 1e9, 3)
            # Sentinel probes only — coverage counts come from the manifest.
            for name in self.SENTINELS:
                rid = self.manifest.registry_id(name)
                if rid is None:
                    continue
                reg = self.gateway.registry(rid)
                registries[name] = (
                    {
                        "exists": True,
                        "id": reg["id"],
                        "created_at": reg["created_at"],
                        "name_matches_manifest": reg["name"] == name,
                    }
                    if reg
                    else {"exists": False, "id": rid}
                )
        except (RpcError, OSError, TimeoutError) as err:
            chain["error"] = str(err)
        result = {
            "app": {
                "name": "nvnm-cite",
                "version": WEBAPP_VERSION,
                "network": self.network.label,
            },
            "network": {
                "key": self.network.key,
                "label": self.network.label,
                "chain_id": self.network.chain_id,
                "chain_id_hex": hex(self.network.chain_id),
                "cosmos_chain_id": self.network.cosmos_chain_id,
                "rpc_urls": [self.rpc_url or self.network.rpc_default],
                "public_rpc": self.network.rpc_default,
                "explorer": self.network.explorer,
                "gas_token": {
                    "name": self.network.gas_token,
                    "symbol": self.network.gas_token,
                    "decimals": 18,
                },
                "gas_price_gwei": gas_price_gwei,
            },
            "chain": chain,
            "registries": registries,
            "coverage": {
                "count": len(self.manifest.ids),
                "source": "pinned registry manifest (creator-verified name->id map)",
                "creator": self.manifest.creator,
                "generated_at": self.manifest.generated_at,
                "generated_at_block": self.manifest.generated_at_block,
            },
            "index": {"registries": self.index.coverage()},
            "loader": {"bulk_load_running": self._loader_running()},
            # Opt-in aggregate, by-citation lookup analytics (item 2b). When on,
            # the privacy copy discloses it; never tied to a document or identity.
            "telemetry": {"enabled": self.telemetry_enabled},
            "versions": {
                "normalizer": NORMALIZER_VERSION,
                "citation_spec": CANONICAL_SPEC,
                "receipt_schema": RECEIPT_SCHEMA,
                "record_schema": "nvnm-cite-record/v1",
            },
            "constants": {
                "precompile": pc.PRECOMPILE_ADDRESS,
                "chain_id": self.network.chain_id,
                "explorer": self.network.explorer,
                "rpc_url": self.rpc_url,
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
