# NVNM Cite — round 2 handoff notes (flow revisions, 2026-07)

Deliverables: revised `index.html` + `app.css`, drop-in, diffed against the
shipped round-1 files. Round-1 notes in `HANDOFF.md` still apply (fonts, base
contrast table, aria recommendations, the `.size-fill` CSSOM exception).
The `demo/` folder remains **dev-only** and now drives every round-2 state.

**No round-1 id or class was renamed or removed.** The five-status vocabulary,
its colors, and the AA table are untouched. No new color tones were introduced
— every new element uses existing tokens (see §4 for the two newly-used pairs).

---

## 1. Contract delta — new ids

| id | element | purpose / states |
|---|---|---|
| `coverage-scope` | span in Check lede | server-filled coverage sentence ("the canonical record of … during the pilot" → mainnet: "all US case law"). Design tolerates any length. |
| `sample-run` | button, Check alt-links | loads the bundled Mata v. Avianca sample and runs the check (P1-8) |
| `check-progress` | div, Check | long-check progress (P1-2). Toggle `hidden`. Bar has class `indeterminate` when total unknown. |
| `check-progress-text` | span | progress copy, textContent ("Checking citation 12 of 63 against NVNM Chain…") |
| `check-progress-fill` | div | width set via CSSOM — **sanctioned exception #2** (same pattern as `.size-fill`) |
| `check-verdict` | div, Check result, has `role="status"` | verdict banner container (P0-1). JS builds one `.verdict` child: `.verdict-bad` / `.verdict-ok` / `.verdict-warn`. Empty when no verdict (zero-citation state). |
| `check-empty` | div, Check result | zero-citation empty state (P1-5). Static copy; toggle `hidden`. When shown, also hide `#check-summary`, the table's `.table-scroll`, `.legend`, `.next-step`. |
| `legend-coverage` | span in legend NOT COVERED row | server-filled registry list (P1-1) |
| `step-line` / `step-line-state` | li / span, Record stepper | new step 2 "Registry line on filing". States: "not yet" → "copy it now" → ok "on filing" / warn "not on filing" (post-prepare, from the engineering boolean). |
| `step-anchor-state` | span (id added to existing node) | step 4 states: "waiting" → busy "anchoring…" → ok "done" / bad "failed" |
| `paste-warning` | div, Record | paste-provenance warning (P0-4). Show when the checked doc came from paste (engineering flag). |
| `paste-gocheck` | button in paste-warning | navigates to Check tab |
| `filer-input` / `matter-input` | text inputs, Record | filer + matter entry; the registry line is deterministic from them |
| `regline-callout` | div, Record | "Put this line on your filing now" step (P0-2). Always visible in record-main. |
| `regline-text` | code | the registry line, textContent. Class `pending` (italic sans) until filer+matter present. Value: **[ENGINEERING: registry-line format]** — demo shows a placeholder. |
| `regline-copy` | button | copy affordance; disabled while `pending` |
| `wallet-callout` | div, Record | wallet guidance (P0-3). JS builds `.callout` variants: no-wallet (MetaMask install link), wrong-network (+ switch action), not-connected. Empty when connected. |
| `prepare-gate` | p.hint under prepare button | shown while `#prepare-btn` is disabled; explains prerequisites |
| `regline-status` | div in prepare result | JS builds `.regline-status.regline-found` or `.regline-missing` from the engineering boolean (P0-2). Warning, not blocker. |
| `coverage-empty` | callout, About | honest counts-unavailable state (P1-1). Toggle `hidden`; table shows "—" counts with lookup source "live status (names and ids only)". |

## 2. Contract delta — new classes & hooks

- `.tabs-bar` / `.tabs-shell` — nav moved **out of `<header>`** (structure change;
  `#tabs` and `.tab` untouched). Sticky via CSS. Engineering wires:
  - `.tabs-bar.stuck` when `getBoundingClientRect().top <= 0 && scrollY > 0` (elevation).
  - `data-fade-l` / `data-fade-r` = `"1"|"0"` on `.tabs-shell` from `#tabs` scroll position (overflow cues).
  - On tab activation, center the active tab via `scrollLeft` math (see demo.js `scrollActiveTabIntoView`).
- `.verdict`, `.verdict-bad/-ok/-warn`, `.verdict-head`, `.verdict-title`
  (carries `data-print`, see §5), `.verdict-sub`, `.verdict-list`,
  `.verdict-item`, `.vc-cite`, `.vc-reason`.
- `button.sum-chip` with `aria-pressed` — summary chips as filters. Rows the
  filter excludes get `tr.row-filtered`. Non-interactive chips stay `div`
  (occurrences; receipt cards on Verify).
- `tr.group-row` + `.group-btn` (`aria-expanded`) — NOT COVERED disclosure row;
  collapsed rows get `tr.row-collapsed`. Severity order: NOT_FOUND,
  AMBIGUOUS_JURISDICTION, UNPARSEABLE, VERIFIED, then the disclosure group.
- `.regline`, `.regline-head`, `.regline-row`, `.regline-text` (+`.pending`).
- `.regline-status`, `.regline-found`, `.regline-missing`.
- `.rb-note`, `.rb-note-ok`, `.rb-note-warn` — post-anchor registry-line
  confirmation inside the success banner.
- `.step-state.warn / .bad / .busy` (+ `.step:has()` ring tints) — stepper tones.
- `.field-grid` — filer/matter two-up.
- `.progress`, `.progress-head`, `.progress-bar` (+`.indeterminate`), `.progress-fill`.
- `.empty-state` — zero-citation state.
- `.cite-snippet` + `.snip-label` — unparseable source context (engineering
  supplies the snippet string incl. ellipses).
- `.attr-label` — "as attributed in the brief" label above brief-side lines.
- `.alt-links`, `.sample-link`, `.sample-tag` — sample affordance + result
  header tag.

## 3. Copy rules honored

- Verdict red: "N citations could not be found — review these before filing."
  Green subtext stays honest about coverage. Amber makes no claim either way.
- Registry-line flow teaches: add the line → export the final file → check that
  exact file → anchor. Post-anchor banner is confirmation, never instruction.
- No copy anywhere implies good-law status. New surfaces repeat "existence
  only" where a lawyer might over-read.

## 4. Contrast (no new tones)

All new elements reuse the round-1 AA pairs. Two existing-token pairs newly
used as text-on-tint:

| Foreground | Background | Ratio | Use |
|---|---|---|---|
| `#6d4413` (darkened bronze ink) | `#f3e8d4` bronze-tint | 7.0:1 | regline heading |
| `#4c463b` ink-2 | `#f3e8d4` bronze-tint | 7.7:1 | regline body/hint |

(`#8a5a24` bronze is used only on the 20px icon, not for text.) Stepper warn/
bad states reuse the chip glyph masks — never color alone.

## 5. Print

- `.verdict` prints 2px black border; `.verdict-title::after` appends
  `" — " attr(data-print)` — JS sets `data-print` to "N NOT FOUND" /
  "ALL VERIFIED" / "OUTSIDE COVERAGE".
- NOT COVERED rows print **expanded**; the disclosure row is hidden. Filters
  are ignored in print (`row-filtered` forced visible).
- `.regline` prints (black border, copy button hidden) — the instruction
  belongs on a printed working copy. `.regline-status` / `.rb-note` print
  bordered; warn variants append " — WARNING".
- Hidden in print: `.tabs-bar`, `.progress`, `#wallet-callout`, `#prepare-gate`.
- Everything else inherits round-1 print rules.

## 6. Aria

- `#check-verdict` has `role="status"` — announced when the verdict renders.
- `#check-progress` has `role="status"`; update `#check-progress-text`
  sparingly (e.g. every 10th citation) to avoid chatter.
- `.group-btn` carries `aria-expanded`; `button.sum-chip` carries `aria-pressed`.
- Round-1 recommendations (tablist roles, busy `aria-live`) still stand.

## 7. Assumptions / for engineering

- **Filer + matter fields are new** (`filer-input`, `matter-input`). The brief
  implies they exist; they did not — wire them to the registry-line generator.
- Registry-line format is **[ENGINEERING: value]** — demo shows a placeholder.
- MetaMask link points to https://metamask.io (the only external URL added;
  plain `<a>`, no resource load — CSP-clean).
- Demo gates `#prepare-btn` on wallet-connected only; real gating (checked doc
  + wallet + network) is engineering's, the disabled treatment + `#prepare-gate`
  + stepper are the design surface.
- `#check-progress-fill` width via CSSOM is sanctioned exception #2.
- Out-of-scope items from the brief were not touched (verify-tab ordering,
  gas label, server coverage data, etc.).
