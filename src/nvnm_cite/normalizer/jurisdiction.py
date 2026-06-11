"""Map a resolved case citation to an NVNM registry name.

Registry names are courts-db court IDs prefixed "us-" (us-scotus, us-ca11).
The mapping never guesses: a citation whose court cannot be determined from
the reporter edition or the court parenthetical returns (None, reason) and
the caller reports AMBIGUOUS_JURISDICTION.

Mapping rules, in order:
1. Reporter edition in SCOTUS_EDITIONS -> us-scotus. Needed because eyecite
   sets court='scotus' for bare U.S. and S. Ct. cites but NOT for bare
   L. Ed. / L. Ed. 2d cites (measured against eyecite 2.7.6).
2. eyecite's metadata.court (already a courts-db ID, parsed from the court
   parenthetical) -> us-<id>, after validating the ID against courts-db.
3. Anything else is ambiguous. This includes F.2d/F.3d/F.4th/F. App'x with
   no recognizable parenthetical, state reporters with no parenthetical, and
   early nominative reporters cited without their U.S. volume (reporters-db
   tags them scotus_early, but e.g. "Cranch" is also a D.C. reporter, so
   mapping them to us-scotus would be a guess).
"""

from __future__ import annotations

import re

import courts_db
from eyecite.models import CaseCitation

REGISTRY_PREFIX = "us-"

# The three SCOTUS reporter families (reporters-db edition strings). All carry
# cite_type='federal' in reporters-db, so the edition set, not cite_type, is
# the discriminator.
SCOTUS_EDITIONS = frozenset({"U.S.", "S. Ct.", "L. Ed.", "L. Ed. 2d"})

# Federal reporters that span every circuit: without a court parenthetical
# these are the canonical AMBIGUOUS_JURISDICTION case (called out in the spec).
AMBIGUOUS_FEDERAL_REPORTERS = frozenset(
    {"F.", "F.2d", "F.3d", "F.4th", "F. App'x", "F. Supp.", "F. Supp. 2d", "F. Supp. 3d"}
)

_VALID_COURT_IDS: frozenset[str] = frozenset(c["id"] for c in courts_db.courts)

# Closed-set fallback for standard federal appellate parentheticals.
# eyecite 2.7.6 resolves "(3rd Cir.)" but not the Bluebook-standard
# "(3d Cir.)" (measured; "2d Cir." works, the gap is 3d only). The spec's
# rule 2 makes these 13 forms recognizable per se, so when eyecite reports
# no court we match them exactly: ordinal + "Cir." right after the cite,
# with only pin-cite characters allowed in between so a neighboring
# citation's parenthetical can never be misattributed. An exact whitelist
# is not a guess.
_CIRCUIT_BY_ORDINAL: dict[str, str] = {
    "1st": "ca1", "2d": "ca2", "2nd": "ca2", "3d": "ca3", "3rd": "ca3",
    "4th": "ca4", "5th": "ca5", "6th": "ca6", "7th": "ca7", "8th": "ca8",
    "9th": "ca9", "10th": "ca10", "11th": "ca11", "D.C.": "cadc", "Fed.": "cafc",
}
_CIRCUIT_PARENTHETICAL = re.compile(
    r"^(?:\s*,?\s*(?:at\s+)?[\d\s,\-–&n\.]*)"  # optional pin cites only
    r"\((?P<ordinal>1st|2d|2nd|3d|3rd|4th|5th|6th|7th|8th|9th|10th|11th|D\.C\.|Fed\.)"
    r"\s+Cir\.?(?:[\s,][^)]*)?\)"
)


def _circuit_from_following_text(following_text: str) -> str | None:
    match = _CIRCUIT_PARENTHETICAL.match(following_text)
    if not match:
        return None
    return _CIRCUIT_BY_ORDINAL[match.group("ordinal")]


def registry_for_court(court_id: str) -> str:
    """Registry name for a courts-db court ID. Raises if the ID is unknown."""
    if court_id not in _VALID_COURT_IDS:
        raise ValueError(f"unknown courts-db id: {court_id!r}")
    return REGISTRY_PREFIX + court_id


def map_citation(
    citation: CaseCitation, following_text: str = ""
) -> tuple[str | None, str | None]:
    """(registry, None) when the citation maps cleanly, else (None, reason).

    following_text is the cleaned text immediately after the citation span,
    used only for the closed-set circuit-parenthetical fallback when eyecite
    reports no court. A (None, reason) result means AMBIGUOUS_JURISDICTION
    to the caller.
    """
    edition = citation.corrected_reporter()
    if edition in SCOTUS_EDITIONS:
        return REGISTRY_PREFIX + "scotus", None

    court = (citation.metadata.court or "").strip()
    if court:
        if court in _VALID_COURT_IDS:
            return REGISTRY_PREFIX + court, None
        # eyecite court IDs come from courts-db, so this branch should be
        # unreachable; if the libraries ever skew, refuse rather than guess.
        return None, f"court id {court!r} not found in courts-db"

    fallback = _circuit_from_following_text(following_text)
    if fallback is not None:
        return REGISTRY_PREFIX + fallback, None

    if edition in AMBIGUOUS_FEDERAL_REPORTERS:
        return None, f"{edition} citation with no recognizable court parenthetical"
    return None, "no recognizable court parenthetical"
