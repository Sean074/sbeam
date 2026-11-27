"""Step 55 — DIVERG-card divergence sweep and mode shape.

Covers the divergence eigen-core (`_divergence_roots`) against a closed-form
2-DOF system, the DIVERG-card-driven sweep on the full-span HA144A deck
(consistency with the already-validated single critical `q_div`, sorted roots,
mode shapes, multi-Mach), the DIVERG bulk-card parser in MSC's layout (#73), and
the f06 AERODYNAMIC DIVERGENCE sweep block.
"""

import warnings

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Diverg
from sbeam.solver.sol144 import (
    run_sol144_trim, run_sol144_diverg, _divergence_roots,
)
from sbeam.results.f06_writer import build_f06_sol144_diverg_text
from tests.samples import sample_path

BDF_PATH = sample_path("ha144a_fullspan_sbeam.bdf")


# --------------------------------------------------------------------------- #
# Closed-form eigen-core
# --------------------------------------------------------------------------- #
class TestDivergenceRootsClosedForm:
    def test_diagonal_roots_sorted_ascending(self):
        # K = I, Q = diag(2, 5) → K^-1 Q eigenvalues {2, 5} = 1/q
        # → q = {0.5, 0.2}; lowest divergence pressure first.
        K = np.eye(2)
        Q = np.diag([2.0, 5.0])
        roots = _divergence_roots(K, Q, nroots=2)
        qs = [q for q, _ in roots]
        assert qs == pytest.approx([0.2, 0.5])

    def test_negative_and_complex_eigenvalues_filtered(self):
        # A negative 1/q (stiffening DOF) is not a physical divergence root.
        K = np.eye(2)
        Q = np.diag([4.0, -3.0])
        roots = _divergence_roots(K, Q, nroots=5)
        assert len(roots) == 1
        assert roots[0][0] == pytest.approx(0.25)

    def test_nroots_truncates(self):
        K = np.eye(3)
        Q = np.diag([2.0, 4.0, 8.0])           # 1/q = 2,4,8 → q = .5,.25,.125
        roots = _divergence_roots(K, Q, nroots=2)
        assert [q for q, _ in roots] == pytest.approx([0.125, 0.25])

    def test_no_divergence_returns_empty(self):
        K = np.eye(2)
        Q = np.diag([-1.0, -2.0])              # purely stiffening → no positive root
        assert _divergence_roots(K, Q, nroots=3) == []


# --------------------------------------------------------------------------- #
# DIVERG-card sweep on the HA144A full-span deck
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def ha144a():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi, mach=bulk.trims[1].mach)
    return bulk, aero


def _sweep(bulk, aero, nroots=3, machs=None, card=None):
    """Run DIVERG SID 10, built from ``nroots``/``machs`` or read from ``card`` text."""
    if card is None:
        card = Diverg(sid=10, nroots=nroots, machs=machs or [aero.mach])
    bulk.divergs[10] = card
    sc = SubcaseControl(subcase_id=2, spc_sid=1, diverg_sid=10)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_diverg(bulk, sc, aero)


class TestDivergSweep:
    def test_lowest_root_matches_validated_qdiv(self, ha144a):
        # The Step 55 sweep and the validated single-q_div trim path solve the
        # same restrained-l-set eigenproblem; the sweep's lowest positive root
        # must reproduce the trim q_div to machine precision (V-C2).
        bulk, aero = ha144a
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            trim = run_sol144_trim(
                bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        roots = _sweep(bulk, aero).mach_results[0].roots
        assert roots[0].q_div == pytest.approx(trim.q_div, rel=1e-9)

    def test_roots_sorted_and_positive(self, ha144a):
        roots = _sweep(*ha144a).mach_results[0].roots
        qs = [r.q_div for r in roots]
        assert len(qs) >= 1
        assert all(q > 0 for q in qs)
        assert qs == sorted(qs)

    def test_mode_shape_normalised_and_sized(self, ha144a):
        bulk, _ = ha144a
        n_dofs = 6 * len(build_grid_index(bulk))
        roots = _sweep(*ha144a).mach_results[0].roots
        for r in roots:
            assert r.mode_shape.shape == (n_dofs,)
            assert np.max(np.abs(r.mode_shape)) == pytest.approx(1.0)

    def test_multi_mach_sweep(self, ha144a):
        res = _sweep(*ha144a, machs=[0.0, 0.6])
        assert [mr.mach for mr in res.mach_results] == [0.0, 0.6]
        # Compressibility lowers divergence q: q_div(M=0.6) < q_div(M=0).
        q0 = res.mach_results[0].roots[0].q_div
        q6 = res.mach_results[1].roots[0].q_div
        assert q6 < q0

    def test_msc_example_card_sweeps_its_three_machs(self, ha144a):
        """#73: QRG p.1603's example ran Mach 0.8 and 0.9 only (0.5 was read as RHOREF)."""
        bulk, aero = ha144a
        card = parse_bulk_data(["DIVERG,10,2,.5,.8,.9"]).divergs[10]
        res = _sweep(bulk, aero, card=card)
        assert [mr.mach for mr in res.mach_results] == [0.5, 0.8, 0.9]
        alone = _sweep(bulk, aero, nroots=2, machs=[0.5]).mach_results[0].roots
        assert res.mach_results[0].roots[0].q_div == pytest.approx(alone[0].q_div, rel=1e-12)

    def test_msc_incompressible_example_runs_at_mach_zero(self, ha144a):
        """AAUG 2023.1 p.148: 'DIVERG 100 5 0.0' is Mach 0.0, five roots; it ran at the
        AEROS Mach instead, with 0.0 taken as 'no RHOREF'."""
        bulk, aero = ha144a
        card = parse_bulk_data(["DIVERG,10,5,0.0"]).divergs[10]
        res = _sweep(bulk, aero, card=card)
        assert [mr.mach for mr in res.mach_results] == [0.0]
        assert aero.mach != 0.0            # the old reading would have run at this Mach


# --------------------------------------------------------------------------- #
# DIVERG bulk-card parser: MSC layout, Mach numbers from field 4 (#73)
# --------------------------------------------------------------------------- #
class TestDivergParser:
    def test_no_mach_is_refused(self):
        """#87: an empty list ran at the sbeam-only AEROS Mach, which is gone."""
        with pytest.raises(ValueError, match="DIVERG 7: no Mach number given"):
            parse_bulk_data(["DIVERG,7,2"])

    @pytest.mark.parametrize("line, sid, nroots, machs", [
        ("DIVERG,70,2,.5,.8,.9", 70, 2, [0.5, 0.8, 0.9]),       # QRG p.1603 example
        ("DIVERG     100      5       0.0", 100, 5, [0.0]),     # AAUG p.148 example
        ("DIVERG,7,,.6", 7, 1, [0.6]),                          # NROOT default = 1
        ("DIVERG,7,2,.5,.8,,", 7, 2, [0.5, 0.8]),               # trailing blanks
    ], ids=["qrg", "aaug", "nroot-default", "trailing-blank"])
    def test_fields(self, line, sid, nroots, machs):
        d = parse_bulk_data([line]).divergs[sid]
        assert (d.nroots, d.machs) == (nroots, pytest.approx(machs))

    def test_machs_continue_onto_continuations(self):
        def fixed(*x):
            return "".join(f"{v:<8}" for v in x)
        d = parse_bulk_data([fixed("DIVERG", "8", "1", ".5", ".6", ".7", ".8", ".85", ".9", "+D"),
                             fixed("+D", ".95", ".98")]).divergs[8]
        assert d.machs == pytest.approx([.5, .6, .7, .8, .85, .9, .95, .98])

    @pytest.mark.parametrize("lines, match", [
        (["DIVERG,7,2,.5,,.9"], r"blank Mach field terminates the input.*\['\.9'\]"),
        (["DIVERG,8,1,.5,.6,.7,.8,.85,,+D", "+D,.95"], "blank Mach field terminates"),
        (["DIVERG,7,2,.5,.8,.5"], "must be distinct"),
        (["DIVERG,7,2,-.5"], "non-negative"),
        (["DIVERG,7,0,.5"], "NROOT must be >= 1"),
    ], ids=["blank-then-mach", "blank-before-continuation", "duplicate", "negative", "nroot"])
    def test_refused(self, lines, match):
        """QRG p.1603 remarks 3 and 4; a Mach after a blank is one MSC never reads."""
        with pytest.raises(ValueError, match=match):
            parse_bulk_data(lines)


# --------------------------------------------------------------------------- #
# f06 AERODYNAMIC DIVERGENCE sweep block
# --------------------------------------------------------------------------- #
class TestDivergF06:
    def test_block_contents(self, ha144a):
        bulk, aero = ha144a
        res = _sweep(bulk, aero, nroots=2)
        sc = SubcaseControl(subcase_id=2, spc_sid=1, diverg_sid=10)
        cc = CaseControl(sol=144, title="HA144A diverg", subcases=[sc])
        txt = build_f06_sol144_diverg_text(cc, bulk, res, 2)
        assert "A E R O D Y N A M I C   D I V E R G E N C E" in txt
        assert "ROOT NO." in txt and "Q-DIV" in txt
        assert "D I V E R G E N C E   M O D E   S H A P E" in txt
        # Two roots → two mode-shape blocks.
        assert txt.count("M O D E   S H A P E") == 2

    def test_reports_q_only_as_msc_does(self, ha144a):
        """QRG p.1603 remark 2: divergence dynamic pressures are printed (#73)."""
        bulk, aero = ha144a
        res = _sweep(bulk, aero, nroots=1)
        sc = SubcaseControl(subcase_id=2, spc_sid=1, diverg_sid=10)
        cc = CaseControl(sol=144, title="HA144A diverg", subcases=[sc])
        txt = build_f06_sol144_diverg_text(cc, bulk, res, 2)
        assert "V-DIV" not in txt and "RHOREF" not in txt
