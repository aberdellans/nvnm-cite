"""Pilot web frontend: check a brief, anchor a filing receipt, verify a hash.

A small stdlib HTTP server (`python -m nvnm_cite.webapp`) plus a static
no-framework page. Design rules, in force everywhere in this package:

- Uploaded documents are processed in memory and discarded with the
  response. Nothing is written to disk, nothing is logged but sizes.
- Drafting-time checks (`/api/check`) consult the LOCAL index only and
  perform no RPC of any kind (CLAUDE.md invariant 3: even read traffic
  leaks the brief's citation set to the RPC operator).
- Receipt preparation re-verifies every keyed citation with `records()`
  eth_calls pinned to one block, so a receipt claims chain state at a
  stated height, never local state.
- The server signs nothing and holds no keys. Transactions are prepared
  as calldata by the same golden-tested codec the loader uses
  (chain/abi.py + chain/precompile.py) and signed by the user's wallet
  in the browser. There is deliberately no JavaScript ABI code.
"""
