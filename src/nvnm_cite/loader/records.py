"""Record rendering per docs/record-schema.md v1 (LOCKED 2026-06-11).

corpus rows in, chain-ready (registry, checksum, uri, metadata) out, with
the schema's deterministic truncation rules. Pure functions, no I/O, no
chain access; bulk_load.prepare drives this and reconcile re-renders
through the same code, so expectation and submission cannot drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

METADATA_CAP = 2048
URI_CAP = 2048
CHECKSUM_CAP = 64
COLLISION_NAME_CAP = 256
ELLIPSIS = "…"  # 3 bytes of UTF-8

CHECKSUM_ALGO = "cite-canonical-v1"


@dataclass(frozen=True)
class CaseRow:
    """One distinct decision behind a canonical key (post cluster-dedupe)."""

    cluster_id: int
    name: str
    year: int | None
    slug: str


@dataclass(frozen=True)
class RenderedRecord:
    registry: str
    checksum: str
    uri: str
    metadata: str


class RecordError(ValueError):
    """A row that cannot be rendered within the locked schema's caps."""


def compact_json(obj: object) -> str:
    """Schema section 3.2: UTF-8, ensure_ascii=false, sorted keys, no whitespace."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def truncate_utf8(s: str, max_bytes: int) -> str:
    """Longest prefix of s whose UTF-8 form fits max_bytes (char boundary)."""
    raw = s.encode("utf-8")
    if len(raw) <= max_bytes:
        return s
    cut = raw[:max_bytes]
    while cut:
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


def cluster_uri(cluster_id: int, slug: str) -> str:
    """Schema section 3: bulk-data slug form, API-URL fallback when missing."""
    if slug:
        return f"https://www.courtlistener.com/opinion/{cluster_id}/{slug}/"
    return f"https://www.courtlistener.com/api/rest/v4/clusters/{cluster_id}/"


def _case_obj(case: CaseRow, name: str) -> dict:
    obj: dict = {"cluster": case.cluster_id, "name": name}
    # Schema clarification (DECISIONS 2026-06-11): a cluster with no
    # date_filed has no year; the key is omitted rather than invented.
    if case.year is not None:
        obj["year"] = case.year
    return obj


def _fit_single(case: CaseRow) -> str:
    serialized = compact_json(_case_obj(case, case.name))
    if _utf8_len(serialized) <= METADATA_CAP:
        return serialized
    # Schema 3.3 rule 1: truncate name at a UTF-8 character boundary and
    # append the ellipsis. Binary-search the character count because JSON
    # escaping makes byte arithmetic on the raw name unreliable.
    lo, hi = 0, len(case.name)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = compact_json(_case_obj(case, case.name[:mid] + ELLIPSIS))
        if _utf8_len(candidate) <= METADATA_CAP:
            lo = mid
        else:
            hi = mid - 1
    return compact_json(_case_obj(case, case.name[:lo] + ELLIPSIS))


def _fit_collision(cases: list[CaseRow]) -> str:
    serialized = compact_json({"cases": [_case_obj(c, c.name) for c in cases]})
    if _utf8_len(serialized) <= METADATA_CAP:
        return serialized
    # Schema 3.3 rule 2, step 1: cap each name at 256 bytes.
    capped = [
        _case_obj(
            c,
            c.name
            if _utf8_len(c.name) <= COLLISION_NAME_CAP
            else truncate_utf8(c.name, COLLISION_NAME_CAP - len(ELLIPSIS.encode())) + ELLIPSIS,
        )
        for c in cases
    ]
    kept = list(capped)
    omitted = 0
    while kept:
        obj: dict = {"cases": kept}
        if omitted:
            obj["omitted"] = omitted
        serialized = compact_json(obj)
        if _utf8_len(serialized) <= METADATA_CAP:
            return serialized
        # Step 2: drop trailing entries, counting them in "omitted".
        kept.pop()
        omitted += 1
    raise RecordError("collision metadata cannot fit even one case")


def creation_strings(court_id: str) -> tuple[str, str, str]:
    """(registry name, description, metadata) exactly per the locked schema
    section 2, rendered mechanically from courts-db names — never improvised.
    Generic over any courts-db id (moved here from the phase-2 script for the
    Phase 7 full-scope registries)."""
    from courts_db import courts

    by_id = {c["id"]: c for c in courts}
    court_name = by_id[court_id]["name"]
    name = f"us-{court_id}"
    description = (
        f"Canonical US case citations for {court_name} (courts-db: {court_id}). "
        "Existence registry: a record means this citation string denotes a "
        "published decision. nvnm-cite."
    )
    metadata = compact_json(
        {
            "court": court_id,
            "schema": "nvnm-cite-record/v1",
            "source": "CourtListener bulk data, Free Law Project (courtlistener.com)",
            "spec": "cite-canonical-v1",
        }
    )
    return name, description, metadata


def render_record(registry: str, canonical: str, cases: list[CaseRow]) -> RenderedRecord:
    """Render one (registry, canonical key) record; raises RecordError on
    cap violations the schema says must halt (oversize uri/checksum)."""
    if not cases:
        raise RecordError("no cases for key")
    if _utf8_len(canonical) > CHECKSUM_CAP:
        raise RecordError(f"canonical key exceeds {CHECKSUM_CAP} B checksum cap")

    # Deterministic: collision entries sorted by cluster id; the record uri
    # is the lowest cluster id's url (schema clarification, DECISIONS
    # 2026-06-11 -- the schema fixed per-case uris but not the collision
    # uri choice).
    ordered = sorted(cases, key=lambda c: c.cluster_id)
    uri = cluster_uri(ordered[0].cluster_id, ordered[0].slug)
    if _utf8_len(uri) > URI_CAP:
        raise RecordError(f"uri exceeds {URI_CAP} B cap")

    metadata = _fit_single(ordered[0]) if len(ordered) == 1 else _fit_collision(ordered)
    if not metadata or metadata == "{}":
        raise RecordError("metadata rendered empty")
    if _utf8_len(metadata) > METADATA_CAP:
        raise RecordError("metadata still over cap after truncation")
    return RenderedRecord(registry=registry, checksum=canonical, uri=uri, metadata=metadata)
