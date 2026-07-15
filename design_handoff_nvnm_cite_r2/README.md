# Handoff: NVNM Cite — round 2 flow revisions

## Overview
Revision pass on the NVNM Cite webapp (citation verification & filing receipts
on NVNM Chain). Round 2 fixes flow problems found in a UX review: the results
view now leads with a verdict banner; the Record flow teaches
registry-line-before-anchoring; no-wallet users no longer dead-end; pasted-text
provenance is warned about; plus sticky nav, progress, empty states, and other
P1 items. Visual language (law report × premium fintech) is unchanged from
round 1.

## About the design files — READ THIS FIRST
Unlike a typical design handoff, `index.html` and `app.css` in this bundle are
**drop-in production files**, not references to recreate. They preserve every
round-1 id and class the existing `app.js` binds to. The implementation task
is NOT to rebuild the UI — it is to:

1. Ship `index.html` + `app.css` as-is (after the font swap below).
2. Delete the two `demo/` lines in `<head>` and load the real `app.js`.
3. Wire the **new** ids/classes listed in `HANDOFF-R2.md` §1–2 (the contract
   delta) into `app.js` — every new element's states are specified there.
4. Replace the DEV-ONLY Google Fonts `<link>` tags with self-hosted subset
   woff2 `@font-face` rules and add `font-src 'self'` to the CSP
   (instructions in `HANDOFF.md` §1).

The `demo/` folder (`demo.js`, `devbar.css`) is a dev-only state driver. Do
not ship it — but **read `demo.js` before wiring `app.js`**: it constructs the
exact DOM shapes the CSS expects for every JS-built element (verdict banner,
disclosure row, regline status, wallet callouts, rb-note variants), all via
`textContent`/`createElement` (no HTML strings — keep that XSS posture).

## Fidelity
**High-fidelity and final.** Colors, type, spacing, copy, and print treatment
are the shipped design. Do not restyle; do not "improve" copy — the ethic
("provenance, not truth") is load-bearing and legally reviewed in tone.

## What engineering must wire (the real work)
From the round-2 brief, engineering owns:
- Regrouped table order + NOT COVERED collapse (severity order in
  `HANDOFF-R2.md` §2; demo.js `renderCheckTable` is the reference).
- Verdict banner construction from check results (demo.js `buildVerdict`).
- Registry-line generation from filer + matter (`#regline-text` — format is
  `[ENGINEERING: value]`, the design shows a placeholder).
- The registry-line-found boolean (drives `#regline-status`, step 2's state,
  and the post-anchor `rb-note` variant).
- Paste-provenance flag (drives `#paste-warning` and the pasted doc card).
- Prepare-button gating + stepper states; step 4 completion.
- Progress events for `#check-progress` (determinate + indeterminate).
- `.tabs-bar.stuck` toggle, `data-fade-l/r` attrs, and active-tab scroll
  (reference implementations in demo.js — use `scrollLeft` math).
- Server-filled spans: `#coverage-scope`, `#legend-coverage`; About
  counts-unavailable state (`#coverage-empty`).
- Bundled Mata v. Avianca sample + `#sample-run` handler.

Two sanctioned CSSOM exceptions (the only allowed inline styles):
`.size-fill` width and `#check-progress-fill` width.

## Constraints (hard)
- CSP-clean: no inline styles/scripts, no external resources (MetaMask link is
  a plain `<a>`, loads nothing), icons stay in the in-document SVG sprite,
  dynamic text via `textContent` only.
- Five-status vocabulary, colors, and the AA contrast tables
  (`HANDOFF.md` §2, `HANDOFF-R2.md` §4) are locked.
- Print is first-class: verdict suffix via `data-print`, NOT COVERED prints
  expanded, warn notes append " — WARNING". Don't strip the print CSS.
- Accessibility notes: `HANDOFF-R2.md` §6 (role="status" on verdict/progress,
  aria-expanded/aria-pressed) and `HANDOFF.md` §3 (tablist roles, aria-live).

## Design tokens
All in `:root` of `app.css` (paper/ink/navy/bronze + status tints). Type:
Source Serif 4 (display), Public Sans (UI), IBM Plex Mono (citations, hashes).
No new tones were added in round 2.

## Files
- `index.html` — production markup (swap fonts + demo lines as above)
- `app.css` — production stylesheet (round-2 additions at the bottom)
- `HANDOFF.md` — round 1 notes: fonts, base contrast table, aria, print
- `HANDOFF-R2.md` — round 2 contract delta, state matrices, print/aria/assumptions
- `demo/demo.js` — dev-only state driver = reference DOM shapes for app.js
- `demo/devbar.css` — dev-only state bar styling
