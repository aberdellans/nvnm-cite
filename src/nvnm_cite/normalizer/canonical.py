"""Canonical citation extraction: the cite-canonical/v1 reference pipeline.

Pipeline: clean_text -> get_citations -> resolve_citations, then one
NormalizedCitation per case-citation occurrence, in document order. The
canonical form is "<volume> <edition> <page>" where edition is the
reporters-db edition string via eyecite's corrected_reporter() ("F. 3d"
becomes "F.3d") and volume/page have leading zeros stripped when numeric.
Canonical keys are FIRST-PAGE keys: the page token is the cited first page;
pin pages live in pin_cite and are never part of the key.

Short forms (short cites, id., supra) inherit the canonical of their
antecedent through eyecite's resolution groups. eyecite silently drops
short forms it cannot resolve (measured against 2.7.6), so this module
re-reports them as UNRESOLVED rather than losing them: a dropped "Id." in
a brief is still a citation occurrence the verifier must account for.

Non-case citations (statutes, journals) and short forms that resolve to
them are excluded: registries hold case citations only.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from eyecite import clean_text, get_citations, resolve_citations

# eyecite emits informational logger.warning chatter during resolution (e.g.
# "Unknown overlap case" for an Id. adjacent to a full cite). It is not a
# signal we act on — our output is pinned by the golden suite — and it must
# not leak to a user's terminal or the server log. Quiet it to ERROR while
# leaving genuine errors visible.
logging.getLogger("eyecite").setLevel(logging.ERROR)
from eyecite.models import (
    CitationBase,
    FullCaseCitation,
    IdCitation,
    ShortCaseCitation,
    SupraCitation,
    UnknownCitation,
)

from nvnm_cite.normalizer.jurisdiction import map_citation, vendor_in_key_space, vendor_kind

# 1.1.0 (2026-08-01): jurisdiction mapping expanded — general court-
# parenthetical fallback via courts-db citation strings, corpus-derived
# reporter-edition inference (reporter_registries.json), and the VENDOR
# disposition for Westlaw/LEXIS identifiers. The cite-canonical/v1 KEY
# format is unchanged.
# 1.2.0 (2026-08-02, driven by the real-filings corpus run): (a) orphan
# short-form fallback — a short cite eyecite could not resolve is attached
# to the unique same-volume/reporter full cite whose first page bounds the
# pin page; (b) law-section tokens (§…) classified OUT_OF_SCOPE instead of
# surfacing as unparseable citations; (c) rule-2/rule-4 state-consistency
# gate — a claimed court whose state contradicts the reporter's own
# reporters-db state set is refused (measured: eyecite claims the D.C.
# court 'supctdc' for a N.Y. "Misc. 3d" cite over "(Sup. Ct. 2004)");
# (d) star pagination ("*4") recognized as pin-cite material ahead of a
# court parenthetical. The cite-canonical/v1 KEY format is unchanged.
NORMALIZER_VERSION = "1.2.0"
CANONICAL_SPEC = "cite-canonical-v1"

# all_whitespace repairs line-break-mangled cites ("410\nU. S. 113");
# underscores strips the __underlining__ used in some filed briefs.
CLEAN_STEPS: tuple[str, ...] = ("all_whitespace", "underscores")


class Disposition(str, Enum):
    """Normalizer-level outcome per occurrence (not the verifier status enum).

    OK maps to a registry lookup in the verifier; AMBIGUOUS_JURISDICTION maps
    1:1 onto the verifier status of the same name; VENDOR marks Westlaw/LEXIS
    database identifiers, which are never registry keys — the verifier
    reports them as outside coverage without a chain read; UNRESOLVED covers
    occurrences with no canonical (orphan short forms, unrecognized or
    pending-publication cites) which the verifier reports without a lookup.
    """

    OK = "ok"
    AMBIGUOUS_JURISDICTION = "ambiguous_jurisdiction"
    VENDOR = "vendor"
    UNRESOLVED = "unresolved"
    # Law-section tokens (§/§§ fragments eyecite reports as UnknownCitation
    # when a statute or regulation cite is split by PDF line breaks). They
    # are accounted for — never silently dropped — but they are not case
    # citations, so the verifier keeps them out of the citations table.
    OUT_OF_SCOPE = "out_of_scope"


# A law-section fragment: an optional opening bracket, then § (one or more).
_SECTION_TOKEN = re.compile(r"^[\(\[]?§")


_KIND_BY_TYPE: dict[type, str] = {
    FullCaseCitation: "full",
    ShortCaseCitation: "short",
    IdCitation: "id",
    SupraCitation: "supra",
    UnknownCitation: "unknown",
}


@dataclass(frozen=True)
class NormalizedCitation:
    """One case-citation occurrence in the checked text."""

    as_written: str
    canonical: str | None
    registry: str | None
    disposition: Disposition
    kind: str
    span: tuple[int, int]
    group: int | None
    court: str | None
    year: int | None
    plaintiff: str | None
    defendant: str | None
    pin_cite: str | None
    reason: str | None
    normalizer_version: str = NORMALIZER_VERSION


@dataclass(frozen=True)
class NormalizationResult:
    """Cleaned text plus all case-citation occurrences found in it.

    Spans in citations index into cleaned_text, not the caller's raw text.
    """

    cleaned_text: str
    citations: list[NormalizedCitation] = field(default_factory=list)
    normalizer_version: str = NORMALIZER_VERSION


def canonical_citation(citation: FullCaseCitation) -> tuple[str | None, str | None]:
    """Canonical first-page key for a full case citation, or (None, reason)."""
    groups = citation.groups or {}
    volume = groups.get("volume")
    page = groups.get("page")
    edition = citation.corrected_reporter()
    if not volume or not page or not edition:
        return None, "missing volume, reporter, or page (pending-publication or malformed cite)"
    if volume.isdigit():
        volume = str(int(volume))
    if page.isdigit():
        page = str(int(page))
    return f"{volume} {edition} {page}", None


def canonical_from_parts(
    volume: str | int | None, reporter: str | None, page: str | None
) -> str | None:
    """Canonical key from structured (volume, reporter, page) parts.

    The corpus-side twin of canonical_citation(): CourtListener's citation
    table stores the reporters-db edition string directly, so the key is
    assembled per spec section 1 without going through eyecite. Token rules
    match canonical_citation() exactly. Returns None when any part is
    missing (no canonical key exists).
    """
    volume = "" if volume is None else str(volume).strip()
    reporter = " ".join((reporter or "").split())
    page = "" if page is None else str(page).strip()
    if not volume or not reporter or not page:
        return None
    if volume.isdigit():
        volume = str(int(volume))
    if page.isdigit():
        page = str(int(page))
    return f"{volume} {reporter} {page}"


def _clean_name(value: str | None) -> str | None:
    # eyecite can return '' for a party it matched but could not extract.
    value = (value or "").strip()
    return value or None


def _int_year(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def normalize(text: str, *, clean_steps: tuple[str, ...] = CLEAN_STEPS) -> NormalizationResult:
    """Extract and normalize every case-citation occurrence in text."""
    cleaned = clean_text(text, clean_steps)
    if not cleaned.strip():
        # eyecite raises on empty input; an empty document has no citations.
        return NormalizationResult(cleaned_text=cleaned)
    citations = get_citations(cleaned)
    resolutions = resolve_citations(citations)

    # id(citation) -> (group index in first-appearance order, anchor full cite).
    # Anchors that are not case citations mark groups to exclude entirely.
    membership: dict[int, tuple[int, FullCaseCitation | None]] = {}
    for group_index, (resource, members) in enumerate(resolutions.items()):
        anchor = getattr(resource, "citation", None)
        case_anchor = anchor if isinstance(anchor, FullCaseCitation) else None
        for member in members:
            membership[id(member)] = (group_index, case_anchor)

    # 1.2.0 orphan short-form fallback. eyecite resolves short cites by
    # antecedent case name and strands the rest ("NIFLA, 138 S. Ct. at
    # 2371" when the full cite spelled the name differently — measured on
    # real merits briefs, where this stranded 15 shorts in one document).
    # A stranded short still names its volume and reporter, and a pin page
    # sits at or past its opinion's first page, so the full cite it means
    # is the same-volume/edition full cite with the LARGEST first page
    # <= the pin page ("539 U.S. at 331" with Gratz at 244 and Grutter at
    # 306 in the document -> Grutter). Equal first pages are the same
    # canonical key, so the choice cannot be wrong; no candidate leaves
    # the short an orphan as before.
    def _norm_vol(v: str) -> str:
        return str(int(v)) if v.isdigit() else v

    fulls: list[tuple[str, str, int, FullCaseCitation]] = []
    for c in citations:
        if isinstance(c, FullCaseCitation) and id(c) in membership:
            groups = c.groups or {}
            vol, page = groups.get("volume") or "", groups.get("page") or ""
            edition = c.corrected_reporter()
            if vol and edition and page.isdigit():
                fulls.append((_norm_vol(vol), edition, int(page), c))
    for c in citations:
        if isinstance(c, ShortCaseCitation) and id(c) not in membership:
            groups = c.groups or {}
            vol, pin = groups.get("volume") or "", groups.get("page") or ""
            edition = c.corrected_reporter()
            if not (vol and edition and pin.isdigit()):
                continue
            candidates = [
                (first, full)
                for fvol, fed, first, full in fulls
                if fvol == _norm_vol(vol) and fed == edition and first <= int(pin)
            ]
            if candidates:
                _, full = max(candidates, key=lambda t: t[0])
                membership[id(c)] = membership[id(full)]

    results: list[NormalizedCitation] = []
    for citation in citations:
        kind = _KIND_BY_TYPE.get(type(citation))
        if kind is None and isinstance(citation, FullCaseCitation):
            kind = "full"  # future eyecite subclasses of FullCaseCitation
        in_groups = id(citation) in membership
        if in_groups:
            group, anchor = membership[id(citation)]
            if anchor is None:
                # Resolved to a statute/journal/etc.: not a case citation.
                continue
        else:
            group, anchor = None, None
            if kind is None or kind == "full":
                continue  # non-case full cites; full case cites always resolve
        if kind is None:
            continue

        if anchor is not None:
            canonical, reason = canonical_citation(anchor)
            edition = anchor.corrected_reporter()
            vendor = vendor_kind(edition)
            if canonical is None:
                registry, disposition = None, Disposition.UNRESOLVED
            elif vendor is not None and not vendor_in_key_space(edition):
                # A vendor number with ZERO presence in the registry key
                # space (WL, generic/federal LEXIS): a lookup can never hit,
                # so no jurisdiction question or chain read arises — even
                # with a court parenthetical, which would only manufacture a
                # false "not found" for a possibly-real case.
                registry = None
                disposition = Disposition.VENDOR
                reason = (
                    f"{vendor} database identifier — not a registry key; "
                    "check this case by its official reporter citation or "
                    "docket number"
                )
            else:
                # Window after the anchor's span feeds the mapper's
                # circuit-parenthetical fallback; 64 chars spans pin-cite
                # runs but a guard regex stops at any intervening citation.
                anchor_end = anchor.span()[1]
                registry, ambiguity = map_citation(
                    anchor, cleaned[anchor_end : anchor_end + 64]
                )
                if registry is not None:
                    disposition, reason = Disposition.OK, None
                elif vendor is not None:
                    # A corpus-present LEXIS edition that still failed to map
                    # (e.g. dominance-refused with no parenthetical): report
                    # it as a vendor identifier, not jurisdictional ambiguity.
                    disposition = Disposition.VENDOR
                    reason = (
                        f"{vendor} database identifier without a resolvable "
                        "court — check this case by its official reporter "
                        "citation or docket number"
                    )
                else:
                    disposition, reason = Disposition.AMBIGUOUS_JURISDICTION, ambiguity
            court = anchor.metadata.court or None
            year = _int_year(anchor.metadata.year)
            plaintiff = _clean_name(anchor.metadata.plaintiff)
            defendant = _clean_name(anchor.metadata.defendant)
        else:
            canonical = registry = court = plaintiff = defendant = None
            year = None
            if kind == "unknown" and _SECTION_TOKEN.match(citation.matched_text()):
                # A §/§§ fragment of a statute or regulation cite (PDF line
                # breaks routinely sever these). Accounted for, but not a
                # case citation and never a registry key.
                disposition = Disposition.OUT_OF_SCOPE
                reason = (
                    "law-section reference (statute or regulation) — "
                    "registries hold case citations only"
                )
            else:
                disposition = Disposition.UNRESOLVED
                reason = (
                    "unrecognized citation form"
                    if kind == "unknown"
                    else "orphan short form: no antecedent resolved in this document"
                )

        pin_cite = getattr(citation.metadata, "pin_cite", None) or None
        results.append(
            NormalizedCitation(
                as_written=citation.matched_text(),
                canonical=canonical,
                registry=registry,
                disposition=disposition,
                kind=kind,
                span=tuple(citation.span()),
                group=group,
                court=court,
                year=year,
                plaintiff=plaintiff,
                defendant=defendant,
                pin_cite=pin_cite,
                reason=reason,
            )
        )

    return NormalizationResult(cleaned_text=cleaned, citations=results)
