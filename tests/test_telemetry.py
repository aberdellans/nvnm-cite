"""Aggregate query telemetry (task 4.6): counts by citation only, opt-in.

Pins the privacy-load-bearing property: the store holds (registry, citation)
counts and nothing that could tie a lookup to a document or a client.
"""

from __future__ import annotations

import sqlite3

import pytest

from nvnm_cite.chain.rpc import RpcError
from nvnm_cite.verifier.resolver import ChainResolver
from nvnm_cite.verifier.telemetry import NullTelemetry, SqliteTelemetry


def test_sqlite_telemetry_aggregates(tmp_path):
    sink = SqliteTelemetry(tmp_path / "t.sqlite")
    sink.record("us-scotus", "410 U.S. 113", True)
    sink.record("us-scotus", "410 U.S. 113", True)
    sink.record("us-ca11", "925 F.3d 1339", False)
    top = sink.top()
    by = {r["citation"]: r for r in top}
    assert by["410 U.S. 113"]["lookups"] == 2 and by["410 U.S. 113"]["hits"] == 2
    assert by["925 F.3d 1339"]["lookups"] == 1 and by["925 F.3d 1339"]["hits"] == 0
    assert top[0]["citation"] == "410 U.S. 113"  # ordered by lookups desc
    sink.close()


def test_telemetry_stores_no_document_or_identity_columns(tmp_path):
    path = tmp_path / "t.sqlite"
    SqliteTelemetry(path).close()
    conn = sqlite3.connect(path)
    cols = {c[1] for c in conn.execute("PRAGMA table_info(query_telemetry)")}
    conn.close()
    # registry + citation + counts only — nothing joinable to a document/client
    assert cols == {"registry", "citation", "lookups", "hits", "first_seen", "last_seen"}
    assert not (cols & {"document", "sha256", "document_sha256", "client", "address", "ip"})


def test_null_telemetry_is_a_noop():
    sink = NullTelemetry()
    sink.record("us-scotus", "410 U.S. 113", True)  # must not raise
    sink.close()


class _RpcStub:
    def __init__(self, error):
        self.error = error

    def eth_call(self, to, data, block="latest"):
        raise self.error


def test_resolver_records_keyed_miss(tmp_path):
    sink = SqliteTelemetry(tmp_path / "t.sqlite")
    err = RpcError("eth_call", 3, "collections: not found: key '(\"738\", \"925 F.3d 1339\")'")
    resolver = ChainResolver(lambda: _RpcStub(err), telemetry=sink)
    res = resolver.resolve(738, "925 F.3d 1339", "us-ca11")
    assert res.record is None
    top = sink.top()
    assert top == [{"registry": "us-ca11", "citation": "925 F.3d 1339", "lookups": 1, "hits": 0}]
    sink.close()


def test_resolver_does_not_record_transport_error(tmp_path):
    sink = SqliteTelemetry(tmp_path / "t.sqlite")
    resolver = ChainResolver(lambda: _RpcStub(ConnectionRefusedError("down")), telemetry=sink)
    with pytest.raises(ConnectionRefusedError):
        resolver.resolve(737, "410 U.S. 113", "us-scotus")
    assert sink.top() == []  # a dead chain is not a recordable lookup
    sink.close()
