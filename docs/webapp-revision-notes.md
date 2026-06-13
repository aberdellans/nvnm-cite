# Webapp revision notes — handoff to the main project session

Prepared 2026-06-13 from Albert's review of the redesigned web demo
(`src/nvnm_cite/webapp/`). These are **answers + prepared revisions**, not
applied changes. Several items change product architecture and amend
documented invariants — they need to land in CLAUDE.md / IMPLEMENTATION_PLAN /
DECISIONS deliberately, not as silent edits.

Each item: **Question → Short answer → What the code actually does today →
Decision / prepared revision.** Draft UI copy is marked `DRAFT COPY` and is
content, not final wording.

> Reviewer's note on scope: items 0 and 1 are the architecturally load-bearing
> ones and they reframe each other. Items 2 and 3 (receipt contents, registry
> strategy) are entangled with the still-draft Phase 4 receipt schema. Items
> 4–6 are copy/UX and can proceed independently.

---

## 0. LEAD DECISION — citation lookups read the chain live, not a local copy

**This is the decision the other items flow from. It reverses CLAUDE.md
invariant 3 and must be recorded as such.**

**The principle:** if the website answers "is this citation real?" from a
copy we host, users are trusting *us*, not the chain — and "it's on NVNM
Chain" becomes decoration. The existence verdict must come from a **live
`records(registry, citation)` `eth_call`**, so the answer is the chain's
authoritative state, independently verifiable by anyone, and so third-party
registries (invariant 4) are reachable without us curating them. This makes
invariants 1 (plaintext on chain) and 4 (third-party registries) mean
something at read time.

**What the code does today:** `webapp/service.py::CheckService` resolves
citations through `webapp/localindex.py::LocalIndex`, which reads
`chain_index.sqlite` (a mirror of chain) or `corpus.sqlite` (the CourtListener
build artifact) — **server-side SQLite, no RPC**. That was a deliberate
choice (see invariant 3 below), but it makes our server the de-facto
authority for what counts as a real citation.

**Decision:**
- The drafting-time check resolves each citation via a **live keyed
  `records()` eth_call** against the **NVNM-operated RPC**. The local
  SQLite is **demoted** from "lookup authority" to, at most, an optional
  performance cache and the `rebuild-index` audit tool (anyone can rebuild
  the index from chain to check our work). It is no longer the source of
  truth for a check.
- The chain-read path **already exists**: `ReceiptService` /
  `ChainGateway.keyed_record` already does keyed `records()` reads and
  already treats the `"collections: not found"` keyed-miss as NOT_FOUND
  (`_is_keyed_miss`). So this is mostly *removing* the local-index lookup and
  *promoting* the existing chain-read path to be the check default — not new
  machinery.
- Practicality: a check is **N cheap read-only eth_calls** (N = distinct
  citations, tens not thousands; parallelizable; seconds). Verify the public
  RPC's read throughput / rate limits at product scale, but the per-call cost
  is trivial.

**The privacy consequence — RESOLVED, because we operate the RPC:**
- A keyed read puts the citation in the request (`records("us-scotus",
  "410 U.S. 113")`), so the RPC operator sees the citation set. Invariant 3
  existed to prevent that leak — but it assumed a **third-party** operator.
- **We operate the RPC.** `eth_call` reads are point-to-point to the node:
  never broadcast, never in the mempool, never in a block — **not publicly
  viewable** and leaving no on-chain trace. The citation set is visible only
  to us, the operator, which is the same party that already receives the
  document and runs the extraction. So reading the chain via our own RPC adds
  **no new exposure** beyond the in-memory check; it is privacy-equivalent.
- **The real, surviving win is not secrecy — it's non-repudiation:** with a
  local copy we could omit or fabricate a record undetectably; with the data
  on a public chain we *cannot lie about the answer*, because any skeptic can
  replay the exact `records()` call against an independent node and catch a
  discrepancy. Keep that property real and visible: preserve the
  "replay this query against any node" affordance (the Verify tab already
  does this — extend it to the Check flow), and let advanced users point at a
  different RPC. The honest claim is **"we can't lie about what the chain
  says,"** not "we can't see what you check."
- Optional policy knob: if we want to minimize even our own visibility into
  pre-filing citations, configure the RPC not to log call bodies (or scrub
  them). A policy choice, not architecture.

**Amends:** CLAUDE.md **invariant 3** and Phase 3 **task 3.2** (which
currently specify "drafting-time checks run against the local index only …
leave no chain trace"). New rule to record:

> Drafting checks read the chain live via the NVNM-operated RPC. `eth_call`
> reads are non-public (point-to-point, no mempool, no on-chain trace); the
> citation set is visible only to NVNM Cite as operator — equivalent to the
> in-memory check and never published on chain. The local index is a
> rebuildable audit/cache tool (`rebuild-index`), not the lookup authority.
> Privacy-sensitive users may point at any independent RPC; the exact query
> is surfaced for replay so verdicts are non-repudiable.

---

## 1. Check tab — "Nothing leaves this machine" is no longer accurate

**Question:** the copy says the check "runs on this machine … no chain or
internet request is made — nothing is revealed to anyone before you choose to
record." True? The real product is a website with no local copy.

**Short answer:** True only on `localhost` (where "this machine" = the
server). False for a hosted site: the document is uploaded to our server for
parsing, and (per item 0) the check now makes live chain reads. The copy must
be rewritten.

**What the code does today:** `/api/check` receives the uploaded document
bytes, extracts text (server-side, pdfplumber/python), normalizes citations
(server-side, eyecite — the reference normalizer, invariant 5), and looks them
up. On `localhost` the server is the user's machine, so "nothing leaves this
machine" is literally true. Hosted, the document reaches our server.

**Decision / prepared revision:**
- **Pipeline in the hosted model:** document uploaded → text extracted +
  citations normalized **server-side** (eyecite stays the single reference
  normalizer; reimplementing in JS would fork invariant 5) → each citation
  resolved by **live chain read** (item 0) → verdicts returned. The document
  is held in memory only and discarded with the response; never written to
  disk, never published on chain.
- **Honest privacy claim** — the document transits our server transiently for
  parsing; the *listings* are the chain's, read live:

  `DRAFT COPY` — **Your document stays private.** *"Your brief is parsed in
  memory to find its citations, then discarded the instant your report is
  ready — it is never stored and never published to the chain. The citations
  themselves are checked by reading NVNM Chain directly, live, so the verdict
  is the chain's answer and not ours — anyone can re-run the same lookup and
  get the same result. Nothing about your document goes on chain unless you
  choose to record a receipt."*

- **Further-privacy option (note for later, not required now):** to make the
  document *never* touch the server, extraction would move client-side
  (e.g. pdf.js) — but normalization is eyecite/Python, so either the document
  text or the document itself must reach the server for the trust-boundary
  normalizer to run. The decided model accepts a transient server-side parse.
  Flag if Albert wants to pursue zero-server-exposure later.

---

## 2. Record tab — drop the "KYA id" field; identity is the wallet

**Question:** the "Agent identifier (KYA id, optional)" field is wrong — on
NVNM Chain the KYA identifier *is* the attesting wallet address.

**Short answer:** Correct. The field is redundant and misleading. Identity is
the signing wallet address, always present, intrinsic to the transaction, not
extrapolable to other identity forms (and one wallet per agent, per the NVNM
Chain maxim). The receipt already records `agent.address`.

**Decision / prepared revision:**
- Remove the free-text `kya-id` input. Receipt `agent` object becomes just
  `{address}` — drop `kya_id` from the receipt schema and the `/api/receipt/
  prepare` payload.
- Replace the input with a read-only display of the connected wallet
  ("Attesting as `0xAF63…7ECB`") so the lawyer sees who the receipt will name.
- Any human-readable label, if ever wanted, belongs in an off-chain directory
  keyed by address — never a self-asserted on-chain string.

### 2b. Put references to the valid cases in the receipt payload (analytics)

**The idea:** the receipt should reference the on-chain case records found
valid in the document, enabling analytics (which cases are cited, spotting
issues from chain data).

**Best on-chain reference (the "you figure it out" part):** the case record is
keyed on chain by **`(registry, canonical-citation)`** — which is exactly the
keyed lookup `records(registry, citation)`. The receipt **already carries
this** for each verified row: `c` (canonical citation) + `g` (index into the
receipt's registries table). So a verified entry is *already* a resolvable
on-chain pointer — re-query `records(registries[g].name, c)` and you land on
the case record. No new reference type is needed for resolvability. For
cross-referencing CourtListener / off-chain analytics, the `k` field (cluster
id) is the join key.

**Two real constraints to resolve before enumerating cases (both matter):**
1. **Byte cap vs. enumeration.** The 2048-byte metadata cap drives the
   compaction ladder that currently *collapses* VERIFIED+match rows into a
   `verified_omitted` count — which destroys exactly the per-case references
   you want. To enumerate every valid case you need either the **chunked-
   receipt design (Phase 4 task 4.3)** or a **compact packed encoding** (a
   sorted array of cluster ids — integers pack tightly — rather than full
   citation strings). Recommend a packed cluster-id (or recordId) array for
   analytics density; keep human-readable citations only while they fit.
2. **Confidentiality / strategy leak (decide explicitly).** Enumerating the
   valid authorities in a brief publishes that brief's citation list on a
   public, immutable chain. Before filing, that *is* the litigation strategy.
   After filing it's public record anyway. Options: (a) enumerate only on
   explicit opt-in; (b) publish counts/aggregates by default, full list only
   post-filing; (c) accept it as the deliberate analytics tradeoff. This is a
   policy decision, not a default — and note it's the *publish* side of the
   same concern invariant 3 covers on the *read* side.

**Touches:** Phase 4 receipt schema (still `nvnm-cite-receipt/v1-draft`), so
this can be designed in before v1 locks.

---

## 3. Registry strategy for receipts — open design question + considerations

**Albert will decide in the main thread; this frames it.**

**The issue:** where do filing receipts get written? The precompile requires
*some* registry to hold a record, and on NVNM Chain a registry has an owner
(creator = admin) with **deny-by-default writes** (only creator + `grantRole`'d
editors can write; experiment (d)). So registry choice is simultaneously an
access-control, discoverability, and analytics decision. "No registry at all"
is not an option — the precompile cannot write without one.

**The dominant constraint is discoverability.** A verifier (opposing counsel,
clerk, judge) starts with only the *document* → computes its SHA-256 → needs
to find the receipt. They do **not** know which firm/lawyer/client/case
produced it. So:

- **One global receipts registry** (today's `receipts-v1`): verification is
  trivial — one registry, query by document hash; multiple attesters of the
  same document coexist as versions (a feature). But deny-by-default writes
  mean its admin must `grantRole` every attesting agent → centralized
  gatekeeper. **Open chain question:** can a registry be created with
  open/public write access, or is it always deny-by-default + grantRole? This
  gates the model.
- **Per-firm / per-lawyer / per-client / per-case registries:** clean
  ownership, self-sovereign writes (each creator is admin of its own
  registry, no gatekeeper), natural per-entity analytics. **But they break
  open verification** unless there's a discovery layer — the verifier can't
  guess the registry from a hash. Mitigations: (a) a global discovery index
  mapping document-hash → registry; (b) **the filer cites the receipt in the
  filing itself** ("citation-check receipt: NVNM Chain registry `X`, tx `Y`")
  — natural legal practice, possibly the cleanest answer; (c) a global
  registry that mirrors/points to the per-entity one (double-write or
  pointer).
- **Granularity tradeoffs:** per-firm = good analytics + access control,
  coarse; per-case = great organization, registry sprawl + creation overhead
  per matter; per-lawyer = matches "one wallet per agent" nicely (the agent's
  wallet creates and owns its registry).

**A likely-good shape to evaluate:** each attesting agent (one wallet) owns
its own registry and writes freely to it (no gatekeeper) **plus** a single
global discovery path keyed by document hash — either a global registry that
also receives the receipt, or an off-chain index resolving hash → (registry,
tx). Decide whether discovery is on-chain (costs gas, fully trustless) or
off-chain (cheaper, adds a trust point).

**Open chain questions to resolve first:** (1) open/public-write registries
possible, or always deny-by-default + grantRole? (2) gas/ownership economics
of many small registries vs. one large one.

**Separate axis to keep honest:** reading from chain (item 0) makes the
**read** side trustless; it does not change who **wrote** the registries
(during the pilot, us). Write-side decentralization is invariant 4's job
(third parties standing up their own registries). Don't let the About copy
conflate them.

---

## 4. Verify tab — "The document never leaves your computer" IS true (and stays true)

**Question:** is the browser-side fingerprinting claim true, and will it hold
on a live site?

**Short answer:** Yes, and unlike item 1 this one survives the move to a
hosted site. Keep it.

**What the code does today:** the verify flow hashes the file with **WebCrypto
in the browser** (`crypto.subtle.digest("SHA-256", …)`) and sends **only the
64-char hash** to `/api/receipt/lookup`. The document bytes never reach any
server. On a hosted page the same JS runs in the visitor's browser →
identical behavior: document stays local, only the fingerprint travels.

**Decision / prepared revision:**
- Copy is accurate; optionally tighten: `DRAFT COPY` *"It is fingerprinted
  (SHA-256) in your browser; only that 64-character fingerprint is sent to
  look up the chain — the file itself is never uploaded."*
- Optional max-trust upgrade: have the browser query the (NVNM or any) RPC
  **directly** for the receipt lookup, so the hash needn't transit our app
  server at all (the testnet RPC already returns permissive CORS — confirmed
  this session). Pairs naturally with item 0's "replay against any node."

---

## 5. Inspect tab — rewrite copy: no "mojibake," no explorer dig

**Question:** revise the copy; what is "mojibake"; don't disparage other
explorers; the audience isn't crypto-literate, so describe the function
plainly.

**What "mojibake" means (for reference):** a term (from Japanese 文字化け) for
the garbled characters you get when text is decoded with the wrong character
encoding — e.g. seeing `Ã©` where `é` belongs. Niche jargon; remove it.

**Decision / prepared revision:** drop "mojibake," "ABI framing," "block
explorers," "prove the plaintext claim yourself." Describe what, why, how.

`DRAFT COPY` — **Panel intro:** *"Read the contents of a citation record.
Every record NVNM Cite writes — each case citation and each filing receipt —
is stored on NVNM Chain as plain, readable text. Paste a transaction's
reference number below to see exactly what it contains: the citation, the case
it points to, and when it was recorded."*

`DRAFT COPY` — **Why-use-it (optional):** *"Use this to confirm with your own
eyes what a record says — the case name, citation, and source link — without
taking anyone's word for it."*

`DRAFT COPY` — **How-to:** *"Paste the transaction reference (it starts with
`0x`) and select Decode."*

`DRAFT COPY` — **Post-decode note (replaces the explorer explanation):**
*"This record is stored as plain text on the chain; the panel above shows its
full contents."*

UX nit: consider "transaction reference" / "transaction ID" over "transaction
hash" in user-facing labels (keep the `0x…` as the visual cue).

---

## 6. About tab — rebuild as a newcomer-friendly explainer + lawyer FAQ

**Question:** make it a crypto/blockchain-newbie-friendly explanation: what
NVNM Cite is, how it works, what it does, who should use it / benefit, how
it's used, current status (which cases are on there), and a lawyer FAQ about
viability for filings.

**Decision / prepared content** (numbers must render live from `/api/status`,
never hard-coded):

`DRAFT COPY` — **a. What it is:** *"NVNM Cite checks whether the cases cited in
a legal document are real. AI tools have caused lawyers to file briefs citing
cases that don't exist; NVNM Cite catches that before filing by checking every
citation against an authoritative, public record of real published decisions.
It can also create a permanent, independently-verifiable receipt that you ran
this check on a specific document at a specific time."*

`DRAFT COPY` — **b. How it works (3 steps):** **Check** — upload a brief; each
citation is matched against the public registry (real / not found / not
covered / …). **Record** — optionally save a tamper-proof, timestamped receipt
that this exact document was checked. **Verify** — anyone (opposing counsel, a
clerk, a judge) can confirm for free whether a receipt exists for a given
document.

`DRAFT COPY` — **c. What it does NOT do (keep prominent — this is the brand):**
*"It confirms a citation exists as a real decision. It does not tell you the
case is still good law, hasn't been overruled, or supports your argument.
Existence, not endorsement — Shepardizing / KeyCite is still your job."*

`DRAFT COPY` — **d. Who should use it / benefits:** drafting attorneys and
their AI tools (catch fabrications pre-filing); opposing counsel and courts
(confirm a filing was checked); malpractice insurers and legal-ops
(proof-of-process). Checking and verifying need **no cryptocurrency, no
wallet, no account**; only *recording* uses a wallet, normally handled by the
firm's tool/agent.

`DRAFT COPY` — **e. Current status (pull live from `/api/status`):** *"Today
NVNM Cite covers every citation to the U.S. Supreme Court and the U.S. Court
of Appeals for the Eleventh Circuit — about 260,000 citations, from
CourtListener's public bulk data (snapshot 2026-03-31). Citations to courts
not yet covered are honestly reported as 'not covered' rather than guessed at.
More courts are planned."* (Exact registries/counts/snapshot date render from
the live status endpoint so this never goes stale. Tranche-1 is loaded and
reconcile-clean: us-scotus 218,775 + us-ca11 41,988 = 260,763 records.)

`DRAFT COPY` — **f. FAQ for lawyers (draft Q&A — refine tone/accuracy):**
- *"If a citation comes back 'verified,' is it safe to cite?"* — It's a real,
  published decision. You must still confirm it's good law and on point;
  verification is existence only.
- *"What does 'not found' mean — is my citation definitely fake?"* — No record
  matched in a covered court. Could be fabricated, mistyped, a pin-cite rather
  than a first-page cite, or a court not yet covered. Investigate before
  relying on it.
- *"Is my document made public or stored anywhere?"* — No. It's parsed in
  memory to find its citations and discarded immediately — never stored, never
  put on chain. Only a fingerprint (and, if you record, the check results) can
  go on chain, and only when you choose. (Aligns with items 0–1.)
- *"What exactly does the receipt prove?"* — That a citation check was
  performed, at a chain-stamped time, over the exact document with that
  fingerprint, by a specific wallet. Tamper-evident proof of process — not a
  ruling on your brief.
- *"Is the timestamp legally meaningful?"* — It's an immutable,
  independently-verifiable record; evidentiary weight is for the court, but it
  can't be backdated or altered after the fact.
- *"What if NVNM Cite shuts down?"* — Receipts live on the public chain and
  stay verifiable by anyone; the registries are public and rebuildable from
  the chain.
- *"Do I need crypto to use this?"* — Not to check or verify. Recording a
  receipt uses a wallet, typically managed for you by the firm or its agent.
- *"How much does it cost?"* — Checking and verifying are free. Recording
  costs a small network fee (fractions of a cent on testnet today).

---

## Summary — what changes in the repo's state files

- **CLAUDE.md invariant 3** — amend: drafting checks read the chain live via
  the NVNM-operated RPC (non-public reads; operator-only visibility; local
  index demoted to audit/cache). Supersede the local-index-for-privacy
  rationale. (Item 0.)
- **IMPLEMENTATION_PLAN Phase 3 task 3.2** — the verifier's drafting-time path
  is live chain reads, not local-index-only. Local index = `rebuild-index`
  audit tool + optional cache. (Item 0.)
- **Phase 4 receipt schema (`nvnm-cite-receipt/v1-draft`)** — drop `kya_id`
  (agent = `{address}` only); design the valid-case reference encoding and the
  enumerate-vs-confidentiality + byte-cap handling before v1 locks. (Items 2,
  2b.)
- **Registry strategy** — new open design item; resolve the two chain
  questions (open-write registries? many-vs-one economics) first. (Item 3.)
- **Webapp copy** — Check privacy (item 1), Inspect (item 5), About + FAQ
  (item 6); Verify copy is fine as-is (item 4).
- **DECISIONS.md** — record item 0 as the dated architecture decision; record
  the invariant-3 amendment.

> Cross-cutting: item 0 (read from chain) + item 1 (document handling) are the
> spine; items 2–3 (receipt contents + registry home) should be decided
> together since both touch the draft receipt schema; items 4–6 are
> independent copy/UX and can land anytime.
