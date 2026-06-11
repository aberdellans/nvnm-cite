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


def registry_for_court(court_id: str) -> str:
    """Registry name for a courts-db court ID. Raises if the ID is unknown."""
    if court_id not in _VALID_COURT_IDS:
        raise ValueError(f"unknown courts-db id: {court_id!r}")
    return REGISTRY_PREFIX + court_id


def map_citation(citation: CaseCitation) -> tuple[str | None, str | None]:
    """(registry, None) when the citation maps cleanly, else (None, reason).

    A (None, reason) result means AMBIGUOUS_JURISDICTION to the caller.
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

    if edition in AMBIGUOUS_FEDERAL_REPORTERS:
        return None, f"{edition} citation with no recognizable court parenthetical"
    return None, "no recognizable court parenthetical"
