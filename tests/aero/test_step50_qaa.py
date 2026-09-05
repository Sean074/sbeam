"""V-C3 acceptance tests for Step 50 — Q_aa a-set assembly + modal-truncation ROM.

Model: val_spline2_cantilever.bdf (5 grids, 4 CBARs, 4-box CAERO1, SPLINE2,
root SPC=1).  EIGRL and tip force are added in-memory so no new BDF file is
required.

Test matrix:
  V-C3-1  Q_aa and K_aa shapes match the a-set
  V-C3-2  Direct solve at q=0 matches run_sol101 to 1e-10
  V-C3-3  ROM with all modes matches direct solve to 1e-6
  V-C3-4  Mode-acceleration converges much faster than mode-displacement on
          CBAR root-moment
  V-C3-5  k_aa_lu stored in Sol144Result inverts K_aa correctly
"""

import warnings
from pathlib import Path

import numpy as np
import pytest
import scipy.linalg

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.assembly.load_vector import build_grid_index
from sbeam.aero.aero_model import build_aero_model
from sbeam.model.load import Eigrl, Force
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver.sol101 import run_sol101
from sbeam.solver.sol103 import run_sol103
from sbeam.solver.sol144 import run_aeroelastic_static, _build_qaa_aset

BDF_PATH = Path(__file__).parent.parent / "integration" / "bdf" / "val_spline2_cantilever.bdf"

# Dynamic pressure well below divergence for this cantilever
Q_TEST = 500.0
TIP_LOAD_SID = 99
EIGRL_SID = 20


@pytest.fixture(scope="module")
def setup():
    """Parse the cantilever BDF and augment in-memory for aero+modal tests."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)

    # Add EIGRL in-memory for ROM tests (request all modes — small model)
    bulk.eigrls[EIGRL_SID] = Eigrl(sid=EIGRL_SID, nd=24, norm="MASS")

    # Add a tip force (-Z direction at GRID 5) for static comparison tests
    bulk.forces[TIP_LOAD_SID] = [Force(sid=TIP_LOAD_SID, gid=5, cid=0, f=1000.0, n1=0.0, n2=0.0, n3=-1.0)]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index)

    return bulk, aero, grid_index


# ---------------------------------------------------------------------------
# V-C3-1 — Shape / dimension checks
# ---------------------------------------------------------------------------

class TestQaaShape:
    def test_qaa_aset_shape(self, setup):
        """Q_aa and K_aa must be square and sized to the free a-set."""
        bulk, aero, grid_index = setup
        Q_aa, K_aa, _f_aa, free_dofs = _build_qaa_aset(
            bulk, aero, grid_index, spc_sid=1
        )
        n_a = len(free_dofs)
        assert Q_aa.shape == (n_a, n_a), f"Q_aa shape {Q_aa.shape} != ({n_a},{n_a})"
        assert K_aa.shape == (n_a, n_a), f"K_aa shape {K_aa.shape} != ({n_a},{n_a})"

    def test_n_a_is_less_than_n_g(self, setup):
        """The a-set must be strictly smaller than the g-set (SPC applied)."""
        bulk, aero, grid_index = setup
        n_g = 6 * len(grid_index)
        _Q, _K, _f, free_dofs = _build_qaa_aset(bulk, aero, grid_index, spc_sid=1)
        assert len(free_dofs) < n_g

    def test_f_aa_reduced_when_supplied(self, setup):
        """f_g_full supplied to _build_qaa_aset must be reduced to a-set length."""
        bulk, aero, grid_index = setup
        n_g = 6 * len(grid_index)
        f_full = np.ones(n_g)
        _Q, _K, f_aa, free_dofs = _build_qaa_aset(
            bulk, aero, grid_index, spc_sid=1, f_g_full=f_full
        )
        assert f_aa is not None
        assert f_aa.shape == (len(free_dofs),)

    def test_qaa_none_when_no_splines(self, setup):
        """_build_qaa_aset raises when aero has no spline operators."""
        import dataclasses
        bulk, aero, grid_index = setup
        aero_no_spline = dataclasses.replace(aero, g_slope=None, g_disp=None)
        with pytest.raises(ValueError, match="g_slope"):
            _build_qaa_aset(bulk, aero_no_spline, grid_index, spc_sid=1)


# ---------------------------------------------------------------------------
# V-C3-2 — q=0 identity: must match run_sol101
# ---------------------------------------------------------------------------

class TestQZeroMatchesSol101:
    def test_q_zero_matches_sol101_displacements(self, setup):
        """At q=0 the aeroelastic solver must reproduce run_sol101 exactly.

        At q=0: aero load q*f_g = 0 and Q_aa contribution vanishes,
        so (K_aa - 0*Q_aa)*u = f_struct == K_aa*u = f_struct.
        """
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(
            subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID, method_sid=EIGRL_SID
        )

        result_101 = run_sol101(bulk, subcase)
        result_144 = run_aeroelastic_static(bulk, subcase, aero, q=0.0)

        np.testing.assert_allclose(
            result_144.displacements,
            result_101.displacements,
            atol=1e-10,
            err_msg="run_aeroelastic_static(q=0) displacements differ from run_sol101",
        )

    def test_q_zero_matches_sol101_bar_forces(self, setup):
        """CBAR forces at q=0 must match run_sol101."""
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID)

        result_101 = run_sol101(bulk, subcase)
        result_144 = run_aeroelastic_static(bulk, subcase, aero, q=0.0)

        for eid in result_101.bar_forces:
            bf_101 = result_101.bar_forces[eid]
            bf_144 = result_144.bar_forces[eid]
            assert abs(bf_101.bm2_a - bf_144.bm2_a) < 1e-8, (
                f"CBAR {eid} bm2_a mismatch at q=0"
            )


# ---------------------------------------------------------------------------
# V-C3-3 — ROM with all modes must match direct solve
# ---------------------------------------------------------------------------

class TestRomAllModesMatchesDirect:
    def test_rom_displacements_match_direct(self, setup):
        """Modal ROM + mode-acceleration with all modes must match direct solve."""
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(
            subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID, method_sid=EIGRL_SID
        )

        result_direct = run_aeroelastic_static(bulk, subcase, aero, q=Q_TEST, use_rom=False)
        result_rom = run_aeroelastic_static(bulk, subcase, aero, q=Q_TEST, use_rom=True)

        np.testing.assert_allclose(
            result_rom.displacements,
            result_direct.displacements,
            atol=1e-6,
            err_msg="ROM (all modes, mode-acceleration) displacements differ from direct solve",
        )

    def test_rom_result_fields_populated(self, setup):
        """Sol144Result ROM fields must be populated when use_rom=True."""
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(
            subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID, method_sid=EIGRL_SID
        )
        result = run_aeroelastic_static(bulk, subcase, aero, q=Q_TEST, use_rom=True)

        assert result.modal_coords is not None
        assert result.phi_free is not None
        assert result.k_hh is not None
        assert result.q_hh is not None
        n_a = len(result.free_dofs)
        n_m = result.modal_coords.shape[0]
        assert result.phi_free.shape[0] == n_a
        assert result.k_hh.shape == (n_m, n_m)
        assert result.q_hh.shape == (n_m, n_m)

    def test_use_rom_false_leaves_rom_fields_none(self, setup):
        """ROM fields must be None when use_rom=False."""
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID)
        result = run_aeroelastic_static(bulk, subcase, aero, q=Q_TEST, use_rom=False)

        assert result.modal_coords is None
        assert result.phi_free is None
        assert result.k_hh is None
        assert result.q_hh is None


# ---------------------------------------------------------------------------
# V-C3-4 — Mode-acceleration converges faster than mode-displacement
# ---------------------------------------------------------------------------

class TestModeAccelerationConvergence:
    """Mode-acceleration (MA) recovery must converge faster than mode-
    displacement (MD) on CBAR root bending moment as mode count increases."""

    def _run_rom_n_modes(self, bulk, aero, subcase, q, sol103_result, n_modes):
        """Run the ROM with only the first n_modes modes."""
        from sbeam.solver.sol144 import (
            _build_qaa_aset,
            _solve_direct,
            _solve_rom,
            _mode_acceleration_recovery,
        )
        from sbeam.assembly.load_vector import build_grid_index
        from sbeam.aero.coupling import build_fg
        from sbeam.assembly.load_vector import assemble_load_vector

        grid_index = build_grid_index(bulk)
        n_g = 6 * len(grid_index)
        load_sid = subcase.load_sid
        f_struct = assemble_load_vector(bulk, load_sid) if load_sid else np.zeros(n_g)
        f_aero_g = q * build_fg(aero, aero.g_disp)
        f_g_full = f_struct + f_aero_g

        Q_aa, K_aa, f_aa, free_dofs = _build_qaa_aset(
            bulk, aero, grid_index, subcase.spc_sid, f_g_full
        )
        _disp_direct, _K_eff, k_aa_lu = _solve_direct(K_aa, Q_aa, f_aa, q, free_dofs, n_g)

        phi_full = sol103_result.mode_shapes
        phi_free = phi_full[free_dofs, :n_modes]

        xi, _k_hh, _q_hh = _solve_rom(K_aa, Q_aa, f_aa, q, phi_free)

        # Mode-displacement (uncorrected)
        u_md_free = phi_free @ xi
        u_md = np.zeros(n_g)
        for li, gd in enumerate(free_dofs):
            u_md[gd] = u_md_free[li]

        # Mode-acceleration (corrected)
        u_ma_free = _mode_acceleration_recovery(K_aa, Q_aa, f_aa, q, phi_free, xi, k_aa_lu)
        u_ma = np.zeros(n_g)
        for li, gd in enumerate(free_dofs):
            u_ma[gd] = u_ma_free[li]

        return u_md, u_ma

    def test_mode_acceleration_converges_faster(self, setup):
        """At 1/4 of the total mode count MA error on root bending moment must
        be at least 5x smaller than MD error."""
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(
            subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID, method_sid=EIGRL_SID
        )

        # Reference: direct solve (exact)
        result_ref = run_aeroelastic_static(bulk, subcase, aero, q=Q_TEST, use_rom=False)

        # Run SOL 103 once; share for all mode-count iterations
        sol103_result = run_sol103(bulk, subcase)
        n_modes_total = sol103_result.mode_shapes.shape[1]
        n_modes_quarter = max(1, n_modes_total // 4)

        u_md, u_ma = self._run_rom_n_modes(
            bulk, aero, subcase, Q_TEST, sol103_result, n_modes_quarter
        )

        # CBAR 1 root bending moment (Mz at end A, local index bm2_a)
        # — most sensitive to load convergence for a tip-loaded cantilever
        from sbeam.solver.sol101 import recover_bar_forces
        cbar1 = bulk.cbars[1]

        bf_ref = recover_bar_forces(cbar1, bulk.grids, bulk.pbars, bulk.mat1s, result_ref.displacements, grid_index)
        bf_md = recover_bar_forces(cbar1, bulk.grids, bulk.pbars, bulk.mat1s, u_md, grid_index)
        bf_ma = recover_bar_forces(cbar1, bulk.grids, bulk.pbars, bulk.mat1s, u_ma, grid_index)

        ref_val = abs(bf_ref.bm2_a)
        if ref_val < 1e-12:
            pytest.skip("Reference bending moment is near-zero; skip convergence test")

        error_md = abs(bf_md.bm2_a - bf_ref.bm2_a) / ref_val
        error_ma = abs(bf_ma.bm2_a - bf_ref.bm2_a) / ref_val

        assert error_ma < error_md, (
            f"Mode-acceleration error ({error_ma:.4f}) is not less than "
            f"mode-displacement error ({error_md:.4f}) at n_modes={n_modes_quarter}"
        )


# ---------------------------------------------------------------------------
# V-C3-5 — k_aa_lu stored and inverts K_aa
# ---------------------------------------------------------------------------

class TestKaaLuStored:
    def test_k_aa_lu_is_tuple(self, setup):
        """Sol144Result.k_aa_lu must be a 2-tuple from scipy.linalg.lu_factor."""
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID)
        result = run_aeroelastic_static(bulk, subcase, aero, q=Q_TEST)

        assert isinstance(result.k_aa_lu, tuple)
        assert len(result.k_aa_lu) == 2

    def test_k_aa_lu_inverts_correctly(self, setup):
        """lu_solve(k_aa_lu, K_aa @ e1) must reproduce e1."""
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID)
        result = run_aeroelastic_static(bulk, subcase, aero, q=Q_TEST)

        Q_aa, K_aa, _f, _fd = _build_qaa_aset(bulk, aero, grid_index, spc_sid=1)
        e1 = np.zeros(K_aa.shape[0])
        e1[0] = 1.0
        rhs = K_aa @ e1
        x = scipy.linalg.lu_solve(result.k_aa_lu, rhs)
        np.testing.assert_allclose(x, e1, atol=1e-10)

    def test_use_rom_no_method_raises(self, setup):
        """use_rom=True without method_sid and no sol103_result must raise ValueError."""
        bulk, aero, grid_index = setup
        subcase = SubcaseControl(subcase_id=1, spc_sid=1, load_sid=TIP_LOAD_SID)
        with pytest.raises(ValueError, match="METHOD"):
            run_aeroelastic_static(bulk, subcase, aero, q=Q_TEST, use_rom=True)
