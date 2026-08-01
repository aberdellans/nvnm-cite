"""Generate vectors.json for the normalizer golden suite (task 1.6).

Expectations are hand-derived from docs/canonical-citation-spec.md via the
static tables below; this script never imports nvnm_cite, so the suite stays
an independent statement of intended behavior. Where a spec-derived
expectation disagreed with measured eyecite behavior, the resolution was
adjudicated by hand and recorded in DECISIONS.md, then encoded here.

Run: python tests/golden/normalizer/generate_vectors.py
"""

from __future__ import annotations

import json
from pathlib import Path

OK = "ok"
AMB = "ambiguous_jurisdiction"
VEN = "vendor"
UNR = "unresolved"

VECTORS: list[dict] = []


def vec(category: str, text: str, expect: list[dict]) -> None:
    VECTORS.append(
        {
            "id": f"{category}-{sum(v['category'] == category for v in VECTORS) + 1:03d}",
            "category": category,
            "text": text,
            "expect": expect,
        }
    )


def full(as_written: str, canonical: str | None, registry: str | None,
         disposition: str = OK, kind: str = "full") -> dict:
    return {
        "as_written": as_written,
        "canonical": canonical,
        "registry": registry,
        "disposition": disposition,
        "kind": kind,
    }


# --- 1. SCOTUS editions: every reporter family x spelling variants ---------
SCOTUS_BASES = [(410, 113), (347, 483), (558, 310), (565, 400), (576, 644)]
SCOTUS_SPELLINGS = [
    ("U.S.", "U.S."),
    ("U. S.", "U.S."),
    ("S. Ct.", "S. Ct."),
    ("S.Ct.", "S. Ct."),
    ("L. Ed. 2d", "L. Ed. 2d"),
    ("L.Ed.2d", "L. Ed. 2d"),
    ("L. Ed.", "L. Ed."),
    ("L.Ed.", "L. Ed."),
]
for vol, page in SCOTUS_BASES:
    for written, edition in SCOTUS_SPELLINGS:
        aw = f"{vol} {written} {page}"
        vec(
            "scotus_editions",
            f"See Alpha v. Beta, {aw} (1990).",
            [full(aw, f"{vol} {edition} {page}", "us-scotus")],
        )

# --- 2. Circuit parentheticals: federal appellate reporters x circuits -----
CIRCUITS = [
    ("1st Cir.", "us-ca1"), ("2d Cir.", "us-ca2"), ("3d Cir.", "us-ca3"),
    ("4th Cir.", "us-ca4"), ("5th Cir.", "us-ca5"), ("6th Cir.", "us-ca6"),
    ("7th Cir.", "us-ca7"), ("8th Cir.", "us-ca8"), ("9th Cir.", "us-ca9"),
    ("10th Cir.", "us-ca10"), ("11th Cir.", "us-ca11"), ("D.C. Cir.", "us-cadc"),
    ("Fed. Cir.", "us-cafc"),
]
FED_REPORTERS = [("F.2d", 800), ("F.3d", 925), ("F.4th", 50), ("F. App'x", 789)]
for rep, vol in FED_REPORTERS:
    for paren, registry in CIRCUITS:
        aw = f"{vol} {rep} 1339"
        vec(
            "circuit_parentheticals",
            f"Gamma v. Delta, {aw}, 1345 ({paren} 2019).",
            [full(aw, aw, registry)],
        )

# spacing variants with a parenthetical
for written, edition in [("F. 3d", "F.3d"), ("F. 4th", "F.4th"), ("F. 2d", "F.2d")]:
    aw = f"925 {written} 1339"
    vec(
        "circuit_parentheticals",
        f"Gamma v. Delta, {aw} (11th Cir. 2019).",
        [full(aw, f"925 {edition} 1339", "us-ca11")],
    )

# no-pin variant across every circuit
for paren, registry in CIRCUITS:
    vec(
        "circuit_parentheticals",
        f"Kappa v. Lambda, 412 F.3d 88 ({paren} 2005).",
        [full("412 F.3d 88", "412 F.3d 88", registry)],
    )

# --- 3. Federal reporters, no parenthetical: ambiguous, canonical kept -----
for rep, vol, page in [
    ("F.", 300, 57), ("F.2d", 800, 100), ("F.3d", 538, 1000), ("F.4th", 50, 700),
    ("F. App'x", 789, 12), ("F. Supp.", 100, 9), ("F. Supp. 2d", 200, 19),
    ("F. Supp. 3d", 300, 29),
]:
    aw = f"{vol} {rep} {page}"
    vec(
        "federal_no_parenthetical",
        f"Epsilon v. Zeta, {aw}.",
        [full(aw, aw, None, AMB)],
    )
# with a pin but still no court: first-page key survives, still ambiguous
for rep, vol, page, pin in [
    ("F.3d", 538, 1000, 1004), ("F.2d", 800, 100, 105),
    ("F.4th", 50, 700, 702), ("F. Supp. 2d", 200, 19, 25),
]:
    aw = f"{vol} {rep} {page}"
    vec(
        "federal_no_parenthetical",
        f"Epsilon v. Zeta, {aw}, {pin} (2010).",
        [full(aw, aw, None, AMB)],
    )

# --- 4. District parentheticals -------------------------------------------
DISTRICTS = [
    ("S.D.N.Y.", "us-nysd"), ("E.D.N.Y.", "us-nyed"),
    ("N.D. Ga.", "us-gand"), ("S.D. Fla.", "us-flsd"),
    ("N.D. Cal.", "us-cand"), ("D. Mass.", "us-mad"),
    ("S.D. Tex.", "us-txsd"), ("D.N.J.", "us-njd"),
]
for rep, vol in [("F. Supp.", 100), ("F. Supp. 2d", 200), ("F. Supp. 3d", 300)]:
    for paren, registry in DISTRICTS:
        aw = f"{vol} {rep} 99"
        vec(
            "district_parentheticals",
            f"Eta v. Theta, {aw} ({paren} 2015).",
            [full(aw, aw, registry)],
        )

# --- 5. Line-break mangled --------------------------------------------------
MANGLED = [
    ("410\nU.S. 113", "410 U.S. 113", "410 U.S. 113", "us-scotus"),
    ("410 U.S.\n113", "410 U.S. 113", "410 U.S. 113", "us-scotus"),
    ("410\nU. S.\n113", "410 U. S. 113", "410 U.S. 113", "us-scotus"),
    ("132\nS. Ct. 945", "132 S. Ct. 945", "132 S. Ct. 945", "us-scotus"),
    ("181 L. Ed.\n2d 911", "181 L. Ed. 2d 911", "181 L. Ed. 2d 911", "us-scotus"),
]
for written, aw_clean, canonical, registry in MANGLED:
    vec(
        "line_break_mangled",
        f"See Iota v. Kappa, {written} (1990), on point.",
        [full(aw_clean, canonical, registry)],
    )
for written, aw_clean, canonical in [
    ("925 F.\n3d 1339", "925 F. 3d 1339", "925 F.3d 1339"),
    ("925\nF.3d\n1339", "925 F.3d 1339", "925 F.3d 1339"),
]:
    vec(
        "line_break_mangled",
        f"Lambda v. Mu, {written} (11th Cir. 2019).",
        [full(aw_clean, canonical, "us-ca11")],
    )
# breaks in the case name and inside the parenthetical
vec(
    "line_break_mangled",
    "Varghese v.\nChina S. Airlines Co., 925 F.3d 1339 (11th\nCir. 2019).",
    [full("925 F.3d 1339", "925 F.3d 1339", "us-ca11")],
)
vec(
    "line_break_mangled",
    "Roe v.\nWade, 410 U.S. 113, 116\n(1973), held otherwise.",
    [full("410 U.S. 113", "410 U.S. 113", "us-scotus")],
)
vec(
    "line_break_mangled",
    "See Eta v. Theta, 200 F. Supp.\n2d 19 (S.D.N.Y. 2002).",
    [full("200 F. Supp. 2d 19", "200 F. Supp. 2d 19", "us-nysd")],
)

# --- 6. Short-form chains ----------------------------------------------------
vec(
    "short_form_chains",
    "Roe v. Wade, 410 U.S. 113, 116 (1973), controls. Roe, 410 U.S. at 120. Id. at 121.",
    [
        full("410 U.S. 113", "410 U.S. 113", "us-scotus"),
        full("410 U.S. at 120", "410 U.S. 113", "us-scotus", OK, "short"),
        full("Id.", "410 U.S. 113", "us-scotus", OK, "id"),
    ],
)
vec(
    "short_form_chains",
    "Varghese v. China S. Airlines Co., 925 F.3d 1339 (11th Cir. 2019). Varghese, 925 F.3d at 1345.",
    [
        full("925 F.3d 1339", "925 F.3d 1339", "us-ca11"),
        full("925 F.3d at 1345", "925 F.3d 1339", "us-ca11", OK, "short"),
    ],
)
vec(
    "short_form_chains",
    "Roe v. Wade, 410 U.S. 113 (1973). Roe, supra, at 120.",
    [
        full("410 U.S. 113", "410 U.S. 113", "us-scotus"),
        full("supra,", "410 U.S. 113", "us-scotus", OK, "supra"),
    ],
)
vec(
    "short_form_chains",
    "Smith v. Doe, 538 F.3d 1000 (9th Cir. 2008). Id. at 1005. Id.",
    [
        full("538 F.3d 1000", "538 F.3d 1000", "us-ca9"),
        full("Id.", "538 F.3d 1000", "us-ca9", OK, "id"),
        full("Id.", "538 F.3d 1000", "us-ca9", OK, "id"),
    ],
)
# interleaved: the short cite re-anchors by volume/reporter
vec(
    "short_form_chains",
    "Brown v. Board, 347 U.S. 483 (1954). Roe v. Wade, 410 U.S. 113 (1973). Brown, 347 U.S. at 490.",
    [
        full("347 U.S. 483", "347 U.S. 483", "us-scotus"),
        full("410 U.S. 113", "410 U.S. 113", "us-scotus"),
        full("347 U.S. at 490", "347 U.S. 483", "us-scotus", OK, "short"),
    ],
)

# interleaved chains with id. retargeting and a supra with pin
vec(
    "short_form_chains",
    "Roe v. Wade, 410 U.S. 113 (1973). Id. at 116. Brown v. Board, 347 U.S. 483 (1954). Id. at 490.",
    [
        full("410 U.S. 113", "410 U.S. 113", "us-scotus"),
        full("Id.", "410 U.S. 113", "us-scotus", OK, "id"),
        full("347 U.S. 483", "347 U.S. 483", "us-scotus"),
        full("Id.", "347 U.S. 483", "us-scotus", OK, "id"),
    ],
)
vec(
    "short_form_chains",
    "Varghese v. China S. Airlines Co., 925 F.3d 1339 (11th Cir. 2019), guides. Varghese, supra, at 1345.",
    [
        full("925 F.3d 1339", "925 F.3d 1339", "us-ca11"),
        full("supra,", "925 F.3d 1339", "us-ca11", OK, "supra"),
    ],
)
vec(
    "short_form_chains",
    "Smith v. Doe, 538 F.3d 1000 (9th Cir. 2008). Smith, 538 F.3d at 1003. Id.",
    [
        full("538 F.3d 1000", "538 F.3d 1000", "us-ca9"),
        full("538 F.3d at 1003", "538 F.3d 1000", "us-ca9", OK, "short"),
        full("Id.", "538 F.3d 1000", "us-ca9", OK, "id"),
    ],
)

# --- 7. Orphan short forms ----------------------------------------------------
vec("orphans", "Id. at 5, as previously noted.",
    [full("Id.", None, None, UNR, "id")])
vec("orphans", "See 410 U.S. at 120 for the discussion.",
    [full("410 U.S. at 120", None, None, UNR, "short")])
vec("orphans", "Nu, supra, at 10, settles it.",
    [full("supra,", None, None, UNR, "supra")])
vec("orphans", "925 F.3d at 1345 is the page cited.",
    [full("925 F.3d at 1345", None, None, UNR, "short")])
vec(
    "orphans",
    "The brief opens with Id. at 3, then cites Roe v. Wade, 410 U.S. 113 (1973).",
    [
        full("Id.", None, None, UNR, "id"),
        full("410 U.S. 113", "410 U.S. 113", "us-scotus"),
    ],
)

# --- 8. Parallel citations -----------------------------------------------------
vec(
    "parallel_citations",
    "Citizens United v. FEC, 558 U.S. 310, 130 S. Ct. 876, 175 L. Ed. 2d 753 (2010).",
    [
        full("558 U.S. 310", "558 U.S. 310", "us-scotus"),
        full("130 S. Ct. 876", "130 S. Ct. 876", "us-scotus"),
        full("175 L. Ed. 2d 753", "175 L. Ed. 2d 753", "us-scotus"),
    ],
)
vec(
    "parallel_citations",
    "Milkovich v. Lorain Journal Co., 494 U.S. 472, 110 S.Ct. 1249, 108 L.Ed.2d 400 (1990).",
    [
        full("494 U.S. 472", "494 U.S. 472", "us-scotus"),
        full("110 S.Ct. 1249", "110 S. Ct. 1249", "us-scotus"),
        full("108 L.Ed.2d 400", "108 L. Ed. 2d 400", "us-scotus"),
    ],
)
vec(
    "parallel_citations",
    "New York Times Co. v. Sullivan, 376 U.S. 254, 84 S. Ct. 710 (1964).",
    [
        full("376 U.S. 254", "376 U.S. 254", "us-scotus"),
        full("84 S. Ct. 710", "84 S. Ct. 710", "us-scotus"),
    ],
)
vec(
    "parallel_citations",
    "Gertz v. Robert Welch, Inc., 418 U.S. 323, 339-40, 94 S. Ct. 2997, 41 L. Ed. 2d 789 (1974).",
    [
        full("418 U.S. 323", "418 U.S. 323", "us-scotus"),
        full("94 S. Ct. 2997", "94 S. Ct. 2997", "us-scotus"),
        full("41 L. Ed. 2d 789", "41 L. Ed. 2d 789", "us-scotus"),
    ],
)

# --- 9. Early SCOTUS ------------------------------------------------------------
for written, canonical in [
    ("5 U.S. (1 Cranch) 137", "5 U.S. 137"),
    ("17 U.S. (4 Wheat.) 316", "17 U.S. 316"),
    ("60 U.S. (19 How.) 393", "60 U.S. 393"),
    ("2 U.S. (2 Dall.) 419", "2 U.S. 419"),
    ("33 U.S. (8 Pet.) 591", "33 U.S. 591"),
]:
    vec(
        "early_scotus",
        f"Omicron v. Pi, {written} (1850).",
        [full(written, canonical, "us-scotus")],
    )

# --- 10. State reporters ----------------------------------------------------------
STATE_WITH_PAREN = [
    ("123 So. 2d 456", "Fla. 1960", "us-fla"),
    ("456 P.2d 789", "Cal. 1969", "us-cal"),
    ("250 N.E.2d 200", "N.Y. 1969", "us-ny"),
    ("300 S.W.2d 100", "Tex. 1957", "us-tex"),
    ("150 A.2d 50", "Pa. 1959", "us-pa"),
    ("88 So. 3d 90", "Fla. 2012", "us-fla"),
    ("710 N.W.2d 44", "Minn. 2006", "us-minn"),
    ("950 P.3d 11", "Cal. 2024", "us-cal"),
]
for aw, paren, registry in STATE_WITH_PAREN:
    vec(
        "state_reporters",
        f"Rho v. Sigma, {aw} ({paren}).",
        [full(aw, aw, registry)],
    )
for aw in ["123 So. 2d 456", "456 P.2d 789", "250 N.E.2d 200"]:
    vec(
        "state_reporters",
        f"Tau v. Upsilon, {aw}.",
        [full(aw, aw, None, AMB)],
    )

# --- 11. Statutes and journals excluded -------------------------------------------
for text in [
    "The claim arises under 42 U.S.C. § 1983 and 28 U.S.C. § 1331.",
    "See 29 C.F.R. § 1604.11.",
    "See Charles A. Wright, Law of Federal Courts, 103 Harv. L. Rev. 405 (1989).",
    "The claim arises under 42 U.S.C. § 1983. Id.",
    "Pub. L. No. 110-325, 122 Stat. 3553 (2008).",
]:
    vec("non_case_excluded", text, [])
vec(
    "non_case_excluded",
    "Under 42 U.S.C. § 1983 and Monroe v. Pape, 365 U.S. 167 (1961).",
    [full("365 U.S. 167", "365 U.S. 167", "us-scotus")],
)

# --- 12. Pin cites and the first-page rule ------------------------------------------
PIN_FORMS = ["113, 116", "113, 116-17", "113, 113", "113, 159 n.4", "113, 116, 118", "113, 152-53 & n.7"]
for pin in PIN_FORMS:
    vec(
        "first_page_rule",
        f"Roe v. Wade, 410 U.S. {pin} (1973).",
        [full("410 U.S. 113", "410 U.S. 113", "us-scotus")],
    )
vec(
    "first_page_rule",
    "(quoting Roe v. Wade, 410 U.S. 113, 116 (1973)).",
    [full("410 U.S. 113", "410 U.S. 113", "us-scotus")],
)

# --- 13. Unicode and odd whitespace ---------------------------------------------------
vec(
    "unicode_whitespace",
    "See Phi v. Chi, 410 U.S. 113 (1973).",
    [full("410 U.S. 113", "410 U.S. 113", "us-scotus")],
)
vec(
    "unicode_whitespace",
    "Psi v. Omega, 789 F. App’x 12 (11th Cir. 2019).",
    [full("789 F. App’x 12", "789 F. App'x 12", "us-ca11")],
)
vec(
    "unicode_whitespace",
    "Alpha v. Beta, 410 U.S. 113 (1973), with non-breaking spaces.",
    [full("410 U.S. 113", "410 U.S. 113", "us-scotus")],
)
vec(
    "unicode_whitespace",
    "Gamma v. Delta, 410 U.S. 113, 116–17 (1973), en-dash pin range.",
    [full("410 U.S. 113", "410 U.S. 113", "us-scotus")],
)
vec(
    "unicode_whitespace",
    "“Quoted matter.” Roe v. Wade, 410 U.S. 113 (1973).",
    [full("410 U.S. 113", "410 U.S. 113", "us-scotus")],
)

# --- 14. Pending publication / underscores --------------------------------------------
for text in [
    "Recent v. Pending, 596 U.S. ___ (2022), changes nothing here.",
    "Newest v. Slip, 600 U.S. ____, ____ (2023).",
]:
    vec("pending_publication", text, [])

# --- 15. Noise robustness ---------------------------------------------------------------
vec(
    "noise_robustness",
    "compare Roe v. Wade, 410 U.S. 113 (1973), with Doe v. Bolton, 410 U.S. 179 (1973).",
    [
        full("410 U.S. 113", "410 U.S. 113", "us-scotus"),
        full("410 U.S. 179", "410 U.S. 179", "us-scotus"),
    ],
)
vec(
    "noise_robustness",
    "footnote 12: Varghese v. China S. Airlines Co., 925 F.3d 1339, 1345 (11th Cir. 2019); accord Smith v. Doe, 538 F.3d 1000, 1002 (9th Cir. 2008).",
    [
        full("925 F.3d 1339", "925 F.3d 1339", "us-ca11"),
        full("538 F.3d 1000", "538 F.3d 1000", "us-ca9"),
    ],
)
vec("noise_robustness", "No citations live in this sentence about page 113 and volume 410.", [])
vec("noise_robustness", "", [])
vec("noise_robustness", "   \n\n   ", [])
vec(
    "noise_robustness",
    "See, e.g., Roe v. Wade, 410 U.S. 113 (1973); Brown v. Board, 347 U.S. 483 (1954); Smith v. Doe, 538 F.3d 1000 (9th Cir. 2008).",
    [
        full("410 U.S. 113", "410 U.S. 113", "us-scotus"),
        full("347 U.S. 483", "347 U.S. 483", "us-scotus"),
        full("538 F.3d 1000", "538 F.3d 1000", "us-ca9"),
    ],
)
vec(
    "noise_robustness",
    "Affirmed. Sigma v. Tau, 412 F.3d 88, 90 (2d Cir. 2005) (per curiam) (collecting cases).",
    [full("412 F.3d 88", "412 F.3d 88", "us-ca2")],
)

# --- 12. Normalizer 1.1.0 (2026-08-01): expanded jurisdiction mapping ------
# N.Y. Appellate Division: A.D. editions infer us-nyappdiv from the reporter
# table (bare), and the department / "App. Div." parenthetical forms are a
# definitional closed set (courts-db models the four departments as one
# court). Adjudications in DECISIONS 2026-08-01.
vec(
    "ny_appdiv",
    "Podraza v. Carriero, 212 A.D.2d 331 (4th Dep't 1995).",
    [full("212 A.D.2d 331", "212 A.D.2d 331", "us-nyappdiv")],
)
vec(
    "ny_appdiv",
    "Kingsland Land Co. v. Newman, 1 A.D. 1 (App. Div. 1896).",
    [full("1 A.D. 1", "1 A.D. 1", "us-nyappdiv")],
)
vec(
    "ny_appdiv",
    "Bare edition, no parenthetical: Matter of Smith, 100 A.D.3d 500.",
    [full("100 A.D.3d 500", "100 A.D.3d 500", "us-nyappdiv")],
)
vec(
    "ny_appdiv",
    "People v. Jones, 45 N.Y.S.3d 200 (App. Div. 2017).",
    [full("45 N.Y.S.3d 200", "45 N.Y.S.3d 200", "us-nyappdiv")],
)
vec(
    "ny_appdiv",
    # N.Y.S. genuinely spans courts: bare stays ambiguous (never guess).
    "People v. Jones, 45 N.Y.S.3d 200.",
    [full("45 N.Y.S.3d 200", "45 N.Y.S.3d 200", None, AMB)],
)
vec(
    "ny_appdiv",
    "Bare official reporter infers the Court of Appeals: Palsgraf v. Long Island R.R. Co., 248 N.Y. 339.",
    [full("248 N.Y. 339", "248 N.Y. 339", "us-ny")],
)

# Tax Court: T.C. (curated), T.C. No. and T.C. Memo. (corpus-dominant).
# eyecite reads "T.C. Memo. 1976-300" as volume 1976 / page 300, matching
# the corpus key format exactly.
vec(
    "tax_court",
    "Fehrs v. Commissioner, 65 T.C. 346 (1975).",
    [full("65 T.C. 346", "65 T.C. 346", "us-tax")],
)
vec(
    "tax_court",
    "Smith v. Commissioner, T.C. Memo. 1976-300.",
    [full("T.C. Memo. 1976-300", "1976 T.C. Memo. 300", "us-tax")],
)
vec(
    "tax_court",
    "Jones v. Commissioner, 100 T.C. No. 11 (1993).",
    [full("100 T.C. No. 11", "100 T.C. No. 11", "us-tax")],
)

# Vendor identifiers OUTSIDE the registry key space (WL and the generic /
# federal LEXIS families hold zero corpus records): the verifier reports
# them as outside coverage with no chain read (disposition VENDOR).
vec(
    "vendor_cites",
    "LAM Wholesale, LLC v. United Airlines, Inc., 2019 WL 1439098 (E.D.N.Y. 2019).",
    [full("2019 WL 1439098", "2019 WL 1439098", None, VEN)],
)
vec(
    "vendor_cites",
    "Doe v. Roe, 2019 U.S. App. LEXIS 12345 (1st Cir. 2019).",
    [full("2019 U.S. App. LEXIS 12345", "2019 U.S. App. LEXIS 12345", None, VEN)],
)
vec(
    "vendor_cites",
    # Court-specific LEXIS editions ARE corpus keys (3.28M parallel records
    # on chain): dominance-clean ones map from the table like any reporter.
    "State v. Doe, 1894 La. LEXIS 577.",
    [full("1894 La. LEXIS 577", "1894 La. LEXIS 577", "us-la")],
)
vec(
    "vendor_cites",
    # A corpus-present LEXIS edition the dominance guard keeps OUT of the
    # table (a real us-nysupct second population): bare stays VENDOR...
    "Doe v. Roe, 1912 N.Y. App. Div. LEXIS 7085.",
    [full("1912 N.Y. App. Div. LEXIS 7085", "1912 N.Y. App. Div. LEXIS 7085", None, VEN)],
)
vec(
    "vendor_cites",
    # ...but an explicit court parenthetical still maps it (a lookup there
    # can genuinely hit — the keys are on chain).
    "Doe v. Roe, 1912 N.Y. App. Div. LEXIS 7085 (N.Y. App. Div. 1912).",
    [full("1912 N.Y. App. Div. LEXIS 7085", "1912 N.Y. App. Div. LEXIS 7085", "us-nyappdiv")],
)

# Reporter-edition inference across court classes (corpus-dominant table).
vec(
    "reporter_inference",
    "Bare state officials: People v. A, 61 Cal. 2d 529; Baker v. B, 37 Ill. 2d 111; C v. D, 219 Ga. 555.",
    [
        full("61 Cal. 2d 529", "61 Cal. 2d 529", "us-cal"),
        full("37 Ill. 2d 111", "37 Ill. 2d 111", "us-ill"),
        full("219 Ga. 555", "219 Ga. 555", "us-ga"),
    ],
)
vec(
    "reporter_inference",
    "Neutral formats: In re T, 2013 IL App (1st) 111279-U; State v. U, 2019 OK 5.",
    [
        full("2013 IL App (1st) 111279-U", "2013 IL App (1st) 111279-U", "us-illappct"),
        full("2019 OK 5", "2019 OK 5", "us-okla"),
    ],
)
vec(
    "reporter_inference",
    "Intermediate courts: E v. F, 300 Ill. App. 3d 673; G v. H, 45 Cal. App. 4th 100.",
    [
        full("300 Ill. App. 3d 673", "300 Ill. App. 3d 673", "us-illappct"),
        full("45 Cal. App. 4th 100", "45 Cal. App. 4th 100", "us-calctapp"),
    ],
)

# The general court-parenthetical fallback (courts-db citation strings are
# globally unique) and its precedence over the reporter default.
vec(
    "parenthetical_index",
    "State v. Brown, 100 Ohio St. 3d 500 (Ohio Ct. App. 2003).",
    [full("100 Ohio St. 3d 500", "100 Ohio St. 3d 500", "us-ohioctapp")],
)
vec(
    "parenthetical_index",
    "Doe v. Agency, 50 F. Supp. 3d 10 (D. Mass. 2014).",
    [full("50 F. Supp. 3d 10", "50 F. Supp. 3d 10", "us-mad")],
)

# What must STAY ambiguous under 1.1.0: multi-court reporters with no court
# signal (never guess).
vec(
    "still_ambiguous",
    "Baz v. Qux, 500 S.W.3d 100.",
    [full("500 S.W.3d 100", "500 S.W.3d 100", None, AMB)],
)
vec(
    "still_ambiguous",
    "United States v. Smith, 54 M.J. 783.",
    [full("54 M.J. 783", "54 M.J. 783", None, AMB)],
)
vec(
    "still_ambiguous",
    "Foo v. Bar, 100 F.3d 200.",
    [full("100 F.3d 200", "100 F.3d 200", None, AMB)],
)


def main() -> None:
    out = Path(__file__).parent / "vectors.json"
    payload = {
        "_meta": {
            "spec": "cite-canonical-v1",
            "generator": "generate_vectors.py",
            "note": "Expectations hand-derived from docs/canonical-citation-spec.md; adjudications recorded in DECISIONS.md. Compared fields: as_written, canonical, registry, disposition, kind.",
            "vector_count": len(VECTORS),
            "expectation_rows": sum(len(v["expect"]) for v in VECTORS),
        },
        "vectors": VECTORS,
    }
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    cats: dict[str, int] = {}
    for v in VECTORS:
        cats[v["category"]] = cats.get(v["category"], 0) + 1
    for cat, n in cats.items():
        print(f"{cat}: {n}")
    print(f"TOTAL vectors: {len(VECTORS)}, expectation rows: {payload['_meta']['expectation_rows']}")


if __name__ == "__main__":
    main()
