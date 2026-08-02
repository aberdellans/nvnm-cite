# Web demo: check, anchor, verify in a browser

`uv run python -m nvnm_cite.webapp` serves the lawyer-facing app at
http://127.0.0.1:8787 (`--help` for `--host/--port/--rpc/--data-dir`). It is the
primary product surface and reuses the **same verifier core and locked receipt v1
as the CLI**. Try it with the committed RECAP fixtures, e.g.
`tests/fixtures/briefs/extracted/mata-avianca-nysd-ecf24-reply-memo.txt`
(*Varghese*, the ChatGPT-invented cite, returns NOT_FOUND).

## What it does

| Tab | Who it serves | Chain traffic |
|---|---|---|
| **Check citations** | the drafting lawyer | live keyed `records()` reads — read-only, no gas |
| **Record verification** | the filing lawyer / their AI agent | read-only re-check, then ONE wallet-signed `addRecord` |
| **Verify a receipt** | opposing counsel, clerks, judges | read-only `records()` lookup — free, no wallet |
| **Inspect a transaction** | anyone | read-only — decodes anchoring calldata to plaintext |

## Privacy & non-repudiation (the item-0 model)

Drafting checks read the chain **live** via the NVNM-operated RPC (keyed
`records(registry, citation)` eth_calls). `eth_call` reads are point-to-point — no
mempool, no block, no on-chain trace — so the citation set is visible only to NVNM
as RPC operator, identical to the in-memory parse the server already does, and
**never published**. The surviving win is **non-repudiation**: we cannot lie about
the chain's answer, because any skeptic replays the exact `records()` call against
any node (the result panel shows the exact query to replay). Uploads are parsed in
memory, never written to disk or logged, and discarded with the response.

The free **Verify** tab hashes the document with WebCrypto **in the browser** — the
file never leaves the verifier's machine; only the 64-character SHA-256 and the
registry name reach an RPC.

Aggregate by-citation query stats may be retained by NVNM as RPC operator
(decoupled from document hash and client identity); this is opt-in via
`--telemetry <path>` and disclosed in the Check tab.

## Receipts (locked v1)

The Record tab anchors the **locked, non-enumerating receipt v1**
(`nvnm-cite-receipt/v1`) to a **per-firm-per-case registry** (`<firm>--<case>`,
owned by the filing wallet — the tab shows "Attesting as 0x…"). The receipt binds
the document SHA-256 to provenance (chain id, checked-at-block, normalizer version,
the registries read, the attesting wallet, timestamp) and a **non-identifying
status tally** — never the list of cited cases (~526 B, always under the 2048 B
cap). Authoritative shape: [record-schema.md](record-schema.md) §4. The
per-firm-per-case registry is created with the locked creation strings on first use
(creator becomes admin; deny-by-default writes).

## Trust boundary

There is exactly one ABI codec in the system: the golden-tested `chain/abi.py` +
`chain/precompile.py`. The server prepares calldata with it; the page contains
**no JavaScript ABI code** and never sees a private key — transactions are signed
by the user's own wallet (MetaMask or compatible; the page offers the chain-add for
the server-selected network — mainnet 1611 by default, testnet 787111 with
`--network testnet`). Writes are deny-by-default on chain, and the page pre-flights them
with an `eth_estimateGas` probe so a lawyer learns about a missing editor grant
*before* their wallet pops.

## Honest limits

- `name_check` is a conservative heuristic: `mismatch` only when the brief's
  parties share no significant token with any registry case name.
- PDF extraction uses pdfplumber; image-only scans are detected and flagged (the
  Mata ECF 21 lesson), never silently zero-cited.
- The five-status enum (VERIFIED / NOT_FOUND / NOT_COVERED / AMBIGUOUS_JURISDICTION
  / UNPARSEABLE) is the locked one; the normalizer's UNRESOLVED disposition reports
  as UNPARSEABLE with its reason carried through.
- Bind stays 127.0.0.1 by default. A hosted instance for clerks would expose only
  the read-only tabs behind TLS — a pilot-close deployment decision, not this demo.

The visual design follows the 2026-06-12 Claude Design handoff (law report × premium
fintech; self-hosted Source Serif 4 / Public Sans / IBM Plex Mono, OFL licenses at
`static/fonts-OFL.txt`); the designer's notes (AA contrast, aria wiring, print) are
vendored at [ARCHIVE/design-handoff.md](ARCHIVE/design-handoff.md).
