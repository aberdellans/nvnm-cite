"""Web demo services: check, receipt, lookup, decode, status.

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
  wallet does. Lookup is a keyed ``records(registry, hash)`` read.
- Receipt object: the LOCKED receipt v1 (``nvnm-cite-receipt/v1``,
  DECISIONS 2026-06-15) — MINIMAL and NON-ENUMERATING (document SHA-256 +
  provenance + a non-identifying status tally, never the list of cited
  cases; items 2/2b). ~480 B, always under the 2048 B cap, so there is no
  compaction ladder and no chunking. Receipts live in a PER-FIRM-PER-CASE
  registry owned by the filing party's wallet (item 3), not a global one.

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
from typing import Any, Callable

from nvnm_cite.chain import abi
from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.config import TESTNET_CHAIN_ID, TESTNET_EXPLORER
from nvnm_cite.loader.records import METADATA_CAP
from nvnm_cite.normalizer import CANONICAL_SPEC, NORMALIZER_VERSION
from nvnm_cite.receipts.anchor import prepare_anchor
from nvnm_cite.receipts.schema import (
    RECEIPT_SCHEMA,
    RECEIPT_URI,
    ReceiptError,
)
from nvnm_cite.verifier.check import COVERED_REGISTRIES, CheckError, check_document
from nvnm_cite.verifier.resolver import Resolver
from nvnm_cite.webapp.localindex import LocalIndex

WEBAPP_VERSION = "0.1.0"

# Receipts re-check against the same covered court registries the verifier
# core defines; the receipt registry itself is per-firm-per-case (item 3).
COURT_REGISTRIES = COVERED_REGISTRIES

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TXHASH_RE = re.compile(r"^0x[0-9a-f]{64}$")
# Receipt registry names are <firm-slug>--<case-slug>, lowercase [a-z0-9-],
# <=64 B (receipts/schema.py::receipt_registry_name). Court ids (us-scotus)
# match too, which is harmless for a read-only lookup.
_REGISTRY_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class WebAppError(ValueError):
    """User-facing request error; http_status picks the response code."""

    def __init__(self, message: str, http_status: int = 422):
        super().__init__(message)
        self.http_status = http_status


# =====================================================================
# Drafting-time check (delegates to the shared verifier core)
# =====================================================================


class CheckService:
    """Drafting-time citation check. A thin wrapper over the shared verifier
    core (``nvnm_cite.verifier``), which reads NVNM Chain LIVE via keyed
    ``records()`` reads (item 0, DECISIONS 2026-06-13) — the same core powers
    ``nvnm-cite check``. Kept as a class so the server's wiring and the tests
    construct it uniformly. Transport / RPC failures propagate out of the
    core and surface to the client (a 502) rather than masquerading as
    NOT_FOUND."""

    def __init__(self, resolver: Resolver):
        self.resolver = resolver

    def check(self, data: bytes, filename: str) -> dict:
        try:
            return check_document(data, filename, self.resolver)
        except CheckError as exc:
            raise WebAppError(str(exc), exc.http_status) from exc


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

    @property
    def rpc_factory(self) -> Callable[[], EvmRpc]:
        """The underlying factory, for handing to the receipts layer
        (``prepare_anchor`` builds its own reader/resolver from it)."""
        return self._rpc_factory

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
            if not pc.is_keyed_miss(err):
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
    assembles the minimal, non-enumerating receipt + exact calldata via
    ``receipts.anchor.prepare_anchor`` — so the webapp receipt is
    byte-identical to ``nvnm-cite anchor``'s. The receipt lives in a
    PER-FIRM-PER-CASE registry named ``<firm>--<case>`` and owned by the
    filing wallet (item 3); there is no global receipts registry. ``lookup``
    is a keyed ``records(registry, hash)`` read against the registry named on
    the filing. The server signs nothing; the user's wallet does.
    """

    def __init__(self, gateway: ChainGateway):
        self.gateway = gateway

    # --- prepare (read-only: pins a re-check, builds calldata, sends nothing) ---

    def prepare(self, data: bytes, filename: str, *, firm: str, case: str, agent_address: str) -> dict:
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
        try:
            plan = prepare_anchor(
                data,
                filename,
                firm=firm,
                case=case,
                agent_address=agent_address,
                rpc_factory=self.gateway.rpc_factory,
            )
        except ReceiptError as exc:
            raise WebAppError(str(exc)) from exc
        except CheckError as exc:
            raise WebAppError(str(exc), exc.http_status) from exc

        record_tx = {"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + plan.record_calldata.hex(), "value": "0x0"}
        response: dict[str, Any] = {
            "registry": plan.registry,
            "registry_exists": plan.registry_exists,
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
            "chain": {"chain_id": TESTNET_CHAIN_ID, "checked_at_block": plan.checked_at_block},
            "tx": record_tx,
            "writes": plan.writes,
        }
        if plan.create_registry is not None and plan.create_calldata is not None:
            response["setup"] = dict(
                plan.create_registry,
                tx={"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + plan.create_calldata.hex(), "value": "0x0"},
                note=(
                    f"the {plan.registry} registry does not exist on this chain yet. "
                    "Creating it is a one-time setup transaction; the creating wallet "
                    "becomes its admin — self-sovereign, no NVNM gatekeeper."
                ),
                probe=self.gateway.estimate(agent_address, plan.create_calldata),
            )
        else:
            response["write_probe"] = self.gateway.estimate(agent_address, plan.record_calldata)
        return response

    # --- lookup (free, read-only; registry + hash) ---

    def lookup(self, registry: str, sha256: str) -> dict:
        """Keyed ``records(registry, hash)`` read. The registry comes from the
        filing's discovery link; the hash is computed in the visitor's browser
        (item 4), so the document itself never reaches us here."""
        reg_name = (registry or "").strip().lower()
        if not _REGISTRY_NAME_RE.match(reg_name):
            raise WebAppError(
                "expected the receipt registry name from the filing's discovery link "
                "(lowercase letters, digits and hyphens, e.g. firm--case)"
            )
        sha = sha256.strip().lower()
        if not _SHA256_RE.match(sha):
            raise WebAppError("expected a 64-character hex SHA-256")
        facts = self.gateway.registry(reg_name)
        head = self.gateway.head_block()
        if facts is None:
            return {
                "registry": reg_name,
                "sha256": sha,
                "registry_exists": False,
                "found": False,
                "head_block": head,
                "note": (
                    f"no registry named {reg_name!r} exists on this chain — check the "
                    "registry link printed on the filing"
                ),
            }
        query = pc.build_records_query(registry=reg_name, checksum=sha)
        record = self.gateway.keyed_record(reg_name, sha)
        versions: list[dict] = []
        if record is not None:
            versions.append(_render_receipt_record(record))
            for index in range(1, record.index):  # earlier versions, capped
                if len(versions) >= 10:
                    break
                try:
                    earlier = self.gateway.keyed_record(reg_name, sha, index=index)
                except RpcError:
                    break
                if earlier is not None:
                    versions.append(_render_receipt_record(earlier))
            versions.sort(key=lambda v: v["index"])
        return {
            "registry": reg_name,
            "registry_id": facts["id"],
            "registry_owner": facts["creator"],
            "sha256": sha,
            "registry_exists": True,
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
        input_preview = None
        if decoded is not None and not decoded.get("function"):
            raw = tx.get("input", "")
            input_preview = raw[:200] + ("…" if len(raw) > 200 else "")
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
            "input_preview": input_preview,
            "explorer": f"{TESTNET_EXPLORER}/tx/{tx_hash}",
        }


# =====================================================================
# Status
# =====================================================================


class StatusService:
    """Live status for the header + About panel. The probe is lazy (only on
    the first ``/api/status`` after the 10 s cache lapses) and runs through a
    SHORT-timeout gateway (wired in server.py), so a slow or dead RPC fails
    fast and never stalls the page (task 4.5e)."""

    def __init__(
        self,
        gateway: ChainGateway,
        index: LocalIndex,
        data_dir: Path,
        rpc_url: str = "",
        telemetry_enabled: bool = False,
    ):
        self.gateway = gateway
        self.index = index
        self.data_dir = Path(data_dir)
        self.rpc_url = rpc_url
        self.telemetry_enabled = telemetry_enabled
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
            # Only the court registries are global; receipt registries are
            # per-firm-per-case and discovered via the filing link, never probed.
            for name in COURT_REGISTRIES:
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
                "chain_id": TESTNET_CHAIN_ID,
                "explorer": TESTNET_EXPLORER,
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
