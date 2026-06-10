# Decisions

Append-only. One dated entry per settled choice, newest at the bottom. Open questions do not live here; they live as unchecked tasks in IMPLEMENTATION_PLAN.md.

## 2026-06-10: Chain constants corrected from the v1 draft plan
The draft (docs/ARCHIVE/build-plan-v1-2026-06-09.md) targeted testnet chain ID 58887. That chain (manveniam-1) is retired. Live testnet: nvnm-testnet-1, EVM chain ID 787111, RPC https://evm.testnet.nvnmchain.io, Blockscout explorer https://explorer.evm.testnet.nvnmchain.io. The draft's mainnet explorer URL (explorer.nvnmchain.io) is the Cosmos-side explorer and cannot display EVM transactions; the EVM explorer is https://evm.explorer.nvnmchain.io. Sources: NVNM_MCP_Server/CLAUDE.md chain-ID history table, nvnm-tutorial README.

## 2026-06-10: Precompile semantics adopted from NVNM_MCP_Server; discovery phase narrowed to experiments
Known from the sibling project (ABI vendored at abi/anchoring.json): addRecord takes a 10-field tuple of plain strings and the module does no content validation, so plaintext citations fit in the checksum field natively; records(registry, checksum, recordId, index, pagination) supports keyed reads by registry name + checksum string; the registry creator becomes its admin; grantRole(registryId, checksum, account, role) grants admin/editor at record, registry, or global scope; the precompile emits no events. The genuinely unknown behaviors are Phase 0 experiments (a) through (i) in IMPLEMENTATION_PLAN.md.

## 2026-06-10: Lookup design: keyed chain read AND local index (the draft's options A and B, both)
Receipt-time checks use the direct records() eth_call so a receipt can claim a chain read at a stated block height. Drafting-time checks use the local SQLite index only (no RPC, no trace). The index is rebuildable from chain by anyone with an RPC URL (rebuild-index command), which is the public-auditability claim made executable.

## 2026-06-10: Signer written from scratch in pure Python (user decision)
The draft said to reuse evm_signer_v5.py; that file does not exist on this machine. Albert chose a from-scratch pure-Python signer over the eth-account library: keccak-256 (original Keccak padding; hashlib.sha3_256 is NIST SHA-3 and gives different digests), RLP, secp256k1 with RFC-6979 deterministic k, EIP-155 type-0 signing. chain/ stays stdlib-only. Golden vectors: Keccak team KATs (pre-NIST, original padding), RFC 6979 Appendix A, the EIP-155 worked example (chain id 1, nonce 9, v=37), ethereum/tests RLP cases, plus cross-check vectors generated locally with ethers (node v20 installed). Known tradeoff, accepted: hand-rolled crypto is normally a liability; acceptable here because session keys are throwaway testnet keys, RFC-6979 removes RNG misuse risk, and mainnet writes happen outside Claude Code sessions per the pilot-close preconditions.

## 2026-06-10: Transaction type: legacy type-0 only for V1
The chain accepts EIP-1559 type-2 transactions, but at a fixed 40 gwei floor the typed envelope adds complexity for zero functional gain. Revisit only if Phase 0 shows type-0 rejected.

## 2026-06-10: Pilot corpus: SCOTUS + 11th Circuit
Chosen so the flagship demo's fabricated cite (Varghese v. China Southern Airlines, 925 F.3d 1339 (11th Cir. 2019), from Mata v. Avianca) maps to a covered registry and returns NOT_FOUND from a chain read instead of "court not covered". Gate: the Phase 2 census must confirm CourtListener ca11 coverage (the coverage API reported ~95k opinions, 1981 onward, fetched 2026-06-10). Fallback: 2d Circuit, with a demo cite swap.

## 2026-06-10: SCOTUS corpus is roughly 8x the draft's assumption; load in tranches
The CourtListener coverage API reports ~522k scotus opinions (post Caselaw Access Project merge; cert denials, GVRs, and memoranda are each their own citable cluster). For an existence registry these are legitimate entries: a brief citing a cert denial cites a real citation. Tranche 1 = ca11 complete + SCOTUS precedential; tranche 2 = SCOTUS memoranda, gated on the Phase 0 experiment (i) budget check and the Phase 2 census numbers.

## 2026-06-10: Record schema draft (locks at Phase 1 task 1.5)
Per-case record: checksum = canonical citation plaintext, checksumAlgo = "cite-canonical-v1", uri = CourtListener cluster URL, metadata = compact JSON {name, year, cluster}. Receipts (registry receipts-v1): checksum = document SHA-256, checksumAlgo = "sha256", metadata = full receipt JSON. Registry names = courts-db IDs prefixed "us-". Canonical citation key = the reporters-db EDITION string (F.3d, not F.) with the FIRST-PAGE rule: interior/pin pages are never keys. The first-page rule is load-bearing: the fake Varghese cite (925 F.3d 1339) falls on an interior page of a real case (J.D. v. Azar, 925 F.3d 1291, D.C. Cir.), and first-page keying is why it still returns NOT_FOUND.

## 2026-06-10: Status enum: five statuses plus an orthogonal name_check field
VERIFIED / NOT_FOUND / NOT_COVERED / AMBIGUOUS_JURISDICTION / UNPARSEABLE. NOT_COVERED is new versus the draft: a cite that parses and maps to a court with no on-chain registry (for example a ca2 cite during the scotus+ca11 pilot). Without it, out-of-corpus cites would falsely smell fabricated, and receipts would over-claim. Per-result field name_check: match | mismatch | unknown, a fuzzy compare of the brief's party names against the registry record's case name. It catches the other Mata failure mode (a real citation paired with an invented case name) while staying inside the existence-only invariant: it reports what the registry metadata says the citation denotes, nothing about holdings. It is a field, not a status, because existence and name-pairing are different dimensions and name matching is heuristic.

## 2026-06-10: Golden vector sourcing: published constants + ethers as the independent oracle
Tasks 0.1/0.2 pin keccak-256 and RLP with two independent sources: digests and encodings published in the literature and the Ethereum specs (hardcoded in the tests), and vectors generated by ethers 6.16.0 (shares no code with this repo), vendored with their generator scripts under tests/golden/. This replaces the originally planned download of the Keccak team's KAT files: same independence property, no network dependency, and the generator scripts make regeneration reproducible. The EIP-155 worked example and RFC 6979 Appendix A vectors still come from their primary documents in tasks 0.3/0.4.

## 2026-06-10: Task 0.6 live-testnet findings (round-trip succeeded; dev-probe registry id 733)
- The public RPC sits behind Cloudflare, which blocks the default Python urllib user agent (error 1010); rpc.py identifies as `nvnm-cite/0.1.0`.
- Keyed query misses ERROR instead of returning empty pages: `registries(name=<missing>)` and `records(<registry>, <absent checksum>)` both raise `collections: not found: key ...` through eth_call. The verifier's NOT_FOUND path and the registry-existence check must catch this RpcError pattern; an empty page is NOT the miss signal. A keyed hit returns the full record.
- Chain-set fields: recordId and index number from 1, not 0. Timestamps come back as Go time strings (`2026-06-10 23:10:26.453704492 +0000 UTC`). Registry `creator` is returned in bech32 (`nvnm1...`), not 0x form, even via the EVM interface.
- `count_total=True` on a keyed single-record query returned `total=0`; treat the total as meaningful only for list/pagination queries pending the (g) experiment.
- Gas, measured: addRegistry 63,587; addRecord with ~120 bytes of strings 83,201; node-suggested gas price 45 gwei; eth_estimateGas was exact to the unit on both. Record cost ≈ 0.0037 wmantraUSD (~$0.004). Extrapolation: tranche-1 bulk load (~300k records) ≈ 1.1-1.5k wmantraUSD. The wallet's 10 wmantraUSD covers all Phase 0 work but NOT the Phase 2 bulk load; arrange funding before the load session.
- The from-scratch signer is chain-validated end to end: the node's computed tx hash matched ours on both sends.

## 2026-06-10: Git strategy: main-only with phase-N-done tags
No feature branches: solo project, no reviewer, and the continuity protocol depends on every new session resuming from one unambiguous checkout (CLAUDE.md auto-load reads the working tree). Tags give milestone/rollback semantics read-only. Repo: github.com/aberdellans/nvnm-cite, private; can transfer to an org later if needed.
