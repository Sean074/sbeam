"""Tests for Step 19: Case Control UI — BDF export round-trip."""

import pytest

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
        text = export_bdf_text(cc, include_path="my_model.dat")
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
        text = export_bdf_text(cc, include_path="model.dat")
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
        text = export_bdf_text(cc, include_path="bulk.dat")
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
