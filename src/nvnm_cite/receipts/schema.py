"""Receipt v1 + per-firm-per-case receipt registries — LOCKED at Phase 4
task 4.1 (re-locks docs/record-schema.md section 4).

A receipt is MINIMAL and NON-ENUMERATING (DECISIONS 2026-06-13 items 2/2b):
the checked document's SHA-256 + provenance + a non-identifying status tally,
and NEVER the list of cited cases. The SHA-256 binds the exact document, so a
verifier reproduces every verdict (re-run extract -> normalize -> live keyed
read pinned to checked_at_block) without the brief's authorities ever being
published on a permanent public chain. At ~480 bytes the receipt is always
far under the 2048 B metadata cap, so there is no compaction and no chunking
(task 4.3 dropped).

Receipts live in a registry owned by the FILING PARTY'S OWN WALLET, one per
(firm, case) (item 3): no global registry, so NVNM is never a write-
gatekeeper. The registry name is filer-chosen and human-readable (Albert
2026-06-15), format ``<firm>--<case>``; discovery is the registry LINK
printed on the filing, established when the matter opens.

Pure module: no chain access, no I/O. anchor.py assembles the registries
table and tally (which need chain reads) and calls build_receipt here.
"""

from __future__ import annotations

import re
from typing import Any

from nvnm_cite.config import TESTNET_CHAIN_ID
from nvnm_cite.loader.records import METADATA_CAP, compact_json
from nvnm_cite.normalizer import NORMALIZER_VERSION

RECEIPT_SCHEMA = "nvnm-cite-receipt/v1"
RECEIPT_URI = "urn:nvnm-cite:receipt:v1"  # fixed; schema doc section 4 rationale
RECEIPT_CHECKSUM_ALGO = "sha256"
SPEC = "cite-canonical-v1"

# Registry names are unique on chain. We keep receipt registry names modest
# and to a defined charset so they stay legible and collision-resistant.
REGISTRY_NAME_CAP = 64
_PARTY_CAP = 200  # raw firm/case text kept in description + metadata

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

# The status tally keys, in the order the schema documents them.
TALLY_KEYS = ("checked", "verified", "not_found", "not_covered", "ambiguous", "unparseable", "name_mismatches")
_BY_STATUS_KEY = {
    "verified": "VERIFIED",
    "not_found": "NOT_FOUND",
    "not_covered": "NOT_COVERED",
    "ambiguous": "AMBIGUOUS_JURISDICTION",
    "unparseable": "UNPARSEABLE",
}


class ReceiptError(ValueError):
    """A receipt or registry that cannot be formed within the locked schema."""


# --- per-firm-per-case registry naming (filer-chosen, readable) ---


def slugify(text: str) -> str:
    """Lowercase, alphanumeric-with-single-hyphens slug. Empty if no
    alphanumeric content survives."""
    return _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")


def receipt_registry_name(firm: str, case: str) -> str:
    """Deterministic readable registry name for one (firm, case): the
    filer's two labels slugified and joined by ``--`` (the double hyphen
    distinguishes them from court registries like ``us-ca11`` and from the
    single hyphens inside each slug)."""
    firm_slug, case_slug = slugify(firm), slugify(case)
    if not firm_slug or not case_slug:
        raise ReceiptError("firm and case must each contain alphanumeric characters")
    name = f"{firm_slug}--{case_slug}"
    if len(name.encode("utf-8")) > REGISTRY_NAME_CAP:
        raise ReceiptError(
            f"registry name {name!r} exceeds {REGISTRY_NAME_CAP} bytes; shorten the firm/case labels"
        )
    return name


def receipt_registry_strings(firm: str, case: str) -> tuple[str, str, str]:
    """(name, description, metadata) for addRegistry, rendered from the locked
    templates so anchoring never improvises creation strings."""
    name = receipt_registry_name(firm, case)
    firm_t, case_t = firm.strip()[:_PARTY_CAP], case.strip()[:_PARTY_CAP]
    description = (
        f"nvnm-cite filing receipts for {firm_t} — {case_t}. "
        "SHA-256-keyed records of citation checks against the us-* registries; "
        "owned by the filing party. nvnm-cite."
    )
    metadata = compact_json(
        {"case": case_t, "firm": firm_t, "kind": "receipts", "schema": RECEIPT_SCHEMA, "spec": SPEC}
    )
    if len(metadata.encode("utf-8")) > METADATA_CAP:  # only if absurdly long labels
        raise ReceiptError("registry metadata exceeds the 2048 B cap; shorten the firm/case labels")
    return name, description, metadata


# --- the receipt object ---


def summary_tally(report: dict) -> dict:
    """Non-identifying status tally from a check report's summary."""
    by_status = report["summary"]["by_status"]
    tally = {"checked": report["summary"]["distinct"]}
    for key, status in _BY_STATUS_KEY.items():
        tally[key] = by_status[status]
    tally["name_mismatches"] = report["summary"]["name_mismatches"]
    return tally


def build_receipt(
    *,
    document_sha256: str,
    checked_at_block: int,
    registries: list[dict],
    summary: dict,
    agent_address: str,
    timestamp: str,
    chain_id: int = TESTNET_CHAIN_ID,
) -> tuple[dict, str]:
    """The locked receipt v1 object and its canonical compact JSON.

    ``registries`` is the court registries READ during the check, each
    {id, name, head_block}; ``summary`` is summary_tally()'s output.
    Validates inputs and the (always-satisfied) 2048 B cap.
    """
    sha = (document_sha256 or "").lower()
    if not _SHA256_RE.match(sha):
        raise ReceiptError("document_sha256 must be 64 lowercase hex characters")
    if not _ADDRESS_RE.match(agent_address or ""):
        raise ReceiptError("agent address must be a 0x-prefixed 20-byte address")
    if not isinstance(checked_at_block, int) or checked_at_block < 0:
        raise ReceiptError("checked_at_block must be a non-negative integer")
    if set(summary) != set(TALLY_KEYS):
        raise ReceiptError(f"summary must have exactly the keys {TALLY_KEYS}")

    reg_table = []
    for reg in registries:
        try:
            reg_table.append({"head_block": int(reg["head_block"]), "id": int(reg["id"]), "name": str(reg["name"])})
        except (KeyError, TypeError, ValueError) as exc:
            raise ReceiptError(f"each registry needs int id, int head_block, name: {exc}") from exc

    receipt = {
        "agent": {"address": agent_address.lower()},
        "chain_id": chain_id,
        "checked_at_block": checked_at_block,
        "document_sha256": sha,
        "normalizer_version": NORMALIZER_VERSION,
        "registries": reg_table,
        "schema": RECEIPT_SCHEMA,
        "summary": {k: int(summary[k]) for k in TALLY_KEYS},
        "timestamp": timestamp,
    }
    serialized = compact_json(receipt)
    if len(serialized.encode("utf-8")) > METADATA_CAP:
        # The minimal receipt cannot reach the cap; this guards a future change.
        raise ReceiptError("receipt exceeds the 2048 B metadata cap (unexpected for a minimal receipt)")
    return receipt, serialized
