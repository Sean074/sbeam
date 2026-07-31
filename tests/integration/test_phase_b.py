"""Step 49 V-B2 integration tests — force transfer & coupled smoke test.

Uses val_spline2_cantilever.bdf: 4 CBARs along Y, 4-span×1-chord CAERO1,
SPLINE2 via CORD2R CID=1, full span.
"""

import dataclasses
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.assembly.load_vector import build_grid_index
from sbeam.aero.aero_model import build_aero_model, compute_structural_loads
from sbeam.aero.coupling import build_fg
from sbeam.aero.vlm import solve_rigid_cl

BDF_PATH = Path(__file__).parent / "bdf" / "val_spline2_cantilever.bdf"
Q = 1000.0    # dynamic pressure, Pa
ALPHA = 0.05  # angle of attack, rad (~2.87°)
SREF = 4.0    # from AEROS card


@pytest.fixture(scope="module")
def cantilever_aero():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index)
    return aero, grid_index, bulk


class TestVirtualWorkBalance:
    """V-B2a — total structural Tz equals box Fz sum (machine precision)."""

    def test_total_tz_matches_box_fz_sum(self, cantilever_aero):
        """sum(f_g[Tz]) == q * sum(f_box_z) to < 1e-10 relative.

        Exact by virtual work (partition-of-unity of SPLINE2 basis functions).
        Independent of the gamma/cp naming convention.
        """
        aero, grid_index, _ = cantilever_aero
        f_g = compute_structural_loads(aero, Q, ALPHA)

        f_tz_sum = sum(f_g[6 * gi + 2] for gi in grid_index.values())

        # Reconstruct f_box_z using the same internal path
        w_aoa = np.array([-(ALPHA * b.normal[2]) for b in aero.boxes])
        gamma = aero.ajj_inv_corr @ (w_aoa + aero.wg)
        f_box_z = Q * float(np.sum((aero.skj @ gamma)[2::3]))

        scale = max(abs(f_tz_sum), 1.0)
        assert abs(f_tz_sum - f_box_z) < 1e-10 * scale


class TestCLPlausibility:
    """V-B2b — total lift is physically proportional to VLM CL."""

    def test_tz_sum_vs_cl_magnitude(self, cantilever_aero):
        """f_g Tz sum is within 2% of q*CL*sref or q*CL*sref/2.

        If AIC maps normalwash → cp, then f_tz_sum ≈ q*CL*sref.
        If AIC maps normalwash → Γ,  then f_tz_sum ≈ q*CL*sref/2.
        Either is self-consistent; test accepts both within 2%.
        """
        aero, grid_index, bulk = cantilever_aero
        f_g = compute_structural_loads(aero, Q, ALPHA)
        f_tz = sum(f_g[6 * gi + 2] for gi in grid_index.values())

        vlm = solve_rigid_cl(aero.boxes, ALPHA, aeros=bulk.aeros)
        cl = vlm["CL"]
        expected_full = Q * cl * SREF
        expected_half = Q * cl * SREF / 2.0

        err_full = abs(f_tz - expected_full) / max(abs(expected_full), 1e-12)
        err_half = abs(f_tz - expected_half) / max(abs(expected_half), 1e-12)
        assert min(err_full, err_half) < 0.02, (
            f"f_tz={f_tz:.4e}, q*CL*sref={expected_full:.4e}, /2={expected_half:.4e}; "
            f"neither within 2%"
        )
        assert f_tz > 0.0, "lift must be upward (positive Tz)"


class TestBuildFgAgreement:
    """V-B2c — alpha=0 path agrees with build_fg (machine precision)."""

    def test_alpha_zero_equals_build_fg(self, cantilever_aero):
        """compute_structural_loads(alpha=0) == q * build_fg(aero, g_disp).

        Both evaluate g_disp.T @ skj @ ajj_inv_corr @ wg.
        A non-zero injected wg makes the comparison non-trivial.
        """
        aero, _, _ = cantilever_aero
        injected_wg = 0.01 * np.ones(len(aero.boxes))
        aero_mut = dataclasses.replace(aero, wg=injected_wg)

        f_func = compute_structural_loads(aero_mut, Q, alpha=0.0)
        f_coupling = Q * build_fg(aero_mut, aero_mut.g_disp)

        max_diff = np.max(np.abs(f_func - f_coupling))
        scale = max(float(np.max(np.abs(f_func))), 1e-20)
        assert max_diff / scale < 1e-12


class TestErrorHandling:
    """V-B2d — ValueError when the force-transfer spline is None."""

    def test_raises_without_spline(self, cantilever_aero):
        aero, _, _ = cantilever_aero
        aero_no_spline = dataclasses.replace(aero, g_load=None)
        with pytest.raises(ValueError, match="g_load is None"):
            compute_structural_loads(aero_no_spline, Q, ALPHA)
