"""Tests for Step 19: Case Control UI — BDF export round-trip."""

from pathlib import Path

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import CaseControl, SubcaseControl, parse_case_control
from sbeam.viewer.case_control_ui import export_bdf_text


def _make_sol101_cc() -> CaseControl:
    return CaseControl(
        sol=101,
        title="Test cantilever",
        subcases=[
            SubcaseControl(
                subcase_id=1,
                load_sid=10,
                spc_sid=20,
                displacement=True,
                spcforce=True,
                force=True,
                stress=True,
            )
        ],
        include="model.dat",
    )


def _make_sol103_cc() -> CaseControl:
    return CaseControl(
        sol=103,
        title="Modal test",
        subcases=[
            SubcaseControl(
                subcase_id=1,
                spc_sid=20,
                method_sid=30,
                displacement=True,
            )
        ],
        include="bulk.dat",
    )


class TestExportBdfText:
    def test_sol_line_present(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "SOL 101" in text

    def test_title_present(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "Test cantilever" in text

    def test_subcase_line_present(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "SUBCASE 1" in text

    def test_load_sid_present(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "LOAD = 10" in text

    def test_spc_sid_present(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "SPC = 20" in text

    def test_output_requests_present(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "DISPLACEMENT = ALL" in text
        assert "SPCFORCE = ALL" in text
        assert "FORCE = ALL" in text
        assert "STRESS = ALL" in text

    def test_include_in_text(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc, include_paths=["my_model.dat"])
        assert "my_model.dat" in text

    def test_begin_bulk_present(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "BEGIN BULK" in text

    def test_enddata_present(self):
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "ENDDATA" in text


class TestRoundTrip:
    def test_sol101_round_trip(self):
        """Exported SOL 101 BDF parses back to identical CaseControl."""
        cc = _make_sol101_cc()
        text = export_bdf_text(cc, include_paths=["model.dat"])
        lines = text.splitlines()
        cc2 = parse_case_control(lines)
        assert cc2.sol == cc.sol
        assert cc2.title == cc.title
        assert len(cc2.subcases) == len(cc.subcases)
        sc = cc.subcases[0]
        sc2 = cc2.subcases[0]
        assert sc2.subcase_id == sc.subcase_id
        assert sc2.load_sid == sc.load_sid
        assert sc2.spc_sid == sc.spc_sid
        assert sc2.displacement == sc.displacement
        assert sc2.spcforce == sc.spcforce
        assert sc2.force == sc.force
        assert sc2.stress == sc.stress

    def test_sol103_round_trip(self):
        """Exported SOL 103 BDF includes METHOD and parses back correctly."""
        cc = _make_sol103_cc()
        text = export_bdf_text(cc, include_paths=["bulk.dat"])
        assert "METHOD = 30" in text
        lines = text.splitlines()
        cc2 = parse_case_control(lines)
        assert cc2.sol == 103
        assert cc2.subcases[0].method_sid == 30
        assert cc2.subcases[0].spc_sid == 20

    def test_no_load_omitted(self):
        """Subcases without LOAD don't produce a LOAD line."""
        cc = CaseControl(
            sol=103,
            title="",
            subcases=[SubcaseControl(subcase_id=1, spc_sid=10, method_sid=20)],
            include="m.dat",
        )
        text = export_bdf_text(cc)
        assert "LOAD" not in text

    def test_no_method_omitted_for_sol101(self):
        """SOL 101 subcase without METHOD doesn't produce a METHOD line."""
        cc = _make_sol101_cc()
        text = export_bdf_text(cc)
        assert "METHOD" not in text


class TestMultiSubcaseRoundTrip:
    """B1 acceptance: 2-subcase export → parse round-trip with distinct per-subcase fields."""

    def _make_two_subcase_cc(self) -> CaseControl:
        return CaseControl(
            sol=101,
            title="Two subcase test",
            subcases=[
                SubcaseControl(
                    subcase_id=1,
                    load_sid=10,
                    spc_sid=1,
                    displacement=True,
                    spcforce=True,
                    force=True,
                    stress=False,
                ),
                SubcaseControl(
                    subcase_id=2,
                    load_sid=20,
                    spc_sid=1,
                    displacement=True,
                    spcforce=False,
                    force=False,
                    stress=True,
                ),
            ],
            include="model.dat",
        )

    def test_both_subcases_in_text(self):
        cc = self._make_two_subcase_cc()
        text = export_bdf_text(cc)
        assert "SUBCASE 1" in text
        assert "SUBCASE 2" in text

    def test_distinct_load_sids_in_text(self):
        cc = self._make_two_subcase_cc()
        text = export_bdf_text(cc)
        assert "LOAD = 10" in text
        assert "LOAD = 20" in text

    def test_two_subcase_round_trip(self):
        """Both subcases survive export → parse with correct, independent field values."""
        cc = self._make_two_subcase_cc()
        text = export_bdf_text(cc, include_paths=["model.dat"])
        cc2 = parse_case_control(text.splitlines())

        assert cc2.sol == 101
        assert len(cc2.subcases) == 2

        sc1, sc2 = cc2.subcases[0], cc2.subcases[1]

        assert sc1.subcase_id == 1
        assert sc1.load_sid == 10
        assert sc1.spc_sid == 1
        assert sc1.displacement is True
        assert sc1.spcforce is True
        assert sc1.force is True
        assert sc1.stress is False

        assert sc2.subcase_id == 2
        assert sc2.load_sid == 20
        assert sc2.spc_sid == 1
        assert sc2.displacement is True
        assert sc2.spcforce is False
        assert sc2.force is False
        assert sc2.stress is True


# ---------------------------------------------------------------------------
# P12 S2 — SOL 144 case-control export + round-trip
# ---------------------------------------------------------------------------

_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample"


def _make_sol144_cc() -> CaseControl:
    return CaseControl(
        sol=144,
        title="Full-surface SOL 144",
        subcases=[
            SubcaseControl(subcase_id=1, title="trim", spc_sid=1, trim_sid=10,
                           trimobj_sid=11, diverg_sid=12, massset_sid=20,
                           displacement=True, force=True, aerof=True, apres=True),
            SubcaseControl(subcase_id=2, title="maneuver", spc_sid=1,
                           mloads_sid=30, massset_sid=21, stress=True),
        ],
        include="model.dat",
        includes=["model.dat", "overlay.dat"],
    )


class TestSol144Export:
    def test_all_keywords_emitted(self):
        text = export_bdf_text(_make_sol144_cc())
        for expected in ["SOL 144", "TRIM = 10", "TRIMOBJ = 11", "DIVERG = 12",
                         "MLOADS = 30", "MASSSET = 20", "MASSSET = 21",
                         "AEROF = ALL", "APRES = ALL"]:
            assert expected in text, expected

    def test_multi_include_preserved(self):
        text = export_bdf_text(_make_sol144_cc())
        assert "INCLUDE 'model.dat'" in text
        assert "INCLUDE 'overlay.dat'" in text
        # INCLUDE lines must sit above BEGIN BULK where the parser reads them.
        assert text.index("INCLUDE 'overlay.dat'") < text.index("BEGIN BULK")

    def test_sol144_round_trip_zero_loss(self):
        cc = _make_sol144_cc()
        cc2 = parse_case_control(export_bdf_text(cc).splitlines())
        assert cc2.sol == 144
        assert cc2.includes == cc.includes
        assert cc2.subcases == cc.subcases

    def test_authored_block_emitted_inline(self):
        text = export_bdf_text(_make_sol144_cc(),
                               authored_block="TRIM, 10, 0.9, 40.0, PITCH, 0.0\n")
        bulk_part = text.split("BEGIN BULK")[1]
        assert "TRIM, 10" in bulk_part
        assert bulk_part.index("TRIM, 10") < bulk_part.index("ENDDATA")


class TestSampleDeckCaseControlRoundTrip:
    def test_sample_decks_round_trip(self):
        """The two MLOADS sample decks' case control survives export → parse."""
        for deck in ("ha144a_fullspan_mloads.bdf", "ha144a_mloads_massset.bdf"):
            cc, _ = parse_bdf(_SAMPLE_DIR / deck)
            cc2 = parse_case_control(export_bdf_text(cc).splitlines())
            assert cc2.sol == cc.sol, deck
            assert cc2.subcases == cc.subcases, deck
