"""V-M1 — SPLINE0 / un-splined box loads in the SOL 144 trim (Step 64 / DEF-M1).

`sample/ha144a_body_trim.bdf` is the full-span HA144A deck plus a cruciform pair
of decoupled strip body panels (PSTRIP) carried by SPLINE0 — boxes with no
structural spline.  Their aerodynamic force reaches the structure only through
the Step 64 rigid load injection at the SPLINE0 master grid.

The defining gate is the load-factor identity: the *all-box* trimmed lift must
equal the weight.  Before Step 64 the body force was in the printed totals but
not in the force balance, so on this deck the two disagreed by ~31 % — the trim
was not closed.  The delta identity below pins the mechanism itself: whatever
`grid_loads` gains over the pure-kinematic transfer is exactly the resultant of
the structurally-uncoupled boxes.
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
from sbeam.results.f06_writer import _build_f06_sol144_text
from sbeam.results.load_export import build_aero_load_cards_text
from sbeam.solver.sol144 import run_sol144_trim, aero_moment_resultant, load_resultant

_SAMPLE = Path(__file__).parent.parent.parent / "sample"
BODY_BDF = _SAMPLE / "ha144a_body_trim.bdf"
BASE_BDF = _SAMPLE / "ha144a_fullspan_sbeam.bdf"
G = 32.174   # ft/s², the deck's gravity (URDD3 = −32.174 for 1g)


def _trim(path):
    cc, bulk = parse_bdf(str(path))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero
        )
    return result, bulk, grid_index, aero, cc


@pytest.fixture(scope="module")
def body_trim():
    return _trim(BODY_BDF)


@pytest.fixture(scope="module")
def base_trim():
    return _trim(BASE_BDF)


class TestInjectionSetup:
    """The deck exercises both master-grid resolution paths."""

    def test_both_spline0_panels_inject(self, body_trim):
        _r, _b, _gi, aero, _cc = body_trim
        got = [(i.source, i.master_grid, len(i.boxes)) for i in aero.load_injections]
        assert got == [("SPLINE0 9400", 98, 16), ("SPLINE0 9500", 90, 32)], got

    def test_explicit_and_default_master(self, body_trim):
        """Panel 6000 names GRID 98; panel 7000 leaves the field blank → SUPORT 90."""
        _r, bulk, _gi, _aero, _cc = body_trim
        assert bulk.spline0s[9400].grid == 98
        assert bulk.spline0s[9500].grid == 0

    def test_g_slope_still_zero_on_body_boxes(self, body_trim):
        """Injected boxes load the structure but take no downwash from it."""
        _r, _b, _gi, aero, _cc = body_trim
        body_ks = [k for inj in aero.load_injections for k in inj.boxes]
        assert np.allclose(aero.g_slope[body_ks, :], 0.0, atol=1e-14)


class TestTrimIsClosed:
    """The acceptance gate: printed totals and the force balance agree."""

    def test_all_box_lift_equals_weight(self, body_trim):
        result, bulk, _gi, _aero, _cc = body_trim
        weight = compute_gpwg(bulk).total_mass * G
        lift = result.q * bulk.aeros.sref * result.total_cl
        assert abs(lift - weight) < 1e-9 * weight, (
            f"trimmed all-box lift {lift:.4f} != weight {weight:.4f} — the body "
            "panel forces are missing from the trim balance"
        )

    def test_base_deck_gate_unchanged(self, base_trim):
        """Same identity on the parent deck (no uncoupled boxes) — a control."""
        result, bulk, _gi, aero, _cc = base_trim
        assert aero.load_injections == []
        weight = compute_gpwg(bulk).total_mass * G
        lift = result.q * bulk.aeros.sref * result.total_cl
        assert abs(lift - weight) < 1e-9 * weight

    def test_closure_still_machine_zero(self, body_trim):
        result, _b, _gi, _aero, _cc = body_trim
        aero_res = np.abs(result.maneuver_closure)
        assert aero_res[2] < 1e-6 and aero_res[4] < 1e-6, result.maneuver_closure


class TestDeltaIdentity:
    """grid_loads − (kinematic transfer) == resultant of the uncoupled boxes."""

    def test_delta_equals_uncoupled_resultant(self, body_trim):
        result, bulk, grid_index, aero, _cc = body_trim
        ref = np.zeros(3)

        kinematic = aero.g_disp.T @ (result.q * (aero.skj @ result.box_gamma))
        delta = (load_resultant(result.grid_loads, bulk, grid_index, ref)
                 - load_resultant(kinematic, bulk, grid_index, ref))

        ks = sorted(k for inj in aero.load_injections for k in inj.boxes)
        forces = result.box_forces[ks]
        expect = np.concatenate([
            forces.sum(axis=0),
            aero_moment_resultant(forces, [aero.boxes[k] for k in ks], ref),
        ])
        scale = max(np.max(np.abs(expect)), 1.0)
        assert np.allclose(delta, expect, atol=1e-8 * scale), f"{delta} vs {expect}"

    def test_body_panel_carries_real_load(self, body_trim):
        """Guard the test itself: the injected load must be significant."""
        result, bulk, _gi, _aero, _cc = body_trim
        weight = compute_gpwg(bulk).total_mass * G
        fz = result.load_injection_echo[0]['force'][2]
        assert fz > 0.1 * weight, f"body Fz {fz} too small to gate anything"


class TestTrimShift:
    """The body's nose-up increment offloads the canard."""

    def test_angle_of_attack_shifts(self, body_trim, base_trim):
        body, _b1, _g1, _a1, _c1 = body_trim
        base, _b2, _g2, _a2, _c2 = base_trim
        assert body.trim_vars['ANGLEA'] < base.trim_vars['ANGLEA'] - 1e-3
        assert body.trim_vars['ELEV'] < base.trim_vars['ELEV'] - 1e-2


class TestOutputs:
    """The injection is visible in the f06 and reaches the exported cards."""

    def test_f06_block_present(self, body_trim):
        result, bulk, _gi, _aero, cc = body_trim
        text = _build_f06_sol144_text(cc, bulk, result, subcase_id=1)
        assert "I N J E C T E D   A E R O   L O A D S" in text
        assert "SPLINE0 9400" in text

    def test_f06_block_absent_without_injection(self, base_trim):
        result, bulk, _gi, _aero, cc = base_trim
        text = _build_f06_sol144_text(cc, bulk, result, subcase_id=1)
        assert "I N J E C T E D   A E R O   L O A D S" not in text

    def test_export_carries_master_grid_load(self, body_trim):
        """The FORCE/MOMENT export gains the master grid's injected load."""
        result, bulk, grid_index, _aero, _cc = body_trim
        text = build_aero_load_cards_text(bulk, result, sid=101)
        assert any(line.startswith("FORCE") and ", 98," in line
                   for line in text.splitlines()), "no FORCE card for GRID 98"
        assert any(line.startswith("MOMENT") and ", 98," in line
                   for line in text.splitlines()), "no MOMENT card for GRID 98"

    def test_monitor_sees_the_body_load(self, body_trim):
        """MONPNT3 over every load-carrying grid recovers the full aero Fz."""
        result, _b, _gi, _aero, _cc = body_trim
        mon = result.monitor_loads['MALLEA']
        total_fz = result.grid_loads[2::6].sum()
        assert abs(mon.aero[2] - total_fz) < 1e-6 * max(abs(total_fz), 1.0)


class TestNoSuportDecksStillBuild:
    """A body panel with no master grid AND no SUPORT — warn, never raise.

    The master grid resolves from SPLINE0 field 5, falling back to the SUPORT grid.
    With neither, the body force has nowhere to go: the build must say so loudly and
    drop the injection rather than raise or silently keep it.

    This used to be parametrised over sample/cessna210_body.bdf and _strip.bdf, two
    SOL 101 decks that happened to have no SUPORT.  Step 66 folded those into the
    flagship family, whose decks all carry one, so the case is now built explicitly —
    which also states the precondition instead of relying on a deck to keep it.
    """

    _MIN_DECK = """\
AEROS, 0, 0, 1.0, 2.0, 2.0, 0, 0, 0.0
PAERO1, 10
MAT1, 1, 7.0e10, 2.69e10, 0.3, 2700.0
PBAR, 1, 1, 0.01, 1.0e-5, 1.0e-5, 2.0e-5
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
CBAR, 1, 1, 1, 2, 0.0, 0.0, 1.0
CAERO1, 400, 10, 0, 2, 2, 0, 0, 1
+, 0.0, -0.5, 0.0, 1.0, 0.0, 0.5, 0.0, 1.0
SPLINE0, 9400, 400, 400, 403
"""

    def _bulk(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        bulk = parse_bulk_data(self._MIN_DECK.splitlines())
        assert not bulk.supports, "precondition: this deck must have no SUPORT"
        assert bulk.spline0s[9400].grid in (None, 0), \
            "precondition: SPLINE0 must not name a master grid"
        return bulk

    def test_builds_with_warning(self):
        bulk = self._bulk()
        grid_index = build_grid_index(bulk)
        with pytest.warns(UserWarning, match="no master grid for load injection"):
            aero = build_aero_model(bulk, grid_index=grid_index)
        assert aero.load_injections == []
        assert np.array_equal(aero.g_load, aero.g_disp)
