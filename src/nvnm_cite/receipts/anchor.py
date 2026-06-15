"""Anchoring: turn a checked document into an on-chain filing receipt.

Two clearly separated halves:

- ``prepare_anchor`` is READ-ONLY. It pins the check to one block, assembles
  the minimal receipt and the exact calldata for (optionally) creating the
  per-firm-per-case registry and writing the receipt, and reports whether the
  registry exists and whether this document is already anchored. Nothing is
  sent.
- ``send`` performs the WRITES (addRegistry if needed, then addRecord). It is
  called ONLY behind an explicit ``--anchor`` flag, after the plan has been
  shown and approved. Signing uses the from-scratch signer; the key never
  leaves the process and is never logged.

The check is pinned to ``checked_at_block`` so the receipt is reproducible:
a verifier re-runs the same check against archive state at that block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.rpc import EvmRpc
from nvnm_cite.chain.secp256k1 import address_from_private_key
from nvnm_cite.chain.signer import LegacyTransaction, sign_transaction
from nvnm_cite.config import TESTNET_CHAIN_ID
from nvnm_cite.receipts.chainio import ChainReader
from nvnm_cite.receipts.schema import (
    RECEIPT_CHECKSUM_ALGO,
    RECEIPT_URI,
    build_receipt,
    receipt_registry_name,
    receipt_registry_strings,
    summary_tally,
)
from nvnm_cite.verifier.check import COVERED_REGISTRIES, check_document
from nvnm_cite.verifier.resolver import ChainResolver

GAS_FLOOR = 40_000_000_000  # 40 gwei chain floor (DECISIONS 2026-06-10)
GAS_HEADROOM_PCT = 25


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AnchorPlan:
    """Everything needed to display the plan and (on approval) send it."""

    registry: str
    registry_exists: bool
    document_sha256: str
    checked_at_block: int
    registries_read: list[dict]
    receipt: dict
    receipt_json: str
    record_calldata: bytes
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
            "registry_exists": self.registry_exists,
            "document_sha256": self.document_sha256,
            "checked_at_block": self.checked_at_block,
            "registries_read": self.registries_read,
            "receipt": self.receipt,
            "receipt_bytes": len(self.receipt_json.encode("utf-8")),
            "already_anchored": self.already_anchored,
            "writes": self.writes,
            "record_tx": {"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + self.record_calldata.hex(), "value": "0x0"},
        }
        if self.create_registry is not None and self.create_calldata is not None:
            out["create_registry"] = dict(
                self.create_registry,
                tx={"to": pc.PRECOMPILE_ADDRESS, "data": "0x" + self.create_calldata.hex(), "value": "0x0"},
            )
        return out


def prepare_anchor(
    data: bytes,
    filename: str,
    *,
    firm: str,
    case: str,
    agent_address: str,
    rpc_factory=None,
    reader: ChainReader | None = None,
    resolver=None,
    covered: tuple[str, ...] = COVERED_REGISTRIES,
) -> AnchorPlan:
    """Read-only: pin the check, build the receipt + calldata, inspect the
    target registry. Sends nothing. ``reader``/``resolver`` are injectable for
    testing; in production they are built from ``rpc_factory``."""
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
    report = check_document(data, filename, resolver, covered=covered)
    sha = report["document"]["sha256"]

    registries_read: list[dict] = []
    for name in covered:
        reg = reader.registry(name)
        if reg is not None:
            registries_read.append({"head_block": head, "id": reg["id"], "name": name})

    receipt, receipt_json = build_receipt(
        document_sha256=sha,
        checked_at_block=head,
        registries=registries_read,
        summary=summary_tally(report),
        agent_address=agent_address,
        timestamp=_utc_now(),
    )

    registry_name = receipt_registry_name(firm, case)
    existing = reader.registry(registry_name)
    already = existing is not None and reader.keyed_record(registry_name, sha) is not None

    create_registry = create_calldata = None
    if existing is None:
        name, description, metadata = receipt_registry_strings(firm, case)
        create_registry = {"name": name, "description": description, "metadata": metadata}
        create_calldata = pc.build_add_registry(name, description, metadata)

    record_calldata = pc.build_add_record(
        registry=registry_name,
        uri=RECEIPT_URI,
        checksum=sha,
        checksum_algo=RECEIPT_CHECKSUM_ALGO,
        metadata=receipt_json,
    )

    return AnchorPlan(
        registry=registry_name,
        registry_exists=existing is not None,
        document_sha256=sha,
        checked_at_block=head,
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


def _send_one(rpc: EvmRpc, key: int, calldata: bytes, label: str) -> dict:
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
    signed = sign_transaction(tx, key, TESTNET_CHAIN_ID)
    tx_hash = rpc.send_raw_transaction(signed.raw)
    receipt = rpc.wait_for_receipt(tx_hash)
    return {
        "label": label,
        "tx_hash": tx_hash,
        "block": int(receipt.get("blockNumber", "0x0"), 16),
        "gas_used": int(receipt.get("gasUsed", "0x0"), 16),
        "ok": int(receipt.get("status", "0x0"), 16) == 1,
    }


def send(plan: AnchorPlan, rpc: EvmRpc, key: int) -> list[dict]:
    """Execute the plan's WRITES in order: create the registry if missing
    (and wait for it, so the receipt write is authorized), then anchor the
    receipt. Strictly sequential — each waits for its receipt before the next,
    so the nonce advances cleanly. Caller must have approval to reach here."""
    sent: list[dict] = []
    if plan.create_calldata is not None:
        sent.append(_send_one(rpc, key, plan.create_calldata, "create-registry"))
    sent.append(_send_one(rpc, key, plan.record_calldata, "anchor-receipt"))
    return sent
