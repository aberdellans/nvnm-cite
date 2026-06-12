# Design brief: NVNM Cite web app (paste this whole document to Claude Design)

You are redesigning the user interface of **NVNM Cite**, a citation-verification
and filing-receipt system for the US legal profession, built on NVNM Chain. A
working but visually plain implementation exists; your job is a complete visual
redesign that reads as **enterprise-grade legal software** — something an
AmLaw 100 partner, a federal clerk of court, or a malpractice insurer would
trust on sight — while remaining a drop-in replacement for the current
templates (the integration contract in §8 is mandatory).

---

## 1. What this product is

Lawyers have been sanctioned for filing briefs containing citations invented by
AI (the famous example: *Mata v. Avianca*, where ChatGPT fabricated
"*Varghese v. China Southern Airlines*, 925 F.3d 1339 (11th Cir. 2019)").
NVNM Cite answers that with public registries of every canonical US case
citation (Supreme Court + Eleventh Circuit during the pilot), stored **in
plaintext** on NVNM Chain, plus:

1. **Check** — a lawyer uploads a brief; every citation is checked for
   *existence* against the registries. Runs locally, makes zero network
   requests, keeps no copy of the document.
2. **Record verification** — at filing time, the lawyer (or their AI agent)
   anchors a *filing receipt* on chain: an immutable, timestamped attestation
   that the document with a specific SHA-256 hash was citation-checked, with
   the per-citation results. Signed by their own wallet.
3. **Verify** — opposing counsel, clerks, and judges drop in a document and
   instantly see whether a receipt exists for that exact file. Free, read-only,
   no wallet, no account; the file is hashed in the browser and never uploaded.
4. **Inspect** — decodes any anchoring transaction into readable plaintext
   (generic block explorers mangle it), proving the "plaintext on chain" claim.

The product's one-line ethic, which the UI must radiate: **provenance, not
truth.** It proves a check happened, when, against what, over which exact
document, attested by whom. It never asserts a case supports an argument and
never asserts good-law status. That honesty is the brand.

## 2. Audience and feeling

Primary: attorneys at firms large and small (40–65, conservative taste, deep
skepticism of "crypto"); court clerks and judges (the free verify flow);
legal-ops and malpractice insurers. Secondary: the AI agents' operators.

Target feeling: the gravitas of a law report crossed with the craft of premium
fintech software (Stripe-dashboard-level polish, worn like a tailored suit).
Calm, evidentiary, precise, quietly confident. Dense with information but
never busy.

**Anti-goals (hard):** no crypto aesthetic — no neon gradients, glassmorphism,
dark-hacker themes, rocket/diamond iconography; no playful startup tone; no
generic Bootstrap look. Blockchain vocabulary is demoted to plumbing: the UI
says *record, receipt, attestation, verify, sign* — "wallet/transaction/gas"
appear only where the user must act on them, framed as signing and fees.

## 3. Product truths the design must carry (not bury)

- **Existence, not endorsement.** The disclaimers ("a VERIFIED citation can
  still be overruled…", "provenance, not truth") are first-class UI elements,
  designed deliberately — not legal fine print in the footer.
- **Privacy at drafting time.** "Nothing leaves this machine" on the check
  flow is a key trust message; give it visual weight.
- **Free and open verification.** The verify flow must feel like a public
  service: zero friction, no wallet, prominent "your file never leaves your
  computer."
- **TESTNET badge** always visible during the pilot.
- **Attribution**: "Case data: CourtListener / Free Law Project" must remain
  visible (About + footer).
- The five-status vocabulary with stable semantic colors (see §5); colors must
  stay distinguishable and WCAG-AA on their backgrounds.

## 4. Information architecture and every state to design

Single page, masthead + tab navigation + footer. Five sections. The current
structure is correct — redesign the skin, keep the bones. Design **all** of
the following states (the implementation has them today; a state you don't
design is a state that ships ugly):

**Global / masthead**
- Brand block; TESTNET badge; chain status badge (3 states: loading "chain …",
  healthy "chain 787111 · block 1,616,300", error "chain RPC unreachable").
- Wallet button (4 states: "Connect wallet" / "No wallet detected" /
  connected `0x1f2e3…9c0d` / connected + "wrong network").
- Global banner strip (warning tone), e.g.: "Registry bulk load in progress:
  … a live chain re-check may show NOT_FOUND for real citations until it
  completes." Sometimes two messages concatenated; sometimes hidden.

**Tab 1 · Check citations**
- Empty state: explainer copy, privacy callout, large dropzone (.pdf .docx
  .txt .md), "…or paste text instead" disclosure with textarea + caveat hint.
- Dropzone drag-over state; busy state ("Checking…"); error state (e.g.
  "unsupported file type .gif; supported: .pdf, .docx, .txt, .md").
- Result: document card (filename, SHA-256 — a 64-char monospace string that
  must wrap or truncate-with-copy gracefully — size, extraction method);
  summary stat chips (occurrences / verified / not found / not covered /
  ambiguous / unparseable); optional warning callouts (image-only-scan
  warning; name-mismatch warning); the citations table (columns: status chip,
  citation + as-written variant + party names + reason line, registry record
  (case name(s), year, CourtListener link, "+N more decisions share this
  first page" collision note, source tag), names match/MISMATCH/—,
  occurrence count); a legend explaining all five chips; CTA "Continue to
  record verification →" with the line "Recording is optional and explicit:
  nothing has touched the chain yet."

**Tab 2 · Record verification**
- A 3-step prerequisite stepper (checked document ✓ / wallet connected ✓ /
  re-verify & sign) with per-step met/unmet states.
- No-document state (points back to Check).
- Main: document card; optional "Agent identifier (KYA id)" text field;
  primary action "Prepare receipt — live chain re-check" + the hint that this
  is the first network interaction and is read-only.
- Prepare busy / error states.
- Prepared: metadata rows (checked-at block, registries consulted with ids,
  schema "nvnm-cite-receipt/v1-draft — draft until Phase 4 locks v1", server
  timestamp note); a local-vs-chain diff table (each row: citation, local
  status chip, chain status chip, names; when they differ a note "differs
  from the local check — on-chain registry state is what the receipt
  records"); a collapsible "Receipt JSON (this exact text is what gets
  anchored)" code block; a byte-budget meter "Receipt size: 1,407 of 2048
  bytes" with a near-limit (>85%) warning state and a "compaction applied: …"
  note; write-permission probe results (3 states: ✓ "this wallet may write…
  ~99,000 gas ≈ 0.0045 wmantraUSD" / ✗ "no editor rights… the registry's
  admin must run grantRole(...)" / ✗ generic simulation failure); the
  one-time setup card shown when the receipts registry doesn't exist yet
  (explainer, the exact addRegistry call in a code block, "Create receipts-v1
  with wallet" button); the primary "Sign & anchor with wallet" button
  (disabled until the probe passes).
- Transaction lifecycle: spinner row "Submitted 0xab12… — waiting for
  confirmation…"; success banner ("Verification recorded on NVNM Chain":
  tx hash, block + UTC time labeled "the immutable timestamp", document
  SHA-256, gas; actions: "View on Blockscout ↗", "Verify it now (free
  lookup)", "Decode the transaction"); reverted/failed banner; wallet-rejected
  notice.
- A standing callout: "What the receipt asserts — and all it asserts" (the
  four numbered claims; keep this copy).

**Tab 3 · Verify a receipt** (free, public-facing — clerks and judges)
- Empty: explainer ("for opposing counsel, clerks of court, and judges…"),
  privacy callout ("The document never leaves your computer… only its
  64-character fingerprint is sent"), dropzone, "…or paste a SHA-256 hash"
  disclosure with input + button.
- Busy ("Hashing locally, then querying chain…"); error.
- Result A — receipt found: green confirmation banner; then one card per
  receipt version: "Recorded (chain time) 2026-06-12 15:26:42 +0000 UTC",
  record id/version, attested-by address (+ optional KYA id), checked-at
  block, normalizer version, schema; summary chips of the recorded results; a
  results table decoded from the receipt; a "N VERIFIED results were
  collapsed into a count…" note when present; collapsible raw on-chain
  record. Close with the honesty line ("…existence, not good law").
- Result B — not found: red banner "No receipt for this fingerprint" + the
  explanation that a one-byte change breaks the match.
- Result C — registry not deployed yet: amber banner.
- "Don't trust this page? Replay the lookup yourself" disclosure containing a
  ready-to-run curl command in a code block.

**Tab 4 · Inspect a transaction**
- Input row (66-char hash) + Decode button; busy; error; not-found banner.
- Result: status (confirmed ✓ / REVERTED ✗ / pending), block + time, from,
  to + "(NVNM anchoring precompile)" tag, gas line; "Decoded: addRecord()"
  section with labeled plaintext fields (registry, uri, checksum =
  the citation string, checksumAlgo, metadata…); pretty-printed metadata
  JSON block; the explainer that ABI framing is why explorer UTF-8 views look
  garbled; unknown-selector fallback; Blockscout link.

**Tab 5 · About & status**
- Four value-proposition cards ("It proves provenance" / "It never asserts
  truth" / "Drafting stays private" / "Anyone can audit").
- Live status rows (RPC, chain id, head block, three registries with ids and
  created dates or "not created yet", bulk-load running flag, precompile
  address); registry coverage table (registry / lookup source / citation key
  counts e.g. 218,775 / detail); versions rows (normalizer 1.0.0, citation
  spec cite-canonical-v1, record schema v1, receipt schema draft); attribution.

**Footer**: testnet identity line, precompile short address, "provenance, not
truth", attribution, "this page never sees a private key."

## 5. Real content (design with this, not lorem ipsum)

Statuses and their fixed meanings (chip set):
`VERIFIED` (green) · `NOT_FOUND` (red) · `NOT_COVERED` (amber) ·
`AMBIGUOUS` (amber) · `UNPARSEABLE` (gray); plus name-check marks
`match` / `MISMATCH` / `—`.

Use these rows in the check-table mockup:
- ✅ `410 U.S. 113` — *Roe v. Wade* (1973), us-scotus, names match, 3×,
  CourtListener link.
- ❌ `925 F.3d 1339` — brief says *Varghese v. China Southern Airlines Co.,
  Ltd.* (11th Cir. 2019); "no record for this citation in the us-ca11
  registry (first-page canonical keys)". This is the money shot — the
  fabricated citation caught.
- 🟨 `100 F.3d 200` — "us-ca2 is outside pilot coverage (us-scotus, us-ca11)".
- 🟨 `12 F.3d 34` — "F.3d alone cannot place the court; cite the court
  parenthetical".
- ⬜ `Id.` — "orphan short form: no antecedent resolved in this document".

Sample SHA-256 for document cards:
`0bc0ce36db4f005da90c200ce9018319ecb52567ef9bb5b4257b1e55bcead9b2`

Sample decoded transaction (Inspect tab): function `addRecord`, registry
`us-scotus`, checksum `33 S. Ct. 352`, metadata
`{"cluster":97778,"name":"Porto Rico v. Rosaly Y Castillo","year":1913}`,
uri `https://www.courtlistener.com/opinion/97778/porto-rico-v-rosaly-y-castillo/`,
gas 86,757 @ 45 gwei, block 1,615,584, 2026-06-12T15:26:42Z.

Sample receipt JSON (code block content):
`{"agent":{"address":"0xaf63…","kya_id":"kya:demo-agent"},"chain_id":787111,"checked_at_block":1616300,"document_sha256":"0bc0…","normalizer_version":"1.0.0","registries":[{"head_block":1616300,"id":737,"name":"us-scotus"},{"head_block":1616300,"id":738,"name":"us-ca11"}],"results":[{"c":"410 U.S. 113","g":0,"k":108713,"n":"m","o":3,"s":"V"},{"c":"925 F.3d 1339","g":1,"s":"N"}],"schema":"nvnm-cite-receipt/v1-draft","timestamp":"2026-06-12T16:05:09Z"}`

Gas/token: testnet gas is paid in **wmantraUSD** (≈ 45 gwei; an anchor costs
roughly 0.005–0.01 wmantraUSD).

## 6. Visual direction (latitude within these rails)

- **Typography.** An authoritative serif for display/headings (self-hostable
  OFL faces only — e.g. Source Serif 4, Spectral, Libre Caslon Text); a
  neutral grotesque for UI text (e.g. Inter, Public Sans, IBM Plex Sans); a
  tabular monospace for citations, hashes, JSON (e.g. IBM Plex Mono,
  JetBrains Mono). Subset woff2, self-hosted (§7), with system-stack
  fallbacks. Tabular numerals for block numbers and counts.
- **Palette.** The established direction is paper/ivory ground, near-black
  ink, deep navy primary, bronze/oxblood accent — evolve it freely, but keep
  light mode primary (legal printing culture), keep the five status hues
  semantically stable and AA-compliant, and keep overall chroma restrained.
  A `prefers-color-scheme: dark` variant is a welcome bonus, not required.
- **Texture.** Law-report and ledger cues used with restraint: hairline
  rules, small-caps labels, generous measure (~70ch) for prose, confident
  whitespace. Density is fine in tables; chrome is not.
- **Components to craft.** Status chips; summary stat cards; the 3-step
  stepper; dropzones (idle/hover/drag-over/focus); callouts in three tones
  (info/privacy/warning); key-value rows; data tables (must survive a 64-char
  hash and 90-char case names); code/JSON blocks; the byte-budget meter;
  spinner + transaction-pending row; result banners (ok/bad/warn);
  details/summary disclosures; copy-to-clipboard affordances for hashes and
  curl commands (clipboard API is available).
- **Iconography.** Minimal single-color inline SVG (scales of justice, seal,
  shield-check, document, fingerprint, link-out). Replace the current
  text-glyph ✓/✗/⚖ usage. No emoji in the final UI.
- **Motion.** Restrained and purposeful: 150–250 ms ease on state changes,
  a subtle confirmation moment when a receipt anchors or a verify comes back
  green. Nothing springy.
- **Print.** The check report and the verify result must print to a clean
  black-and-white US-letter page (a lawyer will put it in a filing folder).
  A print stylesheet exists today in rudimentary form; design it properly.
- **First paint.** Design the skeleton/placeholder state (status badge shows
  "chain …" until the first status fetch returns).

## 7. Hard engineering constraints (violating any of these blocks shipping)

- **Static, no build step, no framework.** Final artifacts are flat files
  served by a tiny Python server: `index.html`, `app.css`, the existing
  `app.js`, plus any font/SVG assets. No React/Tailwind/SASS pipelines; no
  npm. Hand-authored modern CSS (custom properties, grid, flex) only.
- **Strict Content-Security-Policy**, currently:
  `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'
  data:; connect-src 'self'; form-action 'none'; base-uri 'none';
  frame-ancestors 'none'`.
  Consequences: **no** inline `style=""` attributes, **no** inline
  `<style>`/`<script>` blocks, **no** external CDNs, fonts, or analytics of
  any kind. Self-hosted fonts are fine — note in your handoff that
  `font-src 'self'` must be added to the header. One sanctioned exception
  exists in current JS: the size-meter fill width is set via CSSOM
  (`element.style.width`), which CSP permits; keep a `.size-fill` element
  for it.
- **All dynamic text is injected via `textContent`** (XSS posture — case
  names come from chain data). Decorative treatments must not require HTML
  inside dynamic strings.
- **Accessibility: WCAG 2.1 AA.** Visible focus states everywhere; tab
  navigation operable by keyboard (tabs are `<button class="tab"
  data-tab="…">`); dropzones are focusable with `role="button"` and respond
  to Enter/Space (already wired); status must not be conveyed by color alone
  (chips carry text). If you want `aria-live` regions or `role="tablist"`
  semantics, specify the exact attribute additions in handoff notes and the
  engineer will wire them.
- **Responsive 360 px → 1440 px+.** Tables must degrade gracefully on
  mobile (judges use iPads).
- **Budget.** CSS ≤ ~60 KB; fonts subsetted; no raster images.

## 8. Integration contract (this makes your work drop-in)

The existing `app.js` drives everything by element id and class name. You may
restructure wrappers, add ids/classes, and restyle without limit, but:

- **Preserve all 64 element ids** currently in `index.html`:
  `net-badge, chain-badge, wallet-btn, global-banner, tabs, panel-check,
  check-drop, check-file, paste-toggle, paste-area, paste-text, paste-check,
  check-busy, check-error, check-result, check-doc, check-summary,
  check-warning, check-table, to-record, panel-record, step-report,
  step-report-state, step-wallet, step-wallet-state, step-anchor,
  record-nodoc, record-gocheck, record-main, record-doc, kya-id, prepare-btn,
  prepare-busy, prepare-error, prepare-result, prepare-meta, prepare-table,
  receipt-json, size-meter, setup-box, probe-box, anchor-btn, anchor-status,
  panel-verify, verify-drop, verify-file, hash-toggle, hash-area, hash-input,
  hash-lookup, verify-busy, verify-error, verify-result, panel-inspect,
  tx-input, tx-inspect, inspect-busy, inspect-error, inspect-result,
  panel-about, about-status, coverage-table, about-versions,
  about-attribution`.
- **Preserve these class hooks** (JS toggles or constructs them):
  state toggles `hidden`, `active` (tabs/panels), `dragover`, `ok`
  (step-state); families `chip chip-<STATUS>` (+ `chip-big`),
  `sum-chip sum-<STATUS>`, `result-banner` + `result-ok|result-bad|result-warn`,
  `probe-ok|probe-bad`, `name-m|name-x|name-u`, `size-bar`, `size-fill`
  (+ `tight`), `spinner`, `txwait`, `busy`, `error`, `callout`,
  `callout-warn`, `callout-privacy`, `doc-card`, `kv`/`row`/`k`/`v`,
  `cite-table`/`cite-canon`/`cite-sub`/`cite-reason`, `codeblock`,
  `json-details`, `summary-chips` (+ child `n`/`l`), `hint`, `linklike`,
  `btn`/`btn-primary`/`btn-outline`, `badge` +
  `badge-testnet|badge-muted|badge-ok|badge-bad`, `banner`/`banner-error`,
  `legend`, `steps`/`step`/`step-state`, `dropzone`/`dz-main`/`dz-sub`,
  `field-row`, `alt-action`, `tabs`/`tab`, `panel`/`panel-head`,
  `about-grid`/`about-card`, `next-step`, `mono`.
  `<STATUS>` ∈ `VERIFIED, NOT_FOUND, NOT_COVERED, AMBIGUOUS_JURISDICTION,
  UNPARSEABLE`.
- Selector facts JS relies on: nav buttons match `.tab` with `data-tab`;
  panels match `.panel` with ids `panel-<name>`; the three data tables
  contain a `tbody`.
- If a rename is truly necessary, ship a literal old→new mapping so the
  engineer can patch `app.js` mechanically.

## 9. Deliverables

1. Redesigned `index.html` and `app.css` (CSP-clean, contract-preserving),
   plus any self-hosted font files and inline-SVG icon set.
2. Handoff notes: status-color contrast table (foreground/background ratios),
   required CSP additions (e.g. `font-src 'self'`), any `aria-*` attributes
   or tiny `app.js` adjustments you recommend, and the rename mapping if any.
3. Optional: `prefers-color-scheme: dark` variant; refined print stylesheet.

## 10. Acceptance bar

Screenshot test: the Check tab showing the *Varghese* NOT_FOUND row should
look like evidence software — credible in a CLE presentation, a partner
meeting, and a courtroom. Every state in §4 designed; zero crypto styling;
AA contrast throughout; clean at 360 px and in print; no CSP violations in
the console; drops into the existing server without touching `app.js` logic.

If you need the current implementation for reference (screenshots, the live
server, or the source of `index.html`/`app.css`/`app.js`), ask — it runs with
one command and the maintainer can paste any of it.
