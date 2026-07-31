"""Step 61 — free-free maneuver modal basis and h-set operator gates.

Fixture: the full-span HA144A MLOADS deck (SPC1 1246 pins the antisymmetric DOFs
on GRID 90, SUPORT 35 frees the symmetric rigid DOFs — so n_r = 2: plunge and
pitch about the RCSID origin).  Gates, in the order the Step 61 spec lists them:

  1. Phi^T M_aa Phi block diagonal, elastic block = I (the mean-axis condition).
  2. M_rr equals the GPWG rigid mass about suport_pos.
  3. M_ax identity: the a-set-reduced sol144 inertial columns are exactly
     -M_aa Phi_r, column for column, via the rigid label map.
  4. Q_hh agrees with the shipped static-ROM projection for the same basis.
  5. K_hh rigid rows/columns vanish (rigid vectors are strain free).

Plus the machinery gates: the rigid-vector round trip through the RBE3/RBAR
transformation, the massless-DOF static condensation (no artificial modes reach
the basis), NMODES/METHOD handling, and the h-set aerodynamic operators
(Q_hc/B_hh/C_hh), whose rigid-rate columns are checked against the exact
rescaling identity they must satisfy with respect to Q_hx.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.gpwg import compute_gpwg
from sbeam.model.load import Eigrl
from sbeam.solver.modal_basis import (
    assemble_aset_operators,
    build_rigid_modes,
    build_maneuver_basis,
    build_hset_gafs,
)
from sbeam.solver.sol144 import _solve_rom

SAMPLE = Path(__file__).parent.parent.parent / "sample"
BDF_PATH = SAMPLE / "ha144a_fullspan_mloads.bdf"


def _model(path=BDF_PATH, spc_sid=1, trim_sid=1):
    _cc, bulk = parse_bdf(str(path))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
    subcase = SubcaseControl(subcase_id=1, spc_sid=spc_sid, trim_sid=trim_sid)
    ops = assemble_aset_operators(bulk, subcase, aero)
    return bulk, gi, aero, ops


@pytest.fixture(scope="module")
def basis_fixture():
    bulk, gi, aero, ops = _model()
    basis = build_maneuver_basis(bulk, ops)
    return bulk, gi, aero, ops, basis


# ---------------------------------------------------------------------------
# Rigid basis
# ---------------------------------------------------------------------------

def test_rigid_basis_shape_and_reference(basis_fixture):
    """One column per SUPORT DOF, about the RCSID origin."""
    bulk, gi, aero, ops, basis = basis_fixture
    assert ops.rigid_dofs == [3, 5]          # SUPORT 90, 35
    assert basis.n_r == 2
    assert basis.phi.shape == (ops.K_aa.shape[0], basis.n_r + basis.n_e)
    assert np.allclose(basis.suport_pos, [15.0, 0.0, 0.0])
    assert basis.rigid_label_map[0]["accel"] == "URDD3"
    assert basis.rigid_label_map[1]["accel"] == "URDD5"
    assert basis.rigid_label_map[1]["rate"] == "PITCH"


def test_rigid_vectors_are_geometric(basis_fixture):
    """Plunge column is unit Tz everywhere; pitch column is the x-lever arm."""
    bulk, gi, aero, ops, basis = basis_fixture
    phi_r_g = np.column_stack(
        [ops.red.expand_to_g(basis.phi[:, c]) for c in range(basis.n_r)])
    for gid, i in gi.items():
        g = bulk.grids[gid]
        assert phi_r_g[6 * i + 2, 0] == pytest.approx(1.0)          # plunge: uz = 1
        # pitch about +y through (15, 0, 0): uz = -(x - 15), ry = 1
        assert phi_r_g[6 * i + 2, 1] == pytest.approx(-(g.x - 15.0), abs=1e-12)
        assert phi_r_g[6 * i + 4, 1] == pytest.approx(1.0)


def test_rigid_roundtrip_detects_non_rigid_transformation(basis_fixture):
    """A rigid vector must survive the RBE3/RBAR expansion unchanged."""
    bulk, gi, aero, ops, basis = basis_fixture
    phi_r = build_rigid_modes(
        bulk, gi, ops.red, ops.rigid_dofs, ops.suport_pos)   # asserts internally
    assert phi_r.shape == (ops.K_aa.shape[0], 2)
    # Constraining a DOF the rigid motion needs (a Tz) breaks the round trip.
    drop = next(i for i, g_dof in enumerate(ops.red.free_dofs) if g_dof % 6 == 2)
    keep = [i for i in range(len(ops.red.free_dofs)) if i != drop]
    bad_red = type(ops.red)(
        T=ops.red.T, dep_dofs=ops.red.dep_dofs, red_dofs=ops.red.red_dofs,
        free_local=[ops.red.free_local[i] for i in keep],
        free_dofs=[ops.red.free_dofs[i] for i in keep],
    )
    with pytest.raises(ValueError, match="not reproduced"):
        build_rigid_modes(bulk, gi, bad_red, ops.rigid_dofs, ops.suport_pos)


# ---------------------------------------------------------------------------
# Gate 1 — orthogonality / mean axis
# ---------------------------------------------------------------------------

def test_basis_orthogonality(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    n_r = basis.n_r
    M_hh = basis.M_hh
    scale = np.abs(np.diag(basis.M_rr)).max()
    # Rigid/elastic coupling = 0 (this IS the mean-axis condition)
    assert np.abs(M_hh[:n_r, n_r:]).max() / scale < 1e-10
    assert np.abs(M_hh[n_r:, :n_r]).max() / scale < 1e-10
    # Elastic block = I
    assert np.abs(M_hh[n_r:, n_r:] - np.eye(basis.n_e)).max() < 1e-10
    assert basis.orthogonality_residual < 1e-10


# ---------------------------------------------------------------------------
# Gate 2 — M_rr vs GPWG
# ---------------------------------------------------------------------------

def test_m_rr_equals_gpwg_rigid_mass(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    gpwg = compute_gpwg(bulk)
    x_sup = basis.suport_pos[0]

    # (plunge, plunge) = total mass
    assert basis.M_rr[0, 0] == pytest.approx(gpwg.total_mass, rel=1e-12)
    # (plunge, pitch) = -m * (x_cg - x_suport)  (pitch column uz = -(x - x_sup))
    assert basis.M_rr[0, 1] == pytest.approx(
        -gpwg.total_mass * (gpwg.cg_x - x_sup), rel=1e-10)
    assert basis.M_rr[1, 0] == pytest.approx(basis.M_rr[0, 1], rel=1e-12)

    # (pitch, pitch) = I_yy about the SUPORT point, summed independently here
    # (GPWG returns mass and CG only, not a 6x6 inertia).
    i_yy = 0.0
    for conm2 in bulk.conm2s.values():
        g = bulk.grids[conm2.gid]
        i_yy += conm2.m * ((g.x - x_sup) ** 2 + g.z ** 2) + conm2.i22
    assert basis.M_rr[1, 1] == pytest.approx(i_yy, rel=1e-10)


# ---------------------------------------------------------------------------
# Gate 3 — M_ax identity
# ---------------------------------------------------------------------------

def test_m_ax_identity(basis_fixture):
    """sol144's inertial columns are -M_aa Phi_r, column for column."""
    bulk, gi, aero, ops, basis = basis_fixture
    for col, info in basis.rigid_label_map.items():
        j = ops.label_to_col[info["accel"]]
        expected = -(ops.M_aa @ basis.phi[:, col])
        actual = ops.M_ax_a[:, j]
        scale = max(1.0, np.abs(expected).max())
        assert np.abs(actual - expected).max() / scale < 1e-12, info["accel"]


def test_m_ax_identity_limits_with_consistent_cbar_mass():
    """With CBAR rho > 0 the identity holds on translational rows only.

    ``build_inertial_cols`` is a *lumped* inertia model while ``M_aa`` is the
    consistent mass matrix.  On translational rows the two agree exactly (the
    consistent beam mass rows sum to the lumped nodal share, rho*A*L/2), so the
    net force is identical.  On rotational rows they do not: a rigid translation
    produces a consistent-mass moment (the 22L/420 + 13L/420 coupling) which the
    lumped model has no term for.  This test pins the exact half and bounds the
    other so the discrepancy cannot drift unnoticed — see the backlog item on
    reconciling the two mass models.
    """
    _cc, bulk = parse_bdf(str(SAMPLE / "val_dihedral_trim.bdf"))
    for mat in bulk.mat1s.values():
        mat.rho = 2700.0                       # give the CBARs distributed mass
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ops = assemble_aset_operators(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        basis = build_maneuver_basis(bulk, ops)

    col = 0                                    # SUPORT 90, 3 -> plunge only
    assert basis.rigid_label_map[col]["accel"] == "URDD3"
    j = ops.label_to_col["URDD3"]
    expected = -(ops.M_aa @ basis.phi[:, col])
    actual = ops.M_ax_a[:, j]

    is_trans = np.array([g % 6 < 3 for g in ops.red.free_dofs])
    scale = np.abs(expected).max()
    # Translational rows: exact (identical net force per grid).
    assert np.abs((actual - expected)[is_trans]).max() / scale < 1e-9
    # Rotational rows: the documented lumped-vs-consistent gap, O(10%) here.
    rot_gap = np.abs((actual - expected)[~is_trans]).max() / scale
    assert 0.0 < rot_gap < 0.25


# ---------------------------------------------------------------------------
# Gate 4 — Q_hh against the shipped static ROM
# ---------------------------------------------------------------------------

def test_q_hh_matches_static_rom_projection(basis_fixture):
    """build_hset_gafs' Q_hh is the same object sol144's ROM forms for a basis."""
    bulk, gi, aero, ops, basis = basis_fixture
    v_inf = bulk.trims[1].velocity()
    gafs = build_hset_gafs(bulk, ops, basis, aero, v_inf)
    f_aa = ops.red.reduce_vector(bulk.trims[1].q * ops.f_aero_g_unit)
    with warnings.catch_warnings():
        # K_hh - q*Q_hh is singular for a free-free basis (the ROM's xi is
        # meaningless here); only its q_hh/k_hh projections are under test.
        warnings.simplefilter("ignore")
        _xi, _k_hh, q_hh_rom = _solve_rom(
            ops.K_aa, ops.Q_aa, f_aa, bulk.trims[1].q, basis.phi)
    scale = np.abs(q_hh_rom).max()
    assert np.abs(gafs.Q_hh - q_hh_rom).max() / scale < 1e-12
    # ... and K_hh likewise
    assert np.abs(basis.K_hh - _k_hh).max() / np.abs(_k_hh).max() < 1e-12


# ---------------------------------------------------------------------------
# Gate 5 — K_hh rigid rows/columns
# ---------------------------------------------------------------------------

def test_k_hh_rigid_block_vanishes(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    n_r = basis.n_r
    norm = np.abs(basis.K_hh).max()
    assert np.abs(basis.K_hh[:n_r, :]).max() / norm < 1e-8
    assert np.abs(basis.K_hh[:, :n_r]).max() / norm < 1e-8


# ---------------------------------------------------------------------------
# Massless-DOF condensation
# ---------------------------------------------------------------------------

def test_massless_dofs_are_condensed_not_filtered(basis_fixture):
    """CONM2-only rotational DOFs never reach the eigensolve.

    Regularising them instead (the old sketch) produced modes with O(1e5)
    amplitudes on the massless DOFs which are orthogonal only against the
    regularised mass — the mean-axis projection then left the basis 0.99
    non-orthogonal despite every mode having unit generalized mass.
    """
    bulk, gi, aero, ops, basis = basis_fixture
    assert basis.n_massless == 18                 # CONM2-only rotational DOFs
    assert basis.n_r + basis.n_e == ops.K_aa.shape[0] - basis.n_massless
    # Only the rigid zero modes are dropped by the generalized-mass filter.
    assert basis.n_filtered == basis.n_r
    assert basis.filtered_freqs_hz.max() < 1e-3 * basis.elastic_freqs_hz[0]
    # No artificial high-frequency modes survive.
    assert basis.elastic_freqs_hz.max() < 1e5
    assert np.abs(basis.phi).max() < 1e3


# ---------------------------------------------------------------------------
# NMODES / METHOD
# ---------------------------------------------------------------------------

def test_nmodes_truncates_elastic_only(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    truncated = build_maneuver_basis(bulk, ops, nmodes=4)
    assert truncated.n_r == basis.n_r          # rigid modes always all retained
    assert truncated.n_e == 4
    assert np.allclose(truncated.elastic_freqs_hz, basis.elastic_freqs_hz[:4])
    assert np.allclose(truncated.phi, basis.phi[:, : basis.n_r + 4])


def test_nmodes_above_available_warns_and_clamps(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    with pytest.warns(UserWarning, match="exceeds"):
        clamped = build_maneuver_basis(bulk, ops, nmodes=10_000)
    assert clamped.n_e == basis.n_e


def test_method_eigrl_bounds_the_solve(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    limited = build_maneuver_basis(
        bulk, ops, eigrl=Eigrl(sid=7, nd=6, norm="MASS"))
    # 6 modes requested, the 2 rigid ones project out
    assert limited.n_e == 6 - limited.n_r
    assert np.allclose(
        limited.elastic_freqs_hz, basis.elastic_freqs_hz[: limited.n_e])


def test_no_suport_raises():
    bulk, gi, aero, ops = _model()
    bulk.supports = []
    ops_nosup = assemble_aset_operators(
        bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    with pytest.raises(ValueError, match="SUPORT"):
        build_maneuver_basis(bulk, ops_nosup)


# ---------------------------------------------------------------------------
# h-set aerodynamic operators
# ---------------------------------------------------------------------------

def test_hset_gafs_shapes_and_control_columns(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    gafs = build_hset_gafs(bulk, ops, basis, aero, bulk.trims[1].velocity())
    n_h = basis.n_h
    assert gafs.Q_hh.shape == (n_h, n_h)
    assert gafs.Q_hx.shape == (n_h, len(ops.all_labels))
    assert gafs.ctrl_labels == ["ELEV"]
    assert np.allclose(gafs.Q_hc[:, 0], gafs.Q_hx[:, ops.label_to_col["ELEV"]])
    assert gafs.f_h0.shape == (n_h,)


def test_b_hh_rigid_rate_columns_are_the_rescaled_steady_columns(basis_fixture):
    """B_hh's rigid columns are the Q_hx label columns divided by the rate scale.

    Plunge rate: alpha = -h_dot / V, so the column is -(1/V) * the ANGLEA column.
    Pitch rate:  PITCH = xi_dot * c_ref / 2V, so the column is c_ref/(2V) * PITCH.
    Elastic-rate columns are zero at Level 1 (the G0-d hook).
    """
    bulk, gi, aero, ops, basis = basis_fixture
    v = bulk.trims[1].velocity()
    gafs = build_hset_gafs(bulk, ops, basis, aero, v)
    c_ref = bulk.aeros.cref

    plunge = -(1.0 / v) * gafs.Q_hx[:, ops.label_to_col["ANGLEA"]]
    pitch = (c_ref / (2.0 * v)) * gafs.Q_hx[:, ops.label_to_col["PITCH"]]
    assert np.abs(gafs.B_hh[:, 0] - plunge).max() / np.abs(plunge).max() < 1e-12
    assert np.abs(gafs.B_hh[:, 1] - pitch).max() / np.abs(pitch).max() < 1e-12
    assert np.abs(gafs.B_hh[:, basis.n_r:]).max() == 0.0


def test_c_hh_modal_damping(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    v = bulk.trims[1].velocity()
    assert np.abs(build_hset_gafs(bulk, ops, basis, aero, v, zeta=0.0).C_hh).max() == 0.0

    zeta = 0.02
    C = build_hset_gafs(bulk, ops, basis, aero, v, zeta=zeta).C_hh
    n_r = basis.n_r
    assert np.abs(C[:n_r, :]).max() == 0.0     # no damping on the rigid partition
    omega = 2.0 * np.pi * basis.elastic_freqs_hz
    assert np.allclose(np.diag(C)[n_r:], 2.0 * zeta * omega)


def test_hset_gafs_requires_a_velocity(basis_fixture):
    bulk, gi, aero, ops, basis = basis_fixture
    with pytest.raises(ValueError, match="v_inf"):
        build_hset_gafs(bulk, ops, basis, aero, 0.0)
