"""V-AE3 — independent unit-Cp force/moment cross-check.

Builds the aerodynamic box force/moment resultants TWO independent ways on the
same model and asserts the totals agree to <=1%:

  Path A (coupling path) — the actual SOL 144 chain:
      f_box = skj @ (ajj_inv_corr @ w)      (w = D_jx ANGLEA column = -n_z)
      Fz    = f_box[2::3].sum()
      My    = pitch_moment(f_box, boxes, x_ref)

  Path B (independent K-J) — solve_rigid_cl (sbeam/aero/vlm.py), which rebuilds
  its own AIC and Kutta-Joukowski resultants in a separate module:
      Fz = CL * S_ref ,   My = CM * S_ref * c_ref   (at unit q)

This is the discriminating gate AE13 lacked: the nearby checks
(test_ae1_step_e_moment.py, test_phase_b.py::test_tz_sum_vs_cl_magnitude) are
only SELF-consistent, so a common scale error or a factor-of-2 parity bug passes
them.  Path B re-derives gamma, cp = 2*gamma/chord and the moment from scratch,
so a scale/parity error in build_aero_model's Gamma->dCp conversion
(aero_model.py) or in skj/pitch_moment fails this test hard.

Why the two paths are comparable:
  * Neither target deck carries a WKK/AECORR correction, so build_aero_model
    sets ajj_inv_corr = solve(AJJ) scaled by 1/beta_pg then 2/chord -> dCp;
    solve_rigid_cl computes gamma = solve(A, rhs)/beta_pg and cp = 2*gamma/chord.
    Same physics, separately coded.
  * Excitation must match: solve_rigid_cl uses rhs = -(alpha*n_z) with NO W2GJ
    baseline.  HA144A HAS a W2GJ (wg != 0), so Path A is driven with the ANGLEA
    column ALONE (= -n_z), excluding aero.wg.  The system is linear, so
    alpha = 1 rad is exact, not a small-angle approximation.
  * Mach must match: effective Mach = bulk.aeros.mach (HA144A 0.9, rect_ar8 0.0)
    is passed to solve_rigid_cl so the beta_pg scaling is identical on both paths.

(Named to avoid collision with the unrelated "V-AE3a" trim-lift gate in
test_trim_urdd.py.)
"""

import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_djx
from sbeam.aero.vlm import solve_rigid_cl
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.coord_transform import get_transform
from sbeam.solver.sol144 import pitch_moment

SAMPLE = Path(__file__).parent.parent.parent / "sample"

DECKS = {
    "ha144a": SAMPLE / "ha144a_fullspan_sbeam.bdf",   # M=0.9, has W2GJ (excluded)
    "rect_ar8": SAMPLE / "val_vlm_rect_ar8.bdf",      # M=0.0, planar, no W2GJ
}


def _x_ref(bulk):
    """Moment reference x (RCSID origin in basic CID 0), as sol144 computes it."""
    if bulk.aeros.rcsid:
        origin, _ = get_transform(bulk.aeros.rcsid, bulk.cord2rs)
        return float(origin[0])
    return 0.0


@pytest.fixture(scope="module", params=sorted(DECKS), ids=sorted(DECKS))
def model(request):
    cc, bulk = parse_bdf(str(DECKS[request.param]))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index)
    return request.param, bulk, aero


def _cross_check(bulk, aero):
    """Return (Fz_coupling, Fz_indep, My_coupling, My_indep) at unit q, alpha=1."""
    x_ref = _x_ref(bulk)
    mach = bulk.aeros.mach

    # Path B (independent) — Kutta-Joukowski resultants from solve_rigid_cl.
    res = solve_rigid_cl(aero.boxes, alpha=1.0, beta=0.0,
                         aeros=bulk.aeros, xref=x_ref, mach=mach)
    Fz_indep = res["CL"] * bulk.aeros.sref
    My_indep = res["CM"] * bulk.aeros.sref * bulk.aeros.cref

    # Path A (coupling) — skj @ ajj_inv_corr @ w, alpha-only normalwash (no wg).
    w = build_djx(aero.boxes, ["ANGLEA"], bulk)[:, 0]   # = -n_z, matches rhs at alpha=1
    f_box = aero.skj @ (aero.ajj_inv_corr @ w)
    Fz_coupling = float(f_box[2::3].sum())
    My_coupling = pitch_moment(f_box, aero.boxes, x_ref)

    return Fz_coupling, Fz_indep, My_coupling, My_indep


def test_total_force_cross_check(model):
    name, bulk, aero = model
    Fz_c, Fz_i, _, _ = _cross_check(bulk, aero)
    assert Fz_c == pytest.approx(Fz_i, rel=0.01), (
        f"{name}: coupling-path Fz {Fz_c:.6g} != solve_rigid_cl CL*S {Fz_i:.6g} "
        f"(rel err {abs(Fz_c - Fz_i) / abs(Fz_i):.3%})"
    )


def test_total_moment_cross_check(model):
    name, bulk, aero = model
    Fz_c, Fz_i, My_c, My_i = _cross_check(bulk, aero)
    # Absolute floor guards against near-zero-normalisation artifacts on a
    # symmetric/planar deck (same trap AE8a documents): scale to the force level
    # via the reference chord.
    abs_floor = 0.01 * abs(Fz_i) * bulk.aeros.cref
    assert My_c == pytest.approx(My_i, rel=0.01, abs=abs_floor), (
        f"{name}: coupling-path My {My_c:.6g} != solve_rigid_cl CM*S*c {My_i:.6g} "
        f"(abs err {abs(My_c - My_i):.6g}, floor {abs_floor:.6g})"
    )
