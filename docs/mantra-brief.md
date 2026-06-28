# NVNM Cite — Briefing for MANTRA

**To:** MANTRA (NVNM Chain infrastructure team)
**From:** Albert Berdellans, Inveniam
**Date:** 2026-06-27 · for review ahead of Monday's meeting
**Re:** Building the **full** US case-citation reference network on NVNM Chain mainnet — the scale, how we keep it cheap and fast, and two precompile features we'd like you to build

> Every number tagged *measured* comes from the completed NVNM **testnet** pilot
> or from our census tool over CourtListener bulk data (no chain writes). Sources
> in the appendix. The only open variable on cost is the wmmUSD/USD peg, which is
> yours to confirm.

---

## 1. What NVNM Cite is

AI-drafted legal briefs now routinely cite **cases that do not exist**. The
canonical incident — *Mata v. Avianca*, where a lawyer was sanctioned for a
ChatGPT-fabricated citation ("Varghese v. China Southern, 925 F.3d 1339") — is
exactly what this service catches: that fake citation returns **NOT_FOUND**
against our on-chain registry in seconds. We proved it end-to-end on testnet.

NVNM Cite is two things on top of NVNM Chain:

1. **Per-court registries of real US case citations**, stored *in plaintext* on
   chain (the citation string `410 U.S. 113` is the record key — never hashed).
   A verifier extracts citations from a brief and checks each one live against
   the chain.
2. **Filing receipts.** At filing time we anchor a tamper-evident receipt that
   binds a document's SHA-256 to the chain state consulted, by which wallet, at
   which block — minimal and **non-enumerating** (it never publishes the brief's
   authorities, only the hash, provenance, and a status tally).

**What it deliberately is NOT:** it never claims a case is good law or supports a
proposition. It proves *existence in a named authoritative source* — provenance,
not truth. **Why NVNM Chain:** non-repudiation — anyone skeptical replays the
exact `records()` read against any node and gets the same answer. Plaintext-on-
chain, the keyed existence read, deny-by-default registry ownership, and an
event-free precompile (privacy by design) are the properties we lean on.

### Status today (testnet, measured)
- From-scratch, golden-tested signer (keccak / RLP / secp256k1 / EIP-155); the
  chain layer has **zero non-stdlib dependencies**.
- **260,763 citations live** across `us-scotus` and `us-ca11`, **reconciled
  clean** (independent chain re-read: 0 missing / 0 extra / 0 drift).
- Receipts round-trip live; a one-byte tamper correctly breaks verification.
- 488 tests green; CLI + web app + query telemetry complete.

---

## 2. The mainnet plan — full US case-law scope

We run the **same** pipeline proven on testnet against mainnet (chain **1611**),
in tranches, human-gated. The target is now the **full US case-law citation
graph** — all federal courts (incl. ~94 districts) **and all state courts** — not
just the federal-appellate backbone. Two reasons: an uncovered court turns a
fabricated cite into NOT_COVERED (indistinguishable from real-but-uncovered, so a
narrow scope lets fabrications hide), and **~90% of US litigation is in state
courts**.

**Measured scale** (CourtListener bulk snapshot 2026-03-31; distinct citations
under real reporters, excluding WL/LEXIS/specialty vendor cites):

| Scope | Citation records | Share |
|---|---:|---:|
| All federal (appellate + districts + bankruptcy + specialized) | ~1,469,892 | 12% |
| All state | ~10,442,192 | **88%** |
| **FULL US case law (~7,837,721 cases)** | **~11,912,016** | 100% |

**Tranche ladder** (load order; each gated on a published per-court completeness bar):
1. **Federal appellate backbone** (SCOTUS + 13 circuits) — **924,421 records**, proven on testnet.
2. **Federal complete** (+ districts, bankruptcy, specialized) — same reporters.
3. **State-normalizer pilot** — 3–5 high-volume states (CA, NY, TX, FL, IL).
4. **All remaining states.**

The genuinely new engineering on our side is a normalizer rebuild for state
reporters (regional + official + neutral citations); the chain side is unchanged
except for the two features in §4, which are *wishlist, not blockers*.

**Mainnet preconditions (all human-gated, none from a dev session):** key
ceremony (mainnet keys generated/held outside any session; testnet keys never
touch mainnet); reconcile-to-zero after each tranche; publish registry IDs + the
open spec + the receipt schema; confirm the wmmUSD peg.

We have already confirmed, **read-only against live mainnet** (chain 1611, no
key, no write), that the anchoring precompile is the **same deployed binary** as
testnet: identical gas estimate to the unit (`addRegistry` = 83,541 gas) and
identical 45 gwei gas price. The cost/behavior model carries over confirmed.

---

## 3. Doing it cheaply and quickly

### 3a. Gas — trivial even at full scope

Per record: **~96k gas ≈ $0.0046** at 45 gwei and a ~$1 peg — *measured*, with
`eth_estimateGas` exact to the unit. Registry creation is ~80k gas (~$0.004) per
court and rounds to zero.

| Scope | Records | Gas cost | Basis |
|---|---:|---:|---|
| Pilot (done, testnet) | 260,763 | **$1,201** | measured (actual spend) |
| Tranche 1: federal appellate backbone | 924,421 | ~$4,252 | measured census |
| All federal | ~1,469,892 | ~$6,800 | measured |
| All state | ~10,442,192 | ~$48,000 | measured |
| **FULL US case law** | **~11,912,016** | **~$54,800** | measured |

**The entire US case-law corpus anchors for ~$55,000 in gas**, because the unit
cost is half a cent. Our load levers are already implemented and measured:
right-sized gas limit from the measured curve (no per-record `estimateGas`),
minimal sorted-key JSON metadata, one record per distinct citation (corpus-side
dedup), and a checkpoint DB as the only idempotency guard (no per-record
existence pre-reads).

### 3b. Speed — "2 tx/s" is **not** a chain limit

We initially measured a ~1.1 tx/s single-sender plateau and assumed it was chain
policy. **It was our client's per-tx overhead** (per-record `estimateGas` +
per-tx receipt polling over un-pooled HTTP). After taking the gas limit from the
measured curve and confirming by account-nonce advance with sampled receipts, a
**single key sustained ~2.1 tx/s**, and the chain absorbed ≥2.2 from one sender
without pushback. The whole pilot ran **submission-bound, never chain-bound**.

The one hard constraint we design around: **nonce-gapped submission is rejected
outright**, so each key submits strictly serially in nonce order — which is why
we parallelize across *keys* rather than firing gapped nonces from one key.

### 3c. Transaction & wall-clock estimates

One `addRecord` per distinct citation, plus one registry-creation tx per court.
Full scope ≈ **~11.9M record txs + ~500 registry txs.**

**Wall-clock** at the measured ~2.1 tx/s/key:

| Keys | Tranche 1 (924k) | Full scope (~11.9M) |
|---:|---:|---:|
| 1 | ~5.1 days | ~65 days |
| 10 | ~12 hours | ~6.6 days |
| 15 | ~8 hours | ~4.4 days |

Full scope is the case that genuinely *needs* a parallel key fleet — and would
most benefit from a native batch write (§4). Note: **receipt** registries are
one-per-(firm, case), created and owned by the *filing parties'* wallets — not
us — so they are outside our build cost and key custody.

---

## 4. Two precompile features we'd like MANTRA to build

Neither blocks mainnet-v1 (the existence registries ship on the precompile as-is).
Both extend NVNM Chain's value well beyond NVNM Cite.

### 4a. `updateRecordStatus` + a supersession pointer (the priority ask)

**The need.** Legal authorities evolve — a case can be corrected, overruled,
vacated, or (in some states) depublished. More broadly, this is the generic
**version-control / revocation primitive**: "this record is no longer the current
one — see *this* instead," without ever deleting or mutating the original. It's
directly useful for **document/file hashes** (v1 → superseded-by v2), **credential
revocation**, and **regulated recordkeeping** (amend, don't delete; keep the
trail) — i.e. across NVNM Chain use cases, not just ours.

**You're ~90% there already.** The record tuple **already carries** `status`,
`recordId`, `index`, and `isLatest`, and `records()` **already returns** `status`.
The chain spec even defined `updateRecordStatus` — it's just **missing from the
deployed binary**. We'd be asking you to finish a feature you designed, plus add
one field.

**Proposed shape:**
```
updateRecordStatus(registry, recordId (or checksum), newStatus, supersededBy, reason)
```
- `newStatus`: extend the existing enum — `Active → Superseded | Revoked | Invalid`.
- `supersededBy`: a pointer to the replacing **record** (by `recordId`, or
  `registry`+`checksum` if cross-registry is allowed).
- `reason`: a short note.
- **Authorization:** registry admin/editor only (your existing `grantRole` model).
- **Append-only:** bumps `index` / moves `isLatest`, preserving prior versions and
  their block height — so "status as of block N" stays reconstructable by archive
  read. `records()` returns the status + pointer in the same keyed read our
  verifier already does.

**The hard invariant (our one firm requirement):** the function must **only ever
write `status` / `supersededBy` / `reason`, never `checksum` / `uri` / `metadata`.**
The original record content stays frozen; the original transaction payload is of
course immutable by the chain regardless. Net: even the registry admin can only
*annotate*, never rewrite — a property a database can't offer.

**Design questions for you:** status-enum values + reversibility; pointer scope
(record-only vs cross-registry); a status-change **event** (helps indexers, but
conflicts with the current no-events privacy stance — your call); reason format;
gas. We're happy to co-author the one-page spec.

### 4b. Native batch write — `addRecords` (efficiency, lower priority)

At ~11.9M records the load is submission-bound. A method that writes **N records
per tx** would amortize the ~21k intrinsic gas per tx (~22%, ~$12k across full
scope) and collapse millions of txs into far fewer. It would **not** change our
data model — each citation is still its own keyed record (the keyed `records()`
read depends on that). Strictly an efficiency win; parallel keys already get us
to ~1 week without it, so treat this as nice-to-have.

---

## 5. Questions for MANTRA on Monday

1. **Is the throughput limit per-sender or global?** This determines whether
   parallel keys give linear speedup — the difference between full scope taking
   ~4 days or ~65. The pilot never needed to find out (one key sufficed).
2. **Confirm the wmmUSD/USD peg** (we've assumed $1). The only number in this
   brief we can't read from the chain; cost scales linearly with it.
3. **Sender/mempool policy for a sustained multi-day, multi-key load** — any rate
   caps, per-account limits, or preferred submission window so a days-long write
   campaign across a key fleet doesn't trip protection mechanisms.

---

## 6. The one honest risk to name

**Source-data completeness**, and it grows at state scale. CourtListener holds
some real, published opinions with **no reporter cite attached** — ~4.1% of
published 11th-Circuit clusters, ~0.0% of SCOTUS (*measured*); state and older
coverage is more uneven (the Caselaw Access Project is strong through ~2018, but
recent and neutral state cites vary by state). A keyed registry would
false-`NOT_FOUND` those real cases. We **never invent cites**; we backfill only
from authoritative sources and **publish a per-court completeness bar** rather
than claim blanket coverage. This is a data-curation problem on our side, not a
chain problem, and it doesn't affect the cost or throughput numbers above.

---

## Appendix — where the numbers come from

All figures reproducible from the project repository.

| Figure | Source |
|---|---|
| Per-record ~96k gas; $0.0046/record; 45 gwei | `DECISIONS.md` — 2026-06-10 gas entry; 2026-06-13 cost extrapolation |
| Single-key ~2.1 tx/s; "1.1 tx/s" was client overhead | `DECISIONS.md` — 2026-06-11 load entries |
| Parallel-key (`grantRole`) writes validated; nonce-gap rejected | `DECISIONS.md` — Phase 0 experiments (d), (e) |
| Pilot spend $1,201 for 260,763 records, reconcile clean | `DECISIONS.md` — 2026-06-11 "Tranche-1 load COMPLETE" |
| Mainnet precompile = same binary (83,541 gas, 45 gwei), read-only probe | `docs/proposal-mainnet.md` Appendix A; live probe of chain 1611, 2026-06-24 |
| Tranche-1 census: 14 courts, 924,421 records | census over `data/corpus_fed_appellate.sqlite`; `docs/proposal-mainnet.md` Appendix B |
| **Full-scope: ~7.84M cases / ~11.9M records; federal 1.47M / state 10.44M** | census over CourtListener citations bulk (2026-03-31), bucketed by reporter type; `IMPLEMENTATION_PLAN.md` Phase 7 |
| Record tuple has `status`/`recordId`/`index`/`isLatest`; `records()` returns `status`; `updateRecordStatus` spec'd but unshipped | vendored ABI `src/nvnm_cite/chain/anchoring.json`; `CLAUDE.md` chain constants |
| Field caps (checksum 64 B, uri/metadata 2048 B); metadata gas ~76 B + ~77k | `DECISIONS.md` — Phase 0 experiment (b) |
| Source-completeness gap (~4.1% ca11) | `IMPLEMENTATION_PLAN.md` known risks; Phase 7.1 |

*Case data: [CourtListener](https://www.courtlistener.com) / [Free Law Project](https://free.law). Citation parsing builds on FLP's eyecite, reporters-db, courts-db.*
