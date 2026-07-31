# nvnm-cite On-Chain Record Schema v1

Status: v1, locked at Phase 1 task 1.5 (2026-06-11), informed by the Phase 0 experiment matrix. After this point, changes require a version bump (new checksumAlgo / schema string), never an edit. Records written under v1 are never rewritten; versions coexist.

This document defines exactly what nvnm-cite writes into the NVNM Chain anchoring precompile (`0x0000000000000000000000000000000000000A00`) for its two record types: per-case citation records and filing receipts.

## 1. Chain context

`addRecord` takes a 10-field tuple of strings (plus two uint64 and a bool). The writer supplies six fields; the chain manages the rest (measured in Phase 0: the chain overwrites them regardless of submitted values):

| Field | Writer submits | Authority |
|---|---|---|
| `registry` | registry name | writer |
| `uri` | per record type, below | writer |
| `checksum` | per record type, below | writer |
| `checksumAlgo` | per record type, below | writer |
| `metadata` | per record type, below | writer |
| `status` | `Active` | writer |
| `timestamp` | empty string | chain (Go time string) |
| `recordId` | `0` | chain (numbers from 1) |
| `index` | `0` | chain (version counter from 1) |
| `isLatest` | `false` | chain |

Measured constraints every write must pre-validate (DECISIONS 2026-06-10, experiment (b)):

- `checksum` <= 64 bytes; `uri` <= 2048 bytes; `metadata` <= 2048 bytes.
- `uri`, `checksumAlgo`, `metadata` are required non-empty, and `"{}"` counts as empty. (`metadata` must therefore always carry at least one key.)
- Duplicate (registry, checksum) submissions create new VERSIONS (index bumps, isLatest moves); they never revert. Idempotency is the writer's job (checkpoint DB), not the chain's.

The PLAINTEXT invariant: citation identifiers are stored and checked in plaintext, never hashed. The only hash anywhere in this schema is the SHA-256 of the checked document inside a receipt record.

## 2. Registry naming and creation

| Registry | Contents |
|---|---|
| `us-<courts-db id>` (`us-scotus`, `us-ca11`) | per-case citation records for that court |
| `<firm>--<case>` (filer-chosen, e.g. `inveniam--mata-v-avianca`) | filing receipts for one (firm, case), owned by the filing party's wallet |

Registry names are unique on chain (experiment (c)); creation is idempotent via the estimate-probe. `addRegistry(name, description, metadata)` values, fixed here so the loader/anchorer do not improvise:

- Court registry description: `Canonical US case citations for <court name> (courts-db: <id>). Existence registry: a record means this citation string denotes a published decision. nvnm-cite.`
- Court registry metadata (compact JSON, rules of section 3.2): `{"court":"<courts-db id>","schema":"nvnm-cite-record/v1","source":"CourtListener bulk data, Free Law Project (courtlistener.com)","spec":"cite-canonical-v1"}`
- Receipt registry (per-firm-per-case, re-locked at Phase 4 task 4.1; supersedes the global `receipts-v1`): name = `<firm-slug>--<case-slug>`, filer-chosen, lowercase `[a-z0-9-]`, `--` separating firm from case, <= 64 B (`receipts/schema.py::receipt_registry_name`). Description: `nvnm-cite filing receipts for <firm> — <case>. SHA-256-keyed records of citation checks against the us-* registries; owned by the filing party. nvnm-cite.` Metadata: `{"case":"<case>","firm":"<firm>","kind":"receipts","schema":"nvnm-cite-receipt/v1","spec":"cite-canonical-v1"}`. The creating wallet becomes admin — self-sovereign writes, no global gatekeeper (invariant 4).

CourtListener / Free Law Project attribution lives in the registry metadata (here), README, and demos.

## 3. Record type 1: per-case citation record

One record per (court registry, canonical citation). Parallel citations of the same decision are distinct records (in `us-scotus`: one each under `558 U.S. 310`, `130 S. Ct. 876`, `175 L. Ed. 2d 753`) sharing the same `cluster` in metadata.

| Field | Value |
|---|---|
| `registry` | `us-<courts-db id>` |
| `checksum` | the canonical citation key in PLAINTEXT per cite-canonical/v1, e.g. `410 U.S. 113`. First-page keys only; max canonical key length is far below the 64 B cap. |
| `checksumAlgo` | `cite-canonical-v1` |
| `uri` | CourtListener cluster URL: `https://www.courtlistener.com/opinion/<cluster_id>/<slug>/` with the slug from the bulk-data cluster row. If the slug is missing or empty in the source data, the deterministic fallback is the API form `https://www.courtlistener.com/api/rest/v4/clusters/<cluster_id>/`. |
| `metadata` | compact JSON, section 3.1 |
| `status` | `Active` |

### 3.1 Metadata payload

Single-case form (the normal case):

```json
{"cluster":108713,"name":"Roe v. Wade","year":1973}
```

- `cluster`: CourtListener cluster id, JSON integer.
- `name`: case name as given by CourtListener (`case_name`, falling back to `case_name_short`), string.
- `year`: year of `date_filed`, JSON integer.

Collision form, used ONLY when the Phase 2 census finds distinct decisions sharing one (registry, canonical key), e.g. two short orders on one reporter page:

```json
{"cases":[{"cluster":111,"name":"A v. B","year":1990},{"cluster":222,"name":"C v. D","year":1990}]}
```

A reader distinguishes the forms by the presence of the `cases` key. The verifier's `name_check` compares against `name` or every `cases[].name`.

### 3.2 JSON serialization rules (all metadata in this schema)

- UTF-8, `ensure_ascii=false` (case names stay human-readable on the explorer).
- Keys sorted lexicographically; separators `,` and `:` with no whitespace.
- Byte budgets measured on the UTF-8 encoding.

### 3.3 Cap handling (metadata > 2048 bytes)

Deterministic truncation, applied in order until the serialized form fits:

1. Single-case form: truncate `name` at a UTF-8 character boundary and append `…` (U+2026).
2. Collision form: truncate each `cases[].name` to at most 256 bytes (UTF-8 boundary + `…`); if still over, drop trailing `cases` entries and add `"omitted":<count>` as a top-level key.

`uri` is never truncated: a write whose uri exceeds 2048 bytes is a loader error, halted and logged, never silently shortened.

## 4. Record type 2: filing receipt

> **RE-LOCKED 2026-06-15 (Phase 4 task 4.1)**, superseding the original global-`receipts-v1` model per DECISIONS 2026-06-13 items 2/2b/3. A receipt is MINIMAL and NON-ENUMERATING, and lives in a per-firm-per-case registry owned by the filing party. Reference implementation: `src/nvnm_cite/receipts/schema.py`.

A receipt record anchors that one exact document was citation-checked — by whom, when, against which court registries, with what tally — and NOTHING about which cases it cites.

| Field | Value |
|---|---|
| `registry` | the filing party's `<firm>--<case>` receipt registry (section 2) |
| `checksum` | lowercase hex SHA-256 of the checked document's bytes. Exactly 64 bytes. |
| `checksumAlgo` | `sha256` |
| `uri` | `urn:nvnm-cite:receipt:v1` (fixed; see note) |
| `metadata` | the receipt object (`nvnm-cite-receipt/v1`), serialized per 3.2. ~480–700 B, always under the 2048 B cap, so there is NO chunking (task 4.3 dropped). |
| `status` | `Active` |

### 4.1 Receipt object (`nvnm-cite-receipt/v1`)

```json
{"agent":{"address":"0x…"},"chain_id":787111,"checked_at_block":1670739,"document_sha256":"<64 hex>","normalizer_version":"1.0.0","registries":[{"head_block":1670739,"id":737,"name":"us-scotus"},{"head_block":1670739,"id":738,"name":"us-ca11"}],"schema":"nvnm-cite-receipt/v1","summary":{"ambiguous":1,"checked":6,"name_mismatches":1,"not_covered":1,"not_found":1,"unparseable":1,"verified":2},"timestamp":"2026-06-15T12:00:00Z"}
```

- `agent.address`: the attesting wallet. Identity IS the wallet; there is no `kya_id`.
- `registries`: the court registries READ during the check, each `{id, name, head_block}`.
- `summary`: a non-identifying status tally — `checked` (distinct citations) + the five status counts + `name_mismatches`. NO per-case list: the document SHA-256 binds the exact file, so every verdict is reproducible by re-running the check pinned to `checked_at_block`, without publishing the brief's authorities on a permanent public chain.
- Serialization per 3.2 (UTF-8, sorted keys, no whitespace).

### 4.2 Discovery and verification

Discovery is the registry LINK printed on the filing (since the v1.2.0 amendment, section 7: "Citation verifications: NVNM Chain (chain `<chain_id>`) registry #`<id>` — `<firm>--<case>`"), a stable pointer fixed when the matter's registry is created — never the receipt/tx, which is circular (the receipt is keyed by the final document hash, so citing it would change the bytes). A verifier uses the #id, hashes the file locally, does a keyed `records(registry_id, sha256)` read, and re-runs the check pinned to `checked_at_block`.

Note on the receipt `uri`: the chain requires non-empty, and improvising at anchor time is forbidden, so v1 fixes a URN rather than a URL. Rationale: the repo is private during the pilot and the project controls no public web host, so any URL written today would dangle for a third-party reader; a URN is honest about being an identifier, not a dereference. When the spec is published at mainnet cutover (task 6.4 preconditions), receipts can move to the published URL under a schema version bump.

## 5. Versions, corrections, revocation

- The chain versions duplicates: re-anchoring the same (registry, checksum) bumps `index` and moves `isLatest` (experiment (a)). Keyed reads return the latest version.
- Correction policy is supersede-by-new-version: write a corrected record under the same key. The superseding record's metadata MAY carry `"supersedes_reason":"<short string>"` as an additional top-level key.
- `status` is always written as `Active` in v1. Revocation semantics through `updateRecordStatus` are out of scope (the method is absent from the deployed testnet binary); a revocation, should one ever be needed, is a superseding version whose metadata carries `"revoked":true` plus `supersedes_reason`.

## 6. Writer conformance checklist

Before any `addRecord` submission a conforming writer MUST:

1. Produce `checksum` only via cite-canonical/v1 (court records) or as a lowercase hex SHA-256 (receipts).
2. Verify all three byte caps on the UTF-8 encoding; apply 3.3 truncation to metadata only; halt on oversize uri or checksum.
3. Verify `uri`, `checksumAlgo`, `metadata` are non-empty and metadata is not `{}`.
4. Submit `timestamp=""`, `recordId=0`, `index=0`, `isLatest=false` and treat the chain's values as authoritative on read.
5. Treat duplicate-key submission as versioning, and rely on its own checkpoint state for idempotency, never on the chain.

## 7. Anchoring v1.2.0 amendment (2026-07-31; additive — no schema bump)

The 2026-07-30 chain upgrade (anchoring module v1.2.0) made registry names
NON-UNIQUE and moved every chain call — reads and writes — to the numeric
`registryId`. Consequences for this document, none of which change the
locked field layouts above:

- **The canonical reference to any registry is its numeric #id.** Names
  remain the human-readable convention of sections 2 and 4, but nothing on
  chain enforces their uniqueness and no chain call accepts them as keys.
  For the court registries the published name→id map is the pinned,
  creator-verified manifest `src/nvnm_cite/chain/registry_manifest_<network>.json`
  (schema `nvnm-cite-registry-manifest/v1`; regenerate with
  `scripts/build_registry_manifest.py`, audit with `nvnm-cite manifest-verify`).
  Mainnet: 2,114 registries, ids 69–2182 (`us-scotus` = 82).
- **The discovery line on a filing carries the #id.** Locked format
  (`receipts/anchor.py::registry_line`):
  `Citation verifications: NVNM Chain (chain <chain_id>) registry #<id> — <firm>--<case>`.
  A verifier uses the #id; the name is context only. A NEW registry's id is
  assigned by the chain at `addRegistry` confirmation and recovered from the
  AddRegistry event in the transaction receipt, so registry setup precedes
  the final export of the filing.
- **Receipt `registries` table under wide coverage.** With coverage at the
  full manifest, `registries` records the court registries actually READ
  for the document (the distinct chain-resolved citations), never the whole
  coverage set. If an unusually many-court document would push the receipt
  over the 2048 B metadata cap, trailing entries (sorted by id) are dropped
  deterministically and counted in the ADDITIVE OPTIONAL top-level field
  `registries_omitted` (absent when 0). Hash, tally, and every other field
  are untouched; readers that ignore unknown fields are unaffected.
- Section 5's remark that `updateRecordStatus` is "absent from the deployed
  testnet binary" was corrected in DECISIONS 2026-07-07: the method was
  always deployed, id-keyed. The v1 correction policy stands.
