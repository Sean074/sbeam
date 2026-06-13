"""V-LAT — lateral/directional rate-aero derivative columns (Step 52 remainder).

`build_djx` already produces the ROLL/YAW/SIDES quasi-steady normalwash columns;
this gate locks the roll/yaw *moment* recovery added in Step 52 to
`_compute_rigid_derivs` (CMX = roll, CMZ = yaw, both about the AERO reference and
non-dimensionalised by S_ref·b_ref).  From these come the damping derivative C_lp
(ROLL→CMX), C_nr (YAW→CMZ), and the dihedral effect C_lβ (SIDES→CMX).

Sign convention note: moments are the full 3-component cross-product resultant
(`aero_moment_resultant`) in sbeam's z-up / y-starboard aero frame — the same
helper and frame the V-C-DIH dihedral gate uses.  These assertions are therefore
written against that frame's handedness (and its dihedral sign signature), not a
textbook z-down body-axis convention; the magnitudes and the ±Γ symmetry are the
physically meaningful, convention-independent content.

Decks (full-span rectangular AR=8, S_ref=b_ref=8, c_ref=1):
  * val_vlm_rect_ar8  — planar  (C_lβ must vanish)
  * val_vlm_dihedral  — +10° Γ  (C_lβ non-zero)
  * val_vlm_anhedral  — −10° Γ  (C_lβ equal and opposite)
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bulk_file
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_djx
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import _compute_rigid_derivs

SAMPLE = Path(__file__).parent.parent.parent / "sample"
LABELS = ["ANGLEA", "ROLL", "YAW", "SIDES"]


def _derivs(name):
    bulk = parse_bulk_file(str(SAMPLE / f"{name}.bdf"))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
    djx = build_djx(aero.boxes, LABELS, bulk)
    return _compute_rigid_derivs(aero, djx, LABELS, bulk, 0.0, np.zeros(3))


@pytest.fixture(scope="module")
def planar():
    return _derivs("val_vlm_rect_ar8")


@pytest.fixture(scope="module")
def dihedral():
    return _derivs("val_vlm_dihedral")


@pytest.fixture(scope="module")
def anhedral():
    return _derivs("val_vlm_anhedral")


def test_roll_rate_produces_roll_damping(planar):
    """The ROLL column produces a substantial rolling moment (C_lp); its
    magnitude sits in the lifting-line / strip-theory band for an AR=8 wing.

    Strip theory gives |C_lp| = a0/6 ≈ 1.05 (a0 = 2π); induced downwash from the
    rolling load reduces this for finite AR — the VLM value lands around ~0.5."""
    c_lp = planar["ROLL"]["CMX"]
    assert abs(c_lp) > 0.3, f"roll damping too weak: C_lp={c_lp}"
    assert abs(c_lp) < 2 * np.pi / 6 * 1.05, f"roll damping exceeds strip-theory bound: {c_lp}"
    assert abs(c_lp) == pytest.approx(0.54, abs=0.15)


def test_roll_column_decouples_on_planar_wing(planar):
    """A planar wing's roll-rate column is a pure rolling moment — no net lift,
    pitch, or yaw."""
    d = planar["ROLL"]
    assert d["CZ"] == pytest.approx(0.0, abs=1e-9)
    assert d["CMY"] == pytest.approx(0.0, abs=1e-9)
    assert d["CMZ"] == pytest.approx(0.0, abs=1e-9)


def test_yaw_and_sides_vanish_on_planar_wing(planar):
    """With no vertical surface, the yaw-rate and sideslip columns (which act
    through the panel y-normal) produce no load on a flat wing."""
    for lbl in ("YAW", "SIDES"):
        for comp in ("CZ", "CMY", "CMX", "CMZ"):
            assert planar[lbl][comp] == pytest.approx(0.0, abs=1e-9), f"{lbl} {comp}"


def test_dihedral_effect_clbeta_sign_flips(dihedral, anhedral, planar):
    """C_lβ (SIDES→CMX) is the dihedral effect: zero for a planar wing, non-zero
    once the wing is canted, and equal-and-opposite between +Γ and −Γ."""
    clb_plan = planar["SIDES"]["CMX"]
    clb_dih = dihedral["SIDES"]["CMX"]
    clb_anh = anhedral["SIDES"]["CMX"]
    assert clb_plan == pytest.approx(0.0, abs=1e-9)
    assert abs(clb_dih) > 1e-3, f"dihedral C_lβ vanished: {clb_dih}"
    assert clb_dih == pytest.approx(-clb_anh, rel=1e-6)


def test_roll_damping_insensitive_to_small_dihedral(planar, dihedral, anhedral):
    """Roll damping is governed by the (barely changed) projected planform, so a
    ±10° cant leaves |C_lp| nearly unchanged and identical for ±Γ."""
    assert dihedral["ROLL"]["CMX"] == pytest.approx(anhedral["ROLL"]["CMX"], rel=1e-6)
    assert dihedral["ROLL"]["CMX"] == pytest.approx(planar["ROLL"]["CMX"], rel=0.05)
