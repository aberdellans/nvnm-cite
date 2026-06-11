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

from dataclasses import dataclass, field
from enum import Enum

from eyecite import clean_text, get_citations, resolve_citations
from eyecite.models import (
    CitationBase,
    FullCaseCitation,
    IdCitation,
    ShortCaseCitation,
    SupraCitation,
    UnknownCitation,
)

from nvnm_cite.normalizer.jurisdiction import map_citation

NORMALIZER_VERSION = "1.0.0"
CANONICAL_SPEC = "cite-canonical-v1"

# all_whitespace repairs line-break-mangled cites ("410\nU. S. 113");
# underscores strips the __underlining__ used in some filed briefs.
CLEAN_STEPS: tuple[str, ...] = ("all_whitespace", "underscores")


class Disposition(str, Enum):
    """Normalizer-level outcome per occurrence (not the verifier status enum).

    OK maps to a registry lookup in the verifier; AMBIGUOUS_JURISDICTION maps
    1:1 onto the verifier status of the same name; UNRESOLVED covers
    occurrences with no canonical (orphan short forms, unrecognized or
    pending-publication cites) which the verifier reports without a lookup.
    """

    OK = "ok"
    AMBIGUOUS_JURISDICTION = "ambiguous_jurisdiction"
    UNRESOLVED = "unresolved"


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
            if canonical is None:
                registry, disposition = None, Disposition.UNRESOLVED
            else:
                # Window after the anchor's span feeds the mapper's
                # circuit-parenthetical fallback; 64 chars spans pin-cite
                # runs but a guard regex stops at any intervening citation.
                anchor_end = anchor.span()[1]
                registry, ambiguity = map_citation(
                    anchor, cleaned[anchor_end : anchor_end + 64]
                )
                if registry is None:
                    disposition, reason = Disposition.AMBIGUOUS_JURISDICTION, ambiguity
                else:
                    disposition, reason = Disposition.OK, None
            court = anchor.metadata.court or None
            year = _int_year(anchor.metadata.year)
            plaintiff = _clean_name(anchor.metadata.plaintiff)
            defendant = _clean_name(anchor.metadata.defendant)
        else:
            canonical = registry = court = plaintiff = defendant = None
            year = None
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
