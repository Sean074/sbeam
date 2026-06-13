"""V-AE1f gate — full-span HA144A trim cross-check (parity ground truth).

`sample/ha144a_fullspan_sbeam.bdf` is an explicit full-span model (SYMXZ=0): both
wings and both canards are meshed, the structure is mirrored, and the fuselage mass
is doubled so the model is an exact 2x replica of the half-span ha144a_sbeam.bdf —
same CL (W/S) and same CG_x (=17.18 ft). It therefore MUST trim to the same angles
as NASTRAN Listing 7-2, with NO symmetry doubling (parity = AEROS.SYMXZ = 0 → sym=1).

Why this is a permanent regression gate (added with the AE1 parity re-diagnosis,
2026-06-12): the half-span trim is currently wrong because `run_sol144_trim` doubles
the aero load (`sym=2`) but not the inertial load. The full-span path has no `sym`
factor to get wrong, so it is independent ground truth: at SC1 (q=40, rigid-
dominated) it already matches NASTRAN to ~1%. Once the half-model parity fix lands,
the half-model SC1 must agree with this full-span result. This gate locks the
full-span path so a future change cannot silently break it.

NOTE: only SC1 is gated. SC2 (q=1200) exercises the flexible q*Q_aa / restrained-
derivative path, which is a SEPARATE still-open issue (AE1 Step G / AE8) — even the
full-span ground truth misses NASTRAN at SC2, so it is deliberately NOT asserted here.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"

# NASTRAN Listing 7-2 SC1 (q=40) reference — same airplane the half-span trims.
SC1_ANGLEA = 0.169191   # rad
SC1_ELEV   = 0.492457   # rad
REL_TOL    = 0.02       # ~2% (full-span actual: ANGLEA ~1.1% high, ELEV ~0.3% low)

G_FT_S2 = 32.174        # standard gravity, ft/s^2


@pytest.fixture(scope="module")
def fullspan():
    """Parse the full-span deck and build the AeroModel once (parity from SYMXZ=0)."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, parity=bulk.aeros.symxz, grid_index=grid_index)
    return bulk, aero, grid_index


@pytest.fixture(scope="module")
def result_sc1(fullspan):
    bulk, aero, _gi = fullspan
    subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(bulk, subcase, aero)


class TestFullSpanModel:
    """The full-span deck must be built with no symmetry doubling."""

    def test_parity_is_zero(self, fullspan):
        """SYMXZ=0 → parity=0 → sym=1 (no aero doubling on a full-span model)."""
        bulk, aero, _gi = fullspan
        assert bulk.aeros.symxz == 0
        assert aero.parity == 0

    def test_box_count_is_double(self, fullspan):
        """Full span has both wings + both canards = 2x the 40-box half model."""
        _bulk, aero, _gi = fullspan
        assert len(aero.boxes) == 80

    def test_rigid_pitch_reproduced(self, fullspan):
        """Mirrored splines must reproduce a global rigid pitch as uniform incidence.

        Guards the left-wing (CID 3) and left-canard splines: a global theta about
        y through the reference must give uniform streamwise incidence ~ +theta on
        every box (the V-AE1b property, on the full-span geometry).
        """
        bulk, aero, gi = fullspan
        theta, x_ref = 1e-3, 15.0
        u = np.zeros(6 * len(gi))
        for gid, i in gi.items():
            g = bulk.grids[gid]
            r = np.array([g.x - x_ref, g.y, g.z])
            u[6 * i:6 * i + 3] = np.cross(np.array([0.0, theta, 0.0]), r)
            u[6 * i + 4] = theta
        inc = aero.g_slope @ u
        assert np.allclose(inc, theta, atol=2e-5), (
            f"rigid pitch not uniform: min={inc.min():.3e} max={inc.max():.3e}"
        )


class TestFullSpanTrimSC1:
    """V-AE1f — SC1 trim matches NASTRAN within ~2% on the parity ground-truth model."""

    def test_anglea_within_2pct(self, result_sc1):
        val = result_sc1.trim_vars["ANGLEA"]
        assert val == pytest.approx(SC1_ANGLEA, rel=REL_TOL), (
            f"full-span SC1 ANGLEA={val:.6f} not within {REL_TOL:.0%} of {SC1_ANGLEA:.6f}"
        )

    def test_elev_within_2pct(self, result_sc1):
        val = result_sc1.trim_vars["ELEV"]
        assert val == pytest.approx(SC1_ELEV, rel=REL_TOL), (
            f"full-span SC1 ELEV={val:.6f} not within {REL_TOL:.0%} of {SC1_ELEV:.6f}"
        )

    def test_lift_balances_weight(self, result_sc1, fullspan):
        """Trimmed lift must balance the full-span weight (= 2x8000 = 16000 lb)."""
        bulk, _aero, _gi = fullspan
        weight = sum(c.m for c in bulk.conm2s.values()) * G_FT_S2
        lift = result_sc1.q * result_sc1.total_cl * bulk.aeros.sref
        assert lift == pytest.approx(weight, rel=0.01), (
            f"lift={lift:.1f} lb does not balance weight={weight:.1f} lb"
        )
        # Sanity: this really is the doubled (whole-airplane) weight.
        assert weight == pytest.approx(16000.0, rel=0.001)


class TestFullSpanSymmetry:
    """The single-point-ground full-span model must produce a symmetric response
    on its own — no centreline symmetry SPCs are imposed."""

    def test_antisymmetric_dofs_zero(self, result_sc1, fullspan):
        """Centreline Ty/Rx/Rz come out ~0 with no SPC forcing them."""
        _bulk, _aero, gi = fullspan
        u = result_sc1.displacements
        anti = []
        for gid in (97, 98, 99, 100):
            b = gi[gid] * 6
            anti += [u[b + 1], u[b + 3], u[b + 5]]   # Ty, Rx, Rz
        assert max(abs(a) for a in anti) < 1e-9, (
            f"antisymmetric centreline DOF not ~0: max={max(abs(a) for a in anti):.3e}"
        )

    def test_wing_tips_mirror(self, result_sc1, fullspan):
        """Left and right wing-tip vertical deflections must match (mirror symmetry)."""
        _bulk, _aero, gi = fullspan
        u = result_sc1.displacements
        tz_right = u[gi[122] * 6 + 2]
        tz_left = u[gi[222] * 6 + 2]
        assert tz_right == pytest.approx(tz_left, abs=1e-9), (
            f"wing tips not symmetric: right={tz_right:.6e} left={tz_left:.6e}"
        )
        assert abs(tz_right) > 1e-6, "wing-tip deflection ~0 — model may be over-constrained"
