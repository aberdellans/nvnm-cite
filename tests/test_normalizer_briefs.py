"""Integration tests: the normalizer against real RECAP filings.

Fixtures and provenance: tests/fixtures/briefs/manifest.json. The .txt
extractions are committed (regenerate with extract_text.py), so these tests
need no PDF tooling at run time. Assertions use floors and membership, not
exact totals, so an eyecite upgrade that finds MORE citations does not break
them; the synthetic golden suite is what pins exact behavior.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from nvnm_cite.normalizer import Disposition, normalize

BRIEFS = Path(__file__).parent / "fixtures" / "briefs"


def load(stem: str):
    text = (BRIEFS / "extracted" / f"{stem}.txt").read_text(encoding="utf-8")
    return normalize(text)


def test_manifest_matches_files() -> None:
    manifest = json.loads((BRIEFS / "manifest.json").read_text())
    for doc in manifest["documents"]:
        assert (BRIEFS / doc["file"]).exists(), doc["file"]
        assert (BRIEFS / "extracted" / (Path(doc["file"]).stem + ".txt")).exists()
        assert doc["source_url"].startswith("https://storage.courtlistener.com/recap/")


def test_scanned_affirmation_yields_no_citations() -> None:
    # ECF 21 is image-only; its text layer is just ECF header stamps. The
    # honest result is zero citations, which is exactly why Phase 3 measures
    # extraction recall and reports UNPARSEABLE rather than pretending.
    r = load("mata-avianca-nysd-ecf21-affirmation-scanned")
    assert r.citations == []


class TestAviancaReplyMemo:
    def test_finds_the_fabricated_varghese_cite(self) -> None:
        r = load("mata-avianca-nysd-ecf24-reply-memo")
        varghese = [c for c in r.citations if c.canonical == "925 F.3d 1339"]
        assert len(varghese) == 1
        v = varghese[0]
        # The memo cites it with the (11th Cir. 2019) parenthetical, so it
        # maps to the covered registry; existence is the verifier's call.
        assert v.registry == "us-ca11"
        assert v.disposition is Disposition.OK

    def test_breadth(self) -> None:
        r = load("mata-avianca-nysd-ecf24-reply-memo")
        assert len(r.citations) >= 25
        regs = Counter(c.registry for c in r.citations if c.registry)
        assert regs["us-scotus"] >= 3
        assert regs["us-ca11"] >= 2
        assert any(c.disposition is Disposition.AMBIGUOUS_JURISDICTION for c in r.citations)


class TestSanctionsOpinion:
    def test_varghese_appears_repeatedly(self) -> None:
        r = load("mata-avianca-nysd-ecf54-sanctions-opinion")
        varghese = [c for c in r.citations if c.canonical == "925 F.3d 1339"]
        assert len(varghese) >= 2

    def test_breadth_and_short_forms(self) -> None:
        r = load("mata-avianca-nysd-ecf54-sanctions-opinion")
        assert len(r.citations) >= 80
        kinds = Counter(c.kind for c in r.citations)
        assert kinds["id"] >= 5  # judicial opinions lean hard on id.
        regs = Counter(c.registry for c in r.citations if c.registry)
        assert regs["us-ca2"] >= 20  # SDNY opinion applying 2d Cir. law
        assert regs["us-scotus"] >= 5

    def test_every_occurrence_is_stamped(self) -> None:
        r = load("mata-avianca-nysd-ecf54-sanctions-opinion")
        assert all(c.normalizer_version == r.normalizer_version for c in r.citations)


class TestWaltersCa11Brief:
    def test_parallel_triplet_normalized_from_tight_forms(self) -> None:
        # The brief cites Milkovich as "494 U.S. 472, 110 S.Ct. 1249,
        # 108 L.Ed.2d 400": three parallel records, tight reporter spellings.
        r = load("walters-openai-ca11-ecf9-appellant-brief")
        canonicals = {c.canonical for c in r.citations}
        assert {"494 U.S. 472", "110 S. Ct. 1249", "108 L. Ed. 2d 400"} <= canonicals

    def test_registries_match_pilot_corpus_shape(self) -> None:
        r = load("walters-openai-ca11-ecf9-appellant-brief")
        assert len(r.citations) >= 20
        regs = {c.registry for c in r.citations if c.registry}
        assert regs == {"us-ca11", "us-scotus"}
