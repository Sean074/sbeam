"""V-AE1 gate — K_eff in Schur trim solve.

Verifies that SOL 144 trim produces ANGLEA and ELEV values matching the MSC
Nastran Listing 7-2 reference for both HA144A subcases:

  SC1 (q=40  psf): ANGLEA = +0.169191 rad,  ELEV = +0.492457 rad
  SC2 (q=1200 psf): ANGLEA = +0.001373 rad,  ELEV = +0.019325 rad

SC2 at q=1200 exercises the flexible aeroelastic increment (restrained CZα
changes 27% from q=40 to q=1200) that only appears when K_eff = K_aa - q*Q_aa
is used in the Schur partition.
"""

import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_sbeam.bdf"

# Listing 7-2 reference values (MSC Nastran Aeroelastic Analysis User's Guide)
SC1_ANGLEA = 0.169191   # rad
SC1_ELEV   = 0.492457   # rad
SC2_ANGLEA = 0.001373   # rad
SC2_ELEV   = 0.019325   # rad

ATOL_ANGLEA = 1e-3      # rad — loose first pass
ATOL_ELEV   = 5e-3      # rad


@pytest.fixture(scope="module")
def ha144a():
    """Parse HA144A deck and build AeroModel once for the module."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, parity=bulk.aeros.symxz, grid_index=grid_index)
    return bulk, aero


@pytest.fixture(scope="module")
def result_sc1(ha144a):
    bulk, aero = ha144a
    subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(bulk, subcase, aero)


@pytest.fixture(scope="module")
def result_sc2(ha144a):
    bulk, aero = ha144a
    subcase = SubcaseControl(subcase_id=2, spc_sid=1, trim_sid=2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(bulk, subcase, aero)


class TestV_AE1_SC1:
    """SC1: q=40 psf, quasi-rigid trim — gate on sign and magnitude."""

    def test_anglea_sign(self, result_sc1):
        """ANGLEA must be positive (nose-up for upward lift)."""
        val = result_sc1.trim_vars['ANGLEA']
        assert val > 0, f"SC1 ANGLEA = {val:.6f}, expected > 0"

    def test_elev_sign(self, result_sc1):
        """ELEV must be positive."""
        val = result_sc1.trim_vars['ELEV']
        assert val > 0, f"SC1 ELEV = {val:.6f}, expected > 0"

    def test_anglea_value(self, result_sc1):
        """SC1 ANGLEA must match Listing 7-2 within tolerance."""
        val = result_sc1.trim_vars['ANGLEA']
        assert abs(val - SC1_ANGLEA) < ATOL_ANGLEA, (
            f"V-AE1 SC1 ANGLEA: got {val:.6f}, expected {SC1_ANGLEA:.6f} "
            f"(tol {ATOL_ANGLEA})"
        )

    def test_elev_value(self, result_sc1):
        """SC1 ELEV must match Listing 7-2 within tolerance."""
        val = result_sc1.trim_vars['ELEV']
        assert abs(val - SC1_ELEV) < ATOL_ELEV, (
            f"V-AE1 SC1 ELEV: got {val:.6f}, expected {SC1_ELEV:.6f} "
            f"(tol {ATOL_ELEV})"
        )

    def test_trim_lift(self, result_sc1):
        """Total lift must be positive (1g upward, not -1g)."""
        assert result_sc1.total_cl > 0, (
            f"SC1 total_cl = {result_sc1.total_cl:.6f}, expected > 0"
        )


class TestV_AE1_SC2:
    """SC2: q=1200 psf, high-speed — exercises the flexible aeroelastic increment."""

    def test_anglea_sign(self, result_sc2):
        """ANGLEA must be positive."""
        val = result_sc2.trim_vars['ANGLEA']
        assert val > 0, f"SC2 ANGLEA = {val:.6f}, expected > 0"

    def test_elev_sign(self, result_sc2):
        """ELEV must be positive."""
        val = result_sc2.trim_vars['ELEV']
        assert val > 0, f"SC2 ELEV = {val:.6f}, expected > 0"

    def test_anglea_value(self, result_sc2):
        """SC2 ANGLEA must match Listing 7-2 within tolerance."""
        val = result_sc2.trim_vars['ANGLEA']
        assert abs(val - SC2_ANGLEA) < ATOL_ANGLEA, (
            f"V-AE1 SC2 ANGLEA: got {val:.6f}, expected {SC2_ANGLEA:.6f} "
            f"(tol {ATOL_ANGLEA})"
        )

    def test_elev_value(self, result_sc2):
        """SC2 ELEV must match Listing 7-2 within tolerance."""
        val = result_sc2.trim_vars['ELEV']
        assert abs(val - SC2_ELEV) < ATOL_ELEV, (
            f"V-AE1 SC2 ELEV: got {val:.6f}, expected {SC2_ELEV:.6f} "
            f"(tol {ATOL_ELEV})"
        )

    def test_trim_lift(self, result_sc2):
        """Total lift must be positive."""
        assert result_sc2.total_cl > 0, (
            f"SC2 total_cl = {result_sc2.total_cl:.6f}, expected > 0"
        )

    def test_flexible_increment(self, result_sc1, result_sc2):
        """SC2 ANGLEA must be substantially smaller than SC1 (aeroelastic stiffening)."""
        a1 = result_sc1.trim_vars['ANGLEA']
        a2 = result_sc2.trim_vars['ANGLEA']
        assert a2 < a1, (
            f"No flexible increment: SC2 ANGLEA ({a2:.6f}) >= SC1 ANGLEA ({a1:.6f}); "
            "q*Q_aa feedback is missing"
        )
