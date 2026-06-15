"""Verify a filing receipt from (registry + the original file). Read-only.

This is the artifact a court, clerk, or opposing counsel consumes. They have
the document and the registry LINK printed on the filing — nothing else. The
flow:

1. Hash the file locally (SHA-256).
2. Keyed ``records(registry, hash)`` read. A MISS means no receipt for THIS
   exact document — the classic tamper signal: one changed byte changes the
   fingerprint, so an altered file simply has no receipt.
3. If found, re-run the citation check pinned to the receipt's
   ``checked_at_block`` (archive read) and confirm the recomputed status
   tally matches the receipt's. The document hash already proves the bytes
   are the ones anchored; the recompute proves the chain still says the same.

Everything is replayable: the keyed query travels back in the result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from nvnm_cite.normalizer import NORMALIZER_VERSION
from nvnm_cite.receipts.chainio import ChainReader
from nvnm_cite.receipts.schema import summary_tally
from nvnm_cite.verifier.check import COVERED_REGISTRIES, check_document
from nvnm_cite.verifier.resolver import ChainResolver, records_query

# Verdicts
VERIFIED = "verified"            # found, unchanged, and the recheck reproduces the tally
SUMMARY_DRIFT = "summary_drift"  # found + unchanged, but the recomputed tally differs
FOUND = "found"                  # found, but could not recompute (no usable block)
NOT_FOUND = "not_found"          # no receipt for this exact document (altered or never anchored)
REGISTRY_NOT_FOUND = "registry_not_found"
BAD_RECEIPT = "bad_receipt"      # a record exists but its metadata is not a receipt


@dataclass
class VerifyResult:
    registry: str
    registry_exists: bool
    document_sha256: str
    found: bool
    verdict: str
    receipt: dict | None
    recomputed_summary: dict | None
    summary_matches: bool | None
    checked_at_block: int | None
    normalizer_version_receipt: str | None
    normalizer_version_now: str
    notes: list[str] = field(default_factory=list)
    query: dict = field(default_factory=dict)


def verify_document(
    data: bytes,
    filename: str,
    *,
    registry: str,
    rpc_factory=None,
    reader: ChainReader | None = None,
    resolver=None,
    covered: tuple[str, ...] = COVERED_REGISTRIES,
) -> VerifyResult:
    """Read-only verification. ``reader``/``resolver`` are injectable for
    testing; in production they are built from ``rpc_factory``."""
    sha = hashlib.sha256(data).hexdigest()
    _, query = records_query(registry, sha)
    if reader is None:
        if rpc_factory is None:
            raise ValueError("verify_document needs rpc_factory or reader")
        reader = ChainReader(rpc_factory)

    def result(**kw) -> VerifyResult:
        base = dict(
            registry=registry, registry_exists=True, document_sha256=sha, found=False,
            verdict=NOT_FOUND, receipt=None, recomputed_summary=None, summary_matches=None,
            checked_at_block=None, normalizer_version_receipt=None,
            normalizer_version_now=NORMALIZER_VERSION, notes=[], query=query,
        )
        base.update(kw)
        return VerifyResult(**base)

    if reader.registry(registry) is None:
        return result(
            registry_exists=False, verdict=REGISTRY_NOT_FOUND,
            notes=["this registry does not exist on chain — check the link printed on the filing"],
        )

    record = reader.keyed_record(registry, sha)
    if record is None:
        return result(
            verdict=NOT_FOUND,
            notes=[
                "no receipt for this exact document in this registry. A single "
                "changed byte changes the fingerprint, so an altered file will "
                "not match; otherwise it was never anchored here."
            ],
        )

    try:
        receipt = json.loads(record.metadata)
        if not isinstance(receipt, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        return result(found=True, verdict=BAD_RECEIPT, notes=["the record is not a JSON receipt object"])

    checked_at_block = receipt.get("checked_at_block")
    stored_summary = receipt.get("summary")
    receipt_norm = receipt.get("normalizer_version")
    notes: list[str] = []
    if receipt_norm and receipt_norm != NORMALIZER_VERSION:
        notes.append(
            f"receipt used normalizer {receipt_norm}; this build is {NORMALIZER_VERSION} — "
            "a recompute difference may be a version change, not tampering"
        )

    recomputed = None
    summary_matches = None
    if isinstance(checked_at_block, int):
        rsv = resolver or ChainResolver(rpc_factory, block=hex(checked_at_block))
        report = check_document(data, filename, rsv, covered=covered)
        recomputed = summary_tally(report)
        summary_matches = recomputed == stored_summary

    if summary_matches is True:
        verdict = VERIFIED
    elif summary_matches is False:
        verdict = SUMMARY_DRIFT
        notes.append(
            "the document matches the receipt's fingerprint (so the bytes are the "
            "ones anchored), but re-running the check produced a different tally"
        )
    else:
        verdict = FOUND
        notes.append("could not recompute: the receipt has no usable checked_at_block")

    return result(
        found=True, verdict=verdict, receipt=receipt, recomputed_summary=recomputed,
        summary_matches=summary_matches, checked_at_block=checked_at_block,
        normalizer_version_receipt=receipt_norm, notes=notes,
    )
