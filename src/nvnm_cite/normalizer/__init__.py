"""Citation normalizer: text in, normalized case-citation occurrences out.

Built on the Free Law Project stack (eyecite, reporters-db, courts-db).
The canonical form and the jurisdiction mapping are specified in
docs/canonical-citation-spec.md (cite-canonical/v1); this package is the
reference implementation. The normalizer is part of the trust boundary:
every output object carries NORMALIZER_VERSION.
"""

from nvnm_cite.normalizer.canonical import (
    CANONICAL_SPEC,
    CLEAN_STEPS,
    NORMALIZER_VERSION,
    Disposition,
    NormalizationResult,
    NormalizedCitation,
    canonical_citation,
    normalize,
)
from nvnm_cite.normalizer.jurisdiction import (
    AMBIGUOUS_FEDERAL_REPORTERS,
    REGISTRY_PREFIX,
    SCOTUS_EDITIONS,
    map_citation,
    registry_for_court,
)

__all__ = [
    "AMBIGUOUS_FEDERAL_REPORTERS",
    "CANONICAL_SPEC",
    "CLEAN_STEPS",
    "Disposition",
    "NORMALIZER_VERSION",
    "NormalizationResult",
    "NormalizedCitation",
    "REGISTRY_PREFIX",
    "SCOTUS_EDITIONS",
    "canonical_citation",
    "map_citation",
    "normalize",
    "registry_for_court",
]
