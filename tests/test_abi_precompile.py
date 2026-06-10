import json
from pathlib import Path

import pytest

from nvnm_cite.chain import abi
from nvnm_cite.chain.precompile import (
    SELECTORS,
    Page,
    Record,
    Registry,
    build_add_record,
    build_add_registry,
    build_grant_role,
    build_records_query,
    build_registries_query,
    decode_add_record_result,
    decode_add_registry_result,
    decode_records_result,
    decode_registries_result,
)

GOLDEN = Path(__file__).parent / "golden" / "abi" / "vectors.json"

# Selectors published in the original build plan, an independent third source
# for these three (ethers and our keccak both derive them from the ABI).
PUBLISHED_SELECTORS = {
    "addRecord": "0x9b7b7869",
    "addRegistry": "0x318b38b1",
    "records": "0x02abafdf",
}

# Builder calls mirroring generate_vectors.cjs case for case.
BUILDERS = {
    "addRegistry-us-scotus": lambda: build_add_registry(
        "us-scotus", "Canonical citations: Supreme Court of the United States", ""
    ),
    "addRecord-roe": lambda: build_add_record(
        "us-scotus",
        "https://www.courtlistener.com/c/US/410/113/",
        "410 U.S. 113",
        "cite-canonical-v1",
        '{"cluster":108713,"name":"Roe v. Wade","year":1973}',
    ),
    "addRecord-unicode": lambda: build_add_record(
        "dev-probe",
        "",
        "925 F.3d 1339",
        "cite-canonical-v1",
        "unicode test: Variación № ñ §410 “quotes” ☺",
    ),
    "grantRole-editor": lambda: build_grant_role(
        3, "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf", "editor"
    ),
    "records-keyed-existence": lambda: build_records_query(
        registry="us-scotus", checksum="410 U.S. 113", count_total=True
    ),
    "records-paged-resume": lambda: build_records_query(
        page_key=bytes.fromhex("deadbeef00aa"), offset=7, limit=50, reverse=True
    ),
    "registries-by-name": lambda: build_registries_query(name="us-ca11", limit=25),
}


def load_golden() -> dict:
    return json.loads(GOLDEN.read_text())


def test_selectors_match_ethers_and_published() -> None:
    assert SELECTORS == load_golden()["selectors"]
    for name, selector in PUBLISHED_SELECTORS.items():
        assert SELECTORS[name] == selector


@pytest.mark.parametrize("call", load_golden()["calls"], ids=lambda c: c["desc"])
def test_calldata_matches_ethers(call: dict) -> None:
    built = BUILDERS[call["desc"]]()
    assert "0x" + built.hex() == call["calldata"]


def test_decode_simple_results() -> None:
    blobs = {r["desc"]: bytes.fromhex(r["blob"].removeprefix("0x")) for r in load_golden()["results"]}
    assert decode_add_registry_result(blobs["addRegistry-result"]) == 7
    assert decode_add_record_result(blobs["addRecord-result"]) == 123456


def test_decode_records_result() -> None:
    blobs = {r["desc"]: r for r in load_golden()["results"]}
    data = bytes.fromhex(blobs["records-result-two-rows"]["blob"].removeprefix("0x"))
    records, page = decode_records_result(data)
    assert page == Page(next_key=b"next", total=999)
    assert records[0] == Record(
        registry="us-scotus",
        uri="https://www.courtlistener.com/c/US/410/113/",
        checksum="410 U.S. 113",
        checksum_algo="cite-canonical-v1",
        metadata='{"cluster":108713,"name":"Roe v. Wade","year":1973}',
        timestamp="2026-06-10T12:00:00Z",
        status="Active",
        record_id=42,
        index=0,
        is_latest=True,
    )
    assert records[1].checksum == "347 U.S. 483"
    assert records[1].metadata == "unicode: Brown v. Board ☺ §483"
    assert records[1].is_latest is False

    empty = bytes.fromhex(blobs["records-result-empty"]["blob"].removeprefix("0x"))
    assert decode_records_result(empty) == ([], Page(next_key=b"", total=0))


def test_decode_registries_result() -> None:
    blob = next(r for r in load_golden()["results"] if r["desc"] == "registries-result")
    registries, page = decode_registries_result(
        bytes.fromhex(blob["blob"].removeprefix("0x"))
    )
    assert registries == [
        Registry(
            id=11,
            name="us-scotus",
            description="Canonical citations: SCOTUS",
            creator="nvnm1creator",
            created_at="2026-06-10",
            metadata="",
        )
    ]
    assert page == Page(next_key=b"", total=3)


def test_encode_decode_roundtrip_on_record_tuple() -> None:
    record_entry = {
        "type": "tuple[]",
        "components": [
            {"name": "registry", "type": "string"},
            {"name": "uri", "type": "string"},
            {"name": "checksum", "type": "string"},
            {"name": "checksumAlgo", "type": "string"},
            {"name": "metadata", "type": "string"},
            {"name": "timestamp", "type": "string"},
            {"name": "status", "type": "string"},
            {"name": "recordId", "type": "uint64"},
            {"name": "index", "type": "uint64"},
            {"name": "isLatest", "type": "bool"},
        ],
    }
    rows = [
        ["us-ca11", "", "925 F.3d 1291", "cite-canonical-v1", "ñ", "", "Active", 7, 2, True],
        ["us-ca11", "u", "", "", "", "", "", 0, 0, False],
    ]
    blob = abi.encode_values([record_entry], [rows])
    assert abi.decode_values([record_entry], blob) == [rows]


def test_builder_validation() -> None:
    with pytest.raises(ValueError):
        build_add_record("", "u", "c", "a")  # registry required
    with pytest.raises(ValueError):
        build_add_record("r", "u", "", "a")  # checksum required
    with pytest.raises(ValueError):
        build_grant_role(1, "0x" + "11" * 20, "owner")  # bad role
    with pytest.raises(ValueError):
        build_grant_role(1, "0x1234", "editor")  # bad address
    with pytest.raises(ValueError):
        build_add_registry("", "d")
