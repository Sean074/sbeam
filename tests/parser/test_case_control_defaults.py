"""Case control above the first SUBCASE, decks with no SUBCASE, and SUBCASE IDs (#79).

MSC: requests above the subcase level "apply to all the subcases until they are
cancelled" (AAUG 2023.1 PDF p.752); a SUBCASE ID "must be greater than all
previous subcase identification numbers" (QRG 2024.1 PDF p.651, remark 1); the
QRG INCLUDE example (PDF p.465) is a SOL 101 deck with LOAD and no SUBCASE.
"""

import sys
from pathlib import Path

import pytest

import sbeam.main as main_mod
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import parse_case_control
from sbeam.solver.sol101 import run_sol101

BDF_DIR = Path(__file__).parent.parent / "integration" / "bdf"

# V1 cantilever: P = 1000 N, L = 1 m, E = 2e11 Pa, I = 8.333e-4 m^4.
_TIP_NODE = 11
_TIP_DEFLECTION = 1000.0 * 1.0**3 / (3.0 * 2.0e11 * 8.333e-4)


def _v1_deck(tmp_path, case_control: str) -> Path:
    """The V1 cantilever bulk under a replacement case control section."""
    text = (BDF_DIR / "v1_v2_cantilever.bdf").read_text()
    deck = tmp_path / "deck.bdf"
    deck.write_text(case_control + text[text.index("BEGIN BULK"):])
    return deck


def _tip_deflection(deck: Path, index: int = 0) -> float:
    cc, bulk = parse_bdf(str(deck))
    result = run_sol101(bulk, cc.subcases[index])
    return result.displacements[6 * build_grid_index(bulk)[_TIP_NODE] + 1]


class TestDefaultsAboveSubcase:
    def test_selectors_above_subcase_reach_the_solver(self, tmp_path):
        """SPC and LOAD above SUBCASE 1 used to be dropped: an all-zero run."""
        deck = _v1_deck(tmp_path, "SOL 101\nSPC = 1\nLOAD = 10\nSUBCASE 1\n")
        assert _tip_deflection(deck) == pytest.approx(_TIP_DEFLECTION, rel=1e-3)

    def test_every_subcase_inherits(self):
        cc = parse_case_control([
            "SOL 101", "SPC = 1", "DISPLACEMENT = ALL",
            "SUBCASE 1", "  LOAD = 10",
            "SUBCASE 2", "  LOAD = 20",
        ])
        assert [(sc.spc_sid, sc.load_sid, sc.displacement) for sc in cc.subcases] \
            == [(1, 10, True), (1, 20, True)]

    def test_subcase_value_overrides_only_that_subcase(self):
        cc = parse_case_control([
            "SOL 101", "SPC = 1", "LOAD = 10",
            "SUBCASE 1", "  SPC = 2",
            "SUBCASE 2",
        ])
        assert [(sc.spc_sid, sc.load_sid) for sc in cc.subcases] == [(2, 10), (1, 10)]

    def test_none_cancels_a_default_output_request(self):
        cc = parse_case_control([
            "SOL 101", "DISPLACEMENT = ALL", "FORCE = ALL",
            "SUBCASE 1", "  DISPLACEMENT = NONE",
            "SUBCASE 2",
        ])
        assert [(sc.displacement, sc.force) for sc in cc.subcases] \
            == [(False, True), (True, True)]

    def test_title_above_subcase_stays_the_run_title(self):
        cc = parse_case_control(["SOL 101", "TITLE = Run", "SPC = 1", "SUBCASE 1"])
        assert cc.title == "Run"
        assert cc.subcases[0].title == ""


class TestNoSubcase:
    def test_runs_as_subcase_1(self, tmp_path):
        """The QRG INCLUDE-example shape used to write a 0-byte f06."""
        deck = _v1_deck(
            tmp_path, "SOL 101\nCEND\nSPC = 1\nLOAD = 10\nDISPLACEMENT = ALL\n")
        cc, _bulk = parse_bdf(str(deck))
        assert [sc.subcase_id for sc in cc.subcases] == [1]
        assert _tip_deflection(deck) == pytest.approx(_TIP_DEFLECTION, rel=1e-3)

    def test_main_writes_a_non_empty_f06(self, tmp_path, monkeypatch):
        deck = _v1_deck(
            tmp_path, "SOL 101\nCEND\nSPC = 1\nLOAD = 10\nDISPLACEMENT = ALL\n")
        monkeypatch.setattr(sys, "argv", ["sbeam", str(deck)])
        main_mod.main()
        assert "D I S P L A C E M E N T" in deck.with_suffix(".f06").read_text()

    def test_nothing_to_run_is_refused_and_writes_no_f06(self, tmp_path, monkeypatch):
        deck = _v1_deck(tmp_path, "SOL 101\nCEND\n")
        monkeypatch.setattr(sys, "argv", ["sbeam", str(deck)])
        with pytest.raises(SystemExit, match="nothing to run"):
            main_mod.main()
        assert not deck.with_suffix(".f06").exists()


class TestSubcaseIds:
    @pytest.mark.parametrize("ids", [(1, 1), (2, 1), (1, 3, 2)])
    def test_non_increasing_ids_are_refused(self, ids):
        lines = ["SOL 101"] + [f"SUBCASE {i}" for i in ids]
        with pytest.raises(ValueError, match="greater than all previous"):
            parse_case_control(lines)

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_non_positive_id_is_refused(self, value):
        with pytest.raises(ValueError, match="greater than 0"):
            parse_case_control(["SOL 101", f"SUBCASE {value}"])

    def test_non_integer_id_is_refused(self):
        with pytest.raises(ValueError, match="must be an integer"):
            parse_case_control(["SOL 101", "SUBCASE A"])

    def test_increasing_ids_with_gaps_are_accepted(self):
        cc = parse_case_control(["SOL 101", "SUBCASE 1", "SUBCASE 10", "SUBCASE 11"])
        assert [sc.subcase_id for sc in cc.subcases] == [1, 10, 11]
