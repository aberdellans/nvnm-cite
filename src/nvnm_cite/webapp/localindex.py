"""Local citation index: a rebuildable audit/cache, NOT the check authority.

Since item 0 (DECISIONS 2026-06-13) the drafting-time check reads NVNM
Chain live (see ``nvnm_cite.verifier``); this module no longer answers
"is this citation real?". It survives as the coverage source for the
status panel and as the offline mirror behind ``rebuild-index`` (anyone
can reconstruct the registries from an RPC URL and diff our work).

Two sources, preferred in order per registry:

1. ``chain_index.sqlite`` — the indexer's mirror of what is actually on
   chain (rebuildable by anyone with an RPC URL). Used when the registry
   has been synced.
2. ``corpus.sqlite`` — the CourtListener-derived corpus, restricted to
   the tranche-1 reporter whitelist so the counts mirror the record set
   prepared for anchoring (census + whitelist: DECISIONS 2026-06-11).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from nvnm_cite.loader.records import cluster_uri

# Tranche-1 reporter whitelist, exactly as loaded (DECISIONS 2026-06-11,
# census entry): the whitelist IS the tranche definition, so the local
# corpus lookup must apply it or it would "verify" citations that were
# never prepared for the chain (U.S.L.W., WL/LEXIS, nominatives...).
TRANCHE1_REPORTERS: dict[str, frozenset[str]] = {
    "us-scotus": frozenset({"U.S.", "S. Ct.", "L. Ed.", "L. Ed. 2d"}),
    "us-ca11": frozenset({"F.2d", "F.3d", "F.4th", "F. App'x"}),
}


@dataclass(frozen=True)
class IndexHit:
    """One registry record as the local index knows it."""

    registry: str
    canonical: str
    uri: str
    cases: list[dict] = field(default_factory=list)  # {cluster, name, year?}
    collision: bool = False
    source: str = "corpus-snapshot"


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


class LocalIndex:
    """Resolves citation keys against the best available local source."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.chain_index_path = self.data_dir / "chain_index.sqlite"
        self.corpus_path = self.data_dir / "corpus.sqlite"
        self._coverage_cache: list[dict] | None = None

    # --- source resolution ---

    def _chain_synced(self) -> dict[str, dict]:
        """registry -> sync facts, for registries with synced rows."""
        if not self.chain_index_path.is_file():
            return {}
        out: dict[str, dict] = {}
        try:
            return self._chain_synced_query(out)
        except sqlite3.OperationalError:
            # A pre-v1.2.0 (name-keyed) index file: treat as absent — it is a
            # rebuildable cache; delete it and rebuild-index.
            return {}

    def _chain_synced_query(self, out: dict[str, dict]) -> dict[str, dict]:
        with _ro(self.chain_index_path) as conn:
            for row in conn.execute(
                """SELECT s.registry_id, s.registry_name, s.head_block, s.synced_at,
                          (SELECT COUNT(*) FROM records r
                            WHERE r.registry_id = s.registry_id AND r.is_latest = 1) AS n
                     FROM sync_state s"""
            ):
                if row["n"]:
                    out[row["registry_name"]] = {
                        "registry_id": row["registry_id"],
                        "records": row["n"],
                        "synced_block": row["head_block"],
                        "synced_at": row["synced_at"],
                    }
        return out

    def _corpus_meta(self) -> dict[str, str]:
        if not self.corpus_path.is_file():
            return {}
        with _ro(self.corpus_path) as conn:
            return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}

    def coverage(self) -> list[dict]:
        """Per-registry provenance for the status panel; cached (the corpus
        count query scans 1.4M rows once)."""
        if self._coverage_cache is not None:
            return self._coverage_cache
        synced = self._chain_synced()
        meta = self._corpus_meta()
        rows: list[dict] = []
        corpus_courts = set((meta.get("courts") or "").split(",")) - {""}
        for registry, reporters in sorted(TRANCHE1_REPORTERS.items()):
            court = registry.removeprefix("us-")
            if registry in synced:
                rows.append({"registry": registry, "source": "chain-index", **synced[registry]})
            elif court in corpus_courts:
                with _ro(self.corpus_path) as conn:
                    marks = ",".join("?" * len(reporters))
                    n = conn.execute(
                        f"""SELECT COUNT(DISTINCT ci.canonical)
                              FROM citations ci JOIN clusters cl ON cl.cluster_id = ci.cluster_id
                             WHERE cl.court_id = ? AND ci.canonical IS NOT NULL
                               AND ci.reporter IN ({marks})""",
                        [court, *sorted(reporters)],
                    ).fetchone()[0]
                rows.append(
                    {
                        "registry": registry,
                        "source": "corpus-snapshot",
                        "records": n,
                        "snapshot": meta.get("snapshot", "?"),
                        "note": "chain bulk load in progress; lookups use the prepared corpus",
                    }
                )
        self._coverage_cache = rows
        return rows

    @property
    def covered(self) -> set[str]:
        return {row["registry"] for row in self.coverage()}

    # --- lookup ---

    def lookup_many(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], IndexHit]:
        """Resolve (registry, canonical) pairs; absent keys mean NOT_FOUND.

        Opens each database at most once per call; a registry not covered
        by any source contributes nothing (callers map that to
        NOT_COVERED before ever calling here).
        """
        keys = list(dict.fromkeys(keys))
        synced = self._chain_synced()
        hits: dict[tuple[str, str], IndexHit] = {}

        chain_keys = [k for k in keys if k[0] in synced]
        if chain_keys and self.chain_index_path.is_file():
            with _ro(self.chain_index_path) as conn:
                for registry, canonical in chain_keys:
                    # The local index only holds manifest registries, whose
                    # names are unique within it, so name-keyed local queries
                    # stay unambiguous (the CHAIN is queried by id only).
                    row = conn.execute(
                        """SELECT uri, metadata FROM records
                            WHERE registry_name = ? AND checksum = ? AND is_latest = 1""",
                        (registry, canonical),
                    ).fetchone()
                    if row:
                        hits[(registry, canonical)] = _hit_from_metadata(
                            registry, canonical, row["uri"], row["metadata"], "chain-index"
                        )

        corpus_keys = [k for k in keys if k[0] not in synced and k[0] in TRANCHE1_REPORTERS]
        if corpus_keys and self.corpus_path.is_file():
            with _ro(self.corpus_path) as conn:
                for registry, canonical in corpus_keys:
                    reporters = TRANCHE1_REPORTERS[registry]
                    marks = ",".join("?" * len(reporters))
                    rows = conn.execute(
                        f"""SELECT DISTINCT cl.cluster_id, cl.case_name, cl.year, cl.slug
                              FROM citations ci JOIN clusters cl ON cl.cluster_id = ci.cluster_id
                             WHERE ci.canonical = ? AND cl.court_id = ?
                               AND ci.reporter IN ({marks})
                             ORDER BY cl.cluster_id""",
                        [canonical, registry.removeprefix("us-"), *sorted(reporters)],
                    ).fetchall()
                    if rows:
                        cases = [
                            {"cluster": r["cluster_id"], "name": r["case_name"]}
                            | ({"year": r["year"]} if r["year"] is not None else {})
                            for r in rows
                        ]
                        hits[(registry, canonical)] = IndexHit(
                            registry=registry,
                            canonical=canonical,
                            uri=cluster_uri(rows[0]["cluster_id"], rows[0]["slug"]),
                            cases=cases,
                            collision=len(rows) > 1,
                            source="corpus-snapshot",
                        )
        return hits


def _hit_from_metadata(
    registry: str, canonical: str, uri: str, metadata: str, source: str
) -> IndexHit:
    """Decode a chain-index row's metadata JSON (single or collision form)."""
    cases: list[dict] = []
    collision = False
    try:
        parsed = json.loads(metadata)
        if isinstance(parsed, dict):
            if "cases" in parsed:
                collision = True
                cases = [c for c in parsed["cases"] if isinstance(c, dict)]
            elif "cluster" in parsed or "name" in parsed:
                cases = [parsed]
    except json.JSONDecodeError:
        pass
    return IndexHit(
        registry=registry,
        canonical=canonical,
        uri=uri,
        cases=cases,
        collision=collision,
        source=source,
    )
