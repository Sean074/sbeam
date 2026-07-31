"""V-B3g — solver-level ATTACH regression (DEF-H1, 2026-07-31).

The V-B3 operator gates in ``test_spline.py`` pin the ATTACH ``g_slope`` rows;
this module gates what those rows are *for* — the aeroelastic feedback that
reaches the SOL 144 flexible solve through
``(K_aa − q·Q_aa) u = q·f_g``.

Model: ``val_spline2_cantilever.bdf`` (4 CBARs along global Y, flat 4-box
CAERO1 in the XY plane, root SPC).  A uniform 1° built-in incidence is injected
in-memory as a ``W2GJ`` so the baseline load ``f_g`` is non-zero.  The panel is
splined two ways:

  * SPLINE2 — the validated NASTRAN beam spline over all 5 grids;
  * ATTACH  — one card per box, each rigidly tied to the nearest grid.

Both sample the same underlying rigid-body kinematics, so the flexible lift
must move the same way.  The elastic axis sits at the leading edge (x=0) and
the ¼-chord force line at x=0.25, i.e. *aft* of it, so the aero moment is
nose-down and both routes must produce WASHOUT (flexible lift below rigid).

DEF-H1 regression value: with the pre-fix ``g_slope`` rows (Ry=−1, Rx=+1) the
ATTACH route produced washIN — L/L_rigid = 1.071 at q=800 against the SPLINE2
route's 0.988, a 7% lift error of the wrong sign, plus sign-inverted divergence
and trim behaviour.  ``test_attach_matches_spline2_flexible_sign`` fails on that
code.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.load_vector import build_grid_index
from sbeam.aero.aero_model import build_aero_model
from sbeam.model.aero import W2gj, Attach
from sbeam.solver.sol144 import run_aeroelastic_static

BDF_PATH = (
    Path(__file__).parent.parent / "integration" / "bdf" / "val_spline2_cantilever.bdf"
)

ALPHA = np.deg2rad(1.0)   # uniform built-in incidence (W2GJ, nose-up positive)
Q_TEST = 800.0            # well below this cantilever's divergence q
BOX_IDS = [200, 201, 202, 203]
NEAREST_GRID = [2, 3, 4, 5]   # grid nearest each box centre along the span


def _build_model(route: str, e_scale: float = 1.0):
    """Parse the cantilever deck and spline it via *route* ('spline2'|'attach')."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    bulk.w2gjs[1] = W2gj(sid=1, caero_eid=200, data=[ALPHA] * len(BOX_IDS))

    if e_scale != 1.0:
        mat = bulk.mat1s[1]
        bulk.mat1s[1] = type(mat)(
            **{**mat.__dict__, "E": mat.E * e_scale, "G": mat.G * e_scale}
        )

    if route == "attach":
        bulk.spline2s.clear()
        for i, (box_id, gid) in enumerate(zip(BOX_IDS, NEAREST_GRID)):
            bulk.attaches[400 + i] = Attach(
                eid=400 + i, caero=200, id1=box_id, id2=box_id, grid=gid, cid=0
            )

    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
    return bulk, aero


def _rigid_lift(aero) -> float:
    """Total Z force per unit q with no elastic deflection."""
    cp = aero.ajj_inv_corr @ aero.wg
    return float(sum(b.area * b.normal[2] * cp[j] for j, b in enumerate(aero.boxes)))


def _flexible_lift_ratio(bulk, aero, q: float) -> float:
    """Flexible total lift at *q*, normalised by the rigid lift at the same q."""
    subcase = SubcaseControl(subcase_id=1, spc_sid=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = run_aeroelastic_static(bulk, subcase, aero, q=q)
    w = aero.wg + aero.djk @ (aero.g_slope @ result.displacements)
    cp = aero.ajj_inv_corr @ w
    lift = float(sum(b.area * b.normal[2] * cp[j] for j, b in enumerate(aero.boxes)))
    return lift / _rigid_lift(aero)


@pytest.fixture(scope="module")
def ratios():
    return {
        route: _flexible_lift_ratio(*_build_model(route), q=Q_TEST)
        for route in ("spline2", "attach")
    }


class TestAttachFlexibleFeedback:
    """V-B3g: ATTACH aeroelastic feedback must agree with SPLINE2."""

    def test_spline2_route_washes_out(self, ratios):
        """Baseline: the validated SPLINE2 route gives washout on this deck."""
        assert ratios["spline2"] < 1.0, (
            f"SPLINE2 reference route must wash out; ratio={ratios['spline2']:.5f}"
        )

    def test_attach_matches_spline2_flexible_sign(self, ratios):
        """ATTACH must wash out too, and by a comparable amount (DEF-H1).

        Sign agreement is the load-bearing assertion — the pre-fix code washed
        IN.  The 3% magnitude band allows for the two routes' different span
        discretisation (piecewise-constant per-box attachment vs beam spline).
        """
        assert ratios["attach"] < 1.0, (
            f"ATTACH must wash out like SPLINE2, not wash in; "
            f"ratio={ratios['attach']:.5f} (SPLINE2 {ratios['spline2']:.5f})"
        )
        assert ratios["attach"] == pytest.approx(ratios["spline2"], rel=0.03), (
            f"ATTACH flexible lift {ratios['attach']:.5f} disagrees with "
            f"SPLINE2 {ratios['spline2']:.5f} by more than 3%"
        )

    @pytest.mark.parametrize("route", ["spline2", "attach"])
    def test_stiff_limit_converges_to_rigid(self, route):
        """Both routes → rigid lift as the structure is stiffened by 1e6."""
        ratio = _flexible_lift_ratio(*_build_model(route, e_scale=1e6), q=Q_TEST)
        assert ratio == pytest.approx(1.0, abs=1e-6), (
            f"{route} stiff-limit ratio {ratio:.9f} did not converge to rigid"
        )
