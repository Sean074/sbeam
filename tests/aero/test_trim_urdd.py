"""AE5 + AE7 tests — RCSID-frame URDD transform and inertial trim columns.

Unit tests:
  TestUrddRcsidTransform — verify R_rcsid correctly maps URDD3 from z-down
      RCSID frame to basic frame (AE5 math).
  TestInertialCols — verify build_inertial_cols entries for translational
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

from sbeam.assembly.coord_transform import get_transform
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Aeros, Aestat, Trim
from sbeam.model.bulk_data import BulkData
from sbeam.model.constraint import Suport
from sbeam.model.coordinate_system import Cord2r
from sbeam.model.mass import Conm2
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.solver.sol144 import build_inertial_cols, run_sol144_trim

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
        _, R = get_transform(99, cord2rs)
        # R[2,2] must be -1 (local z = -basic z)
        assert abs(R[2, 2] - (-1.0)) < 1e-12, f"R[2,2] = {R[2,2]}, expected -1"
        v_basic = R @ np.array([0.0, 0.0, -G_FT_S2])
        assert abs(v_basic[2] - G_FT_S2) < 1e-10, \
            f"Transformed URDD3: basic z = {v_basic[2]}, expected {G_FT_S2}"

    def test_identity_rcsid_leaves_urdd3_unchanged(self):
        """RCSID=0 (identity): URDD3 value must pass through unchanged."""
        _, R = get_transform(0, {})
        v_basic = R @ np.array([0.0, 0.0, -G_FT_S2])
        assert abs(v_basic[2] - (-G_FT_S2)) < 1e-12


# ---------------------------------------------------------------------------
# Unit tests — build_inertial_cols matrix entries
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
        M = build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
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
        M = build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
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
        M = build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
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
        M = build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
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
        M = build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
        assert np.allclose(M[:, 0], 0.0), "ANGLEA column should be all zeros"
        assert np.allclose(M[:, 1], 0.0), "PITCH column should be all zeros"
        # URDD3 column must be non-zero
        assert not np.allclose(M[:, 2], 0.0)


# ---------------------------------------------------------------------------
# Unit tests — DEF-M3: M_ax must carry the FULL CONM2 mass model
# ---------------------------------------------------------------------------
#
# M_ax is defined as -M_gg @ Phi_r, so everything assemble_global_mass knows
# about a CONM2 (offset transport, products of inertia, CID rotation) and about
# a PBAR (nsm) reaches the inertia-relief columns.  The gates below are written
# against the closed-form rigid-body resultant, NOT against a second call into
# the same code path: for a unit rigid acceleration the d'Alembert loads must
# integrate to exactly the negated rigid mass properties about the reference
# point.  That is unforgeable by any implementation that drops a term.

def _resultant(col: np.ndarray, bulk: BulkData, grid_index: dict, ref: np.ndarray):
    """Total (force, moment about ``ref``) of a g-set nodal load column."""
    F = np.zeros(3)
    Mo = np.zeros(3)
    for gid, i in grid_index.items():
        f = col[6 * i: 6 * i + 3]
        mmt = col[6 * i + 3: 6 * i + 6]
        g = bulk.grids[gid]
        r = np.array([g.x, g.y, g.z]) - ref
        F += f
        Mo += mmt + np.cross(r, f)
    return F, Mo


def _rigid_resultants(m: float, R: np.ndarray, I_cm: np.ndarray, dof: int):
    """Closed-form (F, M about ref) for a unit rigid acceleration of one mass.

    ``R`` is the CM position relative to the reference point, ``I_cm`` the
    inertia tensor about the CM in basic axes.  Translation along unit axis
    ``a`` gives ``F = -m a``, ``M = R x F``.  Rotation about ``a`` gives the CM
    acceleration ``a x R``, hence ``F = -m (a x R)``; the moment about the
    reference collapses to ``M = -I_ref a`` with ``I_ref`` the parallel-axis
    transported tensor, since ``R x (-m (a x R)) = -m(|R|^2 I - R (x) R) a``.
    """
    a = np.zeros(3)
    a[(dof - 1) % 3] = 1.0
    if dof <= 3:
        F = -m * a
        return F, np.cross(R, F)
    I_ref = I_cm + m * (float(R @ R) * np.eye(3) - np.outer(R, R))
    return -m * np.cross(a, R), -I_ref @ a


class TestInertialColsFullMassModel:
    """DEF-M3 — offsets, products of inertia, CID rotation and nsm."""

    def test_offset_conm2_transports_about_the_cm_not_the_grid(self):
        """A CONM2 offset from its grid must accelerate about its own CM.

        The pre-fix lumped model used the *grid* position as the moment arm and
        had no parallel-axis term, so a mass hung below its attach node was
        transported from the wrong point and lost its m*d^2 inertia entirely.
        """
        from sbeam.model.grid import Grid
        m, d = 3.0, np.array([0.0, 0.0, -4.0])      # 4 units below the grid
        p = np.array([10.0, 0.0, 0.0])              # grid position
        ref = np.zeros(3)
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, cp=0, x=p[0], y=p[1], z=p[2], cd=0)
        bulk.conm2s[1] = Conm2(eid=1, gid=1, cid=0, m=m,
                               x1=d[0], x2=d[1], x3=d[2])
        grid_index = {1: 0}
        labels = ['URDD3', 'URDD5']
        M = build_inertial_cols(bulk, labels, grid_index, ref)

        R = p + d - ref                              # CM relative to reference
        for j, dof in enumerate((3, 5)):
            F, Mo = _resultant(M[:, j], bulk, grid_index, ref)
            F_ref, M_ref = _rigid_resultants(m, R, np.zeros((3, 3)), dof)
            assert np.allclose(F, F_ref, atol=1e-12), f"URDD{dof} force"
            assert np.allclose(Mo, M_ref, atol=1e-12), f"URDD{dof} moment"

        # Guard the specific term the old model dropped: the pitch inertia about
        # the reference must include m*(x^2 + z^2) from the offset CM.
        _F, Mo5 = _resultant(M[:, 1], bulk, grid_index, ref)
        assert abs(-Mo5[1] - m * (R[0] ** 2 + R[2] ** 2)) < 1e-12

    def test_products_of_inertia_couple_the_axes(self):
        """Yaw acceleration on a CONM2 with I31 != 0 must produce roll moment."""
        from sbeam.model.grid import Grid
        i31 = 2.5
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, cp=0, x=0.0, y=0.0, z=0.0, cd=0)
        bulk.conm2s[1] = Conm2(eid=1, gid=1, cid=0, m=0.0,
                               i11=8.0, i22=6.0, i33=4.0, i31=i31)
        grid_index = {1: 0}
        M = build_inertial_cols(bulk, ['URDD6'], grid_index, np.zeros(3))
        _F, Mo = _resultant(M[:, 0], bulk, grid_index, np.zeros(3))
        # M = -I @ (0,0,1) = -(I13, I23, I33) = -(i31, i32, i33)
        assert abs(Mo[0] - (-i31)) < 1e-12, "roll moment from I31 is missing"
        assert abs(Mo[2] - (-4.0)) < 1e-12

    def test_conm2_cid_rotates_the_inertia_tensor(self):
        """A CONM2 in a rotated CID: the tensor must be rotated to basic.

        CID 7 is a 90 deg rotation about z (x_local = +y_basic), so a mass with
        I11 = 9 about its *local* 1-axis has 9 about the *basic* y-axis.  The
        pre-fix model read i11/i22/i33 as if always basic-frame and would report
        9 about basic x.
        """
        from sbeam.model.grid import Grid
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, cp=0, x=0.0, y=0.0, z=0.0, cd=0)
        # A=(0,0,0), B=(0,0,1) -> k=z; C=(0,1,0) -> i=y  =>  x_local = y_basic
        bulk.cord2rs[7] = Cord2r(cid=7, rid=0, a=(0.0, 0.0, 0.0),
                                 b=(0.0, 0.0, 1.0), c=(0.0, 1.0, 0.0))
        bulk.conm2s[1] = Conm2(eid=1, gid=1, cid=7, m=0.0, i11=9.0)
        grid_index = {1: 0}
        M = build_inertial_cols(bulk, ['URDD4', 'URDD5'], grid_index, np.zeros(3))
        _F, Mo_roll = _resultant(M[:, 0], bulk, grid_index, np.zeros(3))
        _F, Mo_pitch = _resultant(M[:, 1], bulk, grid_index, np.zeros(3))
        assert abs(Mo_roll[0]) < 1e-12, "local I11 must not land on basic x"
        assert abs(Mo_pitch[1] - (-9.0)) < 1e-12, "local I11 must land on basic y"

    def test_pbar_nsm_contributes(self):
        """Non-structural mass is part of M_aa, so it is part of M_ax."""
        from sbeam.model.grid import Grid
        from sbeam.model.element import Cbar
        from sbeam.model.property import Pbar
        from sbeam.model.material import Mat1

        def _mass_of(nsm: float) -> float:
            bulk = BulkData()
            bulk.grids[1] = Grid(gid=1, cp=0, x=0.0, y=0.0, z=0.0, cd=0)
            bulk.grids[2] = Grid(gid=2, cp=0, x=0.0, y=2.0, z=0.0, cd=0)
            bulk.mat1s[1] = Mat1(mid=1, E=1.0, G=None, nu=0.3, rho=2.0)
            bulk.pbars[1] = Pbar(pid=1, mid=1, A=1.0, I1=0.0, I2=0.0, J=0.0, nsm=nsm)
            bulk.cbars[1] = Cbar(eid=1, pid=1, ga=1, gb=2,
                                 x1=0.0, x2=0.0, x3=1.0, offt='GGG')
            gi = {1: 0, 2: 1}
            M = build_inertial_cols(bulk, ['URDD3'], gi, np.zeros(3))
            F, _Mo = _resultant(M[:, 0], bulk, gi, np.zeros(3))
            return -F[2]

        L = 2.0
        assert abs(_mass_of(0.0) - 2.0 * 1.0 * L) < 1e-12
        assert abs(_mass_of(0.5) - (2.0 * 1.0 + 0.5) * L) < 1e-12

    def test_supplied_m_gg_matches_internal_assembly(self):
        """The M_gg reuse path is bit-identical to assembling internally."""
        from sbeam.assembly.mass_matrix import assemble_global_mass
        bulk = _minimal_bulk_one_conm2(5.0, 1.0, 2.0, 3.0, i11=1.0, i22=2.0, i33=3.0)
        gi = build_grid_index(bulk)
        labels = ['URDD3', 'URDD5']
        ref = np.array([0.5, 0.0, 0.0])
        a = build_inertial_cols(bulk, labels, gi, ref)
        b = build_inertial_cols(bulk, labels, gi, ref,
                                M_gg=assemble_global_mass(bulk, None))
        assert np.array_equal(a, b)

    def test_mismatched_m_gg_raises(self):
        """A wrong-sized M_gg is a caller error, not a silent broadcast."""
        import scipy.sparse
        bulk = _minimal_bulk_one_conm2(5.0, 0.0, 0.0, 0.0)
        with pytest.raises(ValueError, match="same model"):
            build_inertial_cols(bulk, ['URDD3'], {1: 0}, np.zeros(3),
                                M_gg=scipy.sparse.eye(12, format="csr"))

    def test_aero_only_labels_give_zero_matrix(self):
        """No URDD labels at all: M_ax is identically zero, no mass assembled."""
        bulk = _minimal_bulk_one_conm2(5.0, 0.0, 0.0, 0.0)
        M = build_inertial_cols(bulk, ['ANGLEA', 'PITCH'], {1: 0}, np.zeros(3))
        assert M.shape == (6, 2)
        assert np.array_equal(M, np.zeros((6, 2)))


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
        aero = build_aero_model(bulk, grid_index=grid_index)

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
