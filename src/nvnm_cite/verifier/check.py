"""The shared verifier core: a document in, honest per-citation statuses out.

extract -> normalize (eyecite, the one reference normalizer, invariant 5)
-> group occurrences -> resolve each covered citation by a LIVE keyed
``records()`` read (item 0) -> the locked five-status enum + the orthogonal
name_check field. Both the CLI (``nvnm-cite check``) and the webapp call
this, so there is exactly one verification path.

Statuses (LOCKED, DECISIONS 2026-06-10): VERIFIED / NOT_FOUND /
NOT_COVERED / AMBIGUOUS_JURISDICTION / UNPARSEABLE. NOT_FOUND comes ONLY
from a keyed miss on a covered registry; a dead RPC raises out of here and
is never reported as NOT_FOUND (the Resolver enforces this). Coverage is
the pinned per-network registry manifest (Albert's decision 2026-07-31:
every court registry the official attestor loaded — 2,114 on mainnet;
supersedes the fixed pilot pair of 2026-06-14): a citation that maps
outside it is NOT_COVERED without a chain read. Chain calls key on the
manifest's numeric registryId (anchoring v1.2.0: names are non-unique).
Existence only: a VERIFIED result asserts the citation exists on chain,
never that the case is good law or supports a proposition.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from nvnm_cite import config
from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain import registrymap
from nvnm_cite.normalizer import CANONICAL_SPEC, NORMALIZER_VERSION, Disposition, normalize
from nvnm_cite.verifier.extract import ExtractError, extract_text
from nvnm_cite.verifier.resolver import Resolver

# The registries whose jurisdiction mapping AND corpus were proven end-to-end
# during the pilot (SCOTUS + the 13 circuits). A NOT_FOUND outside this set
# carries the expanded-coverage caution below: state-reporter normalization
# is unproven until the plan-7.7 rebuild, so a miss there is a flag to
# verify, never proof of fabrication.
FEDERAL_APPELLATE: frozenset[str] = frozenset(
    {"us-scotus", "us-cadc", "us-cafc"} | {f"us-ca{n}" for n in range(1, 12)}
)

EXPANDED_COVERAGE_CAUTION = (
    "Coverage for this court is newly expanded and its citation formats are "
    "still being proven against real briefs. Treat this as a flag to verify "
    "the citation yourself — never as proof it is fabricated, and never "
    "delete a citation on this signal alone."
)


def default_registry_ids() -> dict[str, int]:
    """Coverage for the active network: the pinned manifest's name -> id map."""
    return registrymap.load_manifest(config.get_network().key).all_registries()

VERIFIED = "VERIFIED"
NOT_FOUND = "NOT_FOUND"
NOT_COVERED = "NOT_COVERED"
AMBIGUOUS = "AMBIGUOUS_JURISDICTION"
UNPARSEABLE = "UNPARSEABLE"
STATUS_ORDER = (VERIFIED, NOT_FOUND, NOT_COVERED, AMBIGUOUS, UNPARSEABLE)
STATUS_CHARS = {VERIFIED: "V", NOT_FOUND: "N", NOT_COVERED: "C", AMBIGUOUS: "A", UNPARSEABLE: "U"}

MAX_TEXT_CHARS = 2_000_000
DISPLAY_CASES = 5  # how many collision cases a result carries inline

CHAIN_SOURCE = "chain (live)"


class CheckError(ValueError):
    """A user-facing check failure; ``http_status`` lets the webapp pick a code."""

    def __init__(self, message: str, http_status: int = 422):
        super().__init__(message)
        self.http_status = http_status


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- name_check heuristic (plan task 3.3; existence-only, never about holdings) ---

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


# --- record metadata decoding (single + collision forms, schema v1) ---


def _parse_metadata(metadata: str) -> dict | None:
    try:
        parsed = json.loads(metadata)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def record_cases(metadata: str) -> tuple[list[dict], int]:
    """(cases, omitted) from a record's metadata JSON. Single form
    {cluster,name,year} -> one case; collision form {cases:[...],omitted:N}
    -> the list plus the deterministic-truncation count."""
    parsed = _parse_metadata(metadata)
    if parsed is None:
        return [], 0
    cases = parsed.get("cases")
    if isinstance(cases, list):
        kept = [c for c in cases if isinstance(c, dict)]
        omitted = parsed.get("omitted")
        return kept, omitted if isinstance(omitted, int) and omitted > 0 else 0
    if "cluster" in parsed or "name" in parsed:
        return [parsed], 0
    return [], 0


def record_names(metadata: str) -> list[str]:
    cases, _ = record_cases(metadata)
    return [c.get("name", "") for c in cases if isinstance(c, dict)]


def record_cluster(metadata: str) -> int | None:
    parsed = _parse_metadata(metadata)
    if isinstance(parsed, dict) and isinstance(parsed.get("cluster"), int):
        return parsed["cluster"]
    return None


def record_view(record: pc.Record) -> dict:
    """The ``record`` cell for a VERIFIED citation: what the chain says the
    citation denotes, with collision cases capped for display."""
    cases, omitted = record_cases(record.metadata)
    return {
        "uri": record.uri,
        "cases": cases[:DISPLAY_CASES],
        "more_cases": max(0, len(cases) - DISPLAY_CASES) + omitted,
        "collision": len(cases) > 1 or omitted > 0,
        "source": CHAIN_SOURCE,
    }


def source_snippet(text: str, span: list[int] | tuple[int, int], context: int = 60) -> str:
    """A short, whitespace-collapsed excerpt around ``span`` so a reader can
    locate an UNPARSEABLE/AMBIGUOUS token in their own document."""
    start, end = max(0, span[0] - context), min(len(text), span[1] + context)
    excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"


# --- occurrence grouping ---


def _entry_key(occ) -> tuple:
    if occ.disposition is Disposition.OK:
        return ("ok", occ.registry, occ.canonical)
    if occ.disposition is Disposition.AMBIGUOUS_JURISDICTION:
        return ("ambiguous", occ.canonical or occ.as_written)
    if occ.disposition is Disposition.VENDOR:
        return ("vendor", occ.canonical or occ.as_written)
    return ("unresolved", occ.as_written.strip().lower())


def _group_occurrences(citations: list) -> tuple[dict[tuple, dict], list[tuple]]:
    """Collapse repeated occurrences of the same citation into one entry,
    keyed so OK/ambiguous/unresolved never merge across dispositions.
    Also returns each occurrence's entry key, in input order, so the
    parallel-citation clustering can trace occurrences back to entries."""
    entries: dict[tuple, dict] = {}
    keys: list[tuple] = []
    for occ in citations:
        key = _entry_key(occ)
        keys.append(key)
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
        entry["spans"].append(
            {"span": list(occ.span), "kind": occ.kind, "as_written": occ.as_written, "pin_cite": occ.pin_cite}
        )
        if occ.as_written not in entry["variants"]:
            entry["variants"].append(occ.as_written)
        for field_name in ("plaintiff", "defendant", "court"):
            if entry[field_name] is None:
                entry[field_name] = getattr(occ, field_name)
        if entry["year"] is None:
            entry["year"] = occ.year
    return entries, keys


def _unresolved_references_view(occurrences: list, cleaned: str) -> dict:
    """Unresolved Id./supra references, folded into one accounting block:
    per-form counts plus a locating snippet for the first occurrence."""
    forms: dict[str, dict] = {}
    for occ in occurrences:
        norm = occ.as_written.strip().lower()
        form = forms.get(norm)
        if form is None:
            form = forms[norm] = {
                "as_written": occ.as_written,
                "occurrences": 0,
                "snippet": source_snippet(cleaned, occ.span),
            }
        form["occurrences"] += 1
    return {
        "count": len(occurrences),
        "forms": sorted(forms.values(), key=lambda f: -f["occurrences"]),
        "note": (
            "reference forms (Id., supra) whose antecedent citation could "
            "not be determined; accounted for here, excluded from the "
            "citations table"
        ),
    }


# --- the core ---


def check_text(
    text: str,
    resolver: Resolver,
    *,
    registry_ids: Mapping[str, int] | None = None,
) -> dict:
    """Normalize ``text`` and resolve every citation against the chain.

    ``registry_ids`` is the coverage map (registry name -> numeric
    registryId); ``None`` loads the active network's pinned manifest.
    Raises ``CheckError`` on an over-long document. Transport / RPC failures
    from the resolver propagate (they are NOT NOT_FOUND); the caller decides
    how to surface a dead chain.
    """
    if len(text) > MAX_TEXT_CHARS:
        raise CheckError(f"document text exceeds {MAX_TEXT_CHARS:,} characters", http_status=413)
    if registry_ids is None:
        registry_ids = default_registry_ids()

    result = normalize(text)
    cleaned = result.cleaned_text

    # 1.2.0: non-case occurrences leave the table before grouping, but are
    # never silently dropped — they come back as summary accounting below.
    case_occurrences: list = []
    law_sections = 0
    law_section_examples: list[str] = []
    unresolved_refs: list = []
    for occ in result.citations:
        if occ.disposition is Disposition.OUT_OF_SCOPE:
            law_sections += 1
            if occ.as_written not in law_section_examples and len(law_section_examples) < 5:
                law_section_examples.append(occ.as_written)
        elif occ.disposition is Disposition.UNRESOLVED and occ.kind in ("id", "supra"):
            # An unresolved Id./supra can never be checked on its own; a
            # per-token UNPARSEABLE row is noise (measured: real merits
            # briefs surface a handful per document).
            unresolved_refs.append(occ)
        else:
            case_occurrences.append(occ)

    entries, occ_keys = _group_occurrences(case_occurrences)

    rows: dict[tuple, dict] = {}
    for key, entry in entries.items():
        kind = key[0]
        record: pc.Record | None = None
        query: dict | None = None
        registry_id: int | None = None
        confidence: str | None = None
        caution: str | None = None
        if kind == "ok":
            registry_id = registry_ids.get(entry["registry"])
            if registry_id is not None:
                resolution = resolver.resolve(
                    registry_id, entry["canonical"], entry["registry"]
                )
                record = resolution.record
                query = resolution.query
                if record is not None:
                    status, reason = VERIFIED, None
                else:
                    status = NOT_FOUND
                    reason = (
                        "no record for this citation in the "
                        f"{entry['registry']} registry (first-page canonical keys)"
                    )
                    if entry["registry"] not in FEDERAL_APPELLATE:
                        confidence = "expanded-coverage"
                        caution = EXPANDED_COVERAGE_CAUTION
                    elif entry["registry"] == "us-scotus":
                        # Measured on real merits briefs (2026-08-02): the
                        # source data records some SCOTUS cases under only
                        # one of the parallel official U.S. / S. Ct. cites.
                        reason += (
                            ". Note: some SCOTUS cases appear here under "
                            "only one of the parallel U.S. / S. Ct. "
                            "citations — check this case's other reporter "
                            "before concluding"
                        )
            else:
                status = NOT_COVERED
                reason = (
                    f"{entry['registry']} has no registry in the pinned coverage "
                    f"manifest ({len(registry_ids)} covered court registries)"
                )
        elif kind == "ambiguous":
            status, reason = AMBIGUOUS, entry["reason"]
        elif kind == "vendor":
            # Westlaw/LEXIS identifiers are never registry keys (corpus scope
            # excludes them by design): outside coverage, no chain read, and
            # crucially NOT a "not found" — a real case may well sit behind a
            # vendor-only citation.
            status, reason = NOT_COVERED, entry["reason"]
        else:
            status, reason = UNPARSEABLE, entry["reason"]
        names = record_names(record.metadata) if record is not None else []
        check = name_check(entry["plaintiff"], entry["defendant"], names)

        rows[key] = (
            {
                "registry": entry["registry"],
                "registry_id": registry_id,
                "confidence": confidence,
                "caution": caution,
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
                "record": record_view(record) if record is not None else None,
                "query": query,
                # Source context so unparseable/ambiguous tokens are findable
                # in the reader's own document; omitted where the citation
                # cell already identifies the location.
                "snippet": (
                    source_snippet(cleaned, entry["first_span"])
                    if status in (AMBIGUOUS, UNPARSEABLE)
                    else None
                ),
            }
        )

    # --- parallel-citation clustering (1.2.0) ---
    # Real filings cite a case by several reporters in one run ("133 Ohio
    # St.3d 10, 2012-Ohio-5270, 979 N.E.2d 1229"): back-to-back full cites
    # separated by nothing but a comma, where the follow-on members carry
    # no party names of their own. Those runs are ONE authority. Cluster
    # the entries, present the strongest member (STATUS_ORDER: a VERIFIED
    # parallel outranks an ambiguous one) as the row, and keep the other
    # members visible under "parallels" — collapsed, never hidden.
    parent: dict[tuple, tuple] = {}

    def _find(k: tuple) -> tuple:
        while parent.get(k, k) != k:
            parent[k] = parent.get(parent[k], parent[k])
            k = parent[k]
        return k

    def _union(a: tuple, b: tuple) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[rb] = ra

    full_occs = sorted(
        ((occ, key) for occ, key in zip(case_occurrences, occ_keys) if occ.kind == "full"),
        key=lambda t: t[0].span[0],
    )

    def _name_key(value: str | None) -> str:
        # eyecite renders the same back-propagated party differently per
        # citation class (measured: "Buckeye Wind, L.L.C." from a reporter
        # cite, "Buckeye Wind, LLC" from the neutral cite in the same run),
        # so names compare punctuation- and case-insensitively.
        return re.sub(r"[^a-z0-9]", "", (value or "").lower())

    for (a, ka), (b, kb) in zip(full_occs, full_occs[1:]):
        gap_text = cleaned[a.span[1] : b.span[0]]
        # A run member may be separated by a pin page as well as the comma
        # ("58 Ohio St.2d 108, 110, 388 N.E.2d 1370"): commas, spaces, and
        # one bare page (or page range) are run-internal; anything else —
        # a semicolon, a case name, prose — ends the run.
        gap_ok = len(gap_text) <= 16 and re.fullmatch(
            r"[\s,]*(?:\d{1,5}(?:[-–—]\d{1,5})?)?[\s,]*", gap_text
        )
        # eyecite back-propagates the case name across a parallel run, so
        # matching party names corroborate the merge; a follow-on member
        # with no names at all is the bare-parallel form.
        names_agree = (
            (b.plaintiff, b.defendant) == (None, None)
            or (
                _name_key(b.plaintiff) == _name_key(a.plaintiff)
                and _name_key(b.defendant) == _name_key(a.defendant)
            )
        )
        if ka != kb and gap_ok and names_agree:
            _union(ka, kb)

    clusters: dict[tuple, list[tuple]] = {}
    for key in rows:
        clusters.setdefault(_find(key), []).append(key)

    def _parallel_view(row: dict) -> dict:
        return {
            field: row[field]
            for field in (
                "canonical", "as_written", "status", "registry", "registry_id",
                "occurrences", "kinds", "reason", "name_check", "record",
            )
        }

    citations = []
    for member_keys in clusters.values():
        members = sorted(
            (rows[k] for k in member_keys),
            key=lambda r: (STATUS_ORDER.index(r["status"]), r["first_span"]),
        )
        primary = members[0]
        primary["parallels"] = [_parallel_view(m) for m in members[1:]]
        primary["first_span"] = min(m["first_span"] for m in members)
        citations.append(primary)

    citations.sort(key=lambda c: c["first_span"])
    counts = {s: 0 for s in STATUS_ORDER}
    mismatches = 0
    for row in citations:
        counts[row["status"]] += 1
        if row["name_check"] == "mismatch":
            mismatches += 1

    covered_names = sorted(registry_ids)
    return {
        "normalizer": {"version": NORMALIZER_VERSION, "spec": CANONICAL_SPEC},
        "coverage": {
            "count": len(registry_ids),
            # The full 2,114-name list would bloat every response; ship it
            # only when small (the testnet pilot pair).
            "covered": covered_names if len(covered_names) <= 20 else None,
            "source": "NVNM Chain (live keyed records() reads)",
        },
        "summary": {
            "occurrences": len(case_occurrences),
            "distinct": len(citations),
            "by_status": counts,
            "name_mismatches": mismatches,
            # 1.2.0 accounting for what the citations table deliberately
            # excludes: nothing is silently dropped.
            "law_sections_out_of_scope": {
                "count": law_sections,
                "examples": law_section_examples,
            },
        },
        "unresolved_references": _unresolved_references_view(unresolved_refs, cleaned),
        "citations": citations,
        "privacy": {
            "persisted": False,
            "note": (
                "Your document is parsed in memory to find its citations and "
                "discarded with this response — never written to disk, never "
                "put on chain. Each citation is checked by reading NVNM Chain "
                "live, so the verdict is the chain's answer, not ours, and "
                "anyone can replay the same lookup."
            ),
        },
    }


def check_document(
    data: bytes,
    filename: str,
    resolver: Resolver,
    *,
    registry_ids: Mapping[str, int] | None = None,
) -> dict:
    """Full pipeline: extract text from ``data``, then check it. The document
    SHA-256 binds the exact bytes (what a Phase 4 receipt anchors)."""
    started = time.monotonic()
    try:
        extraction = extract_text(data, filename)
    except ExtractError as exc:
        raise CheckError(str(exc)) from exc
    sha256 = hashlib.sha256(data).hexdigest()

    report = check_text(extraction.text, resolver, registry_ids=registry_ids)
    report["document"] = {
        "filename": filename,
        "sha256": sha256,
        "bytes": len(data),
        "extraction": {
            "method": extraction.method,
            "chars": len(extraction.text),
            "warning": extraction.warning,
        },
    }
    report["generated_at"] = _utc_now()
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return report
