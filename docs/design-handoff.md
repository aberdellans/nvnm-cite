> Vendored from the Claude Design bundle (2026-06-12) and implemented the
> same day; see DECISIONS.md. Fonts are self-hosted under static/ with
> licenses in static/fonts-OFL.txt; `font-src 'self'` is in the server CSP;
> the aria recommendations are wired (tablist roles, aria-selected,
> aria-live on busy regions, labeled copy buttons). Arrow-key tab
> navigation and the dark-scheme variant remain open follow-ups.

# NVNM Cite redesign — handoff notes

Deliverables: `index.html` + `app.css` (drop-in, contract-preserving).
The `demo/` folder (`demo.js`, `devbar.css`) is **dev-only**: it stands in for
`app.js` so every state can be previewed via the bottom state bar. For
production, delete the two `demo/` lines in `<head>` and load the real
`app.js` instead. No other change is needed — all 64 contract ids and every
class hook from §8 are preserved verbatim; no renames were made (no mapping
needed).

## 1. Fonts (action required)

The preview loads Source Serif 4 / Public Sans / IBM Plex Mono from Google
Fonts **for review only** (the `<link>` tags in `<head>` are marked DEV ONLY).
For production under the strict CSP:

1. Subset and self-host woff2 files (latin subset is enough):
   - Source Serif 4 — 400, 600, 700 (display/headings)
   - Public Sans — 400, 500, 600 (UI text)
   - IBM Plex Mono — 400, 500, 600 (citations, hashes, JSON)
2. Replace the three `<link>` tags with `@font-face` rules at the top of
   `app.css` (`font-display: swap`).
3. **Add `font-src 'self'` to the CSP header.** This is the only CSP change
   required. Everything else is already clean: no inline styles, no inline
   scripts, no external resources, icons are an in-document SVG sprite, chip
   glyphs are `data:` URIs under `img-src data:`.

System fallbacks (Georgia / Helvetica / Consolas chains) are already in the
custom properties, so first paint is acceptable before fonts arrive.

## 2. Status-color contrast (WCAG 2.1 AA)

All status foregrounds on their tint backgrounds (chips, banners, probes):

| Token | Foreground | Background | Ratio | Use |
|---|---|---|---|---|
| VERIFIED | `#19512f` | `#e2eee2` | 7.6:1 | chips, ok banner |
| NOT_FOUND | `#94251d` | `#f8e7e1` | 6.0:1 | chips, bad banner |
| NOT_COVERED / AMBIGUOUS | `#76570e` | `#f6edd2` | 5.6:1 | chips, warn banner |
| UNPARSEABLE | `#5b564a` | `#ebe8dd` | 5.6:1 | chip |
| body ink | `#1e1b15` | `#f6f3ea` | 14.6:1 | text |
| secondary ink | `#4c463b` | `#f6f3ea` | 8.4:1 | ledes, table text |
| tertiary ink | `#7d7666` | `#fffdf7` | 4.6:1 | labels, hints (≥ AA for normal text) |
| primary button | `#f5f1e4` | `#1c3354` | 10.7:1 | btn-primary |
| navy links | `#1c3354` | `#f6f3ea` | 10.4:1 | links, tabs |

Status is never conveyed by color alone: every chip carries text plus a
distinct masked glyph (check / cross / triangle / question / dash).

## 3. Recommended aria additions (wire in app.js / markup)

Already in the markup: `role="alert"` on all `#*-error` nodes,
`role="status"` on `#global-banner`, `aria-label`s on both dropzones,
`scope="col"` on table headers.

Recommended additions (small `app.js` or markup tweaks):

- Tabs: on `#tabs` add `role="tablist"`; on each `.tab` add `role="tab"`,
  `aria-selected="true|false"` (toggle alongside `.active`), and
  `aria-controls="panel-<name>"`; on each `.panel` add `role="tabpanel"` and
  `aria-labelledby`. Arrow-key navigation between tabs is the usual pattern
  but Tab-key operation already works.
- Busy rows (`#check-busy`, `#prepare-busy`, `#verify-busy`,
  `#inspect-busy`): add `aria-live="polite"` so unhiding announces.
- `#anchor-status`: add `aria-live="polite"` (tx lifecycle announcements).
- Result containers (`#check-result`, `#verify-result`, `#inspect-result`):
  `aria-live="polite"` optional; if results are long, prefer moving focus to
  the result heading instead.
- Copy buttons (demo.js constructs them with class `copy-btn`): give them
  `aria-label="Copy <thing> to clipboard"`.

## 4. The sanctioned CSSOM exception

`.size-fill` is present inside `#size-meter`; its width is set via
`element.style.width` exactly as today. `.size-fill.tight` switches it red;
the `tight-note` class on the meter's hint styles the near-limit message.

## 5. Print

`@media print` is designed, not residual: navigation/chrome/dropzones hidden,
chips become bordered black-on-white, banners get a text suffix
("— RECEIPT FOUND" / "— NO RECEIPT") so the verdict survives B&W, link URLs
print after CourtListener links, cards avoid page breaks. Print the active
tab only (Check report and Verify result are the intended printables).

## 6. Notes for app.js text conventions

`demo.js` shows the exact DOM shapes the CSS expects (kv rows, doc card,
receipt card, probe boxes, banners). All of it is `textContent`/
`createElement` — no HTML in dynamic strings anywhere. Chip labels are
title-case ("Not found"); the class, not the text, carries the status.

## 7. Follow-ups (not blocking)

- `prefers-color-scheme: dark` variant (palette tokens are centralized in
  `:root`, so this is an additive block).
- Real subset woff2 files once font hosting is settled.
