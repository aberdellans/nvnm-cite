# Web demo: check, anchor, verify in a browser

> **SUPERSEDED in part (2026-06-15, Phase 4.5).** Everything below about the
> RECEIPT flow is the original draft and no longer matches the code: the webapp
> now uses the LOCKED receipt v1 (`nvnm-cite-receipt/v1`) via `receipts/schema.py`
> + `receipts/anchor.py`, with PER-FIRM-PER-CASE registries (`<firm>--<case>`),
> NON-ENUMERATING ~526 B receipts, NO `kya_id`, NO compaction ladder, and a
> Verify tab that takes (registry + browser-hashed file). `--telemetry <path>`
> opts into by-citation analytics. See `docs/record-schema.md` §4 and the
> DECISIONS entries dated 2026-06-15 for the authoritative shape. The CHECK /
> INSPECT / status notes below are still accurate.

Status: demo deliverable, built 2026-06-12 at Albert's request, out-of-band
from the phase plan. It previews Phase 3 statuses and a Phase 4 receipt
*draft* without locking either; see "Receipt draft semantics" below.

```
uv run python -m nvnm_cite.webapp            # http://127.0.0.1:8787
uv run python -m nvnm_cite.webapp --help     # --host/--port/--rpc/--data-dir
```

Try it with the committed RECAP fixtures, e.g.
`tests/fixtures/briefs/extracted/mata-avianca-nysd-ecf24-reply-memo.txt`
(31 citation occurrences; *Varghese*, the ChatGPT-invented cite, returns
NOT_FOUND).

## What it does

| Tab | Who it serves | Chain traffic |
|---|---|---|
| **Check citations** | the drafting lawyer | **none** (local index only) |
| **Record verification** | the filing lawyer / their AI agent | read-only re-check, then ONE wallet-signed `addRecord` |
| **Verify a receipt** | opposing counsel, clerks, judges | read-only `records()` lookup — free, no wallet |
| **Inspect a transaction** | anyone | read-only — decodes anchoring calldata to plaintext |

## Privacy model (the invariant 3 rationale, written down)

Drafting-time checks reveal a brief's citation set — the shape of its legal
strategy — to whoever serves the lookup. Even *read* RPC calls leak that to
the RPC operator, hours or days before filing. So:

- `/api/check` consults only local SQLite (`chain_index.sqlite` when the
  registry is synced, else `corpus.sqlite` restricted to the tranche-1
  reporter whitelist so the lookup set mirrors what is being anchored; the
  report labels which source answered). The handler performs **no RPC of any
  kind**, uploads are processed in memory, never written to disk, never
  logged, and discarded with the response. The server is stateless between
  requests.
- The chain is touched the first time at **receipt preparation** — after the
  user has decided to file — when every keyed citation is re-verified with
  `records()` eth_calls pinned to one block, so the receipt claims chain
  state at a stated height (plan task 3.2 semantics).
- The free **verify** tab hashes the document with WebCrypto *in the
  browser*: the file never leaves the verifier's machine; only the
  64-character SHA-256 reaches an RPC. The result panel includes the exact
  `eth_call` to replay against any node — no trust in this server required.

## Trust boundary

There is exactly one ABI codec in the system: the golden-tested
`chain/abi.py` + `chain/precompile.py`. The server prepares calldata with
it; the page deliberately contains **no JavaScript ABI code** and never sees
a private key. Transactions are signed by the user's own wallet (MetaMask
or compatible; the page offers the chain-add for 787111). Writes are
deny-by-default on chain, and the page pre-flights them with an
`eth_estimateGas` probe so a lawyer learns about a missing editor grant
*before* their wallet pops.

## Receipt draft semantics (pre-Phase-4)

The receipt object locks at Phase 4 task 4.1. Until then this demo writes
schema string **`nvnm-cite-receipt/v1-draft`** so testnet demo receipts can
never masquerade as the locked v1. Shape follows the 4.1 sketch:
`{schema, chain_id, document_sha256, checked_at_block, normalizer_version,
registries: [{head_block, id, name}], results: [...], agent: {address,
kya_id?}, timestamp}`, serialized per the locked JSON rules (UTF-8, sorted
keys, no whitespace).

Result entries are compact per the 4.3 hints — keys: `c` canonical, `w`
as-written (omitted when equal), `g` registry (int = index into
`registries`; string = registry outside pilot coverage), `s` status char
(V/N/C/A/U), `n` name_check (`m`/`x`; unknown omitted), `k` CourtListener
cluster, `o` occurrence count (omitted when 1). `V`/`N` are chain-read
facts at `checked_at_block`; `C`/`A`/`U` are normalizer facts under
`normalizer_version`.

Overflow ladder for the measured 2048-byte metadata cap, deterministic and
in order: (1) drop `w`; (2) collapse VERIFIED-with-match entries into a
top-level `verified_omitted` count (NOT_FOUND and name-mismatch entries are
never collapsed); (3) refuse — chunked receipts are Phase 4 task 4.3.

`receipts-v1` does not exist on testnet until someone creates it; the
record tab offers that one-time transaction with the creation strings
rendered verbatim from the locked schema doc §2 (creator becomes admin,
measured Phase 0 (d)).

## Design

The UI follows the 2026-06-12 Claude Design handoff (law report × premium
fintech; Source Serif 4 / Public Sans / IBM Plex Mono, self-hosted latin
woff2 subsets with OFL licenses vendored at `static/fonts-OFL.txt`). The
designer's notes — AA contrast table, aria wiring, print behavior — are
vendored at [design-handoff.md](design-handoff.md); the original brief is
[design-prompt.md](design-prompt.md).

## Honest limits

- The `name_check` here is a conservative heuristic preview of task 3.3:
  `mismatch` only when both brief parties share no significant token with
  any registry case name.
- PDF extraction uses pdfplumber, today a dev-group dependency; without it
  the server asks for .docx/.txt. Image-only scans are detected and
  flagged (the Mata ECF 21 lesson), never silently zero-cited.
- The web check is a demo of the verifier-to-be, not Phase 3 itself: the
  five-status enum is the locked one, and the normalizer's UNRESOLVED
  disposition reports as UNPARSEABLE with its reason carried through.
- Bind stays 127.0.0.1 by default. If a hosted instance is ever wanted for
  clerks, host only the read-only tabs and put TLS in front; that is a
  deployment decision for the pilot close, not this demo.
