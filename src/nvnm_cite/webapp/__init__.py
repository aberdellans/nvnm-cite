"""Pilot web frontend: check a brief, anchor a filing receipt, verify a hash.

A small stdlib HTTP server (`python -m nvnm_cite.webapp`) plus a static
no-framework page. Design rules, in force everywhere in this package:

- Uploaded documents are processed in memory and discarded with the
  response. Nothing is written to disk, nothing is logged but sizes.
- Drafting-time checks (`/api/check`) read NVNM Chain LIVE via keyed
  `records()` eth_calls (item 0, DECISIONS 2026-06-13; amends invariant
  3), through the shared verifier core (`nvnm_cite.verifier`). The reads
  are point-to-point (no mempool, no block, no on-chain trace), so the
  citation set is visible only to NVNM as RPC operator — privacy-
  equivalent to the in-memory parse — while the verdict is the chain's
  own and replayable by anyone. The local index is a rebuildable
  audit/cache (status panel), never the lookup authority.
- Receipt preparation re-verifies every keyed citation with `records()`
  eth_calls pinned to one block, so a receipt claims chain state at a
  stated height, never local state.
- The server signs nothing and holds no keys. Transactions are prepared
  as calldata by the same golden-tested codec the loader uses
  (chain/abi.py + chain/precompile.py) and signed by the user's wallet
  in the browser. There is deliberately no JavaScript ABI code.
"""
