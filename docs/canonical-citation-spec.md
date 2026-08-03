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

**Fallback resolution (added 2026-08-02, normalizer 1.2.0).** eyecite resolves short cites by antecedent case name and strands the rest (measured on real merits briefs: `NIFLA, 138 S. Ct. at 2371` stays orphaned when the full cite spelled the name out). A stranded short cite still names its volume and edition, and a pin page sits at or past its opinion's first page, so it is attached to the full citation in the same document with the same volume and edition whose first page is the **largest not exceeding the pin page** (`539 U.S. at 331` with Gratz at 244 and Grutter at 306 in the document resolves to Grutter). Equal first pages are the same canonical key, so the choice cannot be wrong; with no qualifying candidate the short stays unresolved rather than guessed.

A short form whose antecedent cannot be resolved in the document is reported as **unresolved**, with its own occurrence in the output (implementations must not silently drop it; a dangling `id.` is still a citation the verifier must account for).

## 4. Jurisdiction mapping (amended 2026-08-01 normalizer 1.1.0, 2026-08-02 normalizer 1.2.0; adjudications in DECISIONS)

Every canonical key belongs to a registry. Registry names are courts-db court IDs prefixed `us-`: `us-scotus`, `us-ca11`, `us-nysd`. An explicit court signal always outranks a reporter-derived default. Mapping rules, in order:

1. **SCOTUS editions.** If the edition is one of `U.S.`, `S. Ct.`, `L. Ed.`, `L. Ed. 2d`, the registry is `us-scotus`, regardless of any parenthetical. (These three reporter families publish only Supreme Court decisions.)
2. **Court metadata, corroborated.** The court identified by the citation parser (eyecite metadata, already a courts-db ID) gives `us-` + ID — but when that court CONTRADICTS the citation's own reporter default (rule 5), it must be corroborated by the parenthetical immediately adjacent to the cite, else the reporter default wins. (Measured: eyecite's forward parenthetical scan can overreach across a neighboring citation in a string cite and attach the wrong court.)
3. **Federal-circuit parenthetical whitelist.** `1st` through `11th` (including the Bluebook ordinals `2d`/`3d`), `D.C.`, and `Fed.`, followed by `Cir.`, map to `ca1`–`ca11`, `cadc`, `cafc` even where an underlying library misses an ordinal variant (measured: eyecite 2.7.6 resolves `3rd Cir.` but not the Bluebook-standard `3d Cir.`; an exact whitelist is not a guess).
4. **General court parenthetical.** The adjacent parenthetical's content, matched by exact longest prefix against courts-db `citation_string`s (measured globally unique: 1,959 strings, each naming exactly one court), gives the court. Appellate-Division forms (`App. Div.`, `1st Dep't` … `4th Dep't`) are STATE-GATED on the reporter — both New York and New Jersey have an Appellate Division, so the bare form resolves only jointly with the reporter family (N.Y. families → `us-nyappdiv`, N.J. families → `us-njsuperctappdiv`); with any other reporter it is refused.
5. **Reporter-edition inference.** The corpus-derived table `src/nvnm_cite/normalizer/reporter_registries.json` (generated by `scripts/build_reporter_map.py`, reviewed and committed like the registry manifest) maps an edition to a registry when one registry holds ≥ 99.5% of that edition's records across the 11.9M-record mainnet corpus (minimum 100 records; exactly one reporters-db reporter carries the edition; vendor identifiers excluded; curated adjudications applied — e.g. `M.J.` stays out because it genuinely spans five military courts). This is what makes bare `212 A.D.2d 331`, `248 N.Y. 339`, `65 T.C. 346`, or `T.C. Memo. 1976-300` resolvable with no parenthetical at all.
6. **Never guess.** Anything else is **AMBIGUOUS_JURISDICTION**: notably `F.`/`F.2d`/`F.3d`/`F.4th`/`F. App'x`/`F. Supp.` cites with no recognizable court parenthetical (they span every circuit or district), regional reporters (`S.W.2d`, `N.E.2d`, …) with no parenthetical, and editions the corpus itself splits across courts (`N.Y.2d`, `Misc. 2d`, `M.J.`). The canonical key is still computed when possible; only the registry is withheld.

**Vendor identifiers.** Westlaw (`2019 WL 1439098`) and the generic/federal LEXIS families hold zero records in the registry key space, so they are reported as a distinct **vendor** disposition — outside coverage, no chain read — even when a court parenthetical is present (a lookup could only manufacture a false "not found" for a possibly-real case). Court-specific LEXIS editions that ARE corpus keys (92 editions, 3.28M parallel records) behave as ordinary reporters under rules 2–5.

**State-consistency gate (added 2026-08-02, normalizer 1.2.0).** A court claimed by rule 2 or matched by rule 4 whose state contradicts the reporter's own state set (reporters-db `mlz_jurisdiction`, e.g. `Misc.` is a N.Y./Fla. reporter) is refused — measured trigger: eyecite claims the D.C. court `supctdc` from `(Sup. Ct. 2004)` after a N.Y. `Misc. 3d` cite. The gate is inert when either side is unknown (federal and national reporters carry no state set; federal, foreign, and territorial-era courts carry no gated location), so it can only remove wrong answers, never produce one. Pin-cite material ahead of a corroborating parenthetical includes star pagination (`, *4 (Sup. Ct. 2004)`).

A citation that parses and maps to a court whose registry is not on chain is a coverage question for the verifier (NOT_COVERED), not a mapping failure.

## 5. Scope: case citations only

Statute citations (`42 U.S.C. § 1983`), regulation, and journal citations (`103 Harv. L. Rev. 405`) are out of scope, as are short forms that resolve to them. Registries hold case citations only.

Law-section fragments the parser surfaces as unknown citations (`§2000d` severed from its title by a PDF line break; measured throughout real filings) carry a distinct **out_of_scope** disposition as of normalizer 1.2.0: accounted for in the output, never presented as unparseable case citations (added 2026-08-02).

## 6. Parallel citations

A single decision may be citable in several reporters (`558 U.S. 310`, `130 S. Ct. 876`, `175 L. Ed. 2d 753`). Each parallel citation is a **distinct registry record** under its own canonical key; the records share the same CourtListener cluster ID in their metadata. Receipts group per-citation results by cluster ID. Nothing in this spec merges parallel citations into one key.

## 7. Versioning

- The spec version (`cite-canonical-v1`) is the on-chain `checksumAlgo` for registry records: a chain reader can tell exactly which keying rules produced a record.
- The reference implementation exports `NORMALIZER_VERSION` (semver). Receipts record the normalizer version that produced them.
- Any change to canonical-form, cleaning, or inheritance rules — anything that changes what KEY a citation produces — is a new spec version and a new `checksumAlgo` string. Records written under v1 are never rewritten to a new version; versions coexist as separate records.
- Jurisdiction-MAPPING changes (section 4) never touch keys, so they bump `NORMALIZER_VERSION` only, not `checksumAlgo` (clarified 2026-08-01 with the 1.1.0 mapping expansion; the original text lumped mapping in with keying). Receipts record the normalizer version, so a mapping-era difference is always attributable.

## 8. Reference implementation pinning

The golden suite under `tests/golden/normalizer/` is the executable form of this spec. Where eyecite behavior and this spec disagree, the spec wins and the reference implementation must compensate (as it already does for orphan short forms, which eyecite drops and this spec requires reported).
