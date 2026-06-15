"""Aggregate RPC query telemetry (Phase 4 task 4.6; item 2b).

Item 0 makes every drafting-time citation lookup a live ``records()`` read,
which the NVNM-as-operator can observe. This module turns that into honest,
privacy-preserving analytics: it counts how often each CITATION is looked up,
and NOTHING ELSE — never the document a citation came from, never who asked.
The only state is ``(registry, citation) -> (lookups, hits)``.

Opt-in: a check resolves through ``NullTelemetry`` unless a real sink is
attached (CLI ``--telemetry``; the webapp operator enables it and discloses
it in the privacy copy). Thread-safe so the threaded webapp can share one
sink across requests.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Protocol


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TelemetrySink(Protocol):
    def record(self, registry: str, citation: str, found: bool) -> None: ...
    def close(self) -> None: ...


class NullTelemetry:
    """The default: records nothing. A check is telemetry-free unless an
    operator explicitly attaches a real sink."""

    def record(self, registry: str, citation: str, found: bool) -> None:  # noqa: D102
        pass

    def close(self) -> None:  # noqa: D102
        pass


class SqliteTelemetry:
    """Aggregate counts in SQLite, keyed by (registry, citation) only.

    Deliberately stores no document hash and no client identity — the privacy
    claim depends on this table being un-joinable to either. Thread-safe via a
    lock so the threaded webapp can share one instance.
    """

    def __init__(self, path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS query_telemetry (
                       registry   TEXT NOT NULL,
                       citation   TEXT NOT NULL,
                       lookups    INTEGER NOT NULL DEFAULT 0,
                       hits       INTEGER NOT NULL DEFAULT 0,
                       first_seen TEXT NOT NULL,
                       last_seen  TEXT NOT NULL,
                       PRIMARY KEY (registry, citation))"""
            )
            self._conn.commit()

    def record(self, registry: str, citation: str, found: bool) -> None:
        ts = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO query_telemetry (registry, citation, lookups, hits, first_seen, last_seen)
                       VALUES (?, ?, 1, ?, ?, ?)
                   ON CONFLICT(registry, citation) DO UPDATE SET
                       lookups = lookups + 1,
                       hits = hits + excluded.hits,
                       last_seen = excluded.last_seen""",
                (registry, citation, 1 if found else 0, ts, ts),
            )
            self._conn.commit()

    def top(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT registry, citation, lookups, hits FROM query_telemetry "
                "ORDER BY lookups DESC, citation LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"registry": r, "citation": c, "lookups": lk, "hits": h} for r, c, lk, h in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
