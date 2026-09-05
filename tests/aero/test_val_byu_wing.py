"""External-benchmark validation: BYU FLOW Lab VortexLattice.jl wing vs AVL.

Reproduces the "Steady-State Analysis of a Wing" example from
https://flow.byu.edu/VortexLattice.jl/dev/examples/ (itself validated against
AVL to < 0.1%) and asserts sbeam's rigid VLM matches the published coefficients.

This is a real external cross-check against an independent, AVL-validated VLM —
complementing the closed-form analytical gates. It also locks in the CM
moment-arm fix (1/4-chord bound vortex, not 3/4-chord collocation point).

Planform: root chord 2.2, tip 1.8, half-span 7.5, LE sweep 0.4, AR 7.5.
Condition: alpha 1deg + constant twist 2deg, reproduced as uniform 3deg
incidence on the flat planar mesh. Sref=30, cref=2, bref=15, moment about x=0.5.

Reference (VortexLattice.jl / AVL):
    CL = 0.24437 / 0.24454
    CM = -0.02085 / -0.02091   (about x=0.5)
    CDi = 0.00247 / 0.00248    (sbeam has no Trefftz-plane drag — not checked)
"""

from math import radians
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.vlm import solve_rigid_cl

_BDF = Path(__file__).resolve().parents[2] / "sample" / "val_vlm_byu_wing.bdf"

# Reference values (VortexLattice.jl, which matches AVL to < 0.1%)
CL_REF = 0.24437
CM_REF = -0.02085
ALPHA_DEG = 3.0          # 1deg AoA + 2deg uniform twist, folded into incidence
XREF = 0.5               # moment reference x (rref = [0.5, 0, 0])


@pytest.fixture(scope="module")
def result():
    assert _BDF.is_file(), f"missing benchmark BDF: {_BDF}"
    _cc, bulk = parse_bdf(str(_BDF))
    am = build_aero_model(bulk)
    return solve_rigid_cl(am.boxes, radians(ALPHA_DEG),
                          aeros=bulk.aeros, xref=XREF), am


def test_box_count(result):
    _r, am = result
    # 2 half-surfaces x 12 spanwise x 6 chordwise
    assert len(am.boxes) == 144


def test_CL_within_1pct_of_avl(result):
    r, _am = result
    assert r["CL"] == pytest.approx(CL_REF, rel=0.01), (
        f"CL = {r['CL']:.5f} vs AVL {CL_REF} "
        f"({100 * (r['CL'] - CL_REF) / CL_REF:+.2f}%)"
    )


def test_CM_within_2pct_of_avl(result):
    r, _am = result
    assert r["CM"] == pytest.approx(CM_REF, rel=0.02), (
        f"CM = {r['CM']:.5f} vs AVL {CM_REF} "
        f"({100 * (r['CM'] - CM_REF) / CM_REF:+.2f}%)"
    )


def test_CM_uses_quarter_chord_arm(result):
    """Regression guard for the moment-arm fix: with the (wrong) 3/4-chord
    collocation arm, CM would be ~-0.0415 (≈2x). Assert it is not."""
    r, _am = result
    assert abs(r["CM"]) < 0.030, (
        f"CM = {r['CM']:.5f} looks like the 3/4-chord-arm bug (~-0.0415); "
        "the load should act at the 1/4-chord bound vortex"
    )
