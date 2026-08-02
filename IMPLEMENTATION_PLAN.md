# nvnm-cite Implementation Plan

## Status
- Current phase: MAINNET TRANSITION COMPLETE (2026-07-31) — the full corpus is live on mainnet 1611 (2,114 court registries, ids 69–2182, 11.94M records, MANTRA state migration 2026-07-30) and the whole codebase migrated to the BREAKING anchoring v1.2.0 interface: registry names are non-unique, every read/write keys on the numeric registryId (old selectors dead on BOTH networks). Shipped: network profiles + a mainnet signing guard (`config.signing_context`; reads default mainnet, writes testnet), pinned creator-verified name→id manifests (`chain/registry_manifest_*.json` + `manifest-verify`), coverage = all 2,114 (Albert's call; NOT_FOUND outside the proven federal-appellate set carries an expanded-coverage caution), the two-step receipts flow (create → id from the AddRegistry event → id-keyed anchor; filing line carries the #id), chain-index schema v2, webapp 0.2.0 (server-fed network identity, verify-by-#id + legacy-name fallback, creator listing, mainnet browser smoke green). 528 tests + opt-in mainnet read-only smoke. KEY FINDING: the .env dev key IS the mainnet admin (rotation = pending team ops). Full detail in DECISIONS 2026-07-31. Phase 5 (MCP server) SUPERSEDED 2026-08-02: Albert decided against an nvnm-cite MCP server; the agent-facing surface is the website's own agent docs (DECISIONS 2026-08-02).
- Last completed (2026-08-02, second session): PUBLIC-RELEASE PREP — full-history secret scan CLEAN (78 commits; `.env` never tracked, `NVNM_TESTNET_KEY`/`COURTLISTENER_TOKEN` in no commit, golden keys are synthetic spec examples); dropped the pre-v1.2.0 historical scripts (phase0/phase2/backfill + CSV; preserved in history + phase tags) and the merged r2 design bundle; archived completed proposals, design docs, and the old ABI to `docs/ARCHIVE/`; README layout refreshed; version aligned to 0.2.0 (package + pyproject) with readme/urls metadata. FINDING: the GitHub repo is ALREADY PUBLIC — the admin-key-location disclosure in the state files is public, so rotation moved from pending to URGENT; no LICENSE file exists (public default = all rights reserved; the 6.4 human-gated licensing decision is now live). Full detail in DECISIONS 2026-08-02 (release prep). Prior (same day): AGENT-FACING WEB SURFACE — the site itself now teaches AI agents the API: `llms.txt` (root discovery), `agents.md` (workflow tutorial with curl examples + verdict semantics), `openapi.json` (OpenAPI 3.1 contract for all six endpoints; freezes the raw-bytes-POST + X-header shape as the public v0.2 contract), `robots.txt`, all shipped in webapp static/ (`.json`/`.md` added to the static whitelist — the only server change); copy is network-neutral (agents read /api/status first). Decisions: NO nvnm-cite MCP server (Phase 5 superseded), no changes to the generic NVNM Chain MCP server, `GET /api/cite` REJECTED (citations in URL space, context-free verdict drift, RPC load). nvnmcite.com purchased; devops to host the app there. 551 tests green. Full detail in DECISIONS 2026-08-02. Prior (2026-07-16): MAINNET BULK-LOAD EXPORT generated and validated — full US case-law scope, one gzipped JSONL file per court registry in submit shape, for the blockchain-team bulk upload. Fresh 2026-06-30 snapshot: 11,944,960 records / 2,114 registries (3.60 GB raw, 476 MB gz), tranche-laddered (T1 1,028,222 / T2 545,922 / T3 3,617,459 / T4 6,753,357), records+exclusions reconcile to the census keys EXACTLY, live-testnet + chain-read-sample cross-checks byte-identical. Scope v2 (CL types 1/2/3/5/8 + reporters-db edition check) supersedes the pilot whitelists for the mainnet set; 17,992 exclusions (92% `P.R.`) documented, deferred to 7.7. Deliverable in `data/mainnet-full-export/` (gitignored; zip 437 MB). New: `--courts all` corpus mode, `loader/export.py`. Full detail in DECISIONS 2026-07-16. Prior (2026-07-15): webapp round-2 flow revisions integrated from the Claude Design r2 bundle — verdict-first results, severity grouping + NOT COVERED disclosure, registry-line-before-anchoring step (4-step stepper), wallet/paste guidance, sticky tabs, coverage honesty, Mata sample link; bundle merged not swapped (it regressed to round-1 assumptions — see DECISIONS 2026-07-15); server signals registry_line_found + source snippets; 490 green + live testnet smoke. Prior: ABI vendoring (+2 functions, typed builders, ethers-regenerated goldens; 490 tests green) + corrections to CLAUDE.md / mantra-brief (corrigendum) / proposal-mainnet / this plan (exp (f) note, W1 → RESOLVED); LIVE status-change test on dev-probe with Albert's OK (2 txs: index-1 → Superseded → Active; event fired; latest read untouched; ~43.5k gas; state restored). MANTRA answered the open design questions by email (Lance): free-form status, in-place + reversible, archival commitment, metadata convention (reason/correctedField/supersededBy) coming in module docs.
- Next up: (1) the LIVE two-tx receipt anchor on testnet through the new flow — pending Albert's explicit OK (the code path is hermetically proven; prepare/estimate verified live); (2) team ops: mainnet admin-key rotation (grantRole new + revokeRole old across 2,114 registries, or MANTRA-side) — NOW URGENT: the repo is public and the state files disclose the key's location (no key material leaked; scan clean); (2b) Albert: LICENSE decision + GitHub repo description (public repo currently all-rights-reserved by default); (3) full mainnet reconcile of the 11.94M records vs the export files (handoff acceptance — separate ops effort); (4) nvnmcite.com stand-up by devops (serve the app as-is; CDN must not override `Cache-Control: no-store`; `openapi.json`'s servers block assumes a root mount); (5) 7.7 state-normalizer work — largely delivered 2026-08-01 (normalizer 1.1.0: corpus-derived reporter inference, parenthetical index, vendor disposition; 96.8% record-weighted corpus reachability); remaining: the expanded-coverage caution stays until state-cite recall is proven against real filed briefs, and genuinely split editions (N.Y.2d, Misc.*, M.J.) stay ambiguous by design. Open with MANTRA: events guarantee going forward, EOA-only writes vs multisig registry owners, records() reverse/countTotal fix.
- STRATEGIC RE-SCOPE (2026-06-24): Phase 7 (mainnet) rewritten to FULL US case-law scope — all federal (incl. ~94 districts, bankruptcy, specialized) + ALL state courts. Measured: ~7.84M cases / ~11.9M citation records / ~$55k gas (state is ~87%); mainnet gas confirmed live (45 gwei, precompile parity). Federal-appellate backbone (924,421 records / $4,252) is tranche 1; state needs a normalizer rebuild (7.7). See the rewritten Phase 7 + Future development wishlist.

How to read this file: one section per phase with Goal / Depends on / Tasks / Exit criteria. Tick checkboxes as tasks complete and refresh the Status header at session end. Settled choices and measured results go to DECISIONS.md, not here. The session kickoff prompt is in README.md.

Session budget: 9-12 build sessions (P0: 2-3, P1: 1-2, P2: 2-3, P3: 1, P4: 1-2, P5: 1, P6: 1). P3 can merge into P4 if sessions run long.

---

## Phase 0: Pure-Python signer + precompile characterization (2-3 sessions, plan mode)

**Goal:** A golden-tested from-scratch signer, thin precompile wrappers, one successful write/read round-trip on testnet, and empirical answers to every remaining chain uncertainty, recorded in DECISIONS.md.

**Depends on:** `.env` populated with a funded testnet key (`NVNM_TESTNET_KEY`).

**Tasks:**
- [x] 0.1 `src/nvnm_cite/chain/keccak.py`: keccak-f[1600] + keccak-256 with ORIGINAL Keccak padding (hashlib.sha3_256 is NIST SHA-3, a different algorithm). Goldens in `tests/golden/keccak/`: published literature digests + ethers-oracle vectors straddling the 136-byte sponge rate (vector sourcing: see DECISIONS 2026-06-10), plus a negative test asserting output differs from hashlib.sha3_256 on the same input.
- [x] 0.2 `src/nvnm_cite/chain/rlp.py`: RLP encoding (bytes, ints, lists; encode-only). Goldens: published RLP spec examples + ethers encodeRlp oracle vectors (55/56-byte boundaries, 0x7f/0x80 single-byte edge, long-form lengths, legacy-tx shape).
- [x] 0.3 `src/nvnm_cite/chain/secp256k1.py`: generic Weierstrass curve ops + RFC-6979 deterministic k (HMAC-SHA256 via stdlib `hmac`), EIP-2 low-s, EIP-55 addresses. Goldens: RFC 6979 Appendix A.2.5 P-256 vectors verbatim from rfc-editor.org (nonces AND full signatures, exercising the same generic code paths), plus ethers-oracle exact r/s/recovery-id agreement on secp256k1 and key-to-address pairs.
- [x] 0.4 `src/nvnm_cite/chain/signer.py`: EIP-155 legacy type-0 signing with `chain_id` as a parameter, plus `parse_private_key` (0x prefix optional per the MetaMask convention). Goldens: the EIP-155 worked example verbatim from eips.ethereum.org (signing data, sighash, v=37, exact r/s, full raw tx), plus ethers Transaction oracle vectors for chain 787111 including precompile-target and 600-byte-calldata cases (unsigned hash, raw bytes, and tx hash all match exactly).
- [x] 0.5 `src/nvnm_cite/chain/abi.py` + `precompile.py`: generic head/tail ABI codec (string/bytes/uintN/bool/address/tuple/tuple[]) + typed builders and decoders for all five methods, driven by the vendored ABI (moved into the package at `src/nvnm_cite/chain/anchoring.json`). Goldens: published selectors confirmed (addRecord=9b7b7869, addRegistry=318b38b1, records=02abafdf; ethers additionally pins grantRole=b8fdd1a7, registries=15ae270f) and ethers Interface oracle agreement on calldata + result decoding, including unicode and pagination-key cases.
- [x] 0.6 Round-trip on testnet (2026-06-10): `dev-probe` registry created (id 733), test record anchored and read back via keyed `records()` eth_call, both txs confirmed and Blockscout-indexed with the plaintext visible in calldata (the plaintext-on-chain claim, demonstrated live). New modules: `chain/rpc.py` (stdlib JSON-RPC client, custom User-Agent for Cloudflare), `config.py` (.env loading, 0x-optional key parse), `scripts/phase0_roundtrip.py`. Empirical findings logged in DECISIONS (keyed-miss errors, index starts at 1, gas numbers).
- [x] 0.7 Experiment matrix COMPLETE (2026-06-10): all of (a)-(i) answered empirically; results consolidated in the DECISIONS entry "Task 0.7 experiment matrix results" and adversarially audited before recording. Sub-items as run:
  - [x] (a) Duplicate (registry, checksum): submit an identical record twice, then the same checksum with different metadata. Which behavior: revert as duplicate (observed on mainnet, May 2026) or new index / isLatest flip (chain spec)? Also test whether eth_estimateGas already reverts on the duplicate (a free idempotency probe for the bulk loader).
  - [x] (b) Metadata size ceiling + gas curve: addRecord with metadata of 256 B / 1 KB / 4 KB / 8 KB / 16 KB / 32 KB / 64 KB until failure; record gas used at each step. Sets the receipt design (task 4.3) and the cost model (task 2.6).
  - [x] (c) addRegistry name uniqueness: create `dev-probe` twice; reject or duplicate id?
  - [x] (d) Write permissions: from a second throwaway key, attempt addRecord into the first key's registry (expect deny); grantRole editor to key 2; retry (expect allow). Validates that the third-party-attestor invariant is possible, not just claimed.
  - [x] (e) Throughput: ~200 sequential-nonce addRecords at pipeline depths 1 / 5 / 20; measure sustained confirmed-tx/s and whether the mempool accepts nonce-gapped bursts.
  - [x] (f) updateRecordStatus present? eth_call its selector; "unknown method" means still missing (it was absent from the deployed testnet binary as of May 2026). Sets the correction policy: supersede with a new version or write a tombstone record, contingent on (a). *(SUPERSEDED 2026-07-07: the function WAS deployed all along — the probe and the May report both guessed name/checksum-keyed signatures, but the real signature is id-keyed: `updateRecordStatus(registryId, recordId, index, status)`. See DECISIONS 2026-07-07. The v1 correction policy stands regardless.)*
  - [x] (g) records() pagination stability while a concurrent writer appends; find the max page size one eth_call returns.
  - [x] (h) Historical eth_call depth: call records() at height minus 1000 or more. Does the public RPC serve archive state? (The NVNM_MCP_Server repo has an archive-RPC env var, which hints one exists.) Receipt re-verification pinned to a block depends on this; the fallback is designed in task 4.4.
  - [x] (i) Gas budget: key balance versus planned testnet record count x measured gas x 40 gwei. Decide the tranche scope BEFORE the bulk load. If short, top up via the DuKong bridge flow documented in nvnm-tutorial/README.md.

**Exit criteria:** all goldens green with zero non-stdlib runtime deps in `chain/`; one registry + record visible on the testnet explorer; DECISIONS.md entries for (a)-(i); duplicate handling, metadata ceiling, and checksumAlgo strings settled.

---

## Phase 1: Normalizer, jurisdiction mapper, open spec (1-2 sessions)

**Goal:** Text in, list of (as_written, canonical, registry, metadata) out, under an open versioned spec, with the on-chain record schema locked.

**Depends on:** Phase 0 experiments (a) and (b) for task 1.5; the rest can start any time.

**Tasks:**
- [x] 1.1 Add dependencies `eyecite`, `reporters-db`, `courts-db` via uv; record version pins and licenses in DECISIONS.md.
- [x] 1.2 `normalizer/canonical.py`: `clean_text(["all_whitespace", "underscores"])`, then `get_citations`, then `resolve_citations`. Canonical form = `"<volume> <corrected_reporter()> <page>"`. Short forms (short cites, id., supra) inherit the antecedent's canonical via eyecite's Resource grouping. Export `NORMALIZER_VERSION`.
- [x] 1.3 `normalizer/jurisdiction.py`: eyecite's `metadata.court` (already a courts-db id, e.g. `ca11`, parsed from the court parenthetical) + the reporter's cite_type map to a registry name (`us-` + courts-db id). U.S. / S. Ct. / L. Ed. map to `us-scotus` (eyecite flags scotus editions even without a parenthetical). F.2d / F.3d / F.4th / F. App'x with no recognizable court parenthetical: return AMBIGUOUS_JURISDICTION. Never guess.
- [x] 1.4 `docs/canonical-citation-spec.md` (cite-canonical/v1, the open spec): canonical key is the reporters-db EDITION string (`F.3d`, not `F.`; editions are what appear in citations and in CourtListener's citation table, so registry keys and corpus keys align by construction); volume/page normalization rules; the FIRST-PAGE rule stated explicitly (registry keys are first-page citations; interior/pin pages are never keys); parallel citations are distinct records sharing a cluster id. Spec version constant exported from the package.
- [x] 1.5 Lock `docs/record-schema.md` v1 from the draft in DECISIONS.md, informed by experiments (a)/(b). The locked schema must assign every chain-required tuple field a non-empty value for BOTH record types (uri, checksumAlgo, metadata are required; receipts get a defined uri, e.g. the published spec URL, chosen here rather than improvised at anchor time) and respect the measured caps (checksum 64 B, uri/metadata 2048 B; collision case-arrays included). Mirror the one-paragraph summary into CLAUDE.md. After this point, schema changes require a version bump, never an edit.
- [x] 1.6 Golden suite: 200+ fixtures covering parallel citations, reporter variants (`"F. 3d"`), short-form chains, line-break-mangled strings, missing parentheticals; plus 3-5 real RECAP brief PDFs as integration fixtures with a source-URL manifest (the actual Mata v. Avianca brief is in RECAP, SDNY 1:22-cv-01461, and makes a fitting fixture).

**Exit criteria:** golden suite green; spec + record schema reviewed by Albert; normalizer version stamped in every output object.

---

## Phase 2: Corpus pipeline, chain index, bulk load, reconcile (2-3 sessions)

**Goal:** SCOTUS + ca11 corpora extracted from CourtListener bulk data, loaded into testnet registries, and a reconcile command proving chain matches corpus.

**Depends on:** Phases 0 and 1.

**Tasks:**
- [x] 2.1 `loader/courtlistener.py`: streaming three-file join over the quarterly bulk CSVs (S3 bucket com-courtlistener-storage, prefix bulk-data/). Needed files only: citations (~127 MB bz2), opinion-clusters (~2.5 GB bz2), dockets (~5 GB bz2). The ~40 GB opinions full-text dump is NOT needed. Pass 1: stream dockets, keep docket_id where court_id in {scotus, ca11}. Pass 2: stream clusters, keep (cluster_id, case_name, date_filed) for those dockets. Pass 3: stream citations, keep (volume, reporter, page, type, cluster_id) for those clusters. Write to `corpus.sqlite`. Handle the COPY escape format; raise csv.field_size_limit; downloads under `data/` (gitignored); never materialize uncompressed files.
- [x] 2.2 Census FIRST, before any chain write: per-court cluster and citation-row counts; precedential vs memoranda split; citation-string collisions (distinct cases sharing a first page; the record metadata uses a case array when it happens); confirm `925 F.3d 1339` is absent; confirm ca11 2019 F.3d coverage (the demo gate; fallback to ca2 per DECISIONS.md). All numbers go to DECISIONS.md.
- [x] 2.3 `chain/indexer.py`: OFFSET-paged `records()` eth_calls into `chain_index.sqlite` (per (g): plain row-offset cursor per registry, pages capped at 200 rows server-side, end-of-data detected by a short page, never by countTotal which is unreliable; store index and isLatest so versions coexist, and reconcile diffs against isLatest). CLI: `sync` (incremental) and `rebuild-index` (from scratch). rebuild-index is the public-auditability story made executable: anyone with an RPC URL can reconstruct the registry without trusting us.
- [x] 2.4 `loader/bulk_load.py`: checkpointed writer. SQLite `load_state(canonical, status pending/submitted/confirmed, tx_hash, nonce)`; single-key monotonic nonce manager seeded from `eth_getTransactionCount(pending)`; pipeline depth from experiment (e); on a stuck nonce, re-send the same nonce at +25% gas; on RPC ambiguity, halt and reconcile rather than guess. Idempotency (per (a): duplicates VERSION; the revert branch is dead and estimateGas detects nothing): the checkpoint DB is the ONLY guard; never blind-resubmit; on resume, re-verify only the in-flight window via keyed `records(registry, checksum)` reads, treating the keyed-miss RpcError ("collections: not found") as not-loaded. Submission is strictly serialized per key in nonce order (gapped nonces are rejected at submission, per (e)); a failed send halts everything queued behind it. Do not pre-check existence per record in steady state (doubles RPC traffic for nothing).
- [x] 2.5 `loader/reconcile.py`: `corpus.sqlite` vs `chain_index.sqlite` diff producing a coverage report (missing-on-chain, extra-on-chain, metadata drift). First-class CLI command and a demo artifact, not a test utility.
- [x] 2.6 Testnet load. Tranche 1 = ca11 complete + SCOTUS precedential. Tranche 2 = SCOTUS memoranda, gated on budget (experiment (i)) and census numbers. Measure real gas/record and sustained confirmed-tx/s; extrapolate the mainnet load cost into DECISIONS.md. Cost model, now measured (0.6/0.7): ~96-155k gas per record depending on metadata size, 45 gwei in practice, so 300k records ~= 1.2-1.6k wmantraUSD; single-key throughput plateaus at ~1.1 tx/s (300k records ~= 3.2 DAYS per key), so the load plans parallel editor-granted keys (per (d)) and the ~2,000 wmantraUSD top-up decision from DECISIONS (i) gates the session. The load runs as a detached background process against the checkpoint DB (essential at this wall clock, not optional); no session babysits it, and the next session starts with `reconcile`.
- [x] 2.7 `loader/update.py`: daily incremental append of newly published opinions via the REST API (date_MODIFIED cursor - see DECISIONS 2026-06-13; date_created misses late-added cites), cron-shaped, with `--dry-run`. The citation-lookup API (250 cites/request, 60 valid cites/min) is a spot-check oracle only: never the bulk path, never in the verifier's runtime.

**Exit criteria:** `us-scotus` and `us-ca11` populated on testnet (tranche 1); reconcile diff zero or every gap documented; measured throughput and cost table in DECISIONS.md.

---

## Phase 3: Verifier (1 session; may merge into Phase 4)

**Goal:** `nvnm-cite check brief.pdf` produces honest per-citation statuses by reading the chain LIVE (item 0). A shared verifier core (extract → normalize → map → live keyed lookup → 5 statuses + name_check) is called by BOTH the CLI and the webapp, so eyecite stays the one reference normalizer (invariant 5). NOTE: much of this already exists in `src/nvnm_cite/webapp/` (extract.py, CheckService, ChainGateway.keyed_record) — Phase 3 factors it into a shared core and adopts the live-read default.

**Depends on:** Phases 1 and 2.

**Tasks:**
- [x] 3.1 `verifier/extract.py`: PDF (pdfplumber), DOCX (python-docx), plain text. Text cleanup before eyecite (line-break-mangled citations are the main recall killer in real PDFs). Extraction recall measured against the RECAP fixtures and committed alongside the goldens.
- [x] 3.2 `verifier/check.py`: extract, normalize, map, look up. Drafting-time default is now a LIVE keyed `records(registry, checksum)` eth_call against the NVNM-operated RPC (item 0; reverses the old local-only rule, amended invariant 3). NOT_FOUND comes from catching the keyed-miss RpcError ("collections: not found"), never an empty page; transport/RPC failures must NOT be classified as NOT_FOUND; status and name_check read the isLatest version. The local `chain_index.sqlite` is an optional cache + the `rebuild-index` audit tool, never the authority. Surface the exact query for replay (non-repudiation).
- [x] 3.3 Statuses (locked in DECISIONS.md): VERIFIED / NOT_FOUND / NOT_COVERED / AMBIGUOUS_JURISDICTION / UNPARSEABLE, plus the per-result `name_check: match | mismatch | unknown` field (fuzzy compare of the brief's party names against registry metadata).

**Exit criteria:** end-to-end run on the RECAP fixtures plus a synthetic brief that exercises all five statuses and a name_check mismatch.

---

## Phase 4: Receipts + anchoring (1-2 sessions)

**Goal:** Filing-time receipts anchored to a PER-FIRM-PER-CASE registry on testnet, verifiable by a cold third party via the registry link on the filing (item 3).

**Depends on:** Phase 3, plus Phase 0 experiments (b) and (h).

**Tasks:**
- [x] 4.1 `receipts/schema.py`: LOCK the MINIMAL receipt v1: {schema: "nvnm-cite-receipt/v1", chain_id, document_sha256, checked_at_block, normalizer_version, registries: [{id, name, head_block}], summary: {checked, verified, not_found, not_covered, ...}, agent: {address}, timestamp}. NO per-case results array and NO kya_id (identity = wallet, item 2). The SHA-256 binds the document so verdicts are reproducible; the tally is non-identifying (item 2b). Canonical serialization: sorted keys, no whitespace, UTF-8. ~480 B, always under the 2048 B cap. DONE 2026-06-15 — also locked the per-firm-per-case registry naming (filer-chosen `<firm>--<case>`, Albert's call); creation strings + naming helpers in `receipts/schema.py`; docs/record-schema.md §2/§4 re-locked; tests in tests/test_receipts.py.
- [x] 4.2 `receipts/anchor.py`: addRecord to the filing party's PER-FIRM-PER-CASE registry (checksum = document SHA-256 hex; checksumAlgo = "sha256"; metadata = the minimal receipt JSON, always fits; uri = the defined receipts uri). Includes one-time registry creation/onboarding for a (firm, case) — the creating wallet becomes admin (self-sovereign, no NVNM gatekeeper). Anchoring happens only with an explicit `--anchor` flag. DONE + round-tripped LIVE 2026-06-15: `prepare_anchor` (read-only, pins the check to a block) + gated `send`; created `inveniam--mata-v-avianca` (tx 0xf86554ba…, 77,235 gas) and anchored the Mata ECF24 receipt (tx 0xdb9b1508…, 123,530 gas).
- [x] 4.3 Chunked receipt design — DROPPED, no longer needed (DECISIONS 2026-06-13 item 2b). With no per-case enumeration a receipt is ~480 B and always fits the 2048 B cap, so there is nothing to chunk; the webapp's compaction ladder is removed too. (Re-instate only if a future receipt variant ever enumerates.)
- [x] 4.4 `receipts/verify.py`: (registry + original file) in — the registry comes from the filing's "Citation verifications" link (item 3); hash the file locally, do a keyed `records(registry, hash)` lookup, recompute the document SHA-256, re-run the check pinned to checked_at_block (archive eth_call primary; 0.7 (h) confirmed full archive state; rebuild-to-height as resilience), report match or mismatch. Takes (registry + file), NOT a bare hash. This is the artifact a court or insurer consumes. DONE + proven LIVE 2026-06-15: original → VERIFIED (recompute matches the stored tally at the pinned block); one-byte-tampered copy → NO RECEIPT (keyed miss); `verify` exits nonzero when not cleanly verified.
- [x] 4.5 `cli.py`: `nvnm-cite check | anchor | verify | sync | rebuild-index | reconcile | stats | load`. `stats` (and Phase 5's registry_stats/coverage) derive figures from chain_index.sqlite with its sync head stated, never from the precompile's countTotal (unreliable per 0.7 (g)). DONE 2026-06-15: `check`/`anchor`/`verify`/`stats` are structured subcommands; `sync`/`rebuild-index`/`reconcile`/`load`/`update` delegate to their existing module mains (no logic duplication; `<cmd> --help` shows the module's flags, `nvnm-cite --help` lists them in an epilog). `stats` reuses `indexer.index_stats`. Live: `nvnm-cite stats` reports us-scotus 218,775 + us-ca11 41,988 from the local index.

- [x] 4.6 RPC query telemetry: aggregate case-frequency analytics from the live `records()` lookups (item 0), keyed BY CITATION and decoupled from document hash + client identity; internal use; disclosed in the privacy copy (item 2b). DONE 2026-06-15: `verifier/telemetry.py` (`SqliteTelemetry` thread-safe + `NullTelemetry`) records only `(registry, citation) → (lookups, hits)`; hooked into `ChainResolver` (records on hit/keyed-miss, never on transport error); opt-in via `nvnm-cite check --telemetry <path>` (off by default). Schema test pins that no document/identity column exists. Webapp enablement + the disclosure copy fold into Phase 4.5.

**Exit criteria:** anchor + verify round-trip on testnet against a real RECAP brief; the receipt is human-readable on the registry view; a cold third party, given only the filing's registry link + the file, finds and verifies the receipt; verify catches a one-byte tamper of the document.

---

## Phase 4.5: Web app — merge the frontend workstream, harden, host (1-2 sessions)

**Goal:** The existing web demo (`src/nvnm_cite/webapp/`, already on main: commits 2200e32, 41e00c3) becomes the primary product surface — adopting item 0, the minimal receipt, and the per-firm-per-case registry model — honest and usable when hosted (not just on localhost). This phase MERGES the parallel frontend workstream into the plan; the architecture decisions are the DECISIONS 2026-06-13 entries (the prepared-copy working doc docs/webapp-revision-notes.md was removed in the 2026-06-27 repo cleanup; its decisions live in those DECISIONS entries).

**Depends on:** the re-scoped Phase 3 (shared verifier core) and Phase 4 (receipt v1 lock + registry model).

**Tasks:**
- [x] 4.5a Wire item 0 into `CheckService`: resolve via the live keyed read (drop the local-index lookup; promote the existing `ChainGateway.keyed_record` path); surface the replayable `eth_call` query in the Check result. DONE in Phase 3 (CheckService now delegates to the shared `verifier` core with a `ChainResolver`; the result carries a per-citation `query`; honest privacy copy). Remaining for the 4.5 pass: render the replay query visibly in the Check UI.
- [x] 4.5b Hosting model + honest copy: document uploaded → parsed in memory server-side (eyecite, the one normalizer) → discarded with the response; never persisted, never on chain. Rewrite the Check-tab privacy copy (item 1); add the "we keep aggregate lookup stats as RPC operator" disclosure (item 2b). DONE: Check privacy copy was corrected in Phase 3; the telemetry disclosure renders in the Check callout when `/api/status.telemetry.enabled` (webapp `--telemetry <path>`, off by default, by-citation only, un-joinable to doc/identity — verified live).
- [x] 4.5c Receipt + registry UX: drop the kya_id input (show "Attesting as 0x…"); remove the compaction ladder (minimal receipt); per-firm-per-case registry create/onboarding flow; the Verify tab takes (registry link + file), not a bare hash; a CLEAR, clerk-legible registry view. DONE: `ReceiptService.prepare` re-uploads the file + delegates to `prepare_anchor` (byte-identical to the CLI); Record tab has filer/case inputs + live `<firm>--<case>` name preview + "Attesting as 0x…"; setup-box creates the per-case registry; Verify takes (registry + browser-hashed file) and renders the non-enumerating clerk-legible receipt card (attester / block / registries read / tally). Verified live: prepare → 526 B v1 receipt; verify found it by (registry+hash); tamper/unknown-registry handled.
- [x] 4.5d Copy rewrites: Inspect (drop jargon — item 5); About + lawyer FAQ (newcomer-friendly, figures rendered live from `/api/status`, never hard-coded — item 6); Verify copy stays as-is (item 4, now "fingerprint + registry name leave the browser"). DONE + screenshotted: Inspect ("transaction reference", "stored as plain text", no mojibake/ABI-framing); About is the newcomer explainer + 8-Q lawyer FAQ with the coverage figure rendered live from the coverage rows.
- [x] 4.5e `StatusService` fast-fail: short RPC timeout / lazy-cached probe so a slow or down RPC does not block server startup (the ~30 s stall observed 2026-06-13). DONE: the status panel probes through a dedicated SHORT-timeout (`STATUS_RPC_TIMEOUT = 4 s`) gateway, distinct from the 30 s default the check/receipt paths use; lazy + 10 s cached; pinned by `test_server_status_fast_fails_on_dead_rpc`. (The "eager probe at construction" was already gone since Phase 3; the remaining fix was the timeout.)

**Exit criteria:** MET — hosted-mode copy is accurate; a check reads the chain live and shows the per-citation replay query; a receipt anchors to a per-firm-per-case registry and a cold third party verifies it from the filing's registry link + the file (proven live: ECF24 receipt in `inveniam--mata-v-avianca`); the registry view (the Verify receipt card) is legible to a non-technical reader.

---

## Phase 5: MCP server (1 session)

*(SUPERSEDED 2026-08-02: Albert decided against building an nvnm-cite MCP server and against modifying the generic NVNM Chain MCP server. The agent-facing surface is the website itself — llms.txt / agents.md / openapi.json served from webapp static/, built this session. See DECISIONS 2026-08-02. Tasks below retained for the record, not to be built.)*

**Goal:** Any agent can call the verifier. Stdio transport first; this is the KYA story.

**Depends on:** Phase 4.

**Tasks:**
- [ ] 5.1 MCP server on the official Python MCP SDK (FastMCP), stdio transport. Tools: `check_citations` (read-only), `anchor_receipt` (requires an explicit confirm argument), `verify_receipt`, `registry_stats`, `coverage(court)`. Mark read-only vs destructive in tool annotations.
- [ ] 5.2 Claude Desktop config snippet in README; smoke-test from the desktop app (the actual runtime here) against testnet.
- [ ] 5.3 HTTP transport and any mcp.nvnmchain.io fold-in: deferred to post-pilot. Note the decision, build nothing.

**Exit criteria:** all five tools callable from Claude Desktop against testnet; anchoring impossible without the explicit confirm argument.

---

## Phase 6: Demo + pilot wrap (1 session)

**Goal:** The two-minute Mata v. Avianca demo, scripted, rehearsed, and recorded.

**Depends on:** Phases 4 and 5; the Phase 2 census gate (Varghese absent, ca11 2019 F.3d coverage confirmed).

**Tasks:**
- [ ] 6.1 Fixture brief PDF (born-digital): 5 real SCOTUS cites + 1 real ca11 cite + "Varghese v. China Southern Airlines, 925 F.3d 1339 (11th Cir. 2019)" + 1 real ca2 cite. The ca2 cite shows NOT_COVERED honestly on stage, which turns the pilot's scope limit into a trust feature.
- [ ] 6.2 Demo script, under two minutes, rehearsed twice: `check` (Varghese comes back NOT_FOUND in seconds), `anchor`, open the explorer to the receipt tx with readable calldata, `verify`, tamper one byte of the PDF, `verify` again and watch it fail.
- [ ] 6.3 `demo/RUNBOOK.md` + a terminal recording.
- [ ] 6.4 Pilot-close DECISIONS.md entry listing the mainnet cutover preconditions: key ceremony for the registry write key and the receipts agent key (outside Claude Code sessions), open-source posture for the normalizer (open spec; reference implementation licensing decision), registry ID + spec + schema publication, mainnet load budget sign-off (extrapolated cost from task 2.6). All human-gated.

**Exit criteria:** demo runs clean from a fresh shell on testnet; a third party, given only the explorer and the published spec, can independently verify the receipt.

---

## Phase 7: Mainnet production plan — FULL US case-law scope (author before mainnet)

**Goal:** A written, human-gated PLAN (a document, not code) for running NVNM Cite on mainnet 1611 as a production service whose NOT_FOUND a lawyer can trust — at FULL US case-law scope (all federal courts incl. ~94 districts + bankruptcy + specialized, AND all state courts), not just the federal-appellate pilot backbone. Folds in the mainnet cutover preconditions (task 6.4) and the testnet pilot's lessons.

**Depends on:** the whole pilot (Phases 0–6) as the evidence base; the normalizer rebuild (7.7) before any state tranche.

**Scope DECIDED (2026-06-24 exploration; settles the old 7.4 "which courts" question):** the production target is the full US case-law citation graph, loaded in tranches. Why full, not federal-appellate-only: (1) coverage breadth = anti-hallucination power — an uncovered court turns a fabricated cite into NOT_COVERED, indistinguishable from real-but-uncovered, so a narrow scope lets fabrications hide; (2) ~90% of US litigation is in STATE courts, so a federal-only service is not "relevant for real-life legal use." Same pipeline + data source (CourtListener/CAP holds essentially all published US case law) + registry model; the genuinely new engineering is the state-reporter normalizer (7.7).

**Measured scale & cost** (CourtListener bulk snapshot 2026-03-31; full census → DECISIONS. Records = distinct citations under real reporters, excluding WL/LEXIS/specialty vendor cites per the pilot rule; raw-distinct, canonical dedup trims modestly):

| Tranche | Citation records | Gas @ $0.0046/rec |
|---|---:|---:|
| 1. Federal appellate backbone (SCOTUS + 13 circuits) — exact | 924,421 | $4,252 |
| 2. Federal complete (+ ~94 districts, bankruptcy, specialized) | ~1,469,892 (all federal) | ~$6,800 |
| 3–4. All state courts | ~10,442,192 | ~$48,000 |
| **FULL US case law (~7,837,721 cases)** | **~11,912,016** | **~$54,800** |

State is ~87% of the universe. Mainnet gas confirmed live (2026-06-24; parity re-confirmed 2026-07-07 within 30 gas on identical calldata — the 83,541 addRegistry figure is payload-specific, ~79.1k with the locked creation strings; parity is the durable claim): 45 gwei; dollar figures assume wmmUSD ≈ $1 — confirm the peg before budget sign-off. The load is submission-bound (~2.1 tx/s/key): full scope is ~65 days single-key, ~1 week with ~10–15 parallel editor-granted keys (the checkpointed loader is already built).

**Tranche ladder (load order; each gated on a PUBLISHED per-court completeness bar):**
1. Federal appellate backbone — proven on testnet; ship first.
2. Federal complete — same federal reporters, no normalizer change (~$2.5k more records).
3. State-normalizer pilot — 3–5 high-volume states (CA, NY, TX, FL, IL) — proves regional / official / parallel / neutral citation handling on real data before scaling.
4. All remaining states, in tranches.

**Tasks:**
- [ ] 7.1 Data-coverage completeness — THE load-bearing trust issue, larger at state scale. The pilot proved CourtListener holds Published opinions with NO reporter cite (e.g. *Muransky*, 979 F.3d 917; ~4.1% of Published ca11 clusters, ~0.0% SCOTUS), false-NOT_FOUNDing real cases. State/older coverage is MORE uneven (CAP strong through ~2018; recent + neutral cites vary). Decide how to close or bound (supplemental source, cluster-name fallback, vetted backfill, scoped guarantees); publish a per-court coverage %; never invent a cite (a cite goes on chain only from an authoritative source). Pilot handling: direct backfill (DECISIONS 2026-06-16).
- [ ] 7.2 NOT_FOUND semantics for production: distinguish "fabricated" from "real but uncovered / missing-from-source"; copy that never nudges a lawyer to delete a real citation.
- [ ] 7.3 Key ceremony + ownership (per 6.4): registry write key(s) + receipts agent key generated and held OUTSIDE sessions; mainnet is never written from a session; the parallel-key fleet (7.6) is part of the ceremony.
- [ ] 7.4 Coverage scope = FULL US case law (DECIDED, above). Court enumeration + per-court census: DONE 2026-07-16 (2,114 registries, per-court counts in the export manifest + DECISIONS; scope rule v2 = CL types 1/2/3/5/8 + reporters-db edition check). Remaining: the tranche schedule + completeness bars; refresh/update cadence + staleness monitoring across all courts.
- [ ] 7.5 Open-source + publication posture: normalizer spec (now incl. state reporters) + reference-implementation licensing; registry IDs / spec / schema publication.
- [ ] 7.6 Cost + load plan — MEASURED (above): ~11.9M records, ~$55k gas. Remaining: confirm the wmmUSD peg; finalize the parallel-key fleet + checkpoint ops at ~12M scale; client-side batched signing if the wall-clock needs it (wishlist W4 if a native batch write is ever added).
- [ ] 7.7 NEW — Normalizer rebuild for state coverage (gating for tranches 3–4; the project's biggest remaining engineering lift). Extend cite-canonical/v1 + the jurisdiction mapper to: the 7 regional reporter families (So./P./S.W./N.E./A./S.E./N.W.), ~50 states' official reporters, neutral / public-domain citation formats, official↔regional parallel-cite resolution, and reporter→state-court registry mapping. eyecite/reporters-db/courts-db already know these reporters; the work is the deterministic canonical spec + an EXHAUSTIVE golden suite (invariant 5: the normalizer is the trust boundary — ~50× the reporters means ~50× the places a normalization bug becomes a wrong NOT_FOUND). Version-bump the normalizer; every receipt records the version.

**Exit criteria:** a reviewed mainnet-plan document exists; full-scope census in DECISIONS; the tranche schedule + per-tranche completeness bars defined; the state-reporter normalizer rebuilt + golden-green; every item has a decision or an explicit "deferred, with reason"; no mainnet write before sign-off.

---

## Future development wishlist (post-mainnet-v1; justification-first, not scheduled)

Candidates beyond the full-scope existence registries, each with the reason it earns a place. None gates mainnet-v1; all extend it.

- [x] **W1 — RESOLVED 2026-07-07: `updateRecordStatus` was already deployed.** The 2026-06/07 MANTRA exchange established: `updateRecordStatus(registryId, recordId, index, status)` is live on BOTH networks (id-keyed; `status` free-form string, no chain enum; in-place, reversible, admin/editor-gated write of status only; prior values reconstructable by archive read — MANTRA commits to the public archival node). The supersession POINTER stays application-side: MANTRA is publishing a recommended metadata key convention (`reason` / `correctedField` / `supersededBy`) in the module docs instead of a chain field. Remaining on OUR side, deliberate and unscheduled: adopting the convention and any non-Active status usage is a record-schema **v2 bump** (v1 policy — status always Active, supersede-by-new-version — stands); wire status handling into verifier/indexer/reconcile tooling only if/when v2 lands. First live status-change test on the dev-probe registry still pending. See DECISIONS 2026-07-07.
- [ ] **W2 — Case-status layer (good-law signals).** On W1: attach overruled / vacated / depublished signals to a case's record, sourced ONLY as a NAMED citator's attested claim (invariant 2), never an NVNM assertion. *Why:* existence-only is correct but leaves the question lawyers fear ("is it still good law?") open; a named-source status layer answers it without NVNM asserting truth. Enabled by one-record-per-case + W1.
- [ ] **W3 — Withdrawal / reassignment handling.** The model is append-only and has no clean story for a cite that DISAPPEARS or is reassigned (rare federally — West doesn't recycle cites — real for state/neutral cites + depublication). *Why:* a correctness edge that grows at state scale; W1's status primitive is the mechanism (mark `Invalid`, keep history).
- [ ] **W4 — Native batch write (`addRecords`).** Propose a batch method to write N records per tx. *Why:* at ~12M records the load is submission-bound; batching amortizes the ~21k intrinsic gas/tx (~22%, ~$12k) and cuts tx count. NOT required (parallel keys already reach full scope in ~1 week) and per-record STORAGE cost dominates regardless — an efficiency win, not a redesign. Does not change one-record-per-case.
- [ ] **W5 — Non-case authority (statutes / rules / regs) — DEFERRED + a near-term transparency fix.** Today the normalizer silently DROPS statutes / rules / regs / constitutional cites (not verified, not flagged, not in the tally). *Near-term, do regardless:* disclose "case citations only" in the receipt + UI (a lawyer should know the check's scope). *Future:* a separate statute existence registry (U.S.C./C.F.R. from OLRC/govinfo) is feasible and the architecture generalizes, but it's a new schema + source + different existence semantics (versioning/repeal), and statutes are less prone to the volume/page fabrication that plagues AI case cites — lower ROI than case coverage. Build on demand.
- [ ] **W6 — Registry handoff to courts.** Transfer registry admin to the actual clerk of court per registry. *Why:* the endgame legitimacy story — the court attests its own citations; the deny-by-default ownership model was built for exactly this. Cleanest at the appellate / state-supreme tier (one clerk per court).

*Considered & not pursued:* a Merkle-commitment model (anchor a corpus root on chain, serve lookups off-chain with proofs) is cheaper on-chain but reintroduces an off-chain data/proof authority, defeating the "the chain itself answers, replayable by anyone" trust property. Revisit only if on-chain storage cost ever dominates — at ~$55k for the full corpus, it does not.

---

## Known risks (tracked, not hidden)

- Parallel citations: one cluster can have up to three registry records (U.S. / S. Ct. / L. Ed.); receipts group results by cluster id.
- Citation-string collisions: two short orders can share a reporter first page; record metadata holds a case array when the census finds them.
- 5th/11th Circuit split: pre-October-1981 old-Fifth cases are binding ca11 precedent but live under court ca5 and are cited "(5th Cir.)"; during the pilot they are honestly NOT_COVERED (registries mirror court identity, not precedential reach). The demo uses post-1981 cites.
- Unpublished/WL-only ca11 cites map to NOT_COVERED with a named reason; the census measures the gap and the reconcile report publishes it.
- CourtListener citation-completeness gap (discovered 2026-06-16): CL holds Published opinion CLUSTERS with NO reporter citation attached, so our CL-keyed registry false-NOT_FOUNDs real cases. Measured ~4.1% of Published ca11 clusters (2,195) / ~0.0% SCOTUS. Most are recent decisions awaiting a West cite (no cite exists yet — not a real false-NOT_FOUND, since you can't cite a nonexistent cite) or genuinely uncited; the real class is older cases whose West cite EXISTS but CL lacks it (e.g. Muransky 979 F.3d 917). Test-pilot handling: targeted backfill (scripts/backfill_supplemental.py, DECISIONS 2026-06-16). Mainnet: Phase 7 task 7.1. We never invent cites — a cite goes on chain only from an authoritative source.
- PDF extraction recall is the demo-day risk for arbitrary real briefs: two-column layouts, footnotes, scans. Mitigations: RECAP fixtures from Phase 1, measured recall per release, UNPARSEABLE as honest output, born-digital demo fixture.
- Archive-state dependency for pinned-block re-verification: RESOLVED, 0.7 (h) confirmed full archive state on the default public RPC; the rebuild fallback stays documented against future pruning-policy changes.
- Attribution: Free Law Project requests attribution for CourtListener data; it lives in README, registry metadata, and the demo. Never copy FLP site prose (CC BY-ND) into project docs.
- FULL-SCOPE state-coverage completeness (Phase 7.1): CAP/CL coverage is strong through ~2018 but recent + neutral state cites vary by state, so the false-NOT_FOUND gap is wider and uneven across states — measure + PUBLISH a per-court coverage % before claiming a state. Never invent a cite.
- Normalizer trust surface at state scale (Phase 7.7): ~50 states' official reporters + 7 regional families + neutral-cite formats mean far more places a normalization bug becomes a wrong NOT_FOUND (invariant 5: the normalizer is the trust boundary). The exhaustive golden suite is the gate, proven on the CA/NY/TX/FL/IL pilot before scaling.
- Append-only has no withdrawal path: a cite that DISAPPEARS or is reassigned (depublication, a vacated reporter cite) can't be retired today — rare federally (West doesn't recycle cites), real at state scale. Mechanism is wishlist W1/W3 (mark Invalid, keep history).

## Mainnet cutover (post-pilot, human-gated; not session work)

Preconditions per task 6.4. Then: create registries on mainnet 1611 from a hardened script outside Claude Code; bulk load by tranche (Phase 7 ladder: federal appellate → federal complete → state-normalizer pilot → all states); run reconcile until the diff is zero or documented after each tranche; wire the daily update cron across all loaded courts; publish registry IDs, the citation spec, and the receipt schema; add monitoring for load failures and registry staleness. Acceptance: a third party, given only the explorer and the published spec, can independently confirm registry coverage and verify a receipt.
