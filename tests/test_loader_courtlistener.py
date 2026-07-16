"""Loader tests (task 2.1): COPY-csv dialect, three-pass join, canonical keys.

Fixtures are synthetic .csv.bz2 files written in the exact dialect measured
on the 2026-03-31 snapshot: unquoted header, every non-NULL data value
double-quoted, embedded quotes and backslashes BACKSLASH-escaped (the
PostgreSQL COPY ESCAPE convention -- not csv-style doubling), literal
newlines inside quoted values, NULL as a bare empty field.
"""

from __future__ import annotations

import bz2
import sqlite3
from pathlib import Path

import pytest

from nvnm_cite.loader.courtlistener import build_corpus
from nvnm_cite.normalizer import canonical_from_parts

DOCKETS_HEADER = (
    "id,date_created,date_modified,source,appeal_from_str,assigned_to_str,"
    "referred_to_str,panel_str,date_last_index,date_cert_granted,date_cert_denied,"
    "date_argued,date_reargued,date_reargument_denied,date_filed,date_terminated,"
    "date_last_filing,case_name_short,case_name,case_name_full,slug,docket_number,"
    "docket_number_core,pacer_case_id,cause,nature_of_suit,jury_demand,"
    "jurisdiction_type,appellate_fee_status,appellate_case_type_information,"
    "mdl_status,filepath_local,filepath_ia,filepath_ia_json,ia_upload_failure_count,"
    "ia_needs_upload,ia_date_first_change,view_count,date_blocked,blocked,"
    "appeal_from_id,assigned_to_id,court_id,idb_data_id,"
    "originating_court_information_id,referred_to_id,federal_dn_case_type,"
    "federal_dn_office_code,federal_dn_judge_initials_assigned,"
    "federal_dn_judge_initials_referred,federal_defendant_number,parent_docket_id,"
    "docket_number_raw,docket_number_source"
)
CLUSTERS_HEADER = (
    "id,date_created,date_modified,judges,date_filed,date_filed_is_approximate,"
    "slug,case_name_short,case_name,case_name_full,scdb_id,scdb_decision_direction,"
    "scdb_votes_majority,scdb_votes_minority,source,procedural_history,attorneys,"
    "nature_of_suit,posture,syllabus,headnotes,summary,disposition,history,"
    "other_dates,cross_reference,correction,citation_count,precedential_status,"
    "date_blocked,blocked,filepath_json_harvard,filepath_pdf_harvard,docket_id,"
    "arguments,headmatter"
)
CITATIONS_HEADER = "id,volume,reporter,page,type,cluster_id,date_created,date_modified"


def _copy_row(header: str, values: dict[str, str | None]) -> str:
    """One data row in the measured COPY dialect (None -> NULL, bare empty)."""
    cells = []
    for name in header.split(","):
        value = values.get(name)
        if value is None:
            cells.append("")
        else:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            cells.append('"' + escaped + '"')
    return ",".join(cells)


def _write_bulk(
    path: Path, header: str, rows: list[dict[str, str | None]], raw_tail: str = ""
) -> None:
    body = header + "\n" + "".join(_copy_row(header, r) + "\n" for r in rows) + raw_tail
    path.write_bytes(bz2.compress(body.encode("utf-8")))


@pytest.fixture()
def bulk_dir(tmp_path: Path) -> Path:
    snapshot = "2099-01-01"
    _write_bulk(
        tmp_path / f"dockets-{snapshot}.csv.bz2",
        DOCKETS_HEADER,
        [
            {"id": "101", "court_id": "scotus"},
            {"id": "102", "court_id": "ca11"},
            {"id": "103", "court_id": "lawd"},  # filtered out
            {"id": "104", "court_id": "ca11"},  # docket with no clusters
        ],
    )
    _write_bulk(
        tmp_path / f"opinion-clusters-{snapshot}.csv.bz2",
        CLUSTERS_HEADER,
        [
            {
                "id": "11",
                "docket_id": "101",
                "date_filed": "1973-01-22",
                "slug": "roe-v-wade",
                "case_name": 'Roe "Jane" v. Wade',  # embedded quotes
                "case_name_short": "Roe",
                "precedential_status": "Published",
                # multi-megabyte text columns exist in real data; embedded
                # newline inside a quoted value is the parser-breaking shape
                "syllabus": "line one\nline two, with comma",
            },
            {
                "id": "12",
                "docket_id": "102",
                "date_filed": "2019-05-31",
                "slug": None,  # NULL slug -> stored as ''
                "case_name": "",  # empty -> falls back to case_name_short
                "case_name_short": "Azar",
                "precedential_status": "Published",
            },
            {
                "id": "13",
                "docket_id": "103",  # wrong court, filtered
                "case_name": "Almeida v. USA",
            },
            {
                "id": "14",
                "docket_id": None,  # NULL docket, skipped
                "case_name": "Orphan",
            },
            {
                "id": "15",
                "docket_id": "102",
                "date_filed": "",  # no date -> year NULL
                "case_name": "Mystery v. Date",
                "precedential_status": "Unpublished",
            },
        ],
        # A structurally short row, as found in the real 2026-03-31 dump:
        # skipped, counted in meta, never fatal.
        raw_tail='"99","2020-01-01"\n',
    )
    _write_bulk(
        tmp_path / f"citations-{snapshot}.csv.bz2",
        CITATIONS_HEADER,
        [
            {"id": "1", "volume": "410", "reporter": "U.S.", "page": "113", "type": "1", "cluster_id": "11"},
            {"id": "2", "volume": "93", "reporter": "S. Ct.", "page": "705", "type": "1", "cluster_id": "11"},
            {"id": "3", "volume": "925", "reporter": "F.3d", "page": "1291", "type": "1", "cluster_id": "12"},
            {"id": "4", "volume": "007", "reporter": "F.3d", "page": "0042", "type": "1", "cluster_id": "15"},
            {"id": "5", "volume": "2019", "reporter": "WL", "page": "xvii", "type": "7", "cluster_id": "15"},
            {"id": "6", "volume": "1", "reporter": "X", "page": "1", "type": "1", "cluster_id": "13"},  # filtered court
            {"id": "7", "volume": "1", "reporter": "Y", "page": "1", "type": "1", "cluster_id": "999"},  # unknown cluster
            {"id": "8", "volume": "", "reporter": "F.3d", "page": "9", "type": "1", "cluster_id": "12"},  # no volume -> canonical NULL
        ],
    )
    return tmp_path


def test_three_pass_join(bulk_dir: Path) -> None:
    db_path = bulk_dir / "corpus.sqlite"
    stats = build_corpus(bulk_dir, "2099-01-01", db_path)
    assert stats["clusters"] == "3"
    # 6, not 5: the volume-less row stays (canonical NULL) so the census
    # can count citations that cannot be keyed.
    assert stats["citations"] == "6"

    db = sqlite3.connect(db_path)
    clusters = {
        row[0]: row
        for row in db.execute(
            "SELECT cluster_id, court_id, case_name, year, precedential_status, slug FROM clusters"
        )
    }
    assert set(clusters) == {11, 12, 15}
    assert clusters[11][1] == "scotus"
    assert clusters[11][2] == 'Roe "Jane" v. Wade'  # doubled quotes decoded
    assert clusters[11][3] == 1973
    assert clusters[12] == (12, "ca11", "Azar", 2019, "Published", "")
    assert clusters[15][3] is None  # empty date_filed -> year NULL

    canon = dict(db.execute("SELECT citation_id, canonical FROM citations"))
    assert set(canon) == {1, 2, 3, 4, 5, 8}
    assert canon[8] is None  # no volume -> no canonical key
    assert canon[1] == "410 U.S. 113"
    assert canon[2] == "93 S. Ct. 705"
    assert canon[4] == "7 F.3d 42"  # leading zeros stripped both sides
    assert canon[5] == "2019 WL xvii"  # non-numeric page preserved verbatim
    meta = dict(db.execute("SELECT key, value FROM meta"))
    assert meta["snapshot"] == "2099-01-01"
    assert meta["malformed_rows"] == "dockets=0,clusters=1,citations=0"
    db.close()


def test_all_courts_mode_keeps_every_court(bulk_dir: Path) -> None:
    db_path = bulk_dir / "corpus-all.sqlite"
    stats = build_corpus(bulk_dir, "2099-01-01", db_path, courts=("all",))
    # The lawd cluster (13) is now kept alongside the pilot courts; the
    # NULL-docket cluster (14) still is not.
    assert stats["clusters"] == "4"
    assert stats["citations"] == "7"
    assert stats["courts"] == "all"

    db = sqlite3.connect(db_path)
    courts = dict(db.execute("SELECT cluster_id, court_id FROM clusters"))
    assert courts == {11: "scotus", 12: "ca11", 13: "lawd", 15: "ca11"}
    # The lawd citation (id 6) survives with its canonical key.
    canon = dict(db.execute("SELECT citation_id, canonical FROM citations"))
    assert canon[6] == "1 X 1"
    db.close()


def test_existing_db_requires_force(bulk_dir: Path) -> None:
    db_path = bulk_dir / "corpus.sqlite"
    build_corpus(bulk_dir, "2099-01-01", db_path)
    with pytest.raises(FileExistsError):
        build_corpus(bulk_dir, "2099-01-01", db_path)
    stats = build_corpus(bulk_dir, "2099-01-01", db_path, force=True)
    assert stats["clusters"] == "3"


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_corpus(tmp_path, "2099-01-01", tmp_path / "corpus.sqlite")


def test_canonical_from_parts() -> None:
    assert canonical_from_parts("410", "U.S.", "113") == "410 U.S. 113"
    assert canonical_from_parts(410, "U.S.", "113") == "410 U.S. 113"
    assert canonical_from_parts("007", "F.3d", "0042") == "7 F.3d 42"
    assert canonical_from_parts("0", "F.3d", "0") == "0 F.3d 0"
    assert canonical_from_parts("181", "L.  Ed.  2d", "911") == "181 L. Ed. 2d 911"
    assert canonical_from_parts("2019", "WL", "xvii") == "2019 WL xvii"
    assert canonical_from_parts("", "U.S.", "113") is None
    assert canonical_from_parts("410", "", "113") is None
    assert canonical_from_parts("410", "U.S.", None) is None
