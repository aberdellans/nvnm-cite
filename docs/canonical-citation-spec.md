# cite-canonical/v1: Canonical US Case Citation Specification

Status: v1, locked at Phase 1. Changes require a version bump (cite-canonical/v2), never an edit.

This specification defines how nvnm-cite turns a US case citation as written in a document into the canonical plaintext key stored in an NVNM Chain registry. It is an open spec: a third party should be able to implement it and arrive at the same keys without using this project's code. The reference implementation is `nvnm_cite.normalizer` (its `CANONICAL_SPEC` constant exports the string `cite-canonical-v1`, which is also the on-chain `checksumAlgo` value for registry records).

The normalizer is part of the trust boundary. Every output object carries `normalizer_version`; receipts record it. Behavior is pinned by golden tests against eyecite 2.7.6, reporters-db 3.2.65, and courts-db 0.10.27.

## 1. The canonical form

```
<volume> <edition> <first-page>
```

One ASCII space (U+0020) between the three tokens, no leading or trailing whitespace. Examples:

| As written in a brief | Canonical key |
|---|---|
| `410 U.S. 113` | `410 U.S. 113` |
| `410 U. S. 113` | `410 U.S. 113` |
| `925 F. 3d 1339` | `925 F.3d 1339` |
| `181 L.Ed.2d 911` | `181 L. Ed. 2d 911` |
| `5 U.S. (1 Cranch) 137` | `5 U.S. 137` |

### 1.1 Volume

The volume number with leading zeros stripped when the token is all digits (`007` becomes `7`). Non-numeric volume tokens are preserved verbatim.

### 1.2 Edition

The edition token is the reporters-db **edition string**, exactly as it appears as an edition key in the reporters-db dataset: `F.3d` (not `F.` and not `F. 3d`), `S. Ct.`, `L. Ed. 2d`, `U.S.`, `So. 2d`. Editions are the right key because they are what actually appears both in citations as written and in CourtListener's citation table, so registry keys and corpus keys align by construction, with no mapping table in between.

Spacing and punctuation variants found in the wild (`F. 3d`, `S.Ct.`, `L.Ed.2d`, `U. S.`) normalize to the reporters-db edition string. In the reference implementation this is eyecite's `corrected_reporter()`.

### 1.3 First page (THE FIRST-PAGE RULE)

**Registry keys are first-page citations. Interior pages and pin cites are never keys.**

The page token is the first page of the case as printed in the reporter, with leading zeros stripped when all digits; non-numeric page tokens (rare star or roman pagination) are preserved verbatim. A citation like `Roe v. Wade, 410 U.S. 113, 116 (1973)` yields the key `410 U.S. 113`; the `116` is a pin cite, carried in output metadata but never part of the key.

This rule is load-bearing for verification: a fabricated citation whose page falls in the interior of some real case (for example `925 F.3d 1339`, an interior page of J.D. v. Azar, 925 F.3d 1291) does not collide with any first-page key and is honestly reported as not found.

A citation with no resolvable page (pending-publication forms such as `___ U.S. ___`) has no canonical key and is reported as unresolved, never guessed.

## 2. Text cleaning

Before extraction, the document text is cleaned with two operations (eyecite clean steps):

1. `all_whitespace`: every run of whitespace, including line breaks, collapses to a single space. This repairs line-break-mangled citations (`410\nU. S. 113`), the main recall killer in text extracted from PDFs.
2. `underscores`: strips the `__underlining__` markup found in some filed briefs.

Character spans reported by the normalizer index into the **cleaned** text.

## 3. Short forms inherit their antecedent

Short cites (`410 U.S. at 120`), `id.`, and `supra` citations do not contain a first page and cannot be keyed alone. They inherit the canonical key, registry, and case metadata of their antecedent full citation, resolved per eyecite's resolution semantics within the same document.

A short form whose antecedent cannot be resolved in the document is reported as **unresolved**, with its own occurrence in the output (implementations must not silently drop it; a dangling `id.` is still a citation the verifier must account for).

## 4. Jurisdiction mapping

Every canonical key belongs to a registry. Registry names are courts-db court IDs prefixed `us-`: `us-scotus`, `us-ca11`, `us-nysd`. Mapping rules, in order:

1. **SCOTUS editions.** If the edition is one of `U.S.`, `S. Ct.`, `L. Ed.`, `L. Ed. 2d`, the registry is `us-scotus`, regardless of any parenthetical. (These three reporter families publish only Supreme Court decisions.)
2. **Court parenthetical.** Otherwise, the court identified from the citation's court parenthetical (`(11th Cir. 2019)` -> courts-db ID `ca11`), validated against courts-db, gives `us-` + ID.
3. **Never guess.** Anything else is **AMBIGUOUS_JURISDICTION**: notably `F.`/`F.2d`/`F.3d`/`F.4th`/`F. App'x`/`F. Supp.` cites with no recognizable court parenthetical (they span every circuit or district), state reporters with no parenthetical, and early nominative reporters cited without their U.S.-series volume (`1 Cranch 137` alone is ambiguous because Cranch also reported for the D.C. circuit; `5 U.S. (1 Cranch) 137` is `us-scotus` via rule 1). The canonical key is still computed when possible; only the registry is withheld.

A citation that parses and maps to a court whose registry is not on chain is a coverage question for the verifier (NOT_COVERED), not a mapping failure.

## 5. Scope: case citations only

Statute citations (`42 U.S.C. § 1983`), regulation, and journal citations (`103 Harv. L. Rev. 405`) are out of scope, as are short forms that resolve to them. Registries hold case citations only.

## 6. Parallel citations

A single decision may be citable in several reporters (`558 U.S. 310`, `130 S. Ct. 876`, `175 L. Ed. 2d 753`). Each parallel citation is a **distinct registry record** under its own canonical key; the records share the same CourtListener cluster ID in their metadata. Receipts group per-citation results by cluster ID. Nothing in this spec merges parallel citations into one key.

## 7. Versioning

- The spec version (`cite-canonical-v1`) is the on-chain `checksumAlgo` for registry records: a chain reader can tell exactly which keying rules produced a record.
- The reference implementation exports `NORMALIZER_VERSION` (semver). Receipts record the normalizer version that produced them.
- Any change to canonical-form, cleaning, inheritance, or mapping rules is a new spec version and a new `checksumAlgo` string. Records written under v1 are never rewritten to a new version; versions coexist as separate records.

## 8. Reference implementation pinning

The golden suite under `tests/golden/normalizer/` is the executable form of this spec. Where eyecite behavior and this spec disagree, the spec wins and the reference implementation must compensate (as it already does for orphan short forms, which eyecite drops and this spec requires reported).
