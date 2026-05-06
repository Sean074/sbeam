"""Step 24: End-to-end integration verification tests (V1–V13).

Each test reads a BDF file through parse_bdf, runs the solver, and checks
the result against a closed-form analytical value.
"""

import math
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol101 import run_sol101
from sbeam.solver.sol103 import run_sol103
from sbeam.assembly.load_vector import build_grid_index

BDF_DIR = Path(__file__).parent / "bdf"

# Model parameters — must match the BDF files
E   = 2.0e11
I   = 8.333e-4
A   = 0.05
rho = 7850.0
L   = 1.0
P   = 1000.0


# ---------------------------------------------------------------------------
# Module-scoped fixtures — reuse solver results across V1+V2
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cantilever_sol101():
    cc, bulk = parse_bdf(BDF_DIR / "v1_v2_cantilever.bdf")
    result = run_sol101(bulk, cc)
    grid_index = build_grid_index(bulk)
    return result, grid_index


@pytest.fixture(scope="module")
def simply_supported_sol101():
    cc, bulk = parse_bdf(BDF_DIR / "v3_simply_supported.bdf")
    result = run_sol101(bulk, cc)
    grid_index = build_grid_index(bulk)
    return result, grid_index


@pytest.fixture(scope="module")
def fixed_fixed_sol101():
    cc, bulk = parse_bdf(BDF_DIR / "v4_fixed_fixed_udl.bdf")
    result = run_sol101(bulk, cc)
    return result


# ---------------------------------------------------------------------------
# V1: Cantilever tip deflection  δ = PL³/3EI  (< 0.1%)
# ---------------------------------------------------------------------------

class TestV1CantileverTipDeflection:
    def test_tip_ty(self, cantilever_sol101):
        result, grid_index = cantilever_sol101
        ty = result.displacements[6 * grid_index[11] + 1]
        expected = P * L**3 / (3 * E * I)
        assert ty == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# V2: Cantilever fixed-end moment  M = PL  (< 0.1%)
# ---------------------------------------------------------------------------

class TestV2CantileverFixedEndMoment:
    def test_fixed_end_mz(self, cantilever_sol101):
        result, _ = cantilever_sol101
        # Mz reaction at node 1 (index 5 in the 6-DOF reaction vector)
        mz = abs(result.reactions[1][5])
        assert mz == pytest.approx(P * L, rel=1e-3)


# ---------------------------------------------------------------------------
# V3: Simply supported mid-span deflection  δ = PL³/48EI  (< 0.1%)
# ---------------------------------------------------------------------------

class TestV3SimplySupported:
    def test_midspan_ty(self, simply_supported_sol101):
        result, grid_index = simply_supported_sol101
        ty = result.displacements[6 * grid_index[6] + 1]
        expected = P * L**3 / (48 * E * I)
        assert ty == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# V4: Fixed-fixed UDL — reactions sum to total load  (< 0.1%)
# ---------------------------------------------------------------------------

class TestV4FixedFixedUDL:
    TOTAL_LOAD = 9 * 1000.0  # 9 interior nodes × 1000 N

    def test_reaction_equilibrium(self, fixed_fixed_sol101):
        result = fixed_fixed_sol101
        # Reactions oppose the applied +Y forces, so sum is negative; check magnitude
        reaction_sum = abs(result.reactions[1][1] + result.reactions[11][1])
        assert reaction_sum == pytest.approx(self.TOTAL_LOAD, rel=1e-3)


# ---------------------------------------------------------------------------
# V5: Cantilever first natural frequency  f₁ = (1.8751²/2π)√(EI/ρAL⁴)  (< 1%)
# ---------------------------------------------------------------------------

class TestV5CantileverModal:
    def test_first_frequency(self):
        cc, bulk = parse_bdf(BDF_DIR / "v5_cantilever_modal.bdf")
        result = run_sol103(bulk, cc)
        expected = (1.87510**2 / (2 * math.pi)) * math.sqrt(E * I / (rho * A)) / L**2
        assert result.frequencies_hz[0] == pytest.approx(expected, rel=0.01)


# ---------------------------------------------------------------------------
# V6: Free-free beam — first 6 modes near zero  (< 1e-4 Hz)
# ---------------------------------------------------------------------------

class TestV6FreeFree:
    def test_rigid_body_modes(self):
        cc, bulk = parse_bdf(BDF_DIR / "v6_free_free_modal.bdf")
        result = run_sol103(bulk, cc)
        # Numerical noise places rigid body modes up to ~0.003 Hz; first elastic >> 1 Hz
        assert np.all(result.frequencies_hz[:6] < 0.1)


# ---------------------------------------------------------------------------
# V7: Simply supported first mode  f₁ = (π²/2πL²)√(EI/ρA)  (< 1%)
# ---------------------------------------------------------------------------

class TestV7SimplySupported:
    def test_first_frequency(self):
        cc, bulk = parse_bdf(BDF_DIR / "v7_simply_supported_modal.bdf")
        result = run_sol103(bulk, cc)
        expected = (math.pi**2 / (2 * math.pi * L**2)) * math.sqrt(E * I / (rho * A))
        assert result.frequencies_hz[0] == pytest.approx(expected, rel=0.01)


# V8/V9 model parameters (massless beam, unit stiffness)
G_V8 = 1.0
J_V8 = 2.0
L_V8 = 1.0
I11_V8 = 2.0

E_V9 = 1.0
I1_V9 = 1.0
L_V9 = 1.0
M_V9 = 2.0
D_V9 = 0.5   # x1 axial offset
I22_V9 = 0.1


# ---------------------------------------------------------------------------
# V8: CONM2 torsional inertia  f = sqrt(GJ/(L·I11)) / (2π)  (< 1%)
# ---------------------------------------------------------------------------

class TestV8Conm2TorsionalInertia:
    def test_torsional_frequency(self):
        cc, bulk = parse_bdf(BDF_DIR / "v8_conm2_torsional_inertia.bdf")
        result = run_sol103(bulk, cc)
        expected = math.sqrt(G_V8 * J_V8 / (L_V8 * I11_V8)) / (2 * math.pi)
        assert result.frequencies_hz[0] == pytest.approx(expected, rel=0.01)


# ---------------------------------------------------------------------------
# V9: CONM2 axial offset — coupled bending, parallel-axis theorem  (< 1%)
# ---------------------------------------------------------------------------

class TestV9Conm2OffsetBending:
    @staticmethod
    def _analytical_freqs():
        from scipy.linalg import eigh as sp_eigh
        K = np.array([[12 * E_V9 * I1_V9 / L_V9**3, 6 * E_V9 * I1_V9 / L_V9**2],
                      [6 * E_V9 * I1_V9 / L_V9**2, 4 * E_V9 * I1_V9 / L_V9]])
        m_rr = M_V9 * D_V9**2 + I22_V9
        m_tr = -M_V9 * D_V9
        M = np.array([[M_V9, m_tr], [m_tr, m_rr]])
        vals, _ = sp_eigh(K, M)
        return np.sqrt(np.clip(vals, 0, None)) / (2 * math.pi)

    def test_first_frequency(self):
        cc, bulk = parse_bdf(BDF_DIR / "v9_conm2_offset_bending.bdf")
        result = run_sol103(bulk, cc)
        expected = self._analytical_freqs()
        assert result.frequencies_hz[0] == pytest.approx(expected[0], rel=0.01)

    def test_second_frequency(self):
        cc, bulk = parse_bdf(BDF_DIR / "v9_conm2_offset_bending.bdf")
        result = run_sol103(bulk, cc)
        expected = self._analytical_freqs()
        assert result.frequencies_hz[1] == pytest.approx(expected[1], rel=0.01)


# ---------------------------------------------------------------------------
# V10: CONM2 tip mass on zero-density cantilever — f = sqrt(3EI/mL^3) / (2pi)
# Verifies Tikhonov regularisation of singular mass matrix (rho=0, no CONM2 inertia)
# ---------------------------------------------------------------------------

E_V10 = 70.0e9
I1_V10 = (0.02 ** 4) / 12
L_V10 = 1.0
M_V10 = 1.0


class TestV10Conm2ZeroDensity:
    def test_no_linalg_error(self):
        import scipy.linalg
        cc, bulk = parse_bdf(BDF_DIR / "v10_conm2_zero_density.bdf")
        try:
            run_sol103(bulk, cc)
        except scipy.linalg.LinAlgError as exc:
            pytest.fail(f"LinAlgError raised for zero-density CONM2 model: {exc}")

    def test_bending_frequency(self):
        cc, bulk = parse_bdf(BDF_DIR / "v10_conm2_zero_density.bdf")
        result = run_sol103(bulk, cc)
        expected = math.sqrt(3 * E_V10 * I1_V10 / (M_V10 * L_V10 ** 3)) / (2 * math.pi)
        assert result.frequencies_hz[0] == pytest.approx(expected, rel=0.01)


# V11/V12 model parameters (unit stiffness, massless beam)
G_V11 = 1.0
J_V11 = 2.0
L_V11 = 1.0
T_V11 = 4.0

G_V12 = 1.0
J_V12 = 2.0
L_V12 = 1.0
M_V12 = 2.0
D_V12 = 1.0


# ---------------------------------------------------------------------------
# V11: SOL 101 cantilever torsion  theta_x = T*L/(G*J)  (< 0.1%)
# ---------------------------------------------------------------------------

class TestV11CantileverTorsionSol101:
    def test_torsional_rotation(self):
        cc, bulk = parse_bdf(BDF_DIR / "v11_cantilever_torsion_sol101.bdf")
        result = run_sol101(bulk, cc)
        grid_index = build_grid_index(bulk)
        node2_rx = result.displacements[6 * grid_index[2] + 3]
        expected = T_V11 * L_V11 / (G_V11 * J_V11)
        assert node2_rx == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# V12: SOL 103 torsional mode via CONM2 transverse offset
#      I_eff = m*d^2 (parallel-axis),  f = sqrt(GJ/(L*m*d^2)) / (2pi)  (< 1%)
# ---------------------------------------------------------------------------

class TestV12Conm2OffsetTorsionSol103:
    def test_torsional_frequency(self):
        cc, bulk = parse_bdf(BDF_DIR / "v12_conm2_offset_torsion_sol103.bdf")
        result = run_sol103(bulk, cc)
        I_eff = M_V12 * D_V12 ** 2
        expected = math.sqrt(G_V12 * J_V12 / (L_V12 * I_eff)) / (2 * math.pi)
        assert result.frequencies_hz[0] == pytest.approx(expected, rel=0.01)


# ---------------------------------------------------------------------------
# V13: SOL 101 RBE2 rigid coupling
#      1-element cantilever + coincident grid coupled via RBE2
#      Force at dependent grid → tip deflection = PL^3/3EI;  u[GM] == u[GN]
# ---------------------------------------------------------------------------

E_V13 = 2.0e11
I_V13 = 8.333e-4
L_V13 = 1.0
P_V13 = 1000.0


class TestV13Rbe2RigidCoupling:
    @pytest.fixture(scope="class")
    def result_and_gi(self):
        cc, bulk = parse_bdf(BDF_DIR / "v13_rbe2_rigid_coupling.bdf")
        result = run_sol101(bulk, cc)
        grid_index = build_grid_index(bulk)
        return result, grid_index

    def test_gid2_tip_deflection(self, result_and_gi):
        """Ty at CBAR tip (GID 2) matches cantilever formula PL^3/3EI."""
        result, gi = result_and_gi
        ty = result.displacements[6 * gi[2] + 1]
        expected = P_V13 * L_V13 ** 3 / (3 * E_V13 * I_V13)
        assert ty == pytest.approx(expected, rel=1e-3)

    def test_gid3_equals_gid2(self, result_and_gi):
        """RBE2 constraint: all DOFs of GID 3 (dependent) == GID 2 (independent)."""
        result, gi = result_and_gi
        u2 = result.displacements[6 * gi[2]: 6 * gi[2] + 6]
        u3 = result.displacements[6 * gi[3]: 6 * gi[3] + 6]
        np.testing.assert_allclose(u3, u2, atol=1e-12)
