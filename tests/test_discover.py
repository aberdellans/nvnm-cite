"""Chain-wide receipt discovery (receipts/discover.py): court-registry
exclusion, hit collection, and the fail-loud transport rule."""

from __future__ import annotations

import pytest

from nvnm_cite.chain.rpc import RpcError
from nvnm_cite.receipts.discover import find_anchors

SHA = "ab" * 32

ROWS = [
    {"id": 82, "name": "us-scotus", "creator": "nvnm1official", "created_at": "t"},
    {"id": 900, "name": "firm--case", "creator": "nvnm1firm", "created_at": "t"},
    {"id": 2200, "name": "firm--case", "creator": "nvnm1other", "created_at": "t"},
]


class FakeReader:
    def __init__(self, registries, records, errors=None):
        self._registries = registries
        self._records = records  # {(registry_id, checksum): record}
        self._errors = errors or {}  # {registry_id: Exception}
        self.probed: list[int] = []

    def all_registries(self):
        return list(self._registries)

    def keyed_record(self, registry_id, checksum):
        self.probed.append(registry_id)
        if registry_id in self._errors:
            raise self._errors[registry_id]
        return self._records.get((registry_id, checksum))


def test_sweep_excludes_court_ids_and_orders_hits():
    reader = FakeReader(ROWS, {(2200, SHA): "rec2200", (900, SHA): "rec900"})
    out = find_anchors(reader, SHA, exclude_ids={82})
    # The court registry is never probed — citation keys live there, not docs.
    assert sorted(reader.probed) == [900, 2200]
    assert [h["registry"]["id"] for h in out["hits"]] == [900, 2200]
    assert out["hits"][0]["record"] == "rec900"
    assert out["registries_swept"] == 2
    assert out["registries_excluded"] == 1


def test_sweep_no_hits_and_empty_target_set():
    out = find_anchors(FakeReader(ROWS, {}), SHA, exclude_ids={82})
    assert out["hits"] == [] and out["registries_swept"] == 2

    only_court = FakeReader([ROWS[0]], {})
    out = find_anchors(only_court, SHA, exclude_ids={82})
    assert out == {"hits": [], "registries_swept": 0, "registries_excluded": 1}
    assert only_court.probed == []


def test_sweep_transport_error_propagates():
    # "could not check a registry" must never read as "not anchored anywhere".
    boom = RpcError("eth_call", -32000, "connection reset")
    reader = FakeReader(ROWS, {(900, SHA): "rec900"}, errors={2200: boom})
    with pytest.raises(RpcError):
        find_anchors(reader, SHA, exclude_ids={82})
