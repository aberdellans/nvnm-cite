# NVNM Cite: guide for AI agents

NVNM Cite checks whether the case citations in a legal document exist in per-court registries on NVNM Chain, and can anchor a filing receipt that binds a document's SHA-256 to the chain state consulted. Registries hold canonical US case citations in plaintext, loaded from CourtListener data. Every check is a live keyed read of the chain, so the verdict is the chain's answer, not this server's, and every answer includes what you need to replay it yourself.

What an answer asserts: existence of a registry record, at a stated block, in a named registry. The service never asserts that a case is good law or that it supports a proposition. Those are judgments for you and your user to make, with whatever other tools your mandate includes; the statuses below tell you exactly what was and was not established.

## Conventions

- The API lives on this origin (`https://nvnmcite.com/api/...`). If you are reading this from another deployment, the same paths apply to that origin.
- No authentication and no API keys. Reads are free.
- Every error response is JSON: `{"error": "human-readable message"}` with a meaningful HTTP status (400/404/411/413/422, and 502 when the chain RPC cannot be reached).
- A 502 means the chain could not be consulted. It is never a statement about any citation. Do not report citations as missing because the RPC was down.
- POST bodies are the raw file bytes, not multipart forms. `Content-Length` is required (chunked transfer is rejected with 411). Upload cap: 30 MB. Extracted text cap: 2,000,000 characters.
- Custom request headers (`X-Filename`, `X-Firm`, `X-Case`) are URL-decoded server side, so percent-encode non-ASCII values.
- Formal endpoint contract: [/openapi.json](/openapi.json).

## Start here: identify the deployment

```
curl -sS https://nvnmcite.com/api/status
```

Returns the network this deployment serves (chain id, cosmos chain id, public RPC URL, explorer URL, gas token), coverage (the number of court registries in the pinned name-to-id manifest and its creator), the normalizer and schema versions, live chain health, and whether aggregate telemetry is enabled. Read it once per session; the anchor workflow needs `network.public_rpc`, `network.chain_id`, and `network.explorer` from it.

## Check a document's citations

```
curl -sS -X POST https://nvnmcite.com/api/check \
  -H "X-Filename: brief.pdf" \
  --data-binary @brief.pdf
```

Supported types: `.pdf`, `.docx`, `.txt`, `.md`. The filename extension tells the server how to extract text.

The response you care about:

- `summary.by_status`: counts for the five statuses (listed below), one per authority.
- `citations[]`: one entry per cited authority, in document order. A run of parallel reporters for the same case ("133 Ohio St.3d 10, 2012-Ohio-5270, 979 N.E.2d 1229") is one entry: the strongest member is the row and the rest stay visible in its `parallels` array with their own statuses. Key fields per entry:
  - `canonical`: the normalized citation key that was checked (first-page form, e.g. `410 U.S. 113`), and `as_written` / `variants` for how the document actually wrote it.
  - `status` and `reason`: the verdict and why.
  - `registry` / `registry_id`: which court registry was consulted (e.g. `us-scotus`).
  - `caution`: present on some NOT_FOUND results (see below). If present, relay it verbatim to your user.
  - `name_check`: `match`, `mismatch`, or `unknown`. A token-overlap comparison between the party names in the document and the case name in the on-chain record. `mismatch` flags the failure mode where a real citation is paired with an invented case name. It stays `unknown` when it cannot be sure.
  - `record`: the on-chain record when one was found (case name, year, CourtListener URL).
  - `query`: the exact keyed lookup that was made, so the result can be replayed against any NVNM Chain RPC.
  - `occurrences` and `spans`: where the citation appears in the document.
- `summary.law_sections_out_of_scope` and `unresolved_references`: accounting for what the table deliberately excludes — statute/regulation section fragments (registries hold case citations only) and Id./supra references whose antecedent could not be determined. Nothing is silently dropped.
- `document.sha256`: the SHA-256 of the exact bytes you uploaded. This is what a filing receipt anchors.
- `normalizer.version` and `coverage.count`: provenance of the check.
- `privacy.note`: what happened to the document (parsed in memory, discarded with the response).

### What each status means

- `VERIFIED`: a record for this canonical citation exists in that court's registry on NVNM Chain. Existence only.
- `NOT_FOUND`: the registry for that court was consulted live and has no record under the canonical key. This only ever comes from a real chain read.
- `NOT_COVERED`: no chain read happened. Either the court has no registry in the coverage manifest, or the citation is a vendor identifier (Westlaw/LEXIS), which is never a registry key. A real case may sit behind a NOT_COVERED citation.
- `AMBIGUOUS_JURISDICTION`: the citation could not be mapped to a single court registry (some reporter editions are genuinely split across courts). The `snippet` field shows the source context so you can locate it.
- `UNPARSEABLE`: the token could not be parsed as a citation at all. Also carries a `snippet`.

### The expanded-coverage caution

Jurisdiction mapping was proven end to end for the federal appellate registries (SCOTUS and the thirteen circuits). For every other court, coverage is newly expanded and citation formats are still being proven against real briefs. A `NOT_FOUND` outside the federal appellate set therefore carries `"confidence": "expanded-coverage"` and a `caution` string. Treat such a miss as a flag to verify the citation independently, never as proof of fabrication, and never advise deleting a citation on this signal alone. Pass the caution text through to your user.

## Verify a filed document

Anyone can verify that a filed document's receipt is anchored, for free, without uploading the document anywhere. You need two things: the exact filed bytes, and the registry number from the verification line printed on the filing. The line looks like:

```
Citation verifications: NVNM Chain (chain 1611) registry #4711 — example-firm--example-case
```

Hash the file locally, then look it up. The `registry` parameter accepts the bare number, `#number`, or the whole pasted line; the bare number avoids URL-encoding mistakes (`#` must be `%23` in a URL).

```
shasum -a 256 filed.pdf
curl -sS "https://nvnmcite.com/api/receipt/lookup?registry=4711&sha256=<64-hex-digest>"
```

The response: `found` (whether a receipt record exists for that hash in that registry), `registry` / `registry_id` / `registry_owner`, `versions[]` (each anchored version with its chain timestamp and the receipt JSON: document hash, chain id, block checked, normalizer version, court registries read, attesting wallet, and a status tally), and `proof.request`: the exact `eth_call` (method, `to`, `data`) to replay against any RPC for this network, so no trust in this server is required.

The hash binds exact bytes. If verification fails, first confirm you hashed the file as filed (one changed byte changes the SHA-256), and check the response's `note` field: it distinguishes a missing registry from a missing record.

## Inspect a transaction

```
curl -sS "https://nvnmcite.com/api/tx?hash=0x<64-hex>"
```

Decodes an NVNM Chain anchoring transaction into readable form: the function called with its plaintext arguments, the precompile events it emitted, `success`/`pending`, gas, and an explorer link. After a registry-creation transaction confirms, the `registry_id` field carries the chain-assigned id recovered from the AddRegistry event; the anchor workflow below depends on this. After an anchor transaction confirms, `record_id` carries the chain-assigned record id from the AddRecord event the same way.

## Anchor a filing receipt

This is the one workflow that writes to the chain, and it is deliberately not something this server can do alone: it returns unsigned transactions, and the filing party's own wallet signs them. The server never holds keys. Broadcasting costs gas (see `/api/status` for the token) and writes a public chain, so obtain explicit approval from your user before signing or broadcasting anything.

Receipts live in a per-firm-per-case registry owned by the filing party's wallet. The flow:

1. **Prepare.** POST the final document with the filer's details:

   ```
   curl -sS -X POST https://nvnmcite.com/api/receipt/prepare \
     -H "X-Filename: brief.pdf" \
     -H "X-Firm: Example Firm" \
     -H "X-Case: Example v. Example" \
     -H "X-Agent: 0x<the signing wallet address>" \
     --data-binary @brief.pdf
   ```

2. **First time for this matter: create the registry.** If no receipts registry for this firm and case exists under that wallet, the response includes a `setup` object with an unsigned `addRegistry` transaction (`{to, data, value}`) and a gas `probe`. Have the wallet sign and broadcast it, then poll `/api/tx?hash=...` until it confirms; the response's `registry_id` is the chain-assigned number for this registry.

3. **Put the verification line on the filing, then re-prepare.** The line (exact format above, with the assigned number) must be on the document before its bytes are hashed, because that line is how a future verifier discovers the registry. Add it, produce the final bytes, and POST `/api/receipt/prepare` again with the extra header `X-Registry-Id: <number>`. The response's `registry_line_found` field reports whether the line was detected in the document text (`id`, `name`, or `none`); `none` means a verifier will have nothing to go on.

4. **Anchor.** The re-prepare response includes the receipt itself (`receipt.json`: the document SHA-256, chain id, block checked, normalizer version, court registries read, attesting wallet, timestamp, and a non-identifying status tally; the cited cases are never part of it), the unsigned anchoring transaction in `tx`, and a `write_probe` gas estimate that doubles as a permission check. Have the wallet sign `tx` and broadcast it to the network RPC. Confirm with `/api/tx`. The `already_anchored` flag tells you if this exact document hash is already in the registry.

If the wallet has created more than one registry with the same derived name, the response is `{"ambiguous": true, "candidates": [...]}`; pick the number printed on this matter's filings and re-prepare with `X-Registry-Id`. To list a wallet's registries: `GET /api/receipt/registries?creator=0x...`.

## Privacy

Uploaded documents are parsed in memory and discarded with the response. They are never written to disk, never logged, and never put on chain; a receipt carries the document's hash and a status tally, never the list of cited cases. Drafting-time checks read the chain with `eth_call`, which leaves no on-chain trace. The access log records method, path, and status, with query strings stripped. When the operator enables aggregate telemetry (`/api/status` discloses it), it counts lookups by citation only, decoupled from documents and identities.

## Attribution

Case data comes from CourtListener bulk data, a Free Law Project service (courtlistener.com). Citation parsing builds on Free Law Project's eyecite, reporters-db, and courts-db.
