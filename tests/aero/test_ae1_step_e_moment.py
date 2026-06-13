"""V-AE1 Step E gate — moment/force-transfer consistency.

AE1 Step E single-sources the nose-up-positive pitching-moment convention
(`sol144._pitch_moment`).  The substantive sign fix landed in Step A; this gate
locks in the remaining invariant that the moment which actually drives the Schur
trim — carried through the `g_disp` virtual-work path onto the SUPORT Ry DOF —
agrees in sign AND magnitude with the direct box-moment formula.

For a unit trim-label aero load on HA144A:
  * total Fz from `g_disp.T @ f_box` (virtual work) == direct Σ Fz, and
  * total pitching moment about the SUPORT from the virtual-work g-set force
    field == `_pitch_moment(f_box, boxes, x_ref)` (the direct formula).

A sign flip or a parity/factor error in the force transfer would break this gate
immediately.  When Step D lands, its V-AE1c unit-Cp force check should extend
this class rather than add a parallel gate.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_djx
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.coord_transform import _get_transform
from sbeam.solver.sol144 import _pitch_moment

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


@pytest.fixture(scope="module")
def ha144a():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index)
    return bulk, aero, grid_index


def _x_ref(bulk):
    """Moment reference x (RCSID origin in basic CID 0), as sol144 computes it."""
    if bulk.aeros.rcsid:
        origin, _ = _get_transform(bulk.aeros.rcsid, bulk.cord2rs)
        return float(origin[0])
    return 0.0


def _vw_force_and_moment(bulk, aero, grid_index, f_box, x_ref):
    """Total Fz and nose-up-positive My about x_ref from the g_disp force field."""
    f_g = aero.g_disp.T @ f_box
    Fz = 0.0
    My = 0.0
    for gid, gi in grid_index.items():
        g = bulk.grids[gid]
        Fz += f_g[6 * gi + 2]
        My += -f_g[6 * gi + 2] * (g.x - x_ref) + f_g[6 * gi + 4]
    return Fz, My


class TestStepEMomentConsistency:
    """g_disp virtual-work transfer agrees with the direct _pitch_moment helper."""

    @pytest.mark.parametrize("label", ["ANGLEA", "ELEV"])
    def test_force_and_moment_transfer(self, ha144a, label):
        bulk, aero, grid_index = ha144a
        x_ref = _x_ref(bulk)

        djx = build_djx(aero.boxes, [label], bulk)
        gamma = aero.ajj_inv_corr @ djx[:, 0]
        f_box = aero.skj @ gamma

        Fz_direct = float(f_box[2::3].sum())
        My_direct = _pitch_moment(f_box, aero.boxes, x_ref)

        Fz_vw, My_vw = _vw_force_and_moment(bulk, aero, grid_index, f_box, x_ref)

        # Force transfer is exact by virtual work.
        assert Fz_vw == pytest.approx(Fz_direct, abs=1e-9), (
            f"{label}: VW Fz {Fz_vw} != direct {Fz_direct}"
        )
        # Moment transfer must match in sign and magnitude.
        assert My_vw == pytest.approx(My_direct, rel=1e-6), (
            f"{label}: VW My {My_vw} != direct {My_direct} "
            "(moment-sign/force-transfer inconsistency)"
        )

    def test_anglea_moment_is_nose_down(self, ha144a):
        """Positive ANGLEA on a wing aft of the reference gives nose-down (My < 0).

        Locks the absolute sign of the convention, not just internal consistency:
        a positive incidence load aft of x_ref must produce a negative (nose-down)
        pitching moment, matching solve_rigid_cl.CMα < 0 for HA144A.
        """
        bulk, aero, grid_index = ha144a
        x_ref = _x_ref(bulk)
        djx = build_djx(aero.boxes, ["ANGLEA"], bulk)
        f_box = aero.skj @ (aero.ajj_inv_corr @ djx[:, 0])
        My = _pitch_moment(f_box, aero.boxes, x_ref)
        assert My < 0, f"ANGLEA pitching moment {My} should be nose-down (< 0)"
