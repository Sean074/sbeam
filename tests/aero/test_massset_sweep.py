"""Step 60 — MASSSET payload / mass-case sweep for static SOL 144.

Gates, on `sample/ha144a_massset_sweep.bdf` (one deck, one TRIM, three payload
conditions):

  * **equivalence** — a MASSSET case is identical to a hand-edited deck carrying
    the same final CONM2 set: same M_gg, same GPWG, same trim (machine precision);
  * **baseline unchanged** — with no MASSSET selected every mass-derived operator
    is bit-identical to the pre-Step-60 result, and the EMPTY case reproduces the
    unmodified full-span HA144A deck exactly;
  * **closure** — each mass case is a balanced maneuver (Step 53 closure ≈ 0);
  * **shared aero** — the three subcases share ONE AeroModel: the AIC is
    geometry/Mach-only, so a mass sweep must never invalidate the aero cache;
  * **physics** — heavier case ⇒ larger trimmed ANGLEA at the same q.
"""

import copy
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.gpwg import compute_gpwg
from sbeam.model.mass_overlay import resolve_mass_case
from sbeam.solver.sol144 import run_sol144_trim, AeroCache

SAMPLE = Path(__file__).parent.parent.parent / "sample"
SWEEP_BDF = SAMPLE / "ha144a_massset_sweep.bdf"
FULLSPAN_BDF = SAMPLE / "ha144a_fullspan_sbeam.bdf"

G = 32.174  # ft/s²
# Case weights the deck documents, in lb.
EXPECTED_WEIGHT = {10: 16000.0, 20: 18500.0, 30: 21000.0}


@pytest.fixture(scope="module")
def sweep():
    """Run all three subcases through ONE shared AeroModel + AeroCache."""
    cc, bulk = parse_bdf(str(SWEEP_BDF))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        cache = AeroCache(bulk, grid_index, seed=aero)
        results = {
            sc.subcase_id: run_sol144_trim(bulk, sc, aero, aero_cache=cache)
            for sc in cc.subcases
        }
    return cc, bulk, grid_index, aero, cache, results


# ---------------------------------------------------------------------------
# Equivalence: MASSSET overlay == hand-edited deck
# ---------------------------------------------------------------------------

def _hand_edited(bulk, massset_sid):
    """A copy of ``bulk`` whose baseline CONM2 set IS the mass case's set.

    The MASSSET machinery is stripped out, so running it with no MASSSET
    selected is the hand-edited deck the user would otherwise have authored.
    """
    case = resolve_mass_case(bulk, massset_sid)
    out = copy.deepcopy(bulk)
    out.conm2s = copy.deepcopy(case.conm2s)
    out.masssets = {}
    out.overlay_conm2_eids = set()
    return out


@pytest.mark.parametrize("massset_sid", [10, 20, 30])
def test_massset_case_equals_hand_edited_deck(sweep, massset_sid):
    """Equivalence gate: M_gg, GPWG and the trim solve all match to machine precision."""
    cc, bulk, grid_index, aero, cache, results = sweep
    hand = _hand_edited(bulk, massset_sid)

    M_case = assemble_global_mass(bulk, massset_sid).toarray()
    M_hand = assemble_global_mass(hand).toarray()
    assert np.array_equal(M_case, M_hand), "M_gg differs from the hand-edited deck"

    g_case = compute_gpwg(bulk, massset_sid)
    g_hand = compute_gpwg(hand)
    assert (g_case.total_mass, g_case.cg_x, g_case.cg_y, g_case.cg_z) == (
        g_hand.total_mass, g_hand.cg_x, g_hand.cg_y, g_hand.cg_z)

    sc = next(s for s in cc.subcases if s.massset_sid == massset_sid)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        hand_result = run_sol144_trim(
            hand,
            SubcaseControl(subcase_id=sc.subcase_id, spc_sid=sc.spc_sid,
                           trim_sid=sc.trim_sid),
            build_aero_model(hand, grid_index=build_grid_index(hand)),
        )
    case_result = results[sc.subcase_id]
    for label, value in case_result.trim_vars.items():
        assert value == pytest.approx(hand_result.trim_vars[label], rel=1e-12, abs=1e-12), (
            f"trim var {label} differs from the hand-edited deck")
    assert np.allclose(case_result.displacements, hand_result.displacements,
                       rtol=1e-12, atol=1e-14)


# ---------------------------------------------------------------------------
# Baseline (no MASSSET selected) is unchanged
# ---------------------------------------------------------------------------

class TestBaselineUnchanged:
    def test_deck_without_masssets_is_identical(self):
        """A deck with no MASSSET card: every mass operator matches the None path."""
        _cc, bulk = parse_bdf(str(FULLSPAN_BDF))
        assert bulk.masssets == {} and bulk.overlay_conm2_eids == set()
        assert resolve_mass_case(bulk, None).conm2s == bulk.conm2s
        assert np.array_equal(assemble_global_mass(bulk).toarray(),
                              assemble_global_mass(bulk, None).toarray())

    def test_empty_case_reproduces_the_unmodified_deck(self, sweep):
        """MASSSET 10 (EMPTY) is the original 16000 lb HA144A: same trim, exactly.

        The sweep deck adds a 500 lb baggage CONM2 to the baseline and deletes it
        again in the EMPTY case, so the EMPTY trim must equal the untouched
        full-span deck's subcase 1 trim.
        """
        _cc, _bulk, _gi, _aero, _cache, results = sweep
        _cc2, ref_bulk = parse_bdf(str(FULLSPAN_BDF))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ref = run_sol144_trim(
                ref_bulk,
                SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1),
                build_aero_model(ref_bulk, grid_index=build_grid_index(ref_bulk)),
            )
        empty = results[1]
        assert empty.massset_sid == 10 and empty.massset_label == "EMPTY"
        for label, value in ref.trim_vars.items():
            assert empty.trim_vars[label] == pytest.approx(value, rel=1e-12, abs=1e-12)

    def test_baseline_includes_replace_target_excludes_overlays(self, sweep):
        """The bare deck carries the baggage card but none of the overlay CONM2s."""
        _cc, bulk, *_ = sweep
        baseline = resolve_mass_case(bulk, None).conm2s
        assert 5000 in baseline                      # DELETE/REPLACE target = baseline
        assert not ({6001, 6011, 6020} & set(baseline))   # ADD / REPLACE overlays


# ---------------------------------------------------------------------------
# Mass cases: weights, closure, physics
# ---------------------------------------------------------------------------

class TestMassCases:
    @pytest.mark.parametrize("sc_id, massset_sid", [(1, 10), (2, 20), (3, 30)])
    def test_case_weight(self, sweep, sc_id, massset_sid):
        _cc, _bulk, _gi, _aero, _cache, results = sweep
        r = results[sc_id]
        assert r.massset_sid == massset_sid
        assert r.massset_mass * G == pytest.approx(EXPECTED_WEIGHT[massset_sid], rel=1e-4)

    @pytest.mark.parametrize("sc_id", [1, 2, 3])
    def test_step53_closure(self, sweep, sc_id):
        """Each mass case is a balanced maneuver: symmetric net resultant ≈ 0."""
        _cc, _bulk, _gi, _aero, _cache, results = sweep
        r = results[sc_id]
        scale = max(abs(r.massset_mass * G), 1.0)
        assert abs(r.maneuver_closure[2]) < 1e-6 * scale    # Fz
        assert abs(r.maneuver_closure[4]) < 1e-6 * scale * 40.0   # My (x ref arm)

    def test_lift_balances_case_weight(self, sweep):
        """Trimmed lift equals the case weight — the mass case really drives the trim."""
        _cc, _bulk, _gi, _aero, _cache, results = sweep
        for sc_id in (1, 2, 3):
            r = results[sc_id]
            lift = r.total_cl * r.q * 400.0    # sref = 400 ft²
            assert lift == pytest.approx(r.massset_mass * G, rel=1e-6)

    def test_heavier_case_trims_to_larger_alpha(self, sweep):
        _cc, _bulk, _gi, _aero, _cache, results = sweep
        alphas = [results[i].trim_vars["ANGLEA"] for i in (1, 2, 3)]
        assert alphas[0] < alphas[1] < alphas[2], alphas

    def test_cg_moves_with_payload(self, sweep):
        """Wing fuel is aft of the empty CG, so the case CG marches aft."""
        _cc, _bulk, _gi, _aero, _cache, results = sweep
        cgs = [results[i].massset_cg[0] for i in (1, 2, 3)]
        assert cgs[0] < cgs[1] < cgs[2], cgs


# ---------------------------------------------------------------------------
# The aero model is mass-independent and must be shared across the sweep
# ---------------------------------------------------------------------------

def test_sweep_shares_one_aero_model(sweep):
    """Object-identity: three mass cases, one AIC — no aero-cache invalidation."""
    _cc, _bulk, _gi, aero, cache, _results = sweep
    assert len(cache._cache) == 1, "a mass sweep must not add AeroModels to the cache"
    model = cache.get(0.9)
    assert model is aero
    assert cache.get(0.9) is model
    assert cache.get(0.9).ajj_inv_corr is aero.ajj_inv_corr
