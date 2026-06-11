"""Record rendering tests: the locked schema's serialization + truncation
rules (docs/record-schema.md sections 3.1-3.3) pinned executable."""

from __future__ import annotations

import json

import pytest

from nvnm_cite.loader.records import (
    METADATA_CAP,
    CaseRow,
    RecordError,
    cluster_uri,
    render_record,
    truncate_utf8,
)


def case(cluster_id: int = 108713, name: str = "Roe v. Wade", year: int | None = 1973, slug: str = "roe-v-wade") -> CaseRow:
    return CaseRow(cluster_id, name, year, slug)


def test_single_form_exact_serialization() -> None:
    rec = render_record("us-scotus", "410 U.S. 113", [case()])
    assert rec.metadata == '{"cluster":108713,"name":"Roe v. Wade","year":1973}'
    assert rec.uri == "https://www.courtlistener.com/opinion/108713/roe-v-wade/"
    assert rec.checksum == "410 U.S. 113"


def test_year_omitted_when_unknown() -> None:
    rec = render_record("us-scotus", "410 U.S. 113", [case(year=None)])
    assert json.loads(rec.metadata) == {"cluster": 108713, "name": "Roe v. Wade"}


def test_uri_fallback_without_slug() -> None:
    assert cluster_uri(42, "") == "https://www.courtlistener.com/api/rest/v4/clusters/42/"
    rec = render_record("us-ca11", "1 F.3d 1", [case(cluster_id=42, slug="")])
    assert rec.uri == "https://www.courtlistener.com/api/rest/v4/clusters/42/"


def test_single_form_name_truncation_at_cap() -> None:
    rec = render_record("us-ca11", "1 F.3d 1", [case(name="Ünïcödé " * 400)])
    assert len(rec.metadata.encode("utf-8")) <= METADATA_CAP
    obj = json.loads(rec.metadata)  # still valid JSON
    assert obj["name"].endswith("…")
    assert obj["cluster"] == 108713 and obj["year"] == 1973


def test_collision_form_sorted_and_uri_from_lowest_cluster() -> None:
    rec = render_record(
        "us-ca11",
        "900 F.3d 100",
        [case(cluster_id=222, name="C v. D", slug="c-v-d"), case(cluster_id=111, name="A v. B", slug="a-v-b")],
    )
    obj = json.loads(rec.metadata)
    assert [c["cluster"] for c in obj["cases"]] == [111, 222]
    assert rec.uri == "https://www.courtlistener.com/opinion/111/a-v-b/"


def test_collision_form_caps_and_omitted() -> None:
    cases = [case(cluster_id=i, name=f"Case {i} " + "x" * 300, slug=f"s{i}") for i in range(40)]
    rec = render_record("us-ca11", "900 F.3d 100", cases)
    raw = rec.metadata.encode("utf-8")
    assert len(raw) <= METADATA_CAP
    obj = json.loads(rec.metadata)
    for entry in obj["cases"]:
        assert len(entry["name"].encode("utf-8")) <= 256
        assert entry["name"].endswith("…")
    assert obj["omitted"] == 40 - len(obj["cases"])
    assert obj["cases"][0]["cluster"] == 0  # order preserved while dropping the tail


def test_oversize_checksum_halts() -> None:
    with pytest.raises(RecordError):
        render_record("us-ca11", "9" * 65, [case()])


def test_truncate_utf8_respects_boundaries() -> None:
    s = "abc中文def"
    for cap in range(len(s.encode("utf-8")) + 1):
        cut = truncate_utf8(s, cap)
        assert len(cut.encode("utf-8")) <= cap
        assert s.startswith(cut)
