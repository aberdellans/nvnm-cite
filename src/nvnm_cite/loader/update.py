"""Daily incremental updater (plan task 2.7).

Keeps the testnet registries current between quarterly bulk loads by pulling
newly-available citations from the CourtListener REST API v4 and appending
them through the same locked schema and the same checkpoint DB the bulk
loader uses.

CURSOR = cluster `date_modified`, NOT `date_created`. Verified by probing
the live API (DECISIONS 2026-06-13): a freshly published opinion has an
empty `citations` list -- the reporter cite (volume/page) is added to the
cluster LATER, as a modification. A date_created cursor would therefore
miss every citation we key on. CL exposes no citation-level filter and no
standalone citations endpoint, so we page clusters by date_modified and let
idempotent INSERT-OR-IGNORE absorb the modified-but-no-new-cite churn.

Append-only and idempotent: each in-scope citation becomes a single-case
record; keys already in load_state are left untouched. Two things are out
of scope for the daily delta and remain the job of the quarterly bulk
reload + reconcile: (1) incremental collision MERGES (a new case landing on
the exact first page of an existing different case), and (2) metadata
corrections to existing keys. Both would need a superseding version, which
the daily append deliberately does not write.

The citation-LOOKUP API (250 cites/request, 60/min) is explicitly NOT used
here; it is a spot-check oracle only, per the plan. This updater uses only
the clusters LIST endpoint.

Run:  uv run python -m nvnm_cite.loader.update --dry-run
      uv run python -m nvnm_cite.loader.update --court ca11 --since 2026-03-31
      uv run python -m nvnm_cite.loader.update --submit   # chain write; needs OK
"""

from __future__ import annotations

import argparse
import http.client
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from nvnm_cite.loader.bulk_load import open_state
from nvnm_cite.loader.records import CaseRow, RecordError, RenderedRecord, render_record
from nvnm_cite.loader.scope import courts, registry_for_court, reporters_for_court
from nvnm_cite.normalizer import canonical_from_parts

CL_API_BASE = "https://www.courtlistener.com/api/rest/v4"
USER_AGENT = "nvnm-cite/0.1.0 (incremental updater; CourtListener bulk-data attribution)"


def parse_cl_datetime(value: str) -> datetime:
    """CL ISO timestamp (offset-aware) -> UTC datetime."""
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def normalize_since(value: str) -> str:
    """Accept a date or full ISO timestamp; return a UTC ISO query string."""
    text = value.strip()
    if len(text) == 10:  # bare YYYY-MM-DD
        text += "T00:00:00+00:00"
    return parse_cl_datetime(text).isoformat()


# --------------------------------------------------------------------------
# CourtListener REST client (stdlib only)
# --------------------------------------------------------------------------


class CourtListenerError(RuntimeError):
    pass


class CourtListenerClient:
    """Minimal token-authenticated client for the clusters list endpoint."""

    _TRANSPORT = (urllib.error.URLError, http.client.HTTPException, OSError)

    def __init__(
        self,
        token: str,
        base_url: str = CL_API_BASE,
        page_size: int = 100,
        timeout: float = 60.0,
        min_interval: float = 0.2,
        max_attempts: int = 5,
        log=lambda s: None,
    ):
        if not token:
            raise CourtListenerError("COURTLISTENER_TOKEN is required for incremental updates")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self.log = log

    def _get(self, url: str) -> dict:
        for attempt in range(1, self.max_attempts + 1):
            try:
                request = urllib.request.Request(
                    url, headers={"Authorization": f"Token {self.token}", "User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                # 429 = rate limited (honor Retry-After); 5xx = transient.
                if err.code == 429 and attempt < self.max_attempts:
                    wait = int(err.headers.get("Retry-After", "10"))
                    self.log(f"CL rate-limited; sleeping {wait}s")
                    time.sleep(wait)
                    continue
                if 500 <= err.code < 600 and attempt < self.max_attempts:
                    time.sleep(2 * attempt)
                    continue
                raise CourtListenerError(f"CL HTTP {err.code} on {url}") from err
            except self._TRANSPORT as err:
                if attempt < self.max_attempts:
                    self.log(f"transient {type(err).__name__} from CL; retry {attempt}")
                    time.sleep(2 * attempt)
                    continue
                raise CourtListenerError(f"CL transport failure: {err}") from err
        raise CourtListenerError("unreachable")

    def iter_clusters(
        self, court: str, modified_since_iso: str, max_clusters: int | None = None
    ) -> Iterator[dict]:
        """Yield clusters for one court modified at/after the cursor, oldest
        modification first (so a capped run resumes cleanly next time)."""
        query = urllib.parse.urlencode(
            {
                "docket__court": court,
                "date_modified__gte": modified_since_iso,
                "order_by": "date_modified",
                "page_size": self.page_size,
            }
        )
        url: str | None = f"{self.base_url}/clusters/?{query}"
        yielded = 0
        while url:
            page = self._get(url)
            for cluster in page.get("results", []):
                yield cluster
                yielded += 1
                if max_clusters is not None and yielded >= max_clusters:
                    return
            url = page.get("next")
            if url and self.min_interval:
                time.sleep(self.min_interval)


# --------------------------------------------------------------------------
# Rendering: cluster JSON -> chain-ready records (locked schema)
# --------------------------------------------------------------------------


def cluster_to_records(
    cluster: dict, reporters: frozenset[str], registry: str
) -> tuple[list[RenderedRecord], int]:
    """Render every in-scope citation on a cluster into single-case records.

    Parallel citations (e.g. U.S. + S. Ct. on one SCOTUS decision) yield one
    record each, sharing the cluster. Returns (records, skipped_caps)."""
    cluster_id = int(cluster["id"])
    name = cluster.get("case_name") or cluster.get("case_name_short") or ""
    date_filed = cluster.get("date_filed") or ""
    year = int(date_filed[:4]) if len(date_filed) >= 4 and date_filed[:4].isdigit() else None
    case = CaseRow(cluster_id, name, year, cluster.get("slug") or "")

    records: list[RenderedRecord] = []
    seen: set[str] = set()
    skipped = 0
    for citation in cluster.get("citations") or []:
        if citation.get("reporter") not in reporters:
            continue
        canonical = canonical_from_parts(
            citation.get("volume"), citation.get("reporter"), citation.get("page")
        )
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        try:
            records.append(render_record(registry, canonical, [case]))
        except RecordError:
            skipped += 1
    return records, skipped


# --------------------------------------------------------------------------
# Cursor (stored in the checkpoint DB's meta table)
# --------------------------------------------------------------------------


def _get_meta(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    db.commit()


def corpus_snapshot_iso(corpus_path: Path) -> str | None:
    """Default first-run cursor: the bulk snapshot date (data is current as
    of then, so we want everything modified since)."""
    if not corpus_path.is_file():
        return None
    db = sqlite3.connect(corpus_path)
    try:
        row = db.execute("SELECT value FROM meta WHERE key = 'snapshot'").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        db.close()
    return normalize_since(row[0]) if row else None


# --------------------------------------------------------------------------
# The update pass
# --------------------------------------------------------------------------


@dataclass
class UpdateStats:
    registry: str
    cursor_from: str
    cursor_to: str
    examined: int = 0
    clusters_with_new: int = 0
    appended: int = 0
    skipped_caps: int = 0
    capped: bool = False
    sample: list[str] = field(default_factory=list)


def update_court(
    court: str,
    client: CourtListenerClient,
    db: sqlite3.Connection,
    *,
    dry_run: bool,
    since: str | None = None,
    default_since: str | None = None,
    max_clusters: int | None = None,
    log=lambda s: None,
) -> UpdateStats:
    registry = registry_for_court(court)
    reporters = frozenset(reporters_for_court(court))
    cursor = since or _get_meta(db, f"update_cursor:{registry}") or default_since
    if not cursor:
        raise CourtListenerError(
            f"{registry}: no cursor available; pass --since or build corpus.sqlite first"
        )
    start = parse_cl_datetime(cursor)
    stats = UpdateStats(registry=registry, cursor_from=start.isoformat(), cursor_to=start.isoformat())
    log(f"{registry}: scanning clusters modified >= {start.isoformat()}")

    max_seen = start
    dry_new: set[str] = set()
    examined = 0
    for cluster in client.iter_clusters(court, start.isoformat(), max_clusters):
        examined += 1
        modified = cluster.get("date_modified")
        if modified:
            dt = parse_cl_datetime(modified)
            if dt > max_seen:
                max_seen = dt
        records, skipped = cluster_to_records(cluster, reporters, registry)
        stats.skipped_caps += skipped
        if not records:
            continue
        added_here = 0
        for rec in records:
            if dry_run:
                if rec.checksum in dry_new:
                    continue
                exists = db.execute(
                    "SELECT 1 FROM load_state WHERE registry = ? AND checksum = ?",
                    (rec.registry, rec.checksum),
                ).fetchone()
                if not exists:
                    dry_new.add(rec.checksum)
                    added_here += 1
            else:
                cur = db.execute(
                    "INSERT OR IGNORE INTO load_state"
                    " (registry, checksum, uri, metadata, tranche, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (rec.registry, rec.checksum, rec.uri, rec.metadata, "update", _now()),
                )
                added_here += cur.rowcount
        if added_here:
            stats.clusters_with_new += 1
            stats.appended += added_here
            if len(stats.sample) < 10:
                stats.sample.extend(r.checksum for r in records[:added_here])
    if not dry_run:
        db.commit()

    stats.examined = examined
    stats.capped = max_clusters is not None and examined >= max_clusters
    stats.cursor_to = max_seen.isoformat()
    # Advance the cursor only on a real run. gte is inclusive and the append
    # is idempotent, so re-including the boundary timestamp next run is safe.
    if not dry_run and stats.cursor_to != stats.cursor_from:
        _set_meta(db, f"update_cursor:{registry}", stats.cursor_to)
    return stats


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def print_stats(stats: UpdateStats, dry_run: bool) -> None:
    verb = "WOULD append" if dry_run else "appended"
    print(
        f"{stats.registry}: examined {stats.examined:,} clusters, "
        f"{verb} {stats.appended:,} new keys from {stats.clusters_with_new:,} clusters"
        + (f", {stats.skipped_caps} skipped (caps)" if stats.skipped_caps else "")
    )
    print(f"  cursor: {stats.cursor_from}  ->  {stats.cursor_to}" + ("  [CAPPED]" if stats.capped else ""))
    for key in stats.sample[:10]:
        print(f"    + {stats.registry}  {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", type=Path, default=Path("data/load_state.sqlite"))
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus.sqlite"))
    parser.add_argument("--court", action="append", help="restrict to a court (repeatable); default: all in scope")
    parser.add_argument("--since", help="override cursor (YYYY-MM-DD or ISO ts); applies to every court this run")
    parser.add_argument("--max-clusters", type=int, default=None, help="per-court safety cap (resumable)")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="report what would append; write nothing")
    parser.add_argument("--submit", action="store_true", help="after appending, run the chain load (needs OK)")
    args = parser.parse_args(argv)

    from nvnm_cite.config import load_dotenv

    load_dotenv()
    import os

    token = os.environ.get("COURTLISTENER_TOKEN", "")
    client = CourtListenerClient(token, page_size=args.page_size, log=lambda s: print(f"  {s}", flush=True))
    db = open_state(args.state)
    default_since = corpus_snapshot_iso(args.corpus)
    since = normalize_since(args.since) if args.since else None

    target_courts = args.court or list(courts())
    total_appended = 0
    for court in target_courts:
        stats = update_court(
            court,
            client,
            db,
            dry_run=args.dry_run,
            since=since,
            default_since=default_since,
            max_clusters=args.max_clusters,
            log=lambda s: print(s, flush=True),
        )
        print_stats(stats, args.dry_run)
        total_appended += stats.appended

    if args.submit and not args.dry_run and total_appended:
        print(f"\n--submit: loading {total_appended:,} newly-appended records to chain")
        from nvnm_cite.chain.rpc import EvmRpc
        from nvnm_cite.chain.secp256k1 import address_from_private_key
        from nvnm_cite.config import testnet_private_key, testnet_rpc
        from nvnm_cite.loader.bulk_load import print_status, run_load

        rpc = EvmRpc(testnet_rpc())
        key = testnet_private_key()
        run_load(db, rpc, key)
        print_status(db, rpc, address_from_private_key(key))
    elif args.submit and not total_appended:
        print("\n--submit: nothing new to load")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
