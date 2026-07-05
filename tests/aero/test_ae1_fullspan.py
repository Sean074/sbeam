"""V-AE1f gate — full-span HA144A static-trim acceptance.

`sample/ha144a_fullspan_sbeam.bdf` is the HA144A trim model: an explicit
full-span deck (SYMXZ=0) with both wings and both canards meshed, the structure
mirrored, and the fuselage mass doubled so the whole airplane = 16000 lb. It is
the sole HA144A trim gate since half-span support was removed (the old half-span
deck + its `sym=2` doubling — the AE1 Step D double-count — are gone). With no
`sym` factor anywhere, the aero and inertial loads are both whole-airplane and
consistent, so SC1 (q=40, rigid-dominated) trims to NASTRAN Listing 7-2
(ANGLEA=0.169191, ELEV=0.492457) within ~2%.

SC2 (q=1200) exercises the flexible q*Q_aa / restrained-derivative path, a
SEPARATE still-open issue (AE8): its exact ELEV is not value-gated, but its
signs and the flexible aeroelastic increment (ANGLEA decreasing with q) are.

V-AE1d (AE1 Step F) lives beside V-AE1f here: the same trim, but with
acceptance gauged against each TRIM variable's full-scale physical range, not
relative to its NASTRAN target. A relative tolerance is meaningless for SC2:
its trim AoA legitimately passes through ~0 as q rises, so a fixed absolute
error reads as an exploding percentage (the old gate saw ANGLEA "+136%" for a
0.0019 rad / 0.1deg miss). Normalised to the variable's valid range instead —
AoA over a 30deg neg->pos stall band, the elevator over its 40deg commanded
throw — both subcases pass within <=0.4% FS. SC1 keeps its existing live
relative gate (already green); SC2 is now a live %FS gate (no longer xfail).
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

# NASTRAN Listing 7-2 SC2 (q=1200) reference (xfail target — AE8 / AE1 Step G).
SC2_ANGLEA = 0.001373   # rad
SC2_ELEV   = 0.019325   # rad

# V-AE1d SC1 per-target relative tolerances (SC1 is rigid-dominated, trim point
# well away from zero, so relative tolerances are meaningful there).
REL_ANGLEA_SC1 = 0.005  # SC1 ANGLEA actual +0.011% (post AC7 fuselage+spline fix)
REL_ELEV_SC1   = 0.005  # SC1 ELEV actual -0.15%
LIFT_FULLSPAN  = 16000.0  # lb (whole-airplane weight)

# V-AE1d SC2 %-full-scale tolerances: 1% of each variable's valid physical range.
# SC2's trim point is near zero, so a relative gate is meaningless; normalise to
# the range instead (AE1 Step F). SC2 actual (post-AC7 fuselage+beam-spline fix,
# which removed the old AE8a common-mode bias): ANGLEA +0.0086deg = 0.03% FS,
# ELEV -0.043deg = 0.11% FS — both comfortably inside the tightened bands.
TOL_ANGLEA_FS = np.deg2rad(0.1)  # 0.33% of 30deg AoA neg->pos stall band
TOL_ELEV_FS   = np.deg2rad(0.1)  # 0.25% of the 40deg commanded elevator throw

G_FT_S2 = 32.174        # standard gravity, ft/s^2


@pytest.fixture(scope="module")
def fullspan():
    """Parse the full-span deck and build the AeroModel once (parity from SYMXZ=0)."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index)
    return bulk, aero, grid_index


@pytest.fixture(scope="module")
def result_sc1(fullspan):
    bulk, aero, _gi = fullspan
    subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(bulk, subcase, aero)


@pytest.fixture(scope="module")
def result_sc2(fullspan):
    bulk, aero, _gi = fullspan
    subcase = SubcaseControl(subcase_id=2, spc_sid=1, trim_sid=2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(bulk, subcase, aero)


class TestFullSpanModel:
    """The full-span deck must be built with no symmetry doubling."""

    def test_symxz_is_zero(self, fullspan):
        """Full-span deck carries SYMXZ=SYMXY=0 — no symmetry doubling exists."""
        bulk, _aero, _gi = fullspan
        assert bulk.aeros.symxz == 0
        assert bulk.aeros.symxy == 0

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


class TestFullSpanTrimSC2:
    """SC2 (q=1200): the exact ELEV is AE8-deferred (flexible/restrained-derivative
    path), so it is not value-gated.  Signs and the flexible aeroelastic increment
    (ANGLEA decreases from q=40 to q=1200 as the wing washes out) are robust and
    gated here — this is the coverage previously held by the half-span trim test.
    """

    def test_anglea_near_zero(self, result_sc2):
        """SC2 trim AoA is legitimately ~0 (NASTRAN +0.0787deg); post-AC7 sbeam
        sits at +0.0873deg (+0.03% FS) — gate to the same %FS band as V-AE1d."""
        val = result_sc2.trim_vars["ANGLEA"]
        assert abs(val - SC2_ANGLEA) < TOL_ANGLEA_FS

    def test_elev_positive(self, result_sc2):
        assert result_sc2.trim_vars["ELEV"] > 0

    def test_trim_lift_positive(self, result_sc2):
        assert result_sc2.total_cl > 0

    def test_flexible_increment(self, result_sc1, result_sc2):
        a1 = result_sc1.trim_vars["ANGLEA"]
        a2 = result_sc2.trim_vars["ANGLEA"]
        assert a2 < a1, (
            f"no aeroelastic stiffening: SC2 ANGLEA ({a2:.6f}) >= SC1 ({a1:.6f})"
        )


class TestVAE1dSC1:
    """V-AE1d (AE1 Step F) — SC1 trim vs NASTRAN Listing 7-2 with per-target
    relative tolerances (ANGLEA 1.5%, ELEV 1%, lift 1%)."""

    def test_anglea(self, result_sc1):
        val = result_sc1.trim_vars["ANGLEA"]
        assert val == pytest.approx(SC1_ANGLEA, rel=REL_ANGLEA_SC1), (
            f"SC1 ANGLEA={val:.6f} not within {REL_ANGLEA_SC1:.1%} of {SC1_ANGLEA:.6f}"
        )

    def test_elev(self, result_sc1):
        val = result_sc1.trim_vars["ELEV"]
        assert val == pytest.approx(SC1_ELEV, rel=REL_ELEV_SC1), (
            f"SC1 ELEV={val:.6f} not within {REL_ELEV_SC1:.1%} of {SC1_ELEV:.6f}"
        )

    def test_lift_balances_weight(self, result_sc1, fullspan):
        bulk, _aero, _gi = fullspan
        lift = result_sc1.q * result_sc1.total_cl * bulk.aeros.sref
        assert lift == pytest.approx(LIFT_FULLSPAN, rel=0.01), (
            f"SC1 lift={lift:.1f} lb does not balance {LIFT_FULLSPAN:.0f} lb"
        )


class TestVAE1dSC2:
    """V-AE1d (AE1 Step F) — SC2 trim vs NASTRAN Listing 7-2, gated to 1% of each
    variable's full-scale physical range (not relative-to-value, which is
    meaningless at SC2's near-zero trim point). Both targets pass within <=0.4%
    FS; the residual ~0.1deg q-invariant common-mode offset is tracked on AE8a."""

    def test_anglea(self, result_sc2):
        val = result_sc2.trim_vars["ANGLEA"]
        assert val == pytest.approx(SC2_ANGLEA, abs=TOL_ANGLEA_FS), (
            f"SC2 ANGLEA={val:.6f} off by {np.rad2deg(val - SC2_ANGLEA):+.4f}deg "
            f"({abs(np.rad2deg(val - SC2_ANGLEA)) / 30 * 100:.2f}% FS), "
            f"exceeds the 0.3deg (1% of 30deg AoA) gate"
        )

    def test_elev(self, result_sc2):
        val = result_sc2.trim_vars["ELEV"]
        assert val == pytest.approx(SC2_ELEV, abs=TOL_ELEV_FS), (
            f"SC2 ELEV={val:.6f} off by {np.rad2deg(val - SC2_ELEV):+.4f}deg "
            f"({abs(np.rad2deg(val - SC2_ELEV)) / 40 * 100:.2f}% FS), "
            f"exceeds the 0.4deg (1% of 40deg elevator throw) gate"
        )
