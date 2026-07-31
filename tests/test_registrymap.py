"""Pinned registry manifests: load, resolve, and drift detection."""

import pytest

from nvnm_cite.chain import precompile as pc
from nvnm_cite.chain.registrymap import RegistryManifest, load_manifest

ADMIN = "nvnm14a3em3mr9mvta9ccgk80wn0dxgzt5lkt2r8trx"


def test_mainnet_manifest_pins_live_verified_ids():
    m = load_manifest("mainnet")
    assert m.chain_id == 1611
    assert m.creator == ADMIN
    assert len(m.ids) == 2114
    assert m.registry_id("us-scotus") == 82
    assert m.registry_id("us-ca11") == 71
    assert m.registry_id("us-ca1") == 69
    assert m.registry_name(2182) == "us-wyo"
    assert m.registry_id("not-a-court") is None
    ids = sorted(m.ids.values())
    assert ids[0] == 69 and ids[-1] == 2182
    assert ids == list(range(69, 2183))  # contiguous block, no gaps


def test_testnet_manifest_pins_pilot_pair():
    m = load_manifest("testnet")
    assert m.chain_id == 787111
    assert m.all_registries() == {"us-scotus": 737, "us-ca11": 738}


def test_load_manifest_unknown_network():
    with pytest.raises(FileNotFoundError):
        load_manifest("devnet")


class _FakeRpc:
    """Serves a canned registries() enumeration through eth_call."""

    def __init__(self, rows):
        self._rows = rows

    def eth_call(self, to, data, block="latest"):
        # decode the offset out of the query to serve the right page
        args_entries = pc._FUNCTIONS["registries"]["inputs"]
        from nvnm_cite.chain import abi

        _, page = abi.decode_values(args_entries, data[4:])
        offset, limit = page[1], page[2]
        rows = self._rows[offset : offset + limit]
        as_lists = [
            [r.id, r.name, r.description, r.creator, r.created_at, r.metadata]
            for r in rows
        ]
        return abi.encode_values(
            pc._FUNCTIONS["registries"]["outputs"], [as_lists, [b"", 0]]
        )


def _manifest(ids):
    return RegistryManifest(
        schema="nvnm-cite-registry-manifest/v1",
        network="testnet",
        chain_id=787111,
        creator=ADMIN,
        generated_at="2026-07-31T00:00:00Z",
        generated_at_block=1,
        ids=ids,
    )


def _reg(rid, name, creator=ADMIN):
    return pc.Registry(rid, name, "d", creator, "2026-07-30", "")


def test_diff_against_chain_clean():
    m = _manifest({"us-scotus": 737, "us-ca11": 738})
    rpc = _FakeRpc([_reg(737, "us-scotus"), _reg(738, "us-ca11"), _reg(739, "other", "nvnm1someoneelse")])
    assert m.diff_against_chain(rpc) == {"added": {}, "missing": {}, "renamed": {}}


def test_diff_against_chain_detects_drift():
    m = _manifest({"us-scotus": 737, "us-ca11": 738})
    rpc = _FakeRpc(
        [
            _reg(737, "us-renamed"),  # renamed in place
            # 738 gone entirely
            _reg(740, "us-ca11"),  # a NEW registry by our creator with a manifest name
        ]
    )
    diff = m.diff_against_chain(rpc)
    assert diff["renamed"] == {737: {"pinned": "us-scotus", "chain": "us-renamed"}}
    assert diff["missing"] == {738: "us-ca11"}
    assert diff["added"] == {740: "us-ca11"}
