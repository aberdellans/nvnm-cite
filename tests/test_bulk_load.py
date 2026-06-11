"""Bulk loader tests (task 2.4): prepare rendering/filtering/idempotency and
the run loop's checkpoint state machine against a fake RPC."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import nvnm_cite.loader.bulk_load as bl
from nvnm_cite.config import TESTNET_CHAIN_ID
from nvnm_cite.loader.bulk_load import open_state, prepare, recover_submitted, run_load

TEST_KEY = 0xA11CE  # throwaway scalar; never a funded key

CORPUS_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE clusters (
    cluster_id INTEGER PRIMARY KEY, docket_id INTEGER NOT NULL,
    court_id TEXT NOT NULL, case_name TEXT NOT NULL DEFAULT '',
    date_filed TEXT NOT NULL DEFAULT '', year INTEGER,
    precedential_status TEXT NOT NULL DEFAULT '', slug TEXT NOT NULL DEFAULT ''
);
CREATE TABLE citations (
    citation_id INTEGER PRIMARY KEY, cluster_id INTEGER NOT NULL,
    volume TEXT NOT NULL DEFAULT '', reporter TEXT NOT NULL DEFAULT '',
    page TEXT NOT NULL DEFAULT '', type INTEGER, canonical TEXT
);
"""


def make_corpus(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(CORPUS_SCHEMA)
    db.executemany(
        "INSERT INTO clusters VALUES (?,?,?,?,?,?,?,?)",
        [
            (11, 1, "ca11", "A v. B", "2019-05-31", 2019, "Published", "a-v-b"),
            (12, 2, "ca11", "C v. D", "2019-06-01", 2019, "Published", "c-v-d"),
            (13, 3, "ca11", "Unpub v. Order", "2020-01-01", 2020, "Unpublished", ""),
            (21, 4, "scotus", "Roe v. Wade", "1973-01-22", 1973, "Published", "roe-v-wade"),
            (22, 5, "scotus", "Mem. Order", "2001-10-01", 2001, "Unpublished", ""),
        ],
    )
    db.executemany(
        "INSERT INTO citations VALUES (?,?,?,?,?,?,?)",
        [
            (1, 11, "900", "F.3d", "100", 1, "900 F.3d 100"),
            (2, 12, "900", "F.3d", "100", 1, "900 F.3d 100"),  # collision with 11
            (3, 11, "2019", "WL", "555", 7, "2019 WL 555"),  # vendor type, filtered by --types
            (4, 13, "901", "F.3d", "200", 1, "901 F.3d 200"),
            (5, 13, "902", "Bogus Rep.", "1", 1, "902 Bogus Rep. 1"),  # unknown edition
            (6, 21, "410", "U.S.", "113", 1, "410 U.S. 113"),
            (7, 22, "534", "U.S.", "888", 1, "534 U.S. 888"),
            (8, 21, "410", "U.S.", "", 1, None),  # no canonical, ignored
        ],
    )
    db.execute("INSERT INTO meta VALUES ('snapshot', '2099-01-01')")
    db.commit()
    db.close()


def test_prepare_renders_filters_and_is_idempotent(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.sqlite"
    state_path = tmp_path / "load_state.sqlite"
    make_corpus(corpus)

    stats = prepare(corpus, state_path, "ca11", ("F.3d",), "t1-ca11")
    assert stats["rendered"] == 2  # the collision key + 901 F.3d 200
    assert stats["collisions"] == 1
    assert stats["excluded_reporter"] == 0  # WL and Bogus Rep. never selected

    db = sqlite3.connect(state_path)
    rows = {
        checksum: (uri, metadata)
        for checksum, uri, metadata in db.execute("SELECT checksum, uri, metadata FROM load_state")
    }
    assert set(rows) == {"900 F.3d 100", "901 F.3d 200"}
    assert '"cases":[' in rows["900 F.3d 100"][1]  # collision form
    assert rows["900 F.3d 100"][0].endswith("/opinion/11/a-v-b/")  # lowest cluster's uri
    assert rows["901 F.3d 200"][0].endswith("/api/rest/v4/clusters/13/")  # slugless fallback
    db.close()

    again = prepare(corpus, state_path, "ca11", ("F.3d",), "t1-ca11")
    assert again["rendered"] == 0
    assert again["existing"] == 2

    # A whitelisted reporter that is not a reporters-db edition is excluded
    # with a stored reason (belt and suspenders for whitelist typos).
    bogus = prepare(corpus, state_path, "ca11", ("Bogus Rep.",), "t1-bogus")
    assert bogus["rendered"] == 0
    assert bogus["excluded_reporter"] == 1
    db = sqlite3.connect(state_path)
    reasons = dict(db.execute("SELECT canonical, reason FROM excluded"))
    assert "902 Bogus Rep. 1" in reasons
    db.close()

    scotus = prepare(corpus, state_path, "scotus", ("U.S.",), "t1-scotus", precedential_only=True)
    assert scotus["rendered"] == 1  # Roe only; the Unpublished memo is out
    db = sqlite3.connect(state_path)
    assert db.execute("SELECT COUNT(*) FROM load_state").fetchone()[0] == 3
    db.close()


class FakeRpc:
    """The chain as the loader sees it: instant inclusion, nonce-advance
    confirmation. Deliberately has NO estimate_gas: the optimized loader
    must never call it (gas comes from the measured curve)."""

    BASE_NONCE = 270  # mid-stream account, matches phase-0 reality

    def __init__(self) -> None:
        self.receipts: dict[str, dict] = {}
        self.confirmed_calldata: list[bytes] = []
        self.block = 1_600_000

    def chain_id(self) -> int:
        return TESTNET_CHAIN_ID

    def get_transaction_count(self, _address: str, _tag: str = "pending") -> int:
        # Instant inclusion: latest == pending == base + everything sent.
        return self.BASE_NONCE + len(self.receipts)

    def gas_price(self) -> int:
        return 45_000_000_000

    def send_raw_transaction(self, raw: bytes) -> str:
        tx_hash = "0x" + hashlib.sha256(raw).hexdigest()
        self.block += 1
        self.receipts[tx_hash] = {
            "status": "0x1",
            "gasUsed": hex(96_219),
            "blockNumber": hex(self.block),
        }
        self.confirmed_calldata.append(raw)
        return tx_hash

    def get_transaction_receipt(self, tx_hash: str) -> dict | None:
        return self.receipts.get(tx_hash)

    def get_balance(self, _address: str) -> int:
        return 3_000 * 10**18


def seed_state(path: Path, n: int) -> None:
    db = open_state(path)
    db.executemany(
        "INSERT INTO load_state (registry, checksum, uri, metadata, tranche, updated_at)"
        " VALUES (?,?,?,?,?,?)",
        [
            (
                "us-ca11",
                f"{900 + i} F.3d {100 + i}",
                f"https://example.test/{i}",
                f'{{"cluster":{i},"name":"Case {i}","year":2019}}',
                "t1",
                "now",
            )
            for i in range(n)
        ],
    )
    db.commit()
    db.close()


def test_run_load_confirms_all_with_sequential_nonces(tmp_path: Path) -> None:
    state_path = tmp_path / "load_state.sqlite"
    seed_state(state_path, 60)
    db = open_state(state_path)
    rpc = FakeRpc()

    counters = run_load(db, rpc, TEST_KEY, depth=5, log=lambda s: None)
    assert counters["confirmed"] == 60
    statuses = dict(db.execute("SELECT status, COUNT(*) FROM load_state GROUP BY status"))
    assert statuses == {"confirmed": 60}
    nonces = [n for (n,) in db.execute("SELECT nonce FROM load_state ORDER BY position")]
    assert nonces == list(range(270, 330))  # strictly serialized, no gaps
    # Receipts are SAMPLED (every 50th nonce): exactly nonce 300 here.
    sampled = db.execute(
        "SELECT nonce, gas_used FROM load_state WHERE gas_used IS NOT NULL"
    ).fetchall()
    assert sampled == [(300, 96_219)]
    db.close()


def test_run_load_max_records_probe_stops_cleanly(tmp_path: Path) -> None:
    state_path = tmp_path / "load_state.sqlite"
    seed_state(state_path, 12)
    db = open_state(state_path)
    counters = run_load(db, FakeRpc(), TEST_KEY, depth=5, log=lambda s: None, max_records=3)
    assert counters["confirmed"] == 3
    statuses = dict(db.execute("SELECT status, COUNT(*) FROM load_state GROUP BY status"))
    assert statuses == {"confirmed": 3, "pending": 9}
    db.close()


def test_recover_submitted_settles_by_keyed_read(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "load_state.sqlite"
    seed_state(state_path, 3)
    db = open_state(state_path)
    db.execute("UPDATE load_state SET status='submitted', nonce=5 WHERE position IN (1, 2)")
    db.commit()

    # Row 1's key is on chain (previous run landed it); row 2's is not.
    monkeypatch.setattr(
        bl,
        "chain_has_key",
        lambda _rpc, _registry, checksum, _log=None: checksum == "900 F.3d 100",
    )
    recover_submitted(db, FakeRpc(), "0x" + "11" * 20, log=lambda s: None)
    statuses = dict(db.execute("SELECT position, status FROM load_state"))
    assert statuses == {1: "confirmed", 2: "pending", 3: "pending"}
    assert db.execute("SELECT nonce FROM load_state WHERE position=2").fetchone() == (None,)
    db.close()
