> **SUPERSEDED (2026-06-10).** This is the original draft plan, preserved verbatim for history.
> It contains stale chain constants (testnet 58887 is retired; the live testnet is 787111, and the
> mainnet EVM explorer is evm.explorer.nvnmchain.io) and it pre-dates the precompile facts adopted
> from the NVNM_MCP_Server project. The live plan is ../../IMPLEMENTATION_PLAN.md; the corrections
> are logged in ../../DECISIONS.md.

# NVNM Cite: Build Plan

Citation existence verification and filing receipts on NVNM Chain, built with Claude Code.

**What this is.** A per-jurisdiction registry of canonical case citations stored in plaintext on NVNM Chain, plus a verifier that extracts citations from a brief, checks them against the registries, and anchors a verification receipt at filing time. The receipt binds a document hash to a plaintext citation list, the registry state consulted (block height), the per-citation results, and the verifying agent's KYA identity.

**What this is not.** It never asserts that a case supports a proposition. It never asserts good-law status. It proves the check happened, against what, and by whom. Provenance, not truth.

---

## Invariants (encode these in CLAUDE.md, never let a session violate them)

1. Citations are stored and checked in plaintext. Citation identifiers are never hashed. The only hash in the system is the SHA-256 of the checked document inside a receipt.
2. Existence-only verification. No holdings, no propositions, no good-law flags. If citator data ever enters, it enters as a named citator's attested claim, never as an NVNM assertion.
3. Anchoring is explicit and happens at filing. Drafting-time checks run locally and leave no chain trace by default. The strategy-leak rationale is documented, not just implemented.
4. Architecture must allow third parties to own registries. Inveniam populates registries for the pilot but the write-permission model cannot assume Inveniam is the only attestor.
5. The normalizer is part of the trust boundary. Its spec is open and every receipt records the normalizer version used.
6. The product name is NVNM Chain. Never "Inveniam Chain."

---

## Chain constants

| Item | Value |
|---|---|
| Mainnet chain ID | 1611 |
| Mainnet RPC | https://evm.nvnmchain.io |
| Explorer | https://explorer.nvnmchain.io |
| Testnet chain ID | 58887 (fill in testnet RPC) |
| Anchor precompile | 0x0000000000000000000000000000000000000A00 |
| Selectors | addRecord 9b7b7869, addRegistry 318b38b1, records 02abafdf |
| Gas | mantraUSD, negligible per tx |
| Signer | evm_signer_v5.py (pure Python, EIP-155, RFC-6979). Reuse, parameterize chain_id. |

All development on testnet 58887. Mainnet keys never enter a Claude Code session.

---

## Data sources

- **CourtListener bulk data** (Free Law Project): full corpus of opinion clusters and citations as downloadable files. Primary load source. Public domain case data.
- **CourtListener REST API v4**, including the citation-lookup endpoint: rate-limited, use for spot checks and daily incremental updates, not bulk loads.
- **eyecite** (FLP Python library): citation extraction from text, including short-form resolution (id., supra back to the full cite). Build on it, do not reinvent.
- **reporters-db / courts-db** (FLP): canonical reporter abbreviations and variants, court identifiers. This is the backbone of the normalizer.
- **RECAP archive**: real filed briefs as PDF. Test corpus for extraction recall on messy real-world documents.

Pilot corpus: SCOTUS plus one federal circuit (pick the one matching your first design partner; 2d or 9th are good demo defaults). SCOTUS is tens of thousands of cases; a circuit adds a few hundred thousand. Federal reporters map cleanly to jurisdiction, which defers the regional-reporter ambiguity problem to V2.

---

## Architecture

```
nvnm-cite/
  CLAUDE.md                  # invariants, constants, conventions
  DECISIONS.md               # running log, one entry per settled decision
  docs/
    canonical-citation-spec.md   # the open spec; versioned
    receipt-schema.md
  src/nvnm_cite/
    chain/
      signer.py              # evm_signer_v5 port, chain_id param
      precompile.py          # addRegistry / addRecord / records wrappers
      indexer.py             # event/calldata sync to local SQLite
    normalizer/
      canonical.py           # eyecite + reporters-db -> canonical form
      jurisdiction.py        # citation -> registry id
    loader/
      courtlistener.py       # bulk file + API clients
      bulk_load.py           # idempotent, checkpointed writer
      reconcile.py           # diff chain registry vs CourtListener
      update.py              # daily incremental append
    verifier/
      extract.py             # PDF/DOCX/txt -> text -> citations
      check.py               # citation set -> per-cite status
    receipts/
      schema.py              # versioned receipt object, canonical JSON
      anchor.py              # filing-time addRecord
      verify.py              # tx hash + file -> recompute and confirm
    cli.py                   # nvnm-cite load | check | anchor | verify | reconcile | stats
  mcp_server/                # check_citations, anchor_receipt, verify_receipt, registry_stats
  tests/
    golden/                  # citation fixtures, real RECAP briefs
```

**Registry naming.** One registry per court: `us-scotus`, `us-ca1` through `us-ca11`, `us-cadc`, `us-cafc`. Receipts go to a single `receipts-v1` registry; the verifying agent is identified by its signing key and KYA reference in the payload.

**Record content per case.** Compact JSON in plaintext: canonical citation, case name, decision year, CourtListener cluster ID as the provenance pointer back to the source corpus.

**Lookup architecture.** Two candidate designs; Phase 0 decides which is primary:

- **A. Direct keyed read.** If the precompile supports reading a record by key, derive the key deterministically as keccak256(registry_id, canonical_citation). Existence check is one eth_call. Fully trustless lookup.
- **B. Local index with chain verification.** Sync all records from chain (events or calldata via RPC log scan or Blockscout API) into SQLite. Lookups hit the index; the chain remains the source of truth and anyone can rebuild the index independently, which preserves the public-auditability claim.

Build B regardless: the reconcile tool needs it, and it is the fallback if A is not supported. If A works, use it for the receipt-time check so the receipt can claim a direct chain read.

**Receipt schema (v1).**

```json
{
  "schema": "nvnm-cite-receipt/v1",
  "chain_id": 1611,
  "document_sha256": "...",
  "checked_at_block": 123456,
  "normalizer_version": "1.0.0",
  "registries": [{"id": "us-scotus", "head_block": 123450}],
  "results": [
    {"as_written": "Roe v. Wade, 410 U.S. 113 (1973)",
     "canonical": "410 U.S. 113",
     "registry": "us-scotus",
     "status": "VERIFIED"}
  ],
  "agent": {"kya_id": "...", "address": "0x..."},
  "timestamp": "2026-06-09T12:00:00Z"
}
```

Status values: VERIFIED, NOT_FOUND, AMBIGUOUS_JURISDICTION, UNPARSEABLE. Canonical serialization is sorted-keys, no whitespace. If addRecord takes only bytes32, the full JSON rides in calldata and the bytes32 is its keccak; calldata is permanent and explorer-visible, so the plaintext requirement is still met.

---

## Claude Code setup

One-time, before Phase 0:

1. `git init`, Python 3.11+, uv for env management. `.gitignore` includes `.env`, `*.key`, `*.sqlite` on day one.
2. `.env` holds `NVNM_TESTNET_RPC`, `NVNM_TESTNET_KEY` (throwaway funded testnet key), `COURTLISTENER_TOKEN`. Claude Code reads config names from CLAUDE.md, never the values from chat.
3. Write CLAUDE.md before the first session (template below). Run `/init` afterward if you want Claude Code to extend it with discovered conventions.
4. Drop `evm_signer_v5.py` into the repo root so Phase 0 can port it.
5. Session discipline: one phase per session, one branch per phase. Open every session with "Read CLAUDE.md and DECISIONS.md, then plan before coding." Use plan mode for Phase 0 and any session touching chain-write code. End every session by having Claude Code append settled choices to DECISIONS.md.
6. Tests run with pytest. Tell Claude Code to write the test before the implementation for anything in `normalizer/` and `receipts/`.
7. Optional: a pre-commit hook that runs the golden normalizer tests, so no session can quietly regress canonicalization. Claude Code hooks docs: https://docs.claude.com/en/docs/claude-code/overview

**CLAUDE.md template:**

```markdown
# nvnm-cite

Citation existence verification + filing receipts on NVNM Chain.

## Invariants (never violate)
- Plaintext citations on chain. Never hash citation identifiers.
  Only the checked document is hashed (SHA-256), inside receipts.
- Existence-only. Never assert a case supports a proposition or is good law.
- Anchoring is explicit (--anchor) and intended for filing time.
  Local checks must leave no chain trace.
- Registry write model must support third-party attestors later.
- Normalizer version goes in every receipt.
- "NVNM Chain", never "Inveniam Chain".

## Chain
- Testnet: chain_id 58887, RPC $NVNM_TESTNET_RPC. ALL dev here.
- Mainnet: chain_id 1611, RPC https://evm.nvnmchain.io. NEVER write
  to mainnet from a session. Mainnet keys are not available to you.
- Precompile 0x0000000000000000000000000000000000000A00:
  addRecord 9b7b7869, addRegistry 318b38b1, records 02abafdf.
- Signer: src/nvnm_cite/chain/signer.py (ported evm_signer_v5).

## Conventions
- Python 3.11, uv, pytest. Type hints everywhere. No new deps without
  noting them in DECISIONS.md.
- Build on eyecite / reporters-db / courts-db. Do not write a citation
  parser from scratch.
- Golden tests in tests/golden are the contract for the normalizer.
  Run pytest after every change to normalizer/ or receipts/.
- Append settled decisions to DECISIONS.md before ending a session.
```

---

## Phases

### Phase 0: Precompile discovery and chain plumbing (1 session, plan mode)

The whole lookup architecture hangs on precompile semantics that the selectors alone do not reveal. This session answers four questions on testnet:

1. addRecord payload: bytes32 only, or arbitrary bytes? Determines whether case JSON lives in state or in calldata.
2. Record addressing: can `records` read by a caller-chosen key, or only by sequential index? Decides lookup design A vs B.
3. Registry permissions: after addRegistry, who can write? Owner-key-only matters for the third-party-attestor requirement.
4. Practical limits: max calldata per tx, sane tx throughput for bulk loading.

Tasks: port signer with chain_id parameter; build `precompile.py` wrappers; round-trip on testnet (create registry, add record, read it back, confirm on explorer); write findings to DECISIONS.md.

Session prompt:

```
Read CLAUDE.md. We are in discovery. Port evm_signer_v5.py to
src/nvnm_cite/chain/signer.py with chain_id as a parameter (testnet
58887). Build precompile.py with addRegistry/addRecord/records
wrappers. Then empirically determine on testnet: payload type limits
for addRecord, whether records supports keyed reads, and the registry
write-permission model. Round-trip a test registry and record, verify
on the explorer, and write everything you learn to DECISIONS.md.
Plan first; show me the plan before writing code.
```

Acceptance: a record written on testnet, read back two ways (RPC and explorer), and a DECISIONS.md entry settling design A or B.

### Phase 1: Normalizer and jurisdiction mapper (1-2 sessions)

The canonicalization layer, built on eyecite and reporters-db. Deliverables:

- `docs/canonical-citation-spec.md`: the open spec. Canonical form is the reporters-db canonical reporter key with normalized volume and page, e.g. `410 U.S. 113`. Spec is versioned; version constant exported from the package.
- `canonical.py`: text in, list of (as_written, canonical, metadata) out. Short forms resolved to their antecedent full cites via eyecite resolution.
- `jurisdiction.py`: canonical citation plus extracted court metadata in, registry ID out. U.S./S. Ct./L. Ed. map to us-scotus. F.2d/F.3d/F.4th require the court parenthetical that eyecite captures; if absent or unparseable, return AMBIGUOUS_JURISDICTION rather than guessing.
- Golden suite first: 200+ fixtures covering parallel citations, reporter variants, short forms, mangled line breaks, and a handful of full RECAP briefs as integration fixtures.

Acceptance: golden suite green; spec doc reviewed by you; normalizer version stamping wired.

### Phase 2: Registry loader and reconciliation (1-2 sessions)

- `courtlistener.py`: bulk file parser plus API client for incremental updates.
- `bulk_load.py`: idempotent, checkpointed writer. Deterministic per-case identity (registry, canonical citation) so re-runs never double-write. Nonce manager, batching, resume from checkpoint after any failure.
- `reconcile.py`: diff a chain registry against the CourtListener corpus, output a coverage report. This is a first-class command, not a test utility. It is the public-auditability story made executable, and it is a demo artifact.
- `update.py`: daily incremental append for newly published opinions, designed to run on cron.

Run the full SCOTUS load on testnet. Measure tx throughput and extrapolate mainnet load time. At even a modest sustained rate the SCOTUS corpus loads in hours, not days.

Acceptance: SCOTUS registry on testnet, reconcile diff explained to zero or to documented known gaps, throughput numbers in DECISIONS.md.

### Phase 3: Verifier and receipts (1-2 sessions)

- `extract.py`: PDF (pdfplumber), DOCX (python-docx), plain text. Text cleanup pass before eyecite, because line-break-mangled citations in real PDFs are the main recall killer. Test against RECAP fixtures.
- `check.py`: extract, normalize, map, look up. Per-cite status from the four-value enum. Local-only by default.
- `schema.py` / `anchor.py`: receipt object, canonical serialization, anchor to `receipts-v1` only when `--anchor` is passed. Agent signs with its KYA-registered key.
- `verify.py`: given a receipt tx hash and the original file, recompute the document hash, re-run the check pinned to the receipt's recorded block height, and report match or mismatch. This is the artifact a court or insurer actually consumes.
- `cli.py` tying it together: `nvnm-cite check brief.pdf`, `nvnm-cite anchor brief.pdf`, `nvnm-cite verify <txhash> brief.pdf`.

Acceptance: end-to-end on testnet against a real RECAP brief, plus the demo brief below.

### Phase 4: MCP server and the demo (1 session)

- MCP server exposing `check_citations`, `anchor_receipt`, `verify_receipt`, `registry_stats`. Stand it up locally first; fold into the mcp.nvnmchain.io surface once stable. This is what makes the verifier callable by any agent, which is the KYA story.
- Demo script, scripted end to end: a short brief containing real SCOTUS citations plus the fabricated "Varghese v. China Southern Airlines, 925 F.3d 1339 (11th Cir. 2019)" from Mata v. Avianca. Run check: real cites VERIFIED, Varghese NOT_FOUND. Anchor the receipt. Open the explorer to the receipt tx. Run verify against the file. Total runtime under two minutes.

That demo is the BD asset. It recreates the exact incident every legal buyer already knows, and it ends on a chain explorer page instead of a slide.

### Phase 5: Mainnet cutover and hardening (after pilot validation)

Human-only steps first: key ceremony for the registry write key and the receipts agent key; decide the open-source posture for the normalizer (the DGML pattern fits: open spec, Apache 2.0 reference implementation with CLA, proprietary layers closed).

Then: create registries on mainnet 1611 from a hardened script outside Claude Code; bulk load SCOTUS plus the pilot circuit; run reconcile until the diff is zero or documented; wire the daily update cron; publish registry IDs, the citation spec, and the receipt schema; add monitoring on load failures and registry staleness.

Acceptance: a third party, given only the explorer and the published spec, can independently confirm registry coverage and verify a receipt.

---

## Open questions, tracked honestly

1. **Precompile semantics** (payload type, keyed reads, write permissions). Phase 0 resolves; everything downstream is parameterized on the answer.
2. **Regional reporters.** P.3d, N.E.3d, So. 3d span multiple states. V1 scope of federal courts dodges this; the V2 design needs court-metadata-driven resolution and a multi-registry check fallback. Do not let a session quietly "solve" this with guessing.
3. **CourtListener completeness** for the chosen circuit. The reconcile tool quantifies it; whatever the gap is, it is a published number, not a hidden one.
4. **Extraction recall on real PDFs.** Measured against RECAP fixtures, reported per release. An UNPARSEABLE status is honest output, not a failure to hide.
5. **Attestor model.** Pilot is Inveniam-operated. The permission design from Phase 0 has to leave the door open for Free Law Project, reporters of decisions, or courts to own registries. That is the operator-versus-witness line, and it is a roadmap commitment, not a V1 blocker.

## Effort

Roughly 8 to 12 Claude Code sessions. Testnet demo-ready in one to two weeks of part-time sessions; mainnet pilot the following week, gated on the key ceremony and the open-source decision.
