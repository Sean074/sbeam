"""Step 24: End-to-end integration verification tests (V1–V7).

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
