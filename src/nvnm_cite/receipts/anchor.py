"""Anchoring: turn a checked document into an on-chain filing receipt.

Two clearly separated halves:

- ``prepare_registry`` / ``prepare_anchor`` are READ-ONLY. ``prepare_anchor``
  pins the check to one block, assembles the minimal receipt, and — when the
  target registry's numeric id is known — the exact addRecord calldata.
  Nothing is sent.
- ``send`` performs the WRITES. It is called ONLY behind an explicit
  ``--anchor`` flag, after the plan has been shown and approved. Signing uses
  the from-scratch signer; the key never leaves the process and is never
  logged. The chain id comes from config.signing_context, never a constant.

v1.2.0 changed the flow shape: addRecord keys on the numeric registryId,
which for a NEW registry only exists once its addRegistry tx confirms. So
anchoring into a new registry is TWO steps — create, recover the id from the
AddRegistry event in the tx receipt, then build and send the record calldata.
The discovery line printed on a filing carries the id (names are non-unique).

The check is pinned to ``checked_at_block`` so the receipt is reproducible:
a verifier re-runs the same check against archive state at that block.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import EvmRpc
from nvnm_cite.chain.secp256k1 import address_from_private_key
from nvnm_cite.chain.signer import LegacyTransaction, sign_transaction
from nvnm_cite.receipts.chainio import ChainReader
from nvnm_cite.receipts.schema import (
    RECEIPT_CHECKSUM_ALGO,
    RECEIPT_URI,
    ReceiptError,
    build_receipt,
    receipt_registry_name,
    receipt_registry_strings,
    registries_read_from_report,
    summary_tally,
)
from nvnm_cite.verifier.check import check_document
from nvnm_cite.verifier.resolver import ChainResolver

GAS_FLOOR = 40_000_000_000  # 40 gwei chain floor (DECISIONS 2026-06-10)
GAS_HEADROOM_PCT = 25


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def registry_line(registry_id: int, name: str, chain_id: int) -> str:
    """The discovery line printed on a filing: the id is canonical, the name
    is context. Format locked by the 2026-07-31 schema-doc amendment."""
    return (
        f"Citation verifications: NVNM Chain (chain {chain_id}) "
        f"registry #{registry_id} — {name}"
    )


def prepare_registry(firm: str, case: str) -> dict:
    """Pure: the locked creation strings + addRegistry calldata for this
    (firm, case) receipts registry. The caller sends it, waits for the
    receipt, and recovers the assigned id from the AddRegistry event."""
    name, description, metadata = receipt_registry_strings(firm, case)
    return {
        "name": name,
        "description": description,
        "metadata": metadata,
        "calldata": pc.build_add_registry(name, description, metadata),
    }


def find_receipt_registries(reader: ChainReader, creator: str, name: str) -> list[dict]:
    """All registries with this creator + name (enumeration; names are not
    unique). 0 rows -> create; 1 -> use it; >1 -> the caller MUST surface the
    ambiguity and make a human choose."""
    return [r for r in reader.registries_by_creator(creator) if r["name"] == name]


@dataclass
class AnchorPlan:
    """Everything needed to display the plan and (on approval) send it."""

    registry: str  # the derived <firm>--<case> name
    registry_id: int | None  # None until the registry exists on chain
    registry_exists: bool
    name_matches: bool | None  # chain name == derived name (warn-only signal)
    document_sha256: str
    checked_at_block: int
    chain_id: int
    registries_read: list[dict]
    receipt: dict
    receipt_json: str
    record_calldata: bytes | None  # None while the registry id is unknown
    create_registry: dict | None  # {name, description, metadata} when missing
    create_calldata: bytes | None
    already_anchored: bool
    report: dict = field(repr=False, default_factory=dict)

    @property
    def writes(self) -> int:
        return (1 if self.create_registry else 0) + 1

    def to_display(self) -> dict:
        """JSON-safe view of the plan (calldata as hex), for --json / printing."""
        out = {
            "registry": self.registry,
            "registry_id": self.registry_id,
            "registry_exists": self.registry_exists,
            "name_matches": self.name_matches,
            "document_sha256": self.document_sha256,
            "checked_at_block": self.checked_at_block,
            "chain_id": self.chain_id,
            "registries_read": self.registries_read,
            "receipt": self.receipt,
            "receipt_bytes": len(self.receipt_json.encode("utf-8")),
            "already_anchored": self.already_anchored,
            "writes": self.writes,
        }
        if self.registry_id is not None:
            out["registry_line"] = registry_line(
                self.registry_id, self.registry, self.chain_id
            )
        if self.record_calldata is not None:
            out["record_tx"] = {
                "to": pc.PRECOMPILE_ADDRESS,
                "data": "0x" + self.record_calldata.hex(),
                "value": "0x0",
            }
        if self.create_registry is not None and self.create_calldata is not None:
            out["create_registry"] = dict(
                self.create_registry,
                tx={
                    "to": pc.PRECOMPILE_ADDRESS,
                    "data": "0x" + self.create_calldata.hex(),
                    "value": "0x0",
                },
            )
        return out


def prepare_anchor(
    data: bytes,
    filename: str,
    *,
    firm: str,
    case: str,
    agent_address: str,
    chain_id: int,
    registry_id: int | None = None,
    rpc_factory=None,
    reader: ChainReader | None = None,
    resolver=None,
    registry_ids: Mapping[str, int] | None = None,
) -> AnchorPlan:
    """Read-only: pin the check, build the receipt (+ addRecord calldata when
    ``registry_id`` is known). ``registry_id=None`` means the (firm, case)
    registry does not exist yet: the plan carries the create step and the
    record calldata is built AFTER the create confirms (the id comes from the
    AddRegistry event). ``reader``/``resolver`` are injectable for testing."""
    if reader is None:
        if rpc_factory is None:
            raise ValueError("prepare_anchor needs rpc_factory or reader")
        reader = ChainReader(rpc_factory)
    head = reader.head_block()

    # Pin the check to `head` so the receipt is reproducible at that block.
    if resolver is None:
        if rpc_factory is None:
            raise ValueError("prepare_anchor needs rpc_factory or resolver")
        resolver = ChainResolver(rpc_factory, block=hex(head))
    report = check_document(data, filename, resolver, registry_ids=registry_ids)
    sha = report["document"]["sha256"]

    registries_read = registries_read_from_report(report, head)

    receipt, receipt_json = build_receipt(
        document_sha256=sha,
        checked_at_block=head,
        registries=registries_read,
        summary=summary_tally(report),
        agent_address=agent_address,
        timestamp=_utc_now(),
        chain_id=chain_id,
    )

    derived_name = receipt_registry_name(firm, case)

    name_matches: bool | None = None
    already = False
    record_calldata = create_registry = create_calldata = None
    if registry_id is not None:
        existing = reader.registry(registry_id)
        if existing is None:
            raise ReceiptError(f"registry #{registry_id} does not exist on chain")
        name_matches = existing["name"] == derived_name
        already = reader.keyed_record(registry_id, sha) is not None
        record_calldata = pc.build_add_record(
            registry_id=registry_id,
            uri=RECEIPT_URI,
            checksum=sha,
            checksum_algo=RECEIPT_CHECKSUM_ALGO,
            metadata=receipt_json,
        )
    else:
        plan = prepare_registry(firm, case)
        create_calldata = plan.pop("calldata")
        create_registry = plan

    return AnchorPlan(
        registry=derived_name,
        registry_id=registry_id,
        registry_exists=registry_id is not None,
        name_matches=name_matches,
        document_sha256=sha,
        checked_at_block=head,
        chain_id=chain_id,
        registries_read=registries_read,
        receipt=receipt,
        receipt_json=receipt_json,
        record_calldata=record_calldata,
        create_registry=create_registry,
        create_calldata=create_calldata,
        already_anchored=already,
        report=report,
    )


# --- writes (only behind an explicit flag, after approval) ---


def _send_one(
    rpc: EvmRpc, key: int, chain_id: int, calldata: bytes, label: str
) -> dict:
    address = address_from_private_key(key)
    nonce = rpc.get_transaction_count(address, "pending")
    gas_price = max(rpc.gas_price(), GAS_FLOOR)
    gas = rpc.estimate_gas(address, pc.PRECOMPILE_ADDRESS, calldata)
    tx = LegacyTransaction(
        nonce=nonce,
        gas_price=gas_price,
        gas_limit=gas + gas * GAS_HEADROOM_PCT // 100,
        to=pc.PRECOMPILE_ADDRESS,
        value=0,
        data=calldata,
    )
    signed = sign_transaction(tx, key, chain_id)
    tx_hash = rpc.send_raw_transaction(signed.raw)
    receipt = rpc.wait_for_receipt(tx_hash)
    return {
        "label": label,
        "tx_hash": tx_hash,
        "block": int(receipt.get("blockNumber", "0x0"), 16),
        "gas_used": int(receipt.get("gasUsed", "0x0"), 16),
        "ok": int(receipt.get("status", "0x0"), 16) == 1,
        "logs": receipt.get("logs", []),
    }


def send(plan: AnchorPlan, rpc: EvmRpc, key: int, chain_id: int) -> list[dict]:
    """Execute the plan's WRITES in order. For a new registry: create it, wait
    for the receipt, recover the assigned registryId from the AddRegistry
    event, THEN build and send the id-keyed record calldata. Strictly
    sequential — each waits for its receipt before the next, so the nonce
    advances cleanly. The rpc's chain must match ``chain_id`` (the caller
    resolves both through config.signing_context). Caller must have approval
    to reach here."""
    live_chain = rpc.chain_id()
    if live_chain != chain_id:
        raise RuntimeError(
            f"RPC chain id {live_chain} != signing chain id {chain_id}; refusing to write"
        )
    sent: list[dict] = []
    if plan.create_calldata is not None:
        created = _send_one(rpc, key, chain_id, plan.create_calldata, "create-registry")
        logs = created.pop("logs", [])
        sent.append(created)
        if not created["ok"]:
            return sent
        decoded = pc.decode_add_registry_log(logs)
        if decoded is None:
            raise RuntimeError(
                "create-registry confirmed but no AddRegistry event was found in "
                "the receipt logs; cannot determine the new registryId"
            )
        plan.registry_id = decoded["registry_id"]
        plan.registry_exists = True
        created["registry_id"] = plan.registry_id
        plan.record_calldata = pc.build_add_record(
            registry_id=plan.registry_id,
            uri=RECEIPT_URI,
            checksum=plan.document_sha256,
            checksum_algo=RECEIPT_CHECKSUM_ALGO,
            metadata=plan.receipt_json,
        )
    if plan.record_calldata is None:
        raise RuntimeError("plan has no record calldata and no create step")
    anchored = _send_one(rpc, key, chain_id, plan.record_calldata, "anchor-receipt")
    logs = anchored.pop("logs", [])
    if anchored["ok"]:
        # The assigned recordId/index come from the AddRecord event, the same
        # way the registryId came from AddRegistry. Informational here — the
        # keyed lookup needs only (registry_id, checksum) — so a missing event
        # never fails an anchor that already confirmed.
        record_ev = pc.decode_add_record_log(logs)
        if record_ev is not None:
            anchored["record_id"] = record_ev["record_id"]
            anchored["record_index"] = record_ev["index"]
    sent.append(anchored)
    return sent
