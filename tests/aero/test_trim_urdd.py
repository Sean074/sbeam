"""AE5 + AE7 tests — RCSID-frame URDD transform and inertial trim columns.

Unit tests:
  TestUrddRcsidTransform — verify R_rcsid correctly maps URDD3 from z-down
      RCSID frame to basic frame (AE5 math).
  TestInertialCols — verify _build_inertial_cols entries for translational
      and rotational URDD labels (AE7 matrix structure).

Integration test:
  TestTrimSignAe5 — end-to-end trim on the val_spline2_cantilever model
      with RCSID z-down and URDD3=-32.174 (NASTRAN 1g convention).
      Gate V-AE3a: trim lift must be POSITIVE (sign-of-lift regression
      that was broken by the AE5 defect).
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.assembly.coord_transform import _get_transform
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Aeros, Aestat, Trim
from sbeam.model.bulk_data import BulkData
from sbeam.model.constraint import Suport
from sbeam.model.coordinate_system import Cord2r
from sbeam.model.mass import Conm2
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.solver.sol144 import _build_inertial_cols, run_sol144_trim

BDF_PATH = Path(__file__).parent.parent / "integration" / "bdf" / "val_spline2_cantilever.bdf"

G_FT_S2 = 32.174   # standard gravity, ft/s²


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _z_down_cord2r(cid: int) -> Cord2r:
    """CORD2R whose local z-axis points in the −z_basic direction.

    A=(0,0,0), B=(0,0,-1) → k=(0,0,-1) (z_local = −z_basic)
    C=(1,0,0) → i=(1,0,0) (x_local = +x_basic)
    R = [[1,0,0],[0,-1,0],[0,0,-1]]
    URDD3_basic = R @ [0,0,URDD3_local] → basic_z = -URDD3_local
    """
    return Cord2r(cid=cid, rid=0, a=(0.0, 0.0, 0.0), b=(0.0, 0.0, -1.0), c=(1.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# Unit tests — RCSID coordinate transform math
# ---------------------------------------------------------------------------

class TestUrddRcsidTransform:

    def test_z_down_rcsid_transforms_urdd3(self):
        """CORD2R with local z pointing -z_basic: URDD3=-g → basic z = +g."""
        cord2rs = {99: _z_down_cord2r(99)}
        _, R = _get_transform(99, cord2rs)
        # R[2,2] must be -1 (local z = -basic z)
        assert abs(R[2, 2] - (-1.0)) < 1e-12, f"R[2,2] = {R[2,2]}, expected -1"
        v_basic = R @ np.array([0.0, 0.0, -G_FT_S2])
        assert abs(v_basic[2] - G_FT_S2) < 1e-10, \
            f"Transformed URDD3: basic z = {v_basic[2]}, expected {G_FT_S2}"

    def test_identity_rcsid_leaves_urdd3_unchanged(self):
        """RCSID=0 (identity): URDD3 value must pass through unchanged."""
        _, R = _get_transform(0, {})
        v_basic = R @ np.array([0.0, 0.0, -G_FT_S2])
        assert abs(v_basic[2] - (-G_FT_S2)) < 1e-12


# ---------------------------------------------------------------------------
# Unit tests — _build_inertial_cols matrix entries
# ---------------------------------------------------------------------------

def _minimal_bulk_one_conm2(m: float, gx: float, gy: float, gz: float,
                              i11: float = 0.0, i22: float = 0.0, i33: float = 0.0):
    """BulkData with one GRID at (gx,gy,gz) and one CONM2 of mass m."""
    from sbeam.model.grid import Grid
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, cp=0, x=gx, y=gy, z=gz, cd=0)
    bulk.conm2s[1] = Conm2(eid=1, gid=1, cid=0, m=m, i11=i11, i22=i22, i33=i33)
    return bulk


class TestInertialCols:

    def test_translational_conm2_urdd3(self):
        """URDD3 column: −m at grid Tz DOF; all other entries zero."""
        m = 5.0
        bulk = _minimal_bulk_one_conm2(m, 0.0, 0.0, 0.0)
        grid_index = {1: 0}   # single grid → index 0
        all_labels = ['URDD1', 'URDD2', 'URDD3']
        suport_pos = np.zeros(3)
        M = _build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
        # Shape: (6, 3)
        assert M.shape == (6, 3)
        # URDD3 col = 2; Tz dof = 2 (dof offset for translational z is 2)
        assert abs(M[2, 2] - (-m)) < 1e-15, f"M[Tz, URDD3] = {M[2,2]}, expected {-m}"
        # URDD1 col → Tx dof
        assert abs(M[0, 0] - (-m)) < 1e-15
        # URDD2 col → Ty dof
        assert abs(M[1, 1] - (-m)) < 1e-15
        # Rotational DOFs must be zero for translational URDD
        for rot_dof in range(3, 6):
            for col in range(3):
                assert abs(M[rot_dof, col]) < 1e-15

    def test_translational_cbar_urdd3(self):
        """CBAR distributed mass: −m_half at each end node Tz DOF."""
        from sbeam.model.grid import Grid
        from sbeam.model.element import Cbar
        from sbeam.model.property import Pbar
        from sbeam.model.material import Mat1

        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, cp=0, x=0.0, y=0.0, z=0.0, cd=0)
        bulk.grids[2] = Grid(gid=2, cp=0, x=0.0, y=1.0, z=0.0, cd=0)
        rho = 2.0
        A = 1.0
        bulk.mat1s[1] = Mat1(mid=1, E=1.0, G=None, nu=0.3, rho=rho)
        bulk.pbars[1] = Pbar(pid=1, mid=1, A=A, I1=0.0, I2=0.0, J=0.0)
        bulk.cbars[1] = Cbar(eid=1, pid=1, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0, offt='GGG')
        grid_index = {1: 0, 2: 1}
        all_labels = ['URDD3']
        suport_pos = np.zeros(3)
        M = _build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
        L = 1.0
        m_half = 0.5 * rho * A * L
        # Grid 1 Tz = dof 2; Grid 2 Tz = dof 8
        assert abs(M[2, 0] - (-m_half)) < 1e-12, f"Grid1 Tz: {M[2,0]}, expected {-m_half}"
        assert abs(M[8, 0] - (-m_half)) < 1e-12, f"Grid2 Tz: {M[8,0]}, expected {-m_half}"

    def test_rotational_spin_urdd5(self):
        """URDD5 (pitch) spin term: −I22 at grid Ry DOF."""
        m = 0.0   # zero mass so only spin term contributes
        I22 = 7.5
        bulk = _minimal_bulk_one_conm2(m, 0.0, 0.0, 0.0, i22=I22)
        grid_index = {1: 0}
        all_labels = ['URDD4', 'URDD5', 'URDD6']
        suport_pos = np.zeros(3)
        M = _build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
        # URDD5 col = 1 in ['URDD4','URDD5','URDD6']; Ry dof = 4 (3+1)
        assert abs(M[4, 1] - (-I22)) < 1e-15, f"M[Ry, URDD5] = {M[4,1]}, expected {-I22}"
        # Other rotational diagonals
        assert abs(M[3, 0]) < 1e-15   # URDD4 spin: I11=0
        assert abs(M[5, 2]) < 1e-15   # URDD6 spin: I33=0

    def test_transport_urdd5_tip_mass(self):
        """URDD5 transport: tip CONM2 at r=(10,0,0) → Tz_col = +m*rx, Tx_col = 0."""
        m = 2.0
        rx = 10.0
        # CONM2 at (10,0,0); suport_pos at origin
        bulk = _minimal_bulk_one_conm2(m, rx, 0.0, 0.0)
        grid_index = {1: 0}
        all_labels = ['URDD5']
        suport_pos = np.zeros(3)
        M = _build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
        # alpha_hat for URDD5 = (0,1,0); r = (rx,0,0)
        # F_trans = -m * cross((0,1,0), (rx,0,0)) = -m*(1*0-0*0, 0*rx-0*0, 0*0-1*rx)
        #         = -m*(0, 0, -rx) = (0, 0, m*rx)
        # So Tz = +m*rx, Tx = 0, Ty = 0
        assert abs(M[2, 0] - m * rx) < 1e-12, f"M[Tz, URDD5] = {M[2,0]}, expected {m*rx}"
        assert abs(M[0, 0]) < 1e-12, f"M[Tx, URDD5] = {M[0,0]}, expected 0"
        assert abs(M[1, 0]) < 1e-12, f"M[Ty, URDD5] = {M[1,0]}, expected 0"

    def test_nonurdd_labels_zero(self):
        """ANGLEA and PITCH labels produce zero columns in M_ax."""
        m = 5.0
        bulk = _minimal_bulk_one_conm2(m, 0.0, 0.0, 0.0)
        grid_index = {1: 0}
        all_labels = ['ANGLEA', 'PITCH', 'URDD3']
        suport_pos = np.zeros(3)
        M = _build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
        assert np.allclose(M[:, 0], 0.0), "ANGLEA column should be all zeros"
        assert np.allclose(M[:, 1], 0.0), "PITCH column should be all zeros"
        # URDD3 column must be non-zero
        assert not np.allclose(M[:, 2], 0.0)


# ---------------------------------------------------------------------------
# Integration test — V-AE3a: trim lift positive after AE5 fix
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def trim_setup():
    """Parse val_spline2_cantilever.bdf and augment with trim cards in memory.

    Free variable: ANGLEA (1 DOF → 1 SUPORT DOF).
    SUPORT on tip grid 5, DOF '3' (Tz only).
    RCSID 100: z-down CORD2R (local z = -z_basic).
    Prescribed: PITCH=0, URDD3=-32.174 (NASTRAN 1g-upward in z-down RCSID),
                URDD5=0.
    CONM2 mass 100 lb·s²/ft at tip grid provides the inertial load.

    Only Tz SUPORT + ANGLEA because the beam-along-Y model decouples torsion
    from z-forces — any trim involving Ry would be structurally singular.
    """
    _cc, bulk = parse_bdf(str(BDF_PATH))

    # Override AEROS with RCSID pointing to z-down coordinate system
    bulk.aeros = Aeros(acsid=0, rcsid=100, cref=1.0, bref=4.0, sref=4.0,
                       symxz=0, symxy=0, mach=0.0)

    # CORD2R 100: z-down (local z = -z_basic)
    bulk.cord2rs[100] = _z_down_cord2r(100)

    # AESTAT cards — all trim labels including prescribed URDD ones
    bulk.aestats[1] = Aestat(id=1, label='ANGLEA')
    bulk.aestats[2] = Aestat(id=2, label='PITCH')
    bulk.aestats[3] = Aestat(id=3, label='URDD3')
    bulk.aestats[5] = Aestat(id=5, label='URDD5')

    # SUPORT on tip grid 5, DOF Tz (3) only → 1 free variable (ANGLEA)
    bulk.supports = [Suport(gid=5, dofs='3')]

    # TRIM: PITCH=0, 1g upward in NASTRAN z-down RCSID convention, URDD5=0
    bulk.trims[1] = Trim(sid=1, mach=0.0, q=100.0,
                         vars={'PITCH': 0.0, 'URDD3': -G_FT_S2, 'URDD5': 0.0})

    # CONM2 mass at tip grid (provides the inertial load that must be trimmed)
    bulk.conm2s[99] = Conm2(eid=99, gid=5, cid=0, m=100.0)

    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, parity=0, grid_index=grid_index)

    subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
    return bulk, aero, subcase


class TestTrimSignAe5:
    """V-AE3a — trim lift must be upward after AE5 (RCSID z-down URDD transform)."""

    def test_trim_completes(self, trim_setup):
        """run_sol144_trim must not raise for the test model."""
        bulk, aero, subcase = trim_setup
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_sol144_trim(bulk, subcase, aero)
        assert result is not None

    def test_trim_lift_positive(self, trim_setup):
        """total_cl must be > 0 — trim produces upward lift, not downward (AE5 gate)."""
        bulk, aero, subcase = trim_setup
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_sol144_trim(bulk, subcase, aero)
        assert result.total_cl > 0, (
            f"V-AE3a FAIL: total_cl = {result.total_cl:.6f} ≤ 0 "
            "(sign of lift is inverted — AE5 regression)"
        )

    def test_anglea_positive(self, trim_setup):
        """Trim angle-of-attack must be positive for upward 1g maneuver."""
        bulk, aero, subcase = trim_setup
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_sol144_trim(bulk, subcase, aero)
        anglea = result.trim_vars.get('ANGLEA', result.trim_vars.get('anglea', None))
        assert anglea is not None, "ANGLEA not found in trim_vars"
        assert anglea > 0, (
            f"V-AE3a FAIL: ANGLEA = {anglea:.6f} ≤ 0 "
            "(should be positive for 1g upward trim)"
        )
