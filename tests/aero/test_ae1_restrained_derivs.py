"""V-AE1e (partial) — analytic restrained stability derivatives (AE1 Step G).

``_compute_restrained_derivs`` now returns the exact analytic derivative from the
Schur factorisation (∂u_l/∂δ = K_ll⁻¹·C_ax_l, then the linear normalwash/force
chain) instead of the prior one-pass finite-difference hybrid (AE8).  The trim
problem is linear in each label, so the analytic columns equal the old FD columns
to round-off — these tests lock both that equivalence and the physical targets:

  * the rigid derivative columns are untouched (CZα = 5.071, CMα = −2.871);
  * the restrained CZα reproduces NASTRAN HA144A Table 7-1 (5.103 at q=40, the
    documented ~0.6 % flexible increment over the rigid value);
  * the analytic columns match the captured pre-rewrite FD baseline.

The remaining Table 7-1 restrained columns (Cmα, Cmq, CZδe, Cmδe, …) and the
documented high-q flexible increment require the MSC HA144A manual values; sourcing
them is the completion of V-AE1e and remains tracked on AE8.
"""

import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"

# NASTRAN HA144A references (sbeam sign convention: CZ stored positive).
RIGID_CZA = 5.07097      # rigid CZα (NASTRAN −5.07097)
RIGID_CMA = -2.87093     # rigid CMα (NASTRAN −2.871)
REST_CZA_Q40 = 5.103     # Table 7-1 restrained CZα at q=40 (0.6% flexible increment)

# Captured pre-rewrite finite-difference baseline (q=40), for the FD≈analytic
# regression — the rewrite must be behaviour-preserving.
FD_REST_SC1 = {
    "ANGLEA": {"CZ": 5.112144654508199, "CMY": -2.8991302831553867},
    "ELEV":   {"CZ": 0.25721154880784525, "CMY": 0.5642385940095096},
}


@pytest.fixture(scope="module")
def result_sc1():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        return run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero
        )


class TestRigidColumnsUnchanged:
    """Step G must not disturb the rigid derivative path."""

    def test_rigid_cza(self, result_sc1):
        assert result_sc1.rigid_derivs["ANGLEA"]["CZ"] == pytest.approx(
            RIGID_CZA, rel=0.01
        )

    def test_rigid_cma(self, result_sc1):
        assert result_sc1.rigid_derivs["ANGLEA"]["CMY"] == pytest.approx(
            RIGID_CMA, rel=0.01
        )


class TestRestrainedDerivs:
    """Restrained CZα vs NASTRAN Table 7-1 (q=40)."""

    def test_restrained_cza(self, result_sc1):
        cza = result_sc1.restrained_derivs["ANGLEA"]["CZ"]
        assert cza == pytest.approx(REST_CZA_Q40, rel=0.01), (
            f"restrained CZα={cza:.5f} not within 1% of Table 7-1 {REST_CZA_Q40}"
        )

    def test_restrained_above_rigid(self, result_sc1):
        """The restrained (flexible) CZα magnitude exceeds the rigid value."""
        assert (
            result_sc1.restrained_derivs["ANGLEA"]["CZ"]
            > result_sc1.rigid_derivs["ANGLEA"]["CZ"]
        )


class TestAnalyticMatchesFD:
    """Analytic columns reproduce the captured FD baseline to round-off."""

    @pytest.mark.parametrize("label", ["ANGLEA", "ELEV"])
    @pytest.mark.parametrize("comp", ["CZ", "CMY"])
    def test_matches_fd(self, result_sc1, label, comp):
        got = result_sc1.restrained_derivs[label][comp]
        assert got == pytest.approx(FD_REST_SC1[label][comp], rel=1e-6, abs=1e-9)
