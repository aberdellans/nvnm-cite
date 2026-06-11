# nvnm-cite

Citation existence verification and filing receipts on NVNM Chain. Plaintext per-court registries of canonical US case citations + a verifier that checks briefs against them and anchors a receipt at filing time.

What this is NOT: it never asserts a case supports a proposition, and it never asserts good-law status. Provenance, not truth.

## Invariants (never violate)

1. Citations are stored and checked in PLAINTEXT. Citation identifiers are never hashed. The only hash in the system is the SHA-256 of the checked document inside a receipt.
2. Existence-only verification. No holdings, no propositions, no good-law flags. If citator data ever enters, it enters as a named citator's attested claim, never as an NVNM assertion.
3. Anchoring is explicit and happens at filing time. Drafting-time checks run against the local index only and leave no chain trace (even read RPCs leak to the RPC operator). The strategy-leak rationale gets documented, not just implemented.
4. The registry write model must allow third parties to own registries. Inveniam populates registries for the pilot, but the permission design never assumes Inveniam is the only attestor.
5. The normalizer is part of the trust boundary. Its spec is open and versioned, and every receipt records the normalizer version used.
6. The product name is NVNM Chain. Never "Inveniam Chain".

## Chain constants (verified 2026-06-10)

| Item | Testnet (ALL dev here) | Mainnet (reference only) |
|---|---|---|
| EVM chain ID | 787111 | 1611 |
| Cosmos chain ID | nvnm-testnet-1 | nvnm-1 |
| EVM RPC | https://evm.testnet.nvnmchain.io | https://evm.nvnmchain.io |
| EVM explorer (Blockscout) | https://explorer.evm.testnet.nvnmchain.io | https://evm.explorer.nvnmchain.io |
| Gas token | wmantraUSD | wmmUSD |

- Anchor precompile: `0x0000000000000000000000000000000000000A00` (same address on both networks). Vendored ABI: `src/nvnm_cite/chain/anchoring.json` (addRegistry, addRecord, records, registries, grantRole). `updateRecordStatus` exists in the chain spec but was missing from the deployed testnet binary as of May 2026.
- `records(registry, checksum, recordId, index, pagination)` gives a keyed existence read by registry name + checksum string.
- The precompile emits NO events (privacy by design). Indexing means paging `records()` via eth_call, never log scans.
- Measured behavior (2026-06-10, full detail in DECISIONS): keyed query misses ERROR (`collections: not found`), never empty pages. Field caps: checksum <= 64 B, uri <= 2048 B, metadata <= 2048 B; uri/checksumAlgo/metadata required non-empty and `{}` counts as empty. Registry names unique. Writes deny-by-default (creator = admin; grantRole adds editors). Duplicates create VERSIONS, never revert. Pagination is offset-based only: 200 rows/page server cap, nextKey and countTotal unreliable. Single-sender throughput ~1.1 tx/s; nonce-gapped submission rejected. The public RPC serves full archive state.
- Gas price: 40 gwei chain floor, node suggests 45 gwei in practice; the token pegs to roughly $1.
- WARNING: chain ID 58887 appears in older docs and plans. That testnet (manveniam-1) is RETIRED. Never use it.
- NEVER write to mainnet from a session. Mainnet keys are not available to sessions and must never be. The testnet key lives in `.env` (`NVNM_TESTNET_KEY`); load it in code, never print it.

## Record schema (LOCKED v1 at task 1.5, 2026-06-11; full text in docs/record-schema.md)

- Per-case record: `checksum` = canonical citation string in plaintext per cite-canonical/v1 (e.g. `410 U.S. 113`; first-page keys, spec in docs/canonical-citation-spec.md), `checksumAlgo` = `cite-canonical-v1`, `uri` = CourtListener cluster URL (bulk-data slug form, API-URL fallback), `metadata` = compact JSON {"cluster","name","year"} (collision form {"cases":[...]}; deterministic truncation rules in the schema doc), `status` = `Active`.
- Receipt record (registry `receipts-v1`): `checksum` = document SHA-256 hex (exactly fills the 64 B cap), `checksumAlgo` = `sha256`, `uri` = `urn:nvnm-cite:receipt:v1` (fixed; URL form deferred to mainnet publication under a version bump), `metadata` = receipt JSON when it fits 2048 B, else the Phase 4 chunked design. JSON rules everywhere: UTF-8, ensure_ascii=false, sorted keys, no whitespace.
- Registry names: courts-db IDs prefixed `us-` (`us-scotus`, `us-ca11`), plus `receipts-v1`. Registry creation strings (descriptions + metadata incl. FLP attribution) are fixed in the schema doc.
- Schema changes from here require a version bump, never an edit.

## Conventions

- Python 3.11+, uv for env and deps, pytest, type hints everywhere.
- `src/nvnm_cite/chain/` uses ONLY the standard library. The signer is written from scratch (keccak-256 with original Keccak padding, RLP, secp256k1 + RFC-6979, EIP-155 type-0). The golden suites in `tests/golden/` are the contract; run pytest after every change to `chain/`, `normalizer/`, or `receipts/`.
- Build on eyecite / reporters-db / courts-db (Phase 1 onward). Never write a citation parser from scratch.
- No new dependency without a dated DECISIONS.md entry (name, version pin, license).
- Never print private keys, `.env` values, or seed phrases.
- Case data attribution (CourtListener / Free Law Project) stays in README, registry metadata, and demos.
- Before sending any chain transaction, present the plan and get an explicit OK (use plan mode when available).
- Session cadence (user preference, 2026-06-10): one phase per session. Do not suggest opening a fresh session between tasks of the same phase; wrap up at phase boundaries.

## Where state lives

- `IMPLEMENTATION_PLAN.md`: position. 3-line Status header + checkboxed phases. The next session continues from here.
- `DECISIONS.md`: memory. Append-only, dated. Read it before proposing changes to anything it covers.
- Git: main-only with `phase-N-done` tags, no feature branches. History is the session log.
- The session kickoff prompt lives in README.md.

## Session end ritual (do this without being asked)

When the user says "wrap up", or when the session's goal is reached:
1. Run pytest; do not commit on red without an explicit user OK.
2. Update IMPLEMENTATION_PLAN.md: tick completed checkboxes, refresh the 3-line Status header.
3. Append settled choices to DECISIONS.md (dated).
4. `git add -A && git commit -m "session: <phase> - <one-line summary>"`
5. If a phase just completed: `git tag phase-N-done && git push && git push --tags`. Otherwise just `git push`.
6. Print: phase status, what the next session starts with, and a reminder that the kickoff prompt in README.md is generic.
