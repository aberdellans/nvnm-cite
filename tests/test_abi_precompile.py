import json
from pathlib import Path

import pytest

from nvnm_cite.chain import abi
from nvnm_cite.chain.precompile import (
    EVENT_TOPICS,
    PRECOMPILE_ADDRESS,
    SELECTORS,
    Page,
    Record,
    Registry,
    build_add_record,
    build_add_registry,
    build_grant_role,
    build_records_query,
    build_registries_query,
    build_revoke_role,
    build_update_record_status,
    decode_add_record_result,
    decode_add_registry_log,
    decode_add_registry_result,
    decode_event_logs,
    decode_records_result,
    decode_registries_result,
)

GOLDEN = Path(__file__).parent / "golden" / "abi" / "vectors.json"

# Anchoring-module v1.2.0 selectors. records/registries/addRecord changed with
# the id-keyed interface (published in the v1.2.0 module doc and verified by
# live dispatch on both networks 2026-07-31: these answer, the old name-keyed
# selectors return "unknown method id"). addRegistry/grantRole/revokeRole/
# updateRecordStatus are unchanged from the pre-v1.2.0 interface.
PUBLISHED_SELECTORS = {
    "addRecord": "0x64d25295",
    "addRegistry": "0x318b38b1",
    "grantRole": "0xb8fdd1a7",
    "records": "0xc7be5e37",
    "registries": "0x17bd3e65",
    "revokeRole": "0xacd58bc7",
    "updateRecordStatus": "0x97b40c25",
}

# Builder calls mirroring generate_vectors.cjs case for case.
BUILDERS = {
    "addRegistry-us-scotus": lambda: build_add_registry(
        "us-scotus", "Canonical citations: Supreme Court of the United States", ""
    ),
    "addRecord-roe": lambda: build_add_record(
        82,
        "https://www.courtlistener.com/c/US/410/113/",
        "410 U.S. 113",
        "cite-canonical-v1",
        '{"cluster":108713,"name":"Roe v. Wade","year":1973}',
    ),
    "addRecord-unicode": lambda: build_add_record(
        733,
        "",
        "925 F.3d 1339",
        "cite-canonical-v1",
        "unicode test: Variación № ñ §410 “quotes” ☺",
    ),
    "grantRole-editor": lambda: build_grant_role(
        3, "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf", "editor"
    ),
    "records-keyed-existence": lambda: build_records_query(
        registry_id=82, checksum="410 U.S. 113", count_total=True
    ),
    "records-paged-resume": lambda: build_records_query(
        registry_id=82,
        page_key=bytes.fromhex("deadbeef00aa"),
        offset=7,
        limit=50,
        reverse=True,
    ),
    "registries-by-id": lambda: build_registries_query(registry_id=71, limit=25),
    "registries-enumerate": lambda: build_registries_query(offset=400, limit=200),
    "revokeRole-editor": lambda: build_revoke_role(
        3, "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf", "editor"
    ),
    "updateRecordStatus-supersede": lambda: build_update_record_status(
        733, 1, 1, "Superseded"
    ),
}


def load_golden() -> dict:
    return json.loads(GOLDEN.read_text())


def test_selectors_match_ethers_and_published() -> None:
    assert SELECTORS == load_golden()["selectors"]
    assert SELECTORS == PUBLISHED_SELECTORS


def test_event_topics_match_ethers() -> None:
    golden = load_golden()["eventTopics"]
    assert {EVENT_TOPICS[t]: t for t in EVENT_TOPICS} == golden


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
        uri="https://www.courtlistener.com/c/US/410/113/",
        checksum="410 U.S. 113",
        checksum_algo="cite-canonical-v1",
        metadata='{"cluster":108713,"name":"Roe v. Wade","year":1973}',
        timestamp="2026-06-10T12:00:00Z",
        status="Active",
        record_id=42,
        index=0,
        is_latest=True,
        registry_id=82,
    )
    assert records[1].checksum == "347 U.S. 483"
    assert records[1].metadata == "unicode: Brown v. Board ☺ §483"
    assert records[1].is_latest is False
    assert records[1].registry_id == 82

    empty = bytes.fromhex(blobs["records-result-empty"]["blob"].removeprefix("0x"))
    assert decode_records_result(empty) == ([], Page(next_key=b"", total=0))


def test_decode_registries_result() -> None:
    blob = next(r for r in load_golden()["results"] if r["desc"] == "registries-result")
    registries, page = decode_registries_result(
        bytes.fromhex(blob["blob"].removeprefix("0x"))
    )
    assert registries == [
        Registry(
            id=82,
            name="us-scotus",
            description="Canonical citations: SCOTUS",
            creator="nvnm1creator",
            created_at="2026-07-30",
            metadata="",
        )
    ]
    assert page == Page(next_key=b"", total=3)


def test_decode_add_registry_log_from_golden() -> None:
    golden_log = load_golden()["logs"][0]
    assert golden_log["event"] == "AddRegistry"
    caller = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
    receipt_log = {
        "address": PRECOMPILE_ADDRESS.lower(),
        "topics": [
            next(t for t, n in EVENT_TOPICS.items() if n == "AddRegistry"),
            "0x" + "00" * 12 + caller.removeprefix("0x").lower(),
        ],
        "data": golden_log["data"],
    }
    decoded = decode_add_registry_log([receipt_log])
    assert decoded == {
        "registry_id": golden_log["values"]["registryId"],
        "name": golden_log["values"]["name"],
        "caller": caller.lower(),
    }
    # Foreign-address and unknown-topic logs are skipped, never an error.
    assert decode_event_logs([{"address": "0x" + "11" * 20, "topics": [], "data": "0x"}]) == []
    assert decode_add_registry_log([]) is None


def test_encode_decode_roundtrip_on_record_tuple() -> None:
    record_entry = {
        "type": "tuple[]",
        "components": [
            {"name": "uri", "type": "string"},
            {"name": "checksum", "type": "string"},
            {"name": "checksumAlgo", "type": "string"},
            {"name": "metadata", "type": "string"},
            {"name": "timestamp", "type": "string"},
            {"name": "status", "type": "string"},
            {"name": "recordId", "type": "uint64"},
            {"name": "index", "type": "uint64"},
            {"name": "isLatest", "type": "bool"},
            {"name": "registryId", "type": "uint64"},
        ],
    }
    rows = [
        ["", "925 F.3d 1291", "cite-canonical-v1", "ñ", "", "Active", 7, 2, True, 71],
        ["u", "", "", "", "", "", 0, 0, False, 1],
    ]
    blob = abi.encode_values([record_entry], [rows])
    assert abi.decode_values([record_entry], blob) == [rows]


def test_builder_validation() -> None:
    with pytest.raises(ValueError):
        build_add_record(0, "u", "c", "a")  # registry_id required
    with pytest.raises(ValueError):
        build_add_record(1, "u", "", "a")  # checksum required
    with pytest.raises(ValueError):
        build_grant_role(1, "0x" + "11" * 20, "owner")  # bad role
    with pytest.raises(ValueError):
        build_grant_role(1, "0x1234", "editor")  # bad address
    with pytest.raises(ValueError):
        build_add_registry("", "d")
