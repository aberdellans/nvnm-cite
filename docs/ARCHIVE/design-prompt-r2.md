# Design brief, round 2: NVNM Cite webapp revisions (paste this whole document to Claude Design)

You produced the 2026-06-12 redesign of NVNM Cite (law report × premium fintech;
your handoff notes are attached). It shipped nearly verbatim and holds up well.
A top-to-bottom UX review of the live app found flow problems — ordering, triage,
and dead ends — that need design solutions. This is a revision pass, not a
redesign: keep the visual language, palette, type, and tone exactly as they are.

Attached alongside this brief: the CURRENT production `index.html` and `app.css`
(your baseline — diff against these, not against your original bundle) and your
round-1 handoff notes. Unlike round 1, these are the real shipped files.

## Ground rules (unchanged from round 1, plus lessons learned)

- Drop-in deliverable: revised `index.html` + `app.css`. Preserve every existing
  id and class. New ids/classes are allowed but must be listed in a
  **Contract delta** section of your handoff notes (id, purpose, which states
  use it) so engineering can wire them mechanically.
- Do NOT invent chain constants, addresses, URLs, or example values. Copy them
  verbatim from the attached files. If you need a value that isn't there, write
  `[ENGINEERING: value]` and move on.
- CSP-clean: no inline styles or scripts, no external resources; icons stay in
  the in-document SVG sprite; dynamic text renders via textContent only.
- The five-status vocabulary, its semantic colors, and the AA contrast table
  from your handoff are locked. New tones must come with the same contrast math.
- The ethic is still the brand: provenance, not truth. No copy may imply
  good-law status or that a verified citation supports an argument.
- Print styles are first-class: every new element needs print treatment
  (the check report and verify result go in filing folders).
- Design every state listed below. A state you don't design ships ugly.

## P0-1 · The results view must lead with the verdict

Problem: the product's headline moment — a fabricated citation caught — is
currently one row mid-table, visually equal to rows of "not covered" noise.
In the Mata v. Avianca test, the two NOT FOUND rows sat 6th and 7th of 18.

Design:
- A **verdict banner** directly above the summary chips, three tones:
  - RED: "2 citations could not be found — review these before filing." The
    not-found rows are repeated inside the banner (citation + reason), so the
    lawyer never scrolls to find them.
  - GREEN: "Every covered citation verified." (with honest subtext when some
    citations were outside coverage)
  - NEUTRAL/AMBER: no covered citations found / everything outside coverage.
- **Regroup the table by severity**: NOT FOUND first, then AMBIGUOUS and
  UNPARSEABLE, then VERIFIED. NOT COVERED collapses behind a disclosure row:
  "7 citations outside pilot coverage — show." Design the collapsed and
  expanded states.
- Optional: summary chips double as filters (pressed/unpressed states).
- Print: the verdict banner must survive B&W with a text suffix, like your
  receipt banners ("— 2 NOT FOUND" / "— ALL VERIFIED").

## P0-2 · Record flow: the registry line goes on the filing BEFORE anchoring

Problem (critical): the receipt anchors the document's SHA-256. Discovery
works by a registry line printed on the filing. Today the UI reveals that line
in the post-anchor success banner — telling the user to edit their document
AFTER its hash was anchored, which breaks the match the Verify tab depends on.
The registry name is deterministic from filer + matter, so it is known before
anchoring. The flow must teach: add the line → export the final file → check
that exact file → anchor.

Design:
- Rework the Record tab's progression (current 3-step stepper) into a sequence
  that inserts an explicit step after filer/matter entry: **"Put this line on
  your filing now"** — the copyable registry line, with copy affordance, and
  the instruction that the file checked and anchored must be the final exported
  file containing it.
- The prepare result gains a status row: "Registry line found in document /
  not found." Design both states; the not-found state is a warning, not a
  blocker (engineering supplies the boolean).
- The post-anchor success banner becomes **confirmation**, not instruction:
  registry-line-present → "Your filing already carries the registry line";
  absent → warning variant: "The anchored file does not contain the registry
  line — if you add it now, the filed document will no longer match this
  receipt. Re-check and re-anchor the final file."
- Stepper states for all steps including completion of step 3 (today step 3
  reads "waiting" forever — engineering will wire it; design the states).

## P0-3 · The no-wallet lawyer must not dead-end

Problem: without MetaMask the header shows a disabled "No wallet detected"
button (explanation hidden in a tooltip) and Record's step 2 says "not yet"
with no path forward.

Design an inline callout at the wallet step of the Record tab:
- No wallet detected: "Recording is normally done by your firm's filing tool
  or agent. To record manually from this browser, install MetaMask [link].
  Checking and verifying never need a wallet."
- Wallet present but wrong network: guidance + the existing switch action.
- "Prepare receipt" appears disabled until prerequisites are met, with the
  stepper as the visible explanation of why (design enabled/disabled button
  treatment; engineering wires the gating).

## P0-4 · Warn when the checked document is pasted text

Problem: pasted text becomes `pasted-text.txt` and can be anchored; a receipt
over pasted bytes will never match a filed document. The only caveat lives
back on the Check tab.

Design: a warning callout on the Record tab, shown when the checked document
came from paste: "This attests the pasted text, not the file you will file.
Upload the final file instead." With a link back to Check. (Engineering
supplies the provenance flag.)

## P1 · Smaller design items

1. **Coverage honesty.** About's coverage section currently shows "Coverage is
   loading from the live registry…" forever when the local index is absent.
   Design an honest empty state: registries exist on chain (names + ids from
   live status) but counts unavailable on this instance. Also: the Check
   hero's coverage sentence and the legend's "(us-scotus, us-ca11)" become
   server-filled spans (design for varying length — the mainnet scope is
   "all US case law").
2. **Long-check progress.** The "Checking…" spinner needs a progress variant:
   "Checking citation 12 of 63 against NVNM Chain…" with a quiet progress bar.
   Design indeterminate and determinate states (engineering supplies events).
3. **Sticky navigation.** The tab row (at minimum) stays visible when scrolled
   deep in a results table. Design the stuck state (subtle elevation/hairline).
4. **Mobile tab overflow.** At 375px only two of five tabs are visible with no
   affordance that more exist. Add a fade edge or equivalent cue; ensure the
   active tab scrolls into view.
5. **Zero-citation empty state.** A checked document with no recognizable
   citations currently renders an empty table. Design an explicit empty state
   ("No recognizable citations found in this document"), distinct from the
   image-only-scan warning.
6. **Unparseable rows show context.** A stray "§" renders as the entire
   citation cell. Design the row to carry a short snippet of surrounding
   source text ("…17 N.Y. Jur. 2d Carriers § 542 (2023)…") so the lawyer can
   locate it (engineering supplies the snippet).
7. **"As attributed in the brief" labeling.** The parenthetical year shown
   under a citation sometimes comes from sloppy source text and contradicts
   the registry year in the next column. Label the brief-side line explicitly
   ("as attributed in the brief") so a discrepancy reads as the brief's
   problem, not the product's.
8. **Demo affordance.** Under the Check dropzone: "…or try it with the brief
   from Mata v. Avianca — the case where ChatGPT invented a citation." One
   click loads the bundled sample and runs the check. Design the link and the
   result header treatment identifying the sample document.

## Out of scope for this pass (engineering owns; listed so you don't solve them)

Parallel/progressive citation resolution; wiring the stepper and prepare-button
gating; detection of the registry line in the document; the paste-provenance
flag; hash-first ordering on the Verify tab's dropzone; the gas-price label;
serving coverage data from the server. Your job is the surface each of these
lands on.

## Deliverables (same shape as round 1)

1. Revised `index.html` + `app.css`, drop-in, diffed against the attached files.
2. **Contract delta**: every new/changed id and class, with the state matrix.
3. Updated demo state driver covering every new state above (kept dev-only).
4. Handoff notes: contrast table rows for any new tones, print treatment of
   new elements, aria notes (the verdict banner should be announced — probably
   role="status"), and anything you had to assume.
