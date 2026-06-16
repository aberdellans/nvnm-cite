# nvnm-cite Implementation Plan

## Status
- Current phase: Phase 4 COMPLETE incl. Phase 4.5 web app (tasks 4.5a–4.5e done). The webapp receipt flow is rewired to the LOCKED receipt v1: per-firm-per-case registries (`<firm>--<case>`), non-enumerating ~526 B receipts, no kya_id, Verify takes (registry + browser-hashed file), opt-in by-citation telemetry + its disclosure copy, StatusService fast-fail (short-timeout probe). The webapp now MIRRORS the CLI — `ReceiptService.prepare` delegates to `receipts/anchor.py::prepare_anchor` (re-uploads the file, re-checks pinned to a block), so the webapp receipt is byte-identical to `nvnm-cite anchor`. Verified LIVE end to end in the browser (all 5 tabs, zero console errors) against testnet; one latent JS bug (banner `.rb-sub` null on the found/revert paths) found + fixed. 488 tests green. This session closes Phase 4.5 → tag phase-4-done.
- Last completed: Phase 4.5 web app — `webapp/{service,server,__main__}.py` + `static/{index.html,app.js,app.css}` rewired to locked v1; `tests/test_webapp.py` rewritten to the v1 shape (+ status fast-fail / telemetry-on tests). NO transactions sent this session (read-only verification; the demo receipt already existed from the Phase 4 session). Anchoring (writes) stays gated behind the wallet + an explicit in-chat OK.
- Next up: Phase 5 (MCP server) — FastMCP stdio, 5 tools (check_citations / anchor_receipt[confirm] / verify_receipt / registry_stats / coverage), Claude Desktop smoke-test against testnet. Then P6 (demo). Tranche 2 stays gated by choice.

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
  - [x] (f) updateRecordStatus present? eth_call its selector; "unknown method" means still missing (it was absent from the deployed testnet binary as of May 2026). Sets the correction policy: supersede with a new version or write a tombstone record, contingent on (a).
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

**Goal:** The existing web demo (`src/nvnm_cite/webapp/`, already on main: commits 2200e32, 41e00c3) becomes the primary product surface — adopting item 0, the minimal receipt, and the per-firm-per-case registry model — honest and usable when hosted (not just on localhost). This phase MERGES the parallel frontend workstream into the plan; the architecture decisions are DECISIONS 2026-06-13 and the prepared copy is docs/webapp-revision-notes.md.

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

## Phase 7: Mainnet production plan (placeholder — author at end of project)

**Goal:** A written, human-gated PLAN (a document, not code) for running NVNM Cite "for real" on mainnet 1611 — not a test pilot nobody relies on, but a production service whose NOT_FOUND a lawyer can trust. It folds in the Mainnet cutover preconditions (task 6.4) and the lessons the testnet pilot surfaced.

**Depends on:** the whole pilot (Phases 0–6) as the evidence base.

**Tasks (placeholder — flesh out before writing):**
- [ ] 7.1 Data-coverage completeness — THE load-bearing trust issue. The testnet pilot proved CourtListener holds real, Published opinions with NO reporter citation attached: e.g. *Muransky v. Godiva Chocolatier, Inc.*, 979 F.3d 917 (11th Cir. 2020) (en banc) — the opinion cluster is present (4801215) but the cite is absent from CL's bulk AND live data (citation-lookup → 404). Measured ~4.1% of Published ca11 clusters (2,195) and ~0.0% of SCOTUS lack any reporter cite. A keyed-by-citation registry FALSE-NOT_FOUNDs these real cases. The mainnet plan must decide how to close or bound this (a second/supplemental citation source, a cluster-name fallback signal, vetted backfill, scoped guarantees) while keeping provenance honest ("existence in a NAMED source"). For the test pilot this is handled by direct backfill (see DECISIONS 2026-06-16); mainnet needs a principled answer.
- [ ] 7.2 NOT_FOUND semantics for production: distinguish "fabricated" from "real but uncovered / missing-from-source"; a status model + copy that never nudges a lawyer to delete a real citation.
- [ ] 7.3 Key ceremony + ownership (per 6.4): registry write key + receipts agent key generated and held OUTSIDE Claude Code sessions; mainnet is never written from a session.
- [ ] 7.4 Coverage scope + SLA: which courts, what completeness bar (measured + published), refresh/update cadence, staleness monitoring.
- [ ] 7.5 Open-source + publication posture: normalizer spec + reference-implementation licensing; registry IDs / spec / schema publication.
- [ ] 7.6 Cost + load plan: extrapolated from measured testnet gas/throughput (task 2.6); budget sign-off.

**Exit criteria:** a reviewed mainnet-plan document exists; every item has a decision or an explicit "deferred, with reason"; no mainnet write happens before it is signed off.

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

## Mainnet cutover (post-pilot, human-gated; not session work)

Preconditions per task 6.4. Then: create registries on mainnet 1611 from a hardened script outside Claude Code; bulk load tranche 1; run reconcile until the diff is zero or documented; wire the daily update cron; publish registry IDs, the citation spec, and the receipt schema; add monitoring for load failures and registry staleness. Acceptance: a third party, given only the explorer and the published spec, can independently confirm registry coverage and verify a receipt.
