"""Unit tests for the normalizer pipeline (canonical.py + jurisdiction.py).

These pin behavior measured against eyecite 2.7.6 / reporters-db 3.2.65 /
courts-db 0.10.27. The 200+ entry golden suite (task 1.6) lives separately
under tests/golden/normalizer/; this file covers the API contract.
"""

from __future__ import annotations

import pytest

from nvnm_cite.normalizer import (
    CANONICAL_SPEC,
    NORMALIZER_VERSION,
    Disposition,
    NormalizationResult,
    map_citation,
    normalize,
    registry_for_court,
)


def only(result: NormalizationResult, disposition: Disposition | None = None):
    cites = result.citations
    if disposition is not None:
        cites = [c for c in cites if c.disposition is disposition]
    assert len(cites) == 1, f"expected exactly one citation, got {cites!r}"
    return cites[0]


class TestCanonicalForm:
    def test_basic_scotus_cite(self) -> None:
        r = normalize("Roe v. Wade, 410 U.S. 113, 116 (1973), controls.")
        c = only(r)
        assert c.canonical == "410 U.S. 113"
        assert c.registry == "us-scotus"
        assert c.disposition is Disposition.OK
        assert c.kind == "full"
        assert c.court == "scotus"
        assert c.year == 1973
        assert c.plaintiff == "Roe"
        assert c.defendant == "Wade"
        assert c.pin_cite == "116"

    def test_first_page_rule_pin_never_in_key(self) -> None:
        r = normalize("Roe v. Wade, 410 U.S. 113, 159 (1973).")
        c = only(r)
        assert c.canonical == "410 U.S. 113"
        assert c.pin_cite == "159"

    def test_spaced_reporter_variant_corrected(self) -> None:
        r = normalize("See Varghese v. China S. Airlines Co., 925 F. 3d 1339 (11th Cir. 2019).")
        c = only(r)
        assert c.as_written == "925 F. 3d 1339"
        assert c.canonical == "925 F.3d 1339"
        assert c.registry == "us-ca11"

    def test_spaced_us_reporter(self) -> None:
        r = normalize("Roe v. Wade, 410 U. S. 113 (1973).")
        assert only(r).canonical == "410 U.S. 113"

    def test_line_break_mangled_cite(self) -> None:
        r = normalize("See Roe v. Wade, 410\nU. S.\n113 (1973), holding that.")
        assert only(r).canonical == "410 U.S. 113"

    def test_early_scotus_parallel_form(self) -> None:
        r = normalize("Marbury v. Madison, 5 U.S. (1 Cranch) 137 (1803).")
        c = only(r)
        assert c.canonical == "5 U.S. 137"
        assert c.registry == "us-scotus"

    def test_empty_party_name_becomes_none(self) -> None:
        r = normalize("Foo v. Bar, 1 U.S. 1 (1790). M'Culloch v. Maryland, 17 U.S. 316 (1819).")
        last = r.citations[-1]
        assert last.plaintiff is None or last.plaintiff  # never empty string


class TestJurisdictionMapping:
    def test_bare_l_ed_2d_maps_to_scotus(self) -> None:
        r = normalize("See 181 L. Ed. 2d 911.")
        c = only(r)
        assert c.registry == "us-scotus"
        assert c.disposition is Disposition.OK

    def test_bare_s_ct_maps_to_scotus(self) -> None:
        r = normalize("See 132 S. Ct. 945.")
        assert only(r).registry == "us-scotus"

    def test_f3d_without_parenthetical_is_ambiguous(self) -> None:
        r = normalize("Smith v. Doe, 538 F.3d 1000.")
        c = only(r)
        assert c.disposition is Disposition.AMBIGUOUS_JURISDICTION
        assert c.registry is None
        assert c.canonical == "538 F.3d 1000"  # canonical still computed
        assert "parenthetical" in (c.reason or "")

    def test_f_appx_without_parenthetical_is_ambiguous(self) -> None:
        r = normalize("Doe v. Roe, 789 F. App'x 12.")
        assert only(r).disposition is Disposition.AMBIGUOUS_JURISDICTION

    def test_state_reporter_without_parenthetical_is_ambiguous(self) -> None:
        r = normalize("Jones v. Smith, 123 So. 2d 456.")
        c = only(r)
        assert c.disposition is Disposition.AMBIGUOUS_JURISDICTION
        assert c.registry is None

    def test_circuit_parenthetical_maps_to_circuit(self) -> None:
        r = normalize("Varghese v. China S. Airlines Co., 925 F.3d 1339 (11th Cir. 2019).")
        assert only(r).registry == "us-ca11"

    def test_3d_cir_bluebook_ordinal_maps(self) -> None:
        # eyecite 2.7.6 misses "3d Cir." (it knows "3rd Cir."); the
        # closed-set fallback must cover the Bluebook-standard form.
        r = normalize("Quux v. Corge, 900 F.3d 50, 55 (3d Cir. 2018).")
        c = only(r)
        assert c.registry == "us-ca3"
        assert c.disposition is Disposition.OK

    def test_circuit_fallback_never_crosses_into_next_citation(self) -> None:
        r = normalize("A v. B, 900 F.3d 50; C v. D, 901 F.2d 60 (3d Cir. 1990).")
        first, second = r.citations
        assert first.disposition is Disposition.AMBIGUOUS_JURISDICTION
        assert first.registry is None
        assert second.registry == "us-ca3"

    def test_registry_for_court_validates(self) -> None:
        assert registry_for_court("scotus") == "us-scotus"
        assert registry_for_court("ca11") == "us-ca11"
        with pytest.raises(ValueError):
            registry_for_court("not-a-court")


class TestShortFormResolution:
    TEXT = (
        "Roe v. Wade, 410 U.S. 113, 116 (1973), controls here. "
        "Roe, 410 U.S. at 120. Id. at 121."
    )

    def test_chain_inherits_canonical_and_registry(self) -> None:
        r = normalize(self.TEXT)
        assert [c.kind for c in r.citations] == ["full", "short", "id"]
        assert {c.canonical for c in r.citations} == {"410 U.S. 113"}
        assert {c.registry for c in r.citations} == {"us-scotus"}
        assert {c.group for c in r.citations} == {r.citations[0].group}

    def test_short_form_keeps_own_as_written_and_pin(self) -> None:
        r = normalize(self.TEXT)
        short = r.citations[1]
        assert short.as_written == "410 U.S. at 120"
        assert short.pin_cite == "120"

    def test_orphan_short_forms_reported_not_dropped(self) -> None:
        r = normalize("Id. at 5. Jones, supra, at 10. See 410 U.S. at 120.")
        assert len(r.citations) == 3
        assert {c.disposition for c in r.citations} == {Disposition.UNRESOLVED}
        assert all(c.canonical is None and c.registry is None for c in r.citations)
        assert all("antecedent" in (c.reason or "") for c in r.citations)


class TestNonCaseExclusion:
    def test_statute_and_journal_excluded(self) -> None:
        r = normalize(
            "See 42 U.S.C. § 1983. See also Cass R. Sunstein, "
            "Interpreting Statutes, 103 Harv. L. Rev. 405 (1989)."
        )
        assert r.citations == []

    def test_id_following_statute_excluded(self) -> None:
        # The Id. resolves into the statute's group, so it is not a case cite.
        r = normalize("The claim arises under 42 U.S.C. § 1983. Id.")
        assert r.citations == []

    def test_case_cites_survive_alongside_statutes(self) -> None:
        r = normalize("Under 42 U.S.C. § 1983 and Monroe v. Pape, 365 U.S. 167 (1961).")
        c = only(r)
        assert c.canonical == "365 U.S. 167"


class TestContract:
    def test_version_stamped_everywhere(self) -> None:
        r = normalize("Roe v. Wade, 410 U.S. 113 (1973).")
        assert r.normalizer_version == NORMALIZER_VERSION
        assert all(c.normalizer_version == NORMALIZER_VERSION for c in r.citations)
        assert CANONICAL_SPEC == "cite-canonical-v1"

    def test_empty_text(self) -> None:
        r = normalize("")
        assert r.citations == [] and r.cleaned_text == ""

    def test_no_citations(self) -> None:
        assert normalize("Nothing legal to see here.").citations == []

    def test_spans_index_cleaned_text(self) -> None:
        r = normalize("See Roe v. Wade, 410\nU. S. 113 (1973), and Brown v. Board, 347 U.S. 483 (1954).")
        for c in r.citations:
            start, end = c.span
            assert r.cleaned_text[start:end] == c.as_written

    def test_results_in_document_order(self) -> None:
        r = normalize(
            "Brown v. Board, 347 U.S. 483 (1954). Roe v. Wade, 410 U.S. 113 (1973). "
            "Brown, 347 U.S. at 490."
        )
        assert [c.as_written for c in r.citations] == [
            "347 U.S. 483",
            "410 U.S. 113",
            "347 U.S. at 490",
        ]
        assert r.citations[2].canonical == "347 U.S. 483"

    def test_map_citation_exported_and_usable(self) -> None:
        from eyecite import get_citations

        cite = get_citations("925 F.3d 1339 (11th Cir. 2019)")[0]
        assert map_citation(cite) == ("us-ca11", None)
