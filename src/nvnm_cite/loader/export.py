"""Mainnet bulk-load export (Phase 7): per-registry chain-ready record files.

Renders the full-scope corpus (all courts) into one gzipped JSONL file per
court registry, in SUBMIT shape: exactly the six fields a writer sends to
addRecord (registry, checksum, checksumAlgo, uri, metadata, status). Every
record renders through loader/records.py — the same collision-grouping and
truncation code the testnet load used — so these files are byte-identical
to what our own checkpointed loader would submit.

Scope rule (v2, full scope; DECISIONS 2026-06-24 census rule, supersedes the
pilot per-court reporter whitelists in loader/scope.py for the mainnet set):
a citation row is registry-eligible iff its CL type is 1 (federal),
2 (state), 3 (state_regional), 5 (scotus_early) or 8 (neutral) — vendor
cites (4 specialty, 6 LEXIS, 7 West/WL) stay out — AND its reporter string
is a reporters-db edition (the cite-canonical/v1 key space). Exclusions are
counted per registry in the manifest, never silent.

Output layout (the blockchain-team handoff; load order = tranche order):
    README.md         handoff notes, figures rendered from the manifest
    registries.json   addRegistry inputs for every court, tranche-tagged
    manifest.json     per-file record counts, bytes, sha256
    tranche-1-federal-appellate/us-scotus.jsonl.gz ...
    tranche-2-federal-complete/...
    tranche-3-state-pilot/...
    tranche-4-state-remainder/...

Run:  uv run python -m nvnm_cite.loader.export \
          --corpus data/corpus.sqlite --out data/mainnet-full-export
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from nvnm_cite.loader.bulk_load import known_editions
from nvnm_cite.loader.records import (
    CaseRow,
    RecordError,
    compact_json,
    creation_strings,
    render_record,
)

# CL citation types (cl/citations/models.py): 1 federal, 2 state,
# 3 state_regional, 4 specialty, 5 scotus_early, 6 lexis, 7 west, 8 neutral.
ELIGIBLE_TYPES = (1, 2, 3, 5, 8)

TRANCHE1_COURTS = (
    "scotus",
    *(f"ca{i}" for i in range(1, 12)),
    "cadc",
    "cafc",
)
STATE_PILOT_LOCATIONS = frozenset(
    {"California", "New York", "Texas", "Florida", "Illinois"}
)
TRANCHE_DIRS = {
    1: "tranche-1-federal-appellate",
    2: "tranche-2-federal-complete",
    3: "tranche-3-state-pilot",
    4: "tranche-4-state-remainder",
}


@dataclass(frozen=True)
class CourtClass:
    court_id: str
    tranche: int
    system: str
    location: str
    court_name: str
    in_courts_db: bool


def _courts_db_index() -> dict[str, dict]:
    from courts_db import courts

    return {c["id"]: c for c in courts}


def classify_court(court_id: str, by_id: dict[str, dict]) -> CourtClass:
    """Tranche assignment per the Phase 7 ladder. Courts missing from
    courts-db land VISIBLY in tranche 4 with system 'unknown' — the manifest
    flags them; nothing is dropped silently."""
    entry = by_id.get(court_id)
    if entry is None:
        return CourtClass(court_id, 4, "unknown", "", court_id, False)
    system = entry.get("system") or ""
    location = entry.get("location") or ""
    name = entry.get("name") or court_id
    if court_id in TRANCHE1_COURTS:
        tranche = 1
    elif system == "federal":
        tranche = 2
    elif system == "state" and location in STATE_PILOT_LOCATIONS:
        tranche = 3
    else:
        tranche = 4
    return CourtClass(court_id, tranche, system, location, name, True)


def _submit_line(registry: str, checksum: str, uri: str, metadata: str) -> bytes:
    return (
        compact_json(
            {
                "registry": registry,
                "checksum": checksum,
                "checksumAlgo": "cite-canonical-v1",
                "uri": uri,
                "metadata": metadata,
                "status": "Active",
            }
        )
        + "\n"
    ).encode("utf-8")


def export_court(
    corpus: sqlite3.Connection,
    court: str,
    out_path: Path,
    editions: frozenset[str],
) -> dict:
    """Render one court's registry file; returns its manifest entry (stats
    filled in; classification added by the caller)."""
    registry = f"us-{court}"
    rows = corpus.execute(
        f"""
        SELECT ci.canonical, ci.reporter, cl.cluster_id, cl.case_name, cl.year, cl.slug
        FROM citations ci JOIN clusters cl USING (cluster_id)
        WHERE cl.court_id = ? AND ci.canonical IS NOT NULL
          AND ci.type IN ({','.join('?' * len(ELIGIBLE_TYPES))})
        ORDER BY ci.canonical, cl.cluster_id
        """,
        (court, *ELIGIBLE_TYPES),
    )

    stats = {
        "records": 0,
        "collisions": 0,
        "excluded_reporter": 0,
        "excluded_caps": 0,
        "bytes_uncompressed": 0,
    }
    raw_hash = hashlib.sha256()

    # Group rows by canonical key exactly as bulk_load.prepare does: dedupe
    # clusters within a key; a key whose reporter is not a reporters-db
    # edition is excluded (counted); render through the locked schema code.
    def flush(sink, canonical: str | None, group: dict[int, CaseRow], ok: bool) -> None:
        if canonical is None or not group:
            return
        if not ok:
            stats["excluded_reporter"] += 1
            return
        try:
            rec = render_record(registry, canonical, list(group.values()))
        except RecordError:
            stats["excluded_caps"] += 1
            return
        if len(group) > 1:
            stats["collisions"] += 1
        line = _submit_line(rec.registry, rec.checksum, rec.uri, rec.metadata)
        sink.write(line)
        raw_hash.update(line)
        stats["records"] += 1
        stats["bytes_uncompressed"] += len(line)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 so identical content gzips to identical bytes across runs.
    with open(out_path, "wb") as fh, gzip.GzipFile(
        filename="", fileobj=fh, mode="wb", mtime=0
    ) as sink:
        current: str | None = None
        group: dict[int, CaseRow] = {}
        reporter_ok = True
        for canonical, reporter, cluster_id, name, year, slug in rows:
            if canonical != current:
                flush(sink, current, group, reporter_ok)
                current, group, reporter_ok = canonical, {}, reporter in editions
            group.setdefault(cluster_id, CaseRow(cluster_id, name, year, slug))
        flush(sink, current, group, reporter_ok)

    if stats["records"] == 0:
        out_path.unlink()
        return {"registry": registry, **stats}

    gz_bytes = out_path.read_bytes()
    return {
        "registry": registry,
        **stats,
        "bytes_gz": len(gz_bytes),
        "sha256_gz": hashlib.sha256(gz_bytes).hexdigest(),
        "sha256_uncompressed": raw_hash.hexdigest(),
    }


def export(corpus_path: Path, out_dir: Path, only_courts: tuple[str, ...] = ()) -> dict:
    corpus = sqlite3.connect(corpus_path)
    meta = dict(corpus.execute("SELECT key, value FROM meta"))
    by_id = _courts_db_index()
    editions = known_editions()

    courts = [
        r[0]
        for r in corpus.execute("SELECT DISTINCT court_id FROM clusters ORDER BY court_id")
    ]
    if only_courts:
        courts = [c for c in courts if c in only_courts]

    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    registries: list[dict] = []
    skipped_no_records: list[str] = []
    started = time.monotonic()

    for i, court in enumerate(courts, 1):
        cls = classify_court(court, by_id)
        rel = f"{TRANCHE_DIRS[cls.tranche]}/us-{court}.jsonl.gz"
        entry = export_court(corpus, court, out_dir / rel, editions)
        if entry["records"] == 0:
            skipped_no_records.append(court)
            continue
        entry.update(
            file=rel,
            court=court,
            court_name=cls.court_name,
            system=cls.system,
            tranche=cls.tranche,
            in_courts_db=cls.in_courts_db,
        )
        files.append(entry)

        if cls.in_courts_db:
            name, description, reg_metadata = creation_strings(court)
        else:
            # No courts-db entry: same template with the raw id as the name;
            # flagged for review, never dropped.
            name = f"us-{court}"
            description = (
                f"Canonical US case citations for {court} (courts-db: {court}). "
                "Existence registry: a record means this citation string denotes "
                "a published decision. nvnm-cite."
            )
            reg_metadata = compact_json(
                {
                    "court": court,
                    "schema": "nvnm-cite-record/v1",
                    "source": "CourtListener bulk data, Free Law Project (courtlistener.com)",
                    "spec": "cite-canonical-v1",
                }
            )
        registries.append(
            {
                "name": name,
                "description": description,
                "metadata": reg_metadata,
                "tranche": cls.tranche,
                "court": court,
                "court_name": cls.court_name,
                "system": cls.system,
                "in_courts_db": cls.in_courts_db,
                "records": entry["records"],
            }
        )
        if i % 50 == 0 or entry["records"] >= 100_000:
            print(
                f"  [{i}/{len(courts)}] us-{court}: {entry['records']:,} records "
                f"({time.monotonic() - started:,.0f}s elapsed)",
                flush=True,
            )

    registries.sort(key=lambda r: (r["tranche"], r["name"]))
    files.sort(key=lambda f: (f["tranche"], f["registry"]))

    manifest = {
        "schema": "nvnm-cite-mainnet-export/v1",
        "snapshot": meta.get("snapshot"),
        "corpus_built_at": meta.get("built_at"),
        "scope": (
            "CL citation types 1,2,3,5,8 (vendor cites 4,6,7 excluded) + "
            "reporters-db edition check; keys per cite-canonical/v1"
        ),
        "totals": {
            "registries": len(files),
            "records": sum(f["records"] for f in files),
            "collisions": sum(f["collisions"] for f in files),
            "excluded_reporter": sum(f["excluded_reporter"] for f in files),
            "excluded_caps": sum(f["excluded_caps"] for f in files),
            "bytes_uncompressed": sum(f["bytes_uncompressed"] for f in files),
            "bytes_gz": sum(f["bytes_gz"] for f in files),
            "by_tranche": {
                str(t): {
                    "registries": sum(1 for f in files if f["tranche"] == t),
                    "records": sum(f["records"] for f in files if f["tranche"] == t),
                }
                for t in sorted({f["tranche"] for f in files})
            },
        },
        "courts_without_eligible_records": skipped_no_records,
        "files": files,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "registries.json").write_text(
        json.dumps(registries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "README.md").write_text(_readme(manifest), encoding="utf-8")
    return manifest


def _readme(manifest: dict) -> str:
    totals = manifest["totals"]
    tranche_rows = "\n".join(
        f"| {TRANCHE_DIRS[int(t)]} | {sub['registries']:,} | {sub['records']:,} |"
        for t, sub in totals["by_tranche"].items()
    )
    return f"""# nvnm-cite — mainnet bulk-load export (full US case-law scope)

Generated from the CourtListener bulk snapshot {manifest['snapshot']}
(corpus built {manifest['corpus_built_at']}). One gzipped JSONL file per
court registry; every line is one addRecord submission in SUBMIT shape —
exactly the six writer fields:

| Field | Value |
|---|---|
| `registry` | `us-<courts-db id>` (matches the file name) |
| `checksum` | the canonical citation string in PLAINTEXT (`410 U.S. 113`) — the lookup key, never a hash; <= 64 bytes |
| `checksumAlgo` | fixed `cite-canonical-v1` |
| `uri` | CourtListener cluster URL |
| `metadata` | compact JSON: `{{"cluster":…,"name":…,"year":…}}`, or `{{"cases":[…]}}` when distinct decisions share one first-page key; <= 2048 bytes with deterministic truncation |
| `status` | `Active` |

The chain assigns the remaining four record fields (timestamp, recordId,
index, isLatest) on write. These files were rendered by the same code that
produced the live testnet load (260,763 records, 0 failures, 0 reverts) and
are byte-for-byte what our own checkpointed loader would submit.

## Contents

| Tranche directory (load in this order) | Registries | Records |
|---|---:|---:|
{tranche_rows}

Totals: {totals['registries']:,} registries, {totals['records']:,} records,
{totals['bytes_uncompressed'] / 1e9:.2f} GB uncompressed
({totals['bytes_gz'] / 1e9:.2f} GB as shipped). Per-file record counts,
byte sizes, and sha256 digests (of the .gz as shipped and of the
uncompressed stream) are in `manifest.json` — verify before loading.

Scope rule: {manifest['scope']}. Excluded rows are counted per registry in
the manifest (`excluded_reporter`, `excluded_caps`), never dropped silently.

## Registry creation and ownership

`registries.json` holds the exact `addRegistry` inputs (name, description,
metadata) for every registry, tranche-tagged. Two requirements:

1. **Creator = admin, permanently** (writes are deny-by-default). The
   registries must be created by the Inveniam-held mainnet key from the key
   ceremony — not by a loader key. Loader keys are then granted editor on
   each registry via `grantRole`, and can be revoked with `revokeRole` after
   the load.
2. The Free Law Project attribution in each registry's metadata must be
   preserved verbatim.

## Chain behaviors the loader must handle (all measured on testnet)

- Duplicate (registry, checksum) submissions VERSION rather than revert:
  idempotency is entirely the writer's job. Use a checkpoint DB; never
  blind-resubmit; on resume, re-verify the in-flight window via keyed
  `records(registry, checksum)` reads (a keyed miss ERRORS with
  `collections: not found`, never an empty page).
- Registry names are unique chain-wide; creation is idempotent via an
  estimate-probe.
- `uri`, `checksumAlgo`, `metadata` are required non-empty (`{{}}` counts as
  empty) — every line in these files already satisfies this.
- Nonce-gapped submission is rejected; submission is strictly serialized per
  key. Measured single-key throughput ~2.1 tx/s (submission-bound), ~96k gas
  per average record, 40 gwei floor / 45 gwei suggested. At this scale plan
  a parallel editor-granted key fleet.
- Load order follows the tranche directories; each tranche should reconcile
  clean (our `reconcile` tooling is available) before the next begins.

## Attribution

Case data derives from CourtListener bulk data, Free Law Project
(courtlistener.com), used with attribution. The attribution in each
registry's metadata must be preserved on mainnet.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus.sqlite"))
    parser.add_argument("--out", type=Path, default=Path("data/mainnet-full-export"))
    parser.add_argument(
        "--courts", default="", help="optional comma-separated court subset (debugging)"
    )
    args = parser.parse_args(argv)

    only = tuple(c.strip() for c in args.courts.split(",") if c.strip())
    manifest = export(args.corpus, args.out, only)
    totals = manifest["totals"]
    print(
        f"\nexport complete: {totals['registries']:,} registries, "
        f"{totals['records']:,} records, "
        f"{totals['bytes_uncompressed'] / 1e9:.2f} GB raw / "
        f"{totals['bytes_gz'] / 1e9:.2f} GB gz"
    )
    for t, sub in totals["by_tranche"].items():
        print(f"  tranche {t}: {sub['registries']:,} registries, {sub['records']:,} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
