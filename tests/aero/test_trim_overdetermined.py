"""V-C4 — over-determined (redundant-control) SOL 144 trim (Step 52 remainder).

The determined HA144A trim prescribes PITCH, URDD3, URDD5 and solves for the two
free variables (ANGLEA, ELEV) against the two SUPORT DOFs (Tz, Ry).  An
*over-determined* trim leaves an extra control free (here PITCH), so n_free=3 >
n_suport=2: the trim-equilibrium equality system is under-determined and the
solution is made unique by minimising the weighted-L2 TRIMOBJ objective subject
to the equilibrium equality, the TRIMCON inequalities, and the TRIMVAR bounds.

Gates:
  * With the objective min(PITCH²), the redundant variable is driven to its
    unconstrained optimum (≈0) and the remaining trim reproduces the determined
    ANGLEA/ELEV — a self-consistency check against the validated determined solve.
  * A TRIMCON PITCH ≥ p forces the constraint active (PITCH = p) and the rest of
    the trim re-balances.
  * The convex L2 objective is initial-guess insensitive (KC6).
"""

import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim
from sbeam.model.aero import Trim, Trimobj, Trimvar, Trimcon

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


def _model():
    cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
    return bulk, aero


@pytest.fixture(scope="module")
def determined_trim():
    bulk, aero = _model()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    return res


def _run_overdetermined(trimcons=None, init=0.0):
    """Over-determined HA144A (q=40): leave PITCH free, objective min(PITCH²)."""
    bulk, aero = _model()
    # New TRIM: prescribe only URDD3/URDD5 → ANGLEA, ELEV, PITCH all free (3 > 2).
    bulk.trims[99] = Trim(sid=99, mach=0.9, q=40.0,
                          vars={"URDD3": -32.174, "URDD5": 0.0})
    bulk.trimobjs[99] = Trimobj(sid=99, labels=["PITCH"], weights=[1.0])
    bulk.trimvars[1] = Trimvar(id=1, label="PITCH", init=init, lb=-1.0, ub=1.0)
    if trimcons:
        bulk.trimcons[99] = trimcons
    sc = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=99, trimobj_sid=99)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(bulk, sc, aero)


def test_overdetermined_reports_mode():
    res = _run_overdetermined()
    assert res.trim_mode == "over-determined"


def test_overdetermined_min_pitch_recovers_determined(determined_trim):
    """min(PITCH²) drives the redundant variable to ~0 and reproduces the
    determined ANGLEA/ELEV trim."""
    res = _run_overdetermined()
    assert res.trim_vars["PITCH"] == pytest.approx(0.0, abs=1e-6)
    assert res.trim_vars["ANGLEA"] == pytest.approx(
        determined_trim.trim_vars["ANGLEA"], rel=1e-4)
    assert res.trim_vars["ELEV"] == pytest.approx(
        determined_trim.trim_vars["ELEV"], rel=1e-4)


def test_overdetermined_trimcon_active():
    """A lower bound PITCH ≥ 0.01 forces the constraint active at the optimum."""
    cons = [Trimcon(sid=99, label="PITCH", sense="GE", rhs=0.01)]
    res = _run_overdetermined(trimcons=cons)
    assert res.trim_vars["PITCH"] == pytest.approx(0.01, abs=1e-6)


def test_overdetermined_initial_guess_insensitive(determined_trim):
    """The convex L2 objective converges to the same optimum from any start."""
    r_lo = _run_overdetermined(init=-0.5)
    r_hi = _run_overdetermined(init=+0.5)
    for lbl in ("ANGLEA", "ELEV", "PITCH"):
        assert r_lo.trim_vars[lbl] == pytest.approx(r_hi.trim_vars[lbl], abs=1e-6)


def test_overdetermined_missing_trimobj_raises():
    """An over-determined TRIM without any TRIMOBJ is rejected."""
    bulk, aero = _model()
    bulk.trims[98] = Trim(sid=98, mach=0.9, q=40.0,
                          vars={"URDD3": -32.174, "URDD5": 0.0})
    bulk.trimobjs.clear()
    sc = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=98)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match="TRIMOBJ"):
            run_sol144_trim(bulk, sc, aero)
