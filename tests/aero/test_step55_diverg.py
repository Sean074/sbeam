"""Step 55 — DIVERG-card divergence sweep, mode shape, and V_div.

Covers the divergence eigen-core (`_divergence_roots`) against a closed-form
2-DOF system, the DIVERG-card-driven sweep on the full-span HA144A deck
(consistency with the already-validated single critical `q_div`, sorted roots,
mode shapes, multi-Mach), the `RHOREF → V_div` mapping, the DIVERG bulk-card
parser, and the f06 AERODYNAMIC DIVERGENCE sweep block.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Diverg
from sbeam.solver.sol144 import (
    run_sol144_trim, run_sol144_diverg, _divergence_roots,
)
from sbeam.results.f06_writer import build_f06_sol144_diverg_text

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


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
        aero = build_aero_model(bulk, grid_index=gi)
    return bulk, aero


def _sweep(bulk, aero, nroots=3, rhoref=1.225, machs=None):
    mach = bulk.aeros.mach
    bulk.divergs[10] = Diverg(
        sid=10, nroots=nroots, rhoref=rhoref, machs=machs or [mach])
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

    def test_vdiv_mapping(self, ha144a):
        rho = 1.225
        roots = _sweep(*ha144a, rhoref=rho).mach_results[0].roots
        for r in roots:
            assert r.v_div == pytest.approx(np.sqrt(2.0 * r.q_div / rho))

    def test_vdiv_omitted_without_rhoref(self, ha144a):
        roots = _sweep(*ha144a, rhoref=0.0).mach_results[0].roots
        assert all(r.v_div is None for r in roots)

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


# --------------------------------------------------------------------------- #
# DIVERG bulk-card parser (RHOREF in field 4, Mach list field 5+)
# --------------------------------------------------------------------------- #
class TestDivergParser:
    def test_rhoref_and_machs(self, tmp_path):
        deck = tmp_path / "d.bdf"
        deck.write_text(
            "SOL 144\n"
            "CEND\n"
            "BEGIN BULK\n"
            "DIVERG  5       3       1.225   0.0     0.6     0.85\n"
            "ENDDATA\n"
        )
        _cc, bulk = parse_bdf(str(deck))
        d = bulk.divergs[5]
        assert d.nroots == 3
        assert d.rhoref == pytest.approx(1.225)
        assert d.machs == pytest.approx([0.0, 0.6, 0.85])

    def test_rhoref_optional(self, tmp_path):
        deck = tmp_path / "d.bdf"
        deck.write_text(
            "SOL 144\nCEND\nBEGIN BULK\n"
            "DIVERG  7       2\n"
            "ENDDATA\n"
        )
        _cc, bulk = parse_bdf(str(deck))
        d = bulk.divergs[7]
        assert d.nroots == 2 and d.rhoref == 0.0 and d.machs == []


# --------------------------------------------------------------------------- #
# f06 AERODYNAMIC DIVERGENCE sweep block
# --------------------------------------------------------------------------- #
class TestDivergF06:
    def test_block_contents(self, ha144a):
        bulk, aero = ha144a
        res = _sweep(bulk, aero, nroots=2, rhoref=1.225)
        sc = SubcaseControl(subcase_id=2, spc_sid=1, diverg_sid=10)
        cc = CaseControl(sol=144, title="HA144A diverg", subcases=[sc])
        txt = build_f06_sol144_diverg_text(cc, bulk, res, 2)
        assert "A E R O D Y N A M I C   D I V E R G E N C E" in txt
        assert "ROOT NO." in txt and "Q-DIV" in txt and "V-DIV" in txt
        assert "D I V E R G E N C E   M O D E   S H A P E" in txt
        # Two roots → two mode-shape blocks.
        assert txt.count("M O D E   S H A P E") == 2

    def test_vdiv_column_absent_without_rhoref(self, ha144a):
        bulk, aero = ha144a
        res = _sweep(bulk, aero, nroots=1, rhoref=0.0)
        sc = SubcaseControl(subcase_id=2, spc_sid=1, diverg_sid=10)
        cc = CaseControl(sol=144, title="HA144A diverg", subcases=[sc])
        txt = build_f06_sol144_diverg_text(cc, bulk, res, 2)
        assert "V-DIV" not in txt
