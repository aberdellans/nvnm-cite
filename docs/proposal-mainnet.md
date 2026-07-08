# Proposal: Take NVNM Cite from Proven Pilot to Production — Full US Case-Law Scope

**To:** CEO, CTO, CFO
**From:** Albert Berdellans
**Date:** 2026-06-27 (rev. 2 — re-scoped from federal-appellate to full US case law)
**Re:** Funding, staffing, and time to anchor the full US case-citation graph on NVNM Chain mainnet

> **Status of numbers:** every figure tagged *measured* is an actual result from
> the completed testnet pilot or from our census tool over CourtListener bulk
> data (no chain writes); sources in Appendix A. The full-scope record count is
> now *measured*, not estimated. Gas price and per-record gas are *confirmed live
> on mainnet*. The only cost input we cannot read from the chain is the
> wmmUSD/USD peg.

---

## The ask, in one box

| What | Amount | Notes |
|---|---|---|
| **Approve** | **Full US case-law scope** as the mainnet target | All federal (incl. ~94 districts, bankruptcy, specialized) + all state courts — the citation-verification layer for *all* US litigation |
| **Gas budget** (mainnet wmmUSD) | **$75,000** envelope, drawn down by tranche | Full scope is **~$54,800 measured**; buffer covers backfill, re-versions, a year of updates across all courts, and peg drift |
| **People** | **2–3 now → ~5 at peak**, over a **~6-month** program | Critical hire: the state-reporter normalizer engineer; tailed by backfill/QA |
| **My time** | Program lead, full allocation | I own delivery + the mainnet key ceremony |

**The economics are the headline:** anchoring **all ~7.84 million US cases** —
every federal and state court — costs **~$55,000 in gas, once.** The real
investment is a ~6-month engineering program dominated by the state-reporter
normalizer rebuild and source-data backfill — **not** chain fees.

**Spend is tranche-gated.** Phase A (fund now) proves the mainnet path on the
federal tranches and de-risks the normalizer on 3–5 high-volume states (~$10k of
the gas envelope, 2–3 people, ~3 months). Phase B (full state rollout, the ~$48k
state bulk) is a **go/no-go after Phase A.**

---

## 1. Why this matters (strategic)

AI-drafted legal briefs now routinely cite **cases that do not exist**. The
canonical example — *Mata v. Avianca* (a lawyer sanctioned for a
ChatGPT-fabricated citation, "Varghese v. China Southern, 925 F.3d 1339") — is
exactly the failure NVNM Cite catches: that fake citation returns **NOT_FOUND**
against our registry in seconds, proven end-to-end on testnet.

Two facts set the scope:

- **An uncovered court can't catch a fabrication.** A fake cite to a court we
  don't cover returns NOT_COVERED — indistinguishable from a real-but-uncovered
  cite. So **coverage breadth = how much fabrication we can actually catch.**
- **~90% of US litigation is in state courts.** A federal-only service serves
  appellate specialists; the full scope serves *all* US litigation. State case
  law is **~87% of the universe** (measured).

So the target is the **full US case-law citation graph** — the provenance layer
for every brief in any US court. It proves *existence in a named authoritative
source*; it never claims a case is good law or supports a proposition. That
restraint is what makes it institutionally adoptable, and the deny-by-default
registry model gives a credible path to handing each registry to the court that
owns it.

## 2. Why this is low-risk (built + measured)

This is **not** a research bet. The full pilot runs today on NVNM testnet:

- **From-scratch, golden-tested signer** (keccak / RLP / secp256k1 / EIP-155),
  zero non-stdlib dependencies in the chain layer.
- **260,763 citations loaded** across `us-scotus` and `us-ca11`, **reconciled
  clean** (independent chain re-read: 0 missing / 0 extra / 0 drift).
- **Receipts round-trip live**: a real *Mata v. Avianca* brief checked, anchored,
  verified; a one-byte tamper breaks verification.
- **488 tests green**; CLI + web app + query telemetry complete.

The remaining work is **operational scale-up plus one bounded engineering lift**
(the state-reporter normalizer), not invention.

## 3. What the people and time buy

The chain writes are cheap and fast (days, even at full scope — see §4/§5). The
program is the work *around* them:

- **State-reporter normalizer rebuild** — the one genuinely new engineering item
  and the critical path. Extends the open, versioned normalizer to ~50 states'
  official reporters, the 7 regional reporter families, neutral/public-domain
  citations, and parallel-cite resolution, with an **exhaustive golden suite**
  (the normalizer is our trust boundary — more reporters means more places a bug
  becomes a wrong NOT_FOUND). The critical hire.
- **Per-court corpus + census + reconcile** — existing tooling, ~500 courts,
  parallelizable per court.
- **Backfill curation** — the labor driver, larger at state scale: CourtListener's
  completeness gap is wider and uneven across states. We never invent cites; we
  backfill only from authoritative sources, and publish a per-court coverage %.
- **Parallel-key load operations** — already built and validated on testnet.

## 4. Cost model (measured)

Per-record gas is **~96k ≈ $0.0046** at 45 gwei and a ~$1 peg — *measured*, and
both drivers are **confirmed live on mainnet** (45 gwei; precompile gas estimate
identical to testnet to the unit).

| Scope | Records | Gas cost | Basis |
|---|---:|---:|---|
| Pilot (done, testnet) | 260,763 | **$1,201** | measured (actual spend) |
| Tranche 1: federal appellate backbone (14 courts) | 924,421 | $4,252 | measured census; method validated to the unit |
| All federal (+ ~94 districts, bankruptcy, specialized) | ~1,469,892 | ~$6,800 | measured |
| All state (~87% of the universe) | ~10,442,192 | ~$48,000 | measured |
| **FULL US case law (~7,837,721 cases)** | **~11,912,016** | **~$54,800** | **measured** |

The headline for the CFO: **the entire US case-law corpus anchors for ~$55,000
in gas**, because the unit cost is half a cent. The $75,000 envelope funds the
full scope with headroom; only ~$10k of it draws down before the Phase-A go/no-go.

*The one residual:* the dollar figures assume **wmmUSD ≈ $1**, which is not
readable from the chain — confirm internally before budget sign-off. Cost scales
linearly with the peg; the envelope absorbs reasonable drift.

## 5. Plan and timeline (tranche ladder, ~6 months)

Load order, each tranche gated on a **published per-court completeness bar**:

1. **Federal appellate backbone** (SCOTUS + 13 circuits) — proven on testnet; ship first.
2. **Federal complete** (+ districts, bankruptcy, specialized) — same federal reporters, no normalizer change.
3. **State-normalizer pilot** — 3–5 high-volume states (CA, NY, TX, FL, IL) — proves the regional/official/parallel/neutral citation machinery on real data before scaling.
4. **All remaining states**, in tranches.

**Phase A (fund now, ~3 months):** tranches 1–3 — federal complete + the 5-state
normalizer pilot. Proves the mainnet path end-to-end and de-risks the normalizer.
~$10k gas, 2–3 people.

**Phase B (gated, ~3 months):** tranche 4 — full state rollout. Scale to ~5
people; the ~$48k state gas. Begins only after Phase A's go/no-go.

Chain-write time is small throughout: full scope is ~65 days at one key but
**~1 week with ~10–15 parallel keys** (the checkpointed loader already supports
this). The calendar is the normalizer rebuild + backfill, not the chain.

## 6. Risks, honestly

| Risk | Mitigation |
|---|---|
| **Source-data completeness** — wider and uneven at state scale (CourtListener/CAP strong through ~2018; recent + neutral state cites vary) | Measure + **publish a per-court coverage %** before claiming a state; backfill only from authoritative sources; never invent a cite. The main labor driver. |
| **Normalizer trust surface** — ~50 states' reporters = more places a bug becomes a wrong NOT_FOUND | The exhaustive golden suite is the gate; proven on the 5-state pilot before scaling (the normalizer is the trust boundary, invariant 5). |
| **Mainnet cost differs from testnet** | Checked live, read-only: 45 gwei + precompile gas identical to the unit. Only the wmmUSD peg remains; cost scales linearly; the envelope buffers it. |
| **Mainnet key custody** | Keys generated and held **outside** any dev/AI session via a key ceremony — CTO sign-off before any mainnet write. |
| **PDF extraction recall on arbitrary briefs** | Measured per release; honest UNPARSEABLE output; affects the *verifier UX*, not registry correctness. |

## 7. What your approval unlocks

- **CEO:** the citation-verification layer for **all US litigation** (not just
  federal appellate) — a flagship real-world NVNM Chain use case with a credible
  path to court-clerk adoption.
- **CTO:** scale-up of an already-built, fully-tested system plus **one bounded
  engineering lift** (the state normalizer), tranche-gated, with explicit
  key-custody control.
- **CFO:** **~$55k in gas for the entire US case-law corpus** — a $75k envelope
  that draws down by tranche (only ~$10k before the Phase-A go/no-go). The real
  investment is a gated ~6-month program, not recurring spend.

**Success criteria:** the full US case-law corpus live on mainnet in tranches,
each reconciled clean with a published completeness bar; a third party can
independently verify any receipt from the chain and the public spec.

---

## Appendix A: where every number comes from

All figures are reproducible from the repository.

| Figure | Source |
|---|---|
| Per-record gas ~96k; $0.0046/record; 45 gwei | `DECISIONS.md` (2026-06-10 gas entry; 2026-06-13 cost extrapolation) |
| Mainnet gas price 45 gwei; precompile gas identical (83,541) | live read-only probe of `https://evm.nvnmchain.io` (chain 1611), 2026-06-24 — `eth_gasPrice` + `eth_estimateGas`, no key/no write. *Amended 2026-07-07: the 83,541 figure is payload-specific (locked creation strings ≈ 79.1k); the parity claim is what carries, re-confirmed within 30 gas on identical calldata (DECISIONS 2026-07-07)* |
| Pilot spend $1,201 for 260,763 records | `DECISIONS.md` (2026-06-13 "Tranche-1 load COMPLETE") |
| Throughput ~2.1 tx/s/key; ~1.5 days/tranche | `DECISIONS.md` (2026-06-11 load entries) |
| Parallel-key (grantRole) scaling validated | `DECISIONS.md` (experiment d) |
| Federal-appellate per-court counts (924,421) | census over `data/corpus_fed_appellate.sqlite` (Appendix B) |
| **Full-scope: ~7,837,721 cases / ~11,912,016 records; federal 1.47M / state 10.44M** | **census over CourtListener citations bulk (snapshot 2026-03-31), bucketed by reporter type; `IMPLEMENTATION_PLAN.md` Phase 7** |
| Production phasing; mainnet preconditions | `IMPLEMENTATION_PLAN.md` Phase 7; task 6.4 |
| Coverage-gap risk (~4.1% ca11) | `IMPLEMENTATION_PLAN.md` known risks; Phase 7.1 |

## Appendix B: measured per-court record counts (federal appellate backbone — tranche 1)

Census over `data/corpus_fed_appellate.sqlite`, snapshot 2026-03-31. "Records" =
distinct canonical citations under the federal reporter family, the exact
load-set rule used on chain. SCOTUS and 11th Cir. rows reproduce the locked
testnet load set to the unit, which validates the other twelve.

| Court | courts-db id | Clusters | Records (pilot scope) | Records (+ `F.` 1st series) |
|---|---|---:|---:|---:|
| Supreme Court | `scotus` | 499,471 | 218,775 | 218,775 |
| 1st Circuit | `ca1` | 41,659 | 25,217 | 26,590 |
| 2nd Circuit | `ca2` | 109,510 | 63,000 | 68,753 |
| 3rd Circuit | `ca3` | 95,137 | 47,664 | 50,176 |
| 4th Circuit | `ca4` | 172,866 | 67,142 | 69,157 |
| 5th Circuit | `ca5` | 197,642 | 96,116 | 99,183 |
| 6th Circuit | `ca6` | 99,773 | 49,807 | 52,971 |
| 7th Circuit | `ca7` | 85,722 | 49,020 | 51,426 |
| 8th Circuit | `ca8` | 99,079 | 54,440 | 59,667 |
| 9th Circuit | `ca9` | 210,798 | 121,244 | 124,731 |
| 10th Circuit | `ca10` | 67,414 | 43,097 | 43,097 |
| 11th Circuit | `ca11` | 90,459 | 41,988 | 41,988 |
| D.C. Circuit | `cadc` | 43,101 | 25,813 | 26,431 |
| Federal Circuit | `cafc` | 54,376 | 21,098 | 21,098 |
| **Total** | **14 courts** | **1,867,007** | **924,421** | **954,043** |

Full-scope per-state counts (for the CA/NY/TX/FL/IL pilot and beyond) are
produced the same way — a census run, no chain writes — when tranches 3–4 are
scoped.
