"""V-C-DIH — Step 58 dihedral / anhedral (±Γ) correctness gate.

Locks the SOL 144 chain (VLM → spline → force integration → trim) OUT of the
xy-plane, for both positive dihedral (Γ=+10°) and anhedral (Γ=−10°).  HA144A and
``val_vlm_rect_ar8`` are planar (z=0), so a latent ``(0,0,1)`` normal or an
Fz-only force resultant would pass every other test and only bite on the first
real non-planar wing — the AE13 validation-blind-spot class.  These permanent
gates exercise:

  * the geometric box normal ``n = (0, ∓sinΓ, cosΓ)`` (right wing; mirror left),
  * the 3-component force resultant (canted panels carry side force ``Fy``),
  * rigid ``CL ≈ CL_planar·cosΓ`` and per-semi-span ``Fy``,
  * symmetric ``Fy`` / roll / yaw cancellation over a full-span build,
  * a determined SOL 144 trim on a structured dihedral wing that closes the
    inertia-relief balance out of plane.

Finding (recorded): the architecture was already 3-component and geometry-driven
(``mesh_caero1`` derives the normal from z-bearing corners; ``build_skj`` emits
``area·normal·cp``), so Step 58 needed no production rewrite — only these decks +
gates and the reusable ``aero_moment_resultant`` helper.
"""

import math
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.vlm import solve_rigid_cl, build_ajj
from sbeam.aero.integration import build_skj
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim, aero_moment_resultant

SAMPLE = Path(__file__).parent.parent.parent / "sample"
GAMMA = math.radians(10.0)
COS, SIN = math.cos(GAMMA), math.sin(GAMMA)
ALPHA = math.radians(1.0)

# right-wing surface normal = (0, -SIGN*SIN, COS); SIGN=+1 dihedral, −1 anhedral
DECKS = {"val_vlm_dihedral.bdf": +1.0, "val_vlm_anhedral.bdf": -1.0}


def _rigid_aero(deck):
    _cc, bulk = parse_bdf(str(SAMPLE / deck))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        am = build_aero_model(bulk)
    return am, bulk


def _aoa_box_forces(boxes, alpha):
    """Per-box force [Fx,Fy,Fz] (force/q) at incidence alpha via the skj path."""
    A = build_ajj(boxes)
    rhs = np.array([-(alpha * b.normal[2]) for b in boxes])
    gamma = np.linalg.solve(A, rhs)
    dy = np.array([
        math.hypot(b.bound_b[1] - b.bound_a[1], b.bound_b[2] - b.bound_a[2])
        for b in boxes
    ])
    chord = np.array([b.area / dy[i] for i, b in enumerate(boxes)])
    cp = 2.0 * gamma / chord
    return (build_skj(boxes) @ cp).reshape(-1, 3)


# --------------------------------------------------------------------------- #
# 1. Geometric box normal — the anti-(0,0,1) guard, both signs.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("deck,sign", DECKS.items())
def test_box_normals_canted(deck, sign):
    am, _ = _rigid_aero(deck)
    for b in am.boxes:
        side = 1.0 if b.force_point[1] > 0 else -1.0            # +1 starboard
        target = np.array([0.0, -sign * SIN * side, COS])
        assert b.normal @ target == pytest.approx(1.0, abs=1e-12)
        assert abs(b.normal[0]) < 1e-12                          # chord advances along x̂


# --------------------------------------------------------------------------- #
# 2. Per-box side-force ratio + symmetric cancellation (skj 3-component path).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("deck,sign", DECKS.items())
def test_side_force_ratio_and_cancellation(deck, sign):
    am, _ = _rigid_aero(deck)
    F = _aoa_box_forces(am.boxes, ALPHA)
    # Per box: Fy/Fz == n_y/n_z == ∓tanΓ (exact — force is ∥ normal).
    for j, b in enumerate(am.boxes):
        assert F[j, 1] / F[j, 2] == pytest.approx(b.normal[1] / b.normal[2], abs=1e-10)
    # Side force cancels over the full-span symmetric build; lift is non-trivial.
    assert F[:, 1].sum() == pytest.approx(0.0, abs=1e-10 * abs(F[:, 2].sum()))
    assert abs(F[:, 2].sum()) > 1e-3


# --------------------------------------------------------------------------- #
# 3. Rigid CL ≈ CL_planar·cosΓ (backlog acceptance) + dihedral/anhedral symmetry.
# --------------------------------------------------------------------------- #
def test_rigid_cl_cos_gamma():
    am_p, bulk_p = _rigid_aero("val_vlm_rect_ar8.bdf")
    cl_planar = solve_rigid_cl(am_p.boxes, ALPHA, aeros=bulk_p.aeros)["CL"]

    cls = {}
    for deck in DECKS:
        am, bulk = _rigid_aero(deck)
        r = solve_rigid_cl(am.boxes, ALPHA, aeros=bulk.aeros)
        cls[deck] = r["CL"]
        assert r["CY"] == pytest.approx(0.0, abs=1e-9)            # side force cancels
        assert r["CL"] == pytest.approx(cl_planar * COS, rel=0.01)

    # cos is even → dihedral and anhedral give identical CL.
    assert cls["val_vlm_dihedral.bdf"] == pytest.approx(
        cls["val_vlm_anhedral.bdf"], rel=1e-12
    )


# --------------------------------------------------------------------------- #
# 4. Structured determined trim closes out of plane (spline + force + trim).
# --------------------------------------------------------------------------- #
def test_dihedral_trim_closes_out_of_plane():
    _cc, bulk = parse_bdf(str(SAMPLE / "val_dihedral_trim.bdf"))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        res = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero
        )

    bf = res.box_forces                       # (n_box, 3) physical aero force
    Fy, Fz = bf[:, 1].sum(), bf[:, 2].sum()
    weight = 10.0 * 9.81                       # total mass × g  (URDD3 = −9.81)

    # Inertia-relief closure: aero vertical force opposes the 1g inertial load.
    assert abs(Fz) == pytest.approx(weight, rel=1e-3)
    # Symmetric build → side force / roll / yaw all cancel.
    assert Fy == pytest.approx(0.0, abs=1e-8 * abs(Fz))
    ref = np.zeros(3)
    Mx, My, Mz = aero_moment_resultant(bf, aero.boxes, ref)
    assert Mx == pytest.approx(0.0, abs=1e-8 * abs(Fz))          # roll
    assert Mz == pytest.approx(0.0, abs=1e-8 * abs(Fz))          # yaw

    # The wing is genuinely out of plane (regression against a flattened deck).
    assert max(abs(b.force_point[2]) for b in aero.boxes) > 0.1
