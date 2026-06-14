"""W2GJ baseline-normalwash (wg) sign-convention regression (end-to-end).

Pins the *single canonical* wg sign to the production load path, so the doc /
test drift that previously let a deck silently fly flipped aero loads cannot
recur.

Canonical convention (theory §2.4-2.5, ``sbeam/model/aero.py`` W2gj):
    wg is a dimensionless downwash slope Δz/Δx added DIRECTLY to the assembled
    normalwash (NASTRAN W2GJ convention — not passed through D_jk).  Hence
        POSITIVE wg = local nose-down / washout → LESS lift
        NEGATIVE wg = leading-edge-up built-in incidence → MORE lift

These tests drive the REAL production combination — ``compute_structural_loads``
(``sbeam/aero/aero_model.py``: ``w_total = -(alpha*nz) + wg``; ``gamma =
ajj_inv_corr @ w_total``; ``f_g = q * g_disp.T @ skj @ gamma``) and ``build_fg``
(``sbeam/aero/coupling.py``) — on a splined cantilever wing, and recover the
total vertical load as the sum over the structural Tz DOFs.  That Tz sum equals
the box-Fz sum to machine precision by virtual work (proved by V-B2a in
``test_phase_b.py``), so it is a faithful end-to-end aero-load readout, not a
local raw solve.
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

BDF_PATH = Path(__file__).parent / "bdf" / "val_spline2_cantilever.bdf"
Q = 1000.0      # dynamic pressure (Pa)
ALPHA = 0.05    # angle of attack (rad, ~2.87°)
WG_MAG = 0.02   # uniform baseline-incidence magnitude (rad)


@pytest.fixture(scope="module")
def aero_gi():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index)
    return aero, grid_index


def _total_tz(aero, grid_index, wg_value, alpha):
    """Total vertical structural load through the production load path.

    Replaces wg with a uniform field, runs ``compute_structural_loads``, and
    sums the structural Tz DOFs (== box Fz sum to machine precision, V-B2a).
    """
    n = len(aero.boxes)
    aero_wg = dataclasses.replace(aero, wg=wg_value * np.ones(n))
    f_g = compute_structural_loads(aero_wg, Q, alpha)
    return sum(f_g[6 * gi + 2] for gi in grid_index.values())


class TestWgSignAtAngleOfAttack:
    """At a fixed positive AoA, washout unloads and built-in incidence loads."""

    def test_positive_wg_reduces_lift(self, aero_gi):
        """POSITIVE wg (washout) must REDUCE total lift vs the wg=0 baseline."""
        aero, gi = aero_gi
        base = _total_tz(aero, gi, 0.0, ALPHA)
        washout = _total_tz(aero, gi, +WG_MAG, ALPHA)
        assert base > 0.0, "baseline AoA lift must be upward"
        assert washout < base, (
            f"positive wg must unload the wing: washout Tz={washout:.3f} "
            f"not < baseline Tz={base:.3f}"
        )

    def test_negative_wg_increases_lift(self, aero_gi):
        """NEGATIVE wg (leading-edge-up built-in incidence) must INCREASE lift."""
        aero, gi = aero_gi
        base = _total_tz(aero, gi, 0.0, ALPHA)
        incidence = _total_tz(aero, gi, -WG_MAG, ALPHA)
        assert incidence > base, (
            f"negative wg must add lift: Tz={incidence:.3f} not > baseline {base:.3f}"
        )

    def test_lift_decreases_monotonically_with_wg(self, aero_gi):
        """Total lift falls monotonically as wg sweeps negative → positive."""
        aero, gi = aero_gi
        tz = [_total_tz(aero, gi, w, ALPHA)
              for w in (-WG_MAG, -WG_MAG / 2, 0.0, +WG_MAG / 2, +WG_MAG)]
        assert all(later < earlier for earlier, later in zip(tz, tz[1:])), (
            f"Tz not strictly decreasing with increasing wg: {tz}"
        )


class TestWgSignAtZeroAoA:
    """The baseline wg alone (alpha=0) sets the sign with no AoA contribution."""

    def test_positive_wg_pushes_down(self, aero_gi):
        """alpha=0 + POSITIVE wg → net DOWNWARD (negative Tz) load."""
        aero, gi = aero_gi
        assert _total_tz(aero, gi, +WG_MAG, 0.0) < 0.0

    def test_negative_wg_pushes_up(self, aero_gi):
        """alpha=0 + NEGATIVE wg → net UPWARD (positive Tz) load; antisymmetric."""
        aero, gi = aero_gi
        up = _total_tz(aero, gi, -WG_MAG, 0.0)
        down = _total_tz(aero, gi, +WG_MAG, 0.0)
        assert up > 0.0
        assert up == pytest.approx(-down, rel=1e-9)


class TestBuildFgSign:
    """The coupling.build_fg production site carries the same wg sign."""

    def test_build_fg_positive_wg_downward(self, aero_gi):
        """build_fg(+wg) sums to a downward total Tz (matches compute_structural_loads)."""
        aero, gi = aero_gi
        n = len(aero.boxes)
        aero_wg = dataclasses.replace(aero, wg=+WG_MAG * np.ones(n))
        f_g = build_fg(aero_wg, aero_wg.g_disp)
        tz = sum(f_g[6 * idx + 2] for idx in gi.values())
        assert tz < 0.0, f"build_fg positive-wg Tz must be downward, got {tz:.3e}"
