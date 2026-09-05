"""Step 56 — SOL 144 static aeroelastic .f06 output regression tests.

Exercises the f06 trim formatter (`build_f06_sol144_text`) on the full-span
HA144A trim deck: TRIM VARIABLES, STABILITY DERIVATIVES (rigid + elastic
restrained), AERODYNAMIC TOTALS (CL/CMY), AERODYNAMIC DIVERGENCE, the shared
DISPLACEMENT / BAR FORCE / BAR STRESS blocks, and the AEROF/APRES-gated
AERODYNAMIC BOX PRESSURES AND FORCES block.
"""

import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim
from sbeam.results.f06_writer import build_f06_sol144_text

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


@pytest.fixture(scope="module")
def trim():
    """Run the SC1 trim once; return (bulk, result)."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        result = run_sol144_trim(bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    return bulk, result


def _text(bulk, result, **sc_kwargs):
    sc = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1, **sc_kwargs)
    cc = CaseControl(sol=144, title="HA144A test", subcases=[sc])
    return build_f06_sol144_text(cc, bulk, result, 1)


class TestSol144F06Blocks:
    def test_header_and_subcase_line(self, trim):
        txt = _text(*trim)
        assert "SOL 144 STATIC AEROELASTIC RESPONSE" in txt
        assert "TRIM = 1" in txt and "MACH = 0.9000" in txt

    def test_trim_variables_block(self, trim):
        txt = _text(*trim)
        assert "T R I M   V A R I A B L E S" in txt
        # Free vs prescribed labelling.
        assert "ANGLEA" in txt and "FREE" in txt
        assert "URDD3" in txt and "PRESCRIBED" in txt

    def test_stability_derivatives_block(self, trim):
        txt = _text(*trim)
        assert "S T A B I L I T Y   D E R I V A T I V E S" in txt
        assert "RIGID" in txt and "ELASTIC RESTRAINED" in txt

    def test_totals_block(self, trim):
        _bulk, result = trim
        txt = _text(*trim)
        assert "A E R O D Y N A M I C   T O T A L S" in txt
        assert "TOTAL CL" in txt and "TOTAL CMY" in txt
        # CL ~ 1.0 at the q=40 trim (W/S balance).
        assert result.total_cl == pytest.approx(1.0, abs=0.01)

    def test_divergence_block(self, trim):
        _bulk, result = trim
        txt = _text(*trim)
        assert "A E R O D Y N A M I C   D I V E R G E N C E" in txt
        # q=40 is far below the divergence pressure → small ratio, positive q_div.
        assert result.q_div is not None and result.q_div > result.q
        assert "Q / Q-DIV" in txt

    def test_shared_structural_blocks_present(self, trim):
        txt = _text(*trim)
        assert "D I S P L A C E M E N T   V E C T O R" in txt
        assert "F O R C E S   I N   B A R   E L E M E N T S" in txt
        assert "S T R E S S E S   I N   B A R   E L E M E N T S" in txt


class TestSol144AeroBoxBlock:
    def test_absent_without_request(self, trim):
        assert "B O X   P R E S S U R E S" not in _text(*trim)

    def test_present_with_aerof(self, trim):
        assert "B O X   P R E S S U R E S" in _text(*trim, aerof=True)

    def test_present_with_apres(self, trim):
        assert "B O X   P R E S S U R E S" in _text(*trim, apres=True)

    def test_one_row_per_box(self, trim):
        _bulk, result = trim
        txt = _text(*trim, aerof=True)
        # 80 boxes on the full-span deck → 80 data rows in the block.
        start = txt.index("B O X   P R E S S U R E S")
        block = txt[start:txt.index("* * * END OF JOB", start)]
        n_rows = sum(1 for ln in block.splitlines() if ln.strip().split()[:1] and ln.strip()[0].isdigit())
        assert n_rows == len(result.box_forces) == 80
