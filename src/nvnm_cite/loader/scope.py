"""Pilot corpus scope: which reporters belong to which registry.

Single source of truth for the verifier-reachable key space, settled by the
Phase 2 census (DECISIONS 2026-06-11). The tranche-1 bulk load used exactly
these reporter sets, and the daily updater (loader/update.py) must use the
same ones so the registries stay internally consistent across the bulk and
incremental paths. These are exact CourtListener reporter strings, which are
reporters-db edition strings for everything in scope.
"""

from __future__ import annotations

REGISTRY_REPORTERS: dict[str, tuple[str, ...]] = {
    # SCOTUS: the three official/parallel reporter families (rule 1 of the
    # jurisdiction spec maps all of them to us-scotus).
    "scotus": ("U.S.", "S. Ct.", "L. Ed.", "L. Ed. 2d"),
    # Eleventh Circuit: the federal appellate reporters and the unpublished
    # appendix. WL / LEXIS / specialty (BNA, CCH) reporters are out of scope
    # for the pilot (NOT_COVERED), per the census.
    "ca11": ("F.2d", "F.3d", "F.4th", "F. App'x"),
}


def courts() -> tuple[str, ...]:
    return tuple(REGISTRY_REPORTERS)


def registry_for_court(court: str) -> str:
    return f"us-{court}"


def reporters_for_court(court: str) -> tuple[str, ...]:
    try:
        return REGISTRY_REPORTERS[court]
    except KeyError:
        raise KeyError(
            f"court {court!r} is not in the pilot scope {tuple(REGISTRY_REPORTERS)}"
        ) from None
