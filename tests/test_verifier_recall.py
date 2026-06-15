"""Extraction recall (task 3.1): the FULL pipeline over real RECAP PDFs.

Unlike test_normalizer_briefs.py (which runs the normalizer over committed
.txt extractions), this exercises verifier/extract.py's PDF path itself, so
a regression in PDF text extraction is caught, not just normalization. The
expected numbers live in fixtures/briefs/recall.json (the committed recall
artifact); occurrence/distinct counts are checked as FLOORS, key-cite counts
and the scanned-zero result exactly.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from nvnm_cite.normalizer import normalize
from nvnm_cite.verifier import extract as extract_mod
from nvnm_cite.verifier.extract import extract_text

BRIEFS = Path(__file__).parent / "fixtures" / "briefs"
RECALL = json.loads((BRIEFS / "recall.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(
    extract_mod.pdfplumber is None, reason="pdfplumber not installed (PDF extraction unavailable)"
)


def _measure(stem: str):
    data = (BRIEFS / f"{stem}.pdf").read_bytes()
    extraction = extract_text(data, f"{stem}.pdf")
    return extraction, normalize(extraction.text)


@pytest.mark.parametrize("stem", list(RECALL["documents"]))
def test_recall_meets_committed_floor(stem: str) -> None:
    expected = RECALL["documents"][stem]
    extraction, result = _measure(stem)

    # Varghese (the fabricated cite) appears exactly as many times as recorded.
    varghese = sum(1 for c in result.citations if c.canonical == "925 F.3d 1339")
    assert varghese == expected["varghese_925_f3d_1339"]

    if expected["born_digital"]:
        # Floors: an eyecite upgrade finding MORE citations must not break us.
        assert len(result.citations) >= expected["occurrences"]
        distinct = {(c.registry, c.canonical) for c in result.citations if c.canonical}
        assert len(distinct) >= expected["distinct_keys"]
        assert extraction.warning is None
    else:
        # The scanned affirmation: an image-only PDF, honestly zero citations.
        assert result.citations == []
        assert extraction.warning and "scan" in extraction.warning


def test_walters_registry_shape() -> None:
    # The ca11 appellate brief resolves cleanly to exactly the pilot courts.
    _, result = _measure("walters-openai-ca11-ecf9-appellant-brief")
    regs = {c.registry for c in result.citations if c.registry}
    assert regs == set(RECALL["documents"]["walters-openai-ca11-ecf9-appellant-brief"]["registries"])


def test_recall_manifest_consistency() -> None:
    # Every recall entry names a real fixture file.
    for stem in RECALL["documents"]:
        assert (BRIEFS / f"{stem}.pdf").exists(), stem
