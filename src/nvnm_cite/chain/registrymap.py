"""Pinned registry-name -> registryId manifests (the name->id trust anchor).

Under anchoring v1.2.0 registry names are NON-UNIQUE and every chain call
keys on the numeric registryId. Anyone can create a registry named
"us-scotus"; what makes ours authoritative is the PUBLISHED id + creator
pair. These manifests pin that mapping per network, generated read-only by
scripts/build_registry_manifest.py from a creator-filtered enumeration of
registries() cross-checked against the bulk-load export, and checked in
beside the vendored ABI. Runtime resolution goes through the pinned map,
never through a live name search; diff_against_chain() exists to DETECT
drift, not to follow it silently.

Stdlib only, like the rest of chain/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from nvnm_cite.chain import precompile as pc

MANIFEST_SCHEMA = "nvnm-cite-registry-manifest/v1"


@dataclass(frozen=True)
class RegistryManifest:
    schema: str
    network: str
    chain_id: int
    creator: str
    generated_at: str
    generated_at_block: int
    ids: dict[str, int]  # name -> registryId

    @property
    def names(self) -> dict[int, str]:
        return {rid: name for name, rid in self.ids.items()}

    def registry_id(self, name: str) -> int | None:
        return self.ids.get(name)

    def registry_name(self, registry_id: int) -> str | None:
        return self.names.get(registry_id)

    def all_registries(self) -> dict[str, int]:
        return dict(self.ids)

    def diff_against_chain(self, rpc: Any) -> dict[str, Any]:
        """Re-enumerate registries() (creator-filtered) and diff against the
        pinned map. Returns {added, missing, renamed}; all empty means the
        chain still matches the manifest. Read-only."""
        on_chain: dict[int, str] = {}
        offset = 0
        while True:
            raw = rpc.eth_call(
                pc.PRECOMPILE_ADDRESS,
                pc.build_registries_query(offset=offset, limit=200),
            )
            rows, _ = pc.decode_registries_result(raw)
            if not rows:
                break
            for reg in rows:
                if reg.creator == self.creator:
                    on_chain[reg.id] = reg.name
            offset += len(rows)
            if len(rows) < 200:
                break
        pinned = self.names
        added = {
            rid: name
            for rid, name in on_chain.items()
            if rid not in pinned and name in self.ids
        }
        missing = {rid: name for rid, name in pinned.items() if rid not in on_chain}
        renamed = {
            rid: {"pinned": pinned[rid], "chain": on_chain[rid]}
            for rid in pinned
            if rid in on_chain and on_chain[rid] != pinned[rid]
        }
        return {"added": added, "missing": missing, "renamed": renamed}


def _parse(raw: str) -> RegistryManifest:
    doc = json.loads(raw)
    if doc.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"unexpected manifest schema {doc.get('schema')!r}")
    return RegistryManifest(
        schema=doc["schema"],
        network=doc["network"],
        chain_id=doc["chain_id"],
        creator=doc["creator"],
        generated_at=doc["generated_at"],
        generated_at_block=doc["generated_at_block"],
        ids={name: entry["id"] for name, entry in doc["registries"].items()},
    )


@lru_cache(maxsize=4)
def load_manifest(network_key: str) -> RegistryManifest:
    """Load the pinned manifest for "mainnet" or "testnet" (package data)."""
    filename = f"registry_manifest_{network_key}.json"
    raw = resources.files("nvnm_cite.chain").joinpath(filename).read_text()
    manifest = _parse(raw)
    if manifest.network != network_key:
        raise ValueError(
            f"manifest {filename} claims network {manifest.network!r}"
        )
    return manifest
