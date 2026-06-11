"""Reconcile tests (task 2.5): all three diff classes plus the clean path."""

from __future__ import annotations

from pathlib import Path

from nvnm_cite.chain.indexer import open_index, upsert_records
from nvnm_cite.chain.precompile import Record
from nvnm_cite.loader.bulk_load import open_state
from nvnm_cite.loader.reconcile import reconcile


def chain_record(checksum: str, metadata: str, uri: str = "u", algo: str = "cite-canonical-v1", status: str = "Active") -> Record:
    return Record(
        registry="us-ca11",
        uri=uri,
        checksum=checksum,
        checksum_algo=algo,
        metadata=metadata,
        timestamp="t",
        status=status,
        record_id=1,
        index=1,
        is_latest=True,
    )


def seed(state_path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    db = open_state(state_path)
    db.executemany(
        "INSERT INTO load_state (registry, checksum, uri, metadata, tranche, status, updated_at)"
        " VALUES ('us-ca11', ?, ?, ?, 't1', ?, 'now')",
        rows,
    )
    db.commit()
    db.close()


def test_reconcile_classes(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite"
    index_path = tmp_path / "index.sqlite"
    seed(
        state_path,
        [
            ("1 F.3d 1", "u", "m1", "confirmed"),  # matched
            ("2 F.3d 2", "u", "m2", "confirmed"),  # missing on chain
            ("3 F.3d 3", "u", "m3", "pending"),  # backlog, not a diff
            ("4 F.3d 4", "u", "m4", "confirmed"),  # metadata drift
        ],
    )
    idx = open_index(index_path)
    upsert_records(
        idx,
        [
            chain_record("1 F.3d 1", "m1"),
            chain_record("4 F.3d 4", "DIFFERENT"),
            chain_record("5 F.3d 5", "m5"),  # extra on chain
        ],
    )
    idx.commit()
    idx.close()

    report = reconcile(state_path, index_path, ["us-ca11"])
    assert report.matched == 1
    assert report.confirmed_missing == [("us-ca11", "2 F.3d 2")]
    assert report.backlog == {"pending": 1}
    assert report.extra == [("us-ca11", "5 F.3d 5")]
    assert report.drift == [("us-ca11", "4 F.3d 4", "metadata")]
    assert not report.clean


def test_reconcile_clean(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite"
    index_path = tmp_path / "index.sqlite"
    seed(state_path, [("1 F.3d 1", "u", "m1", "confirmed")])
    idx = open_index(index_path)
    upsert_records(idx, [chain_record("1 F.3d 1", "m1")])
    idx.commit()
    idx.close()
    report = reconcile(state_path, index_path, ["us-ca11"])
    assert report.clean
    assert report.matched == 1
