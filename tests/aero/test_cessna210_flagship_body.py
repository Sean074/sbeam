"""Flagship stage 2 — body panels on the Cessna 210 SOL 144 family (Step 66).

Gates the two body-panel overlays and their drivers.  The flagship bulk itself is
untouched by this step: the overlays are INCLUDEd *after* it, so every Step 65
anchor still holds and `test_cessna210_flagship.py` is unaffected.

The two variants are a CONTROLLED comparison.  Same panel geometry, same
total-aircraft targets, same body-lift share (2.0 % vs 2.2 % of weight) — the one
thing that differs is whether the body boxes carry PAERO1 (cruciform: ordinary VLM,
AIC-coupled) or PSTRIP (strip: diagonal influence block, decoupled).  B4 is the
payoff: the strip perturbs the flying-surface loading at machine precision while the
cruciform moves it by O(0.1) in DCp, even though BOTH reproduce the same
total-aircraft moments and trim to within 0.003 deg of each other.

The AIC build is ~11 s at 372 boxes (pure-Python Biot-Savart), so the parses and builds
live in `tests/aero/conftest.py` at **session** scope and are shared with the three other
modules that use these decks.

Gate map (B-numbers as in the Step 66 plan):
  B1  both drivers parse through the double INCLUDE; 372 boxes; no ID collision;
      the 48 body boxes are SPLINE0-covered and no warning is raised
  B2  the committed body cards regenerate from the CSV TOTAL block
  B3  Step 64 closure: trimmed ALL-box lift = n*W at 1g and 2.5g
  B4  contamination contrast — strip ~ 0, cruciform O(0.1)
  B5  both variants reach the TOTAL targets, with |WT2 ratio| inside RATIO_WARN
  B6  ANGLEA and the elevator shift from the bare flagship in the destabilising
      direction, by much more than solver noise
  B7  MONPNT1 over all 372 boxes = n*W, while the flying-only monitor falls short
      by exactly the injected body resultant
  B8  the body load reaches the structure at the SPLINE0 master grid
  B9  the airplane is still statically stable and still far from divergence
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sbeam.aero import body_correction as bc
from sbeam.aero.integration import build_djx
from sbeam.aero.panel import build_box_id_map
from sbeam.gpwg import compute_gpwg
from sbeam.results.f06_writer import _build_f06_sol144_text
from sbeam.results.load_export import build_aero_load_cards_text
from sbeam.solver.sol144 import run_sol144_trim

_SAMPLE = Path(__file__).parent.parent.parent / "sample"
BARE_PATH = _SAMPLE / "cessna210_flagship_trim.bdf"
CRUCIFORM_PATH = _SAMPLE / "cessna210_flagship_body.bdf"
STRIP_PATH = _SAMPLE / "cessna210_flagship_body_strip_drv.bdf"
CSV_PATH = _SAMPLE / "cessna210_flagship_section_data.csv"

N_BOXES = 372            # 324 flying + 16 horizontal body + 32 vertical body
N_BODY_BOXES = 48
BODY_EIDS = [6000, 7000]
MASTER_GRID = 900        # SPLINE0 field 5 — the trim reference
G = 9.81
Q_CRUISE = 2334.0


# --------------------------------------------------------------------------- #
# Fixtures — the AIC builds live in tests/aero/conftest.py (session-scoped, so the
# four modules that use these decks share one build each)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def cruciform(flagship_cruciform):
    return flagship_cruciform


@pytest.fixture(scope="module")
def strip(flagship_strip):
    return flagship_strip


@pytest.fixture(scope="module")
def bare(flagship_bare):
    """The Step 65 flagship with no body panels — the reference for B4/B6."""
    return flagship_bare


@pytest.fixture(scope="module")
def cruciform_uncorrected(flagship_cruciform_uncorrected):
    return flagship_cruciform_uncorrected


@pytest.fixture(scope="module")
def strip_uncorrected(flagship_strip_uncorrected):
    return flagship_strip_uncorrected


@pytest.fixture(scope="module")
def cruciform_trims(cruciform):
    cc, bulk, aero, _gi, _w = cruciform
    return [run_sol144_trim(bulk, sc, aero) for sc in cc.subcases]


@pytest.fixture(scope="module")
def strip_trim(strip):
    cc, bulk, aero, _gi, _w = strip
    return run_sol144_trim(bulk, cc.subcases[0], aero)


@pytest.fixture(scope="module")
def bare_trim(bare):
    cc, bulk, aero, _gi, _w = bare
    return run_sol144_trim(bulk, cc.subcases[0], aero)


@pytest.fixture(scope="module")
def targets():
    """The TOTAL block of the shared section-data CSV."""
    t = bc.parse_body_targets(pd.read_csv(CSV_PATH), 0.0)
    assert t is not None, "no TOTAL row at Mach 0 in the flagship CSV"
    return t


@pytest.fixture(scope="module")
def weight(cruciform):
    _cc, bulk, _aero, _gi, _w = cruciform
    return compute_gpwg(bulk).total_mass * G


def _flying_idx(aero):
    return np.array([k for k, b in enumerate(aero.boxes) if b.caero_eid < 6000])


def _body_idx(aero):
    return np.array([k for k, b in enumerate(aero.boxes) if b.caero_eid >= 6000])


# --------------------------------------------------------------------------- #
# B1 — the decks compose, mesh and spline
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b1_driver_composes_two_includes(name, request):
    """Both drivers pull the shared bulk and the overlay through two INCLUDEs.

    The flagship bulk is byte-identical to Step 65; everything the body adds
    arrives from the second file.
    """
    cc, bulk, _aero, _gi, _w = request.getfixturevalue(name)
    assert len(cc.includes) == 2
    assert cc.includes[0] == "cessna210_flagship_bulk.bdf"
    assert cc.includes[1].startswith("cessna210_flagship_body_")
    # cards from BOTH files survived the concatenation
    assert 1000 in bulk.caero1s          # wing, from the bulk
    assert sorted(bulk.caero1s) == [1000, 2000, 3000, 4000, 5000, 6000, 7000]


@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b1_mesh_size_and_no_id_collision(name, request):
    _cc, bulk, aero, _gi, _w = request.getfixturevalue(name)
    assert len(aero.boxes) == N_BOXES
    build_box_id_map(aero.boxes)         # raises on a duplicate box ID
    assert len(_body_idx(aero)) == N_BODY_BOXES


@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b1_builds_without_warnings(name, request):
    """No high-aspect-ratio, spline-coverage or load-injection warning.

    The vertical panel is meshed 2x16 rather than the retired body deck's 4x8
    precisely so the box aspect ratio stays inside the VLM's [0.5, 2.0] band.
    """
    _cc, _bulk, _aero, _gi, caught = request.getfixturevalue(name)
    assert caught == []


@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b1_body_boxes_are_spline0_covered(name, request):
    """Every body box reaches the structure through a SPLINE0 master grid."""
    _cc, bulk, aero, _gi, _w = request.getfixturevalue(name)
    assert sorted(bulk.spline0s) == [9400, 9500]
    injected = {k for inj in aero.load_injections for k in inj.boxes}
    assert injected == set(_body_idx(aero).tolist())
    assert {inj.master_grid for inj in aero.load_injections} == {MASTER_GRID}


# --------------------------------------------------------------------------- #
# B2 — the committed body cards are derivable from the CSV
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,builder,card_attr,value_attr",
    [("cruciform", bc.build_body_correction, "aecorrs", "target"),
     ("strip", bc.build_strip_body_correction, "stripks", "data")],
)
def test_b2_committed_body_cards_regenerate(name, builder, card_attr, value_attr,
                                            targets, request):
    """Re-solving the body correction reproduces the cards baked into the overlay.

    Same contract as the flagship's T2: the CSV is the source of truth and the
    committed cards are derivable from it, not hand-tuned.  Solved against the
    body-uncorrected model and compared to what the deck actually carries.
    """
    committed_bulk = request.getfixturevalue(name)[1]
    _cc, bulk, aero, gi, _w = request.getfixturevalue(f"{name}_uncorrected")
    res = builder(bulk, horiz_eid=6000, vert_eid=7000, targets=targets,
                  aero=aero, grid_index=gi)
    assert res.converged
    assert sorted(res.cards) == BODY_EIDS

    committed = getattr(committed_bulk, card_attr)
    for eid, (w2, second) in res.cards.items():
        assert w2.sid in committed_bulk.w2gjs, \
            f"W2GJ {w2.sid} (CAERO {eid}) not committed"
        assert second.sid in committed, \
            f"card {second.sid} (CAERO {eid}) not committed"
        # Tolerance is set by the "%.6E" card text, not by the maths (DEF-M12) —
        # the same limit the flagship's T2 documents.
        np.testing.assert_allclose(
            committed_bulk.w2gjs[w2.sid].data, w2.data, rtol=1e-6, atol=1e-7,
            err_msg=f"committed W2GJ {w2.sid} differs from the CSV regeneration")
        np.testing.assert_allclose(
            getattr(committed[second.sid], value_attr),
            getattr(second, value_attr), rtol=1e-6, atol=1e-7,
            err_msg=f"committed {card_attr} {second.sid} differs from the CSV "
                    "regeneration")


def test_b2_total_block_is_separate_from_the_flying_rows(targets):
    """The CSV carries both blocks; only the TOTAL one drives the body."""
    flying, totals = bc.split_total_rows(pd.read_csv(CSV_PATH))
    assert len(totals) == 1
    assert set(flying["var"].str.upper()) == {"ALPHA", "BETA"}
    assert targets.cm_alpha == pytest.approx(-1.4921)


# --------------------------------------------------------------------------- #
# B3 — Step 64 closure: the body force is in the trim balance
# --------------------------------------------------------------------------- #
def test_b3_cruciform_lift_equals_load_factor_times_weight(cruciform_trims,
                                                           cruciform, weight):
    """All-box lift = n*W at both 1g and 2.5g.

    This is the defining body-panel gate.  The body boxes have no structural
    spline, so before Step 64 their force appeared in the printed totals but not
    in the force balance and the trim was not closed.
    """
    _cc, _bulk, aero, _gi, _w = cruciform
    for r, n in zip(cruciform_trims, (1.0, 2.5)):
        fz = r.box_forces.reshape(-1, 3)[:, 2].sum()
        assert fz == pytest.approx(n * weight, rel=1e-6)


def test_b3_strip_lift_equals_weight(strip_trim, weight):
    fz = strip_trim.box_forces.reshape(-1, 3)[:, 2].sum()
    assert fz == pytest.approx(weight, rel=1e-6)


@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b3_body_carries_a_small_share_of_the_lift(name, weight, request):
    """A fuselage should carry a couple of percent, not a couple of tenths.

    The correction matches MOMENTS only and leaves body lift free, so this is a
    real authoring constraint rather than something the solver enforces: at the
    PSTRIP default slope the strip body trims out carrying 11 % of the weight.
    The committed slope (0.35) brings it to the cruciform's share.
    """
    trims = request.getfixturevalue(
        "cruciform_trims" if name == "cruciform" else "strip_trim")
    r = trims[0] if name == "cruciform" else trims
    _cc, _bulk, aero, _gi, _w = request.getfixturevalue(name)
    body_fz = r.box_forces.reshape(-1, 3)[_body_idx(aero), 2].sum()
    assert 0.01 < body_fz / weight < 0.04


# --------------------------------------------------------------------------- #
# B4 — the contamination contrast (the point of carrying both variants)
# --------------------------------------------------------------------------- #
def _flying_response(bulk, aero):
    """Flying-box DCp response to unit ANGLEA / SIDES, and the baseline DCp.

    Taken at a FIXED aerodynamic state on purpose.  Comparing trimmed box loads
    instead would confound the question: both variants add body lift, so both
    trim to a different alpha, and the flying loads move for that reason alone.
    Contamination is a property of the influence operator, so that is where it
    has to be measured.
    """
    idx = _flying_idx(aero)
    d_jx = build_djx(aero.boxes, ["ANGLEA", "SIDES"], bulk)
    return {
        "alpha": (aero.ajj_inv_corr @ d_jx[:, 0])[idx],
        "beta": (aero.ajj_inv_corr @ d_jx[:, 1])[idx],
        "baseline": (aero.ajj_inv_corr @ aero.wg)[idx],
    }


def test_b4_strip_does_not_contaminate_the_flying_surfaces(strip, bare):
    """A PSTRIP block of the influence operator is diagonal, so the wing/HTP/VTP
    response is the bare airplane's to machine precision — no matter that the
    horizontal panel sits directly under the wing."""
    _c1, bulk_s, aero_s, _g1, _w1 = strip
    _c2, bulk_b, aero_b, _g2, _w2 = bare
    s, b = _flying_response(bulk_s, aero_s), _flying_response(bulk_b, aero_b)
    for key in s:
        assert np.abs(s[key] - b[key]).max() < 1e-12, key


def test_b4_cruciform_does_contaminate_the_flying_surfaces(cruciform, bare):
    """The same geometry on PAERO1 is a real VLM surface, and a body box 0.95 m
    under the wing genuinely loads it: the flying-box DCp response moves by
    O(0.1), tens of percent of a typical box DCp.  The corrected TOTALS are still
    exact — which is the trap.  Totals agreeing is not the load distribution
    agreeing."""
    _c1, bulk_c, aero_c, _g1, _w1 = cruciform
    _c2, bulk_b, aero_b, _g2, _w2 = bare
    c, b = _flying_response(bulk_c, aero_c), _flying_response(bulk_b, aero_b)
    assert np.abs(c["alpha"] - b["alpha"]).max() > 0.1
    assert np.abs(c["beta"] - b["beta"]).max() > 0.1


def test_b4_both_variants_still_reach_the_same_total_moments(cruciform_trims,
                                                             strip_trim, targets):
    """Two mechanisms, opposite contamination behaviour, identical rigid Cm_alpha."""
    cm_cruciform = cruciform_trims[0].rigid_derivs["ANGLEA"]["CMY"]
    cm_strip = strip_trim.rigid_derivs["ANGLEA"]["CMY"]
    assert cm_cruciform == pytest.approx(targets.cm_alpha, abs=1e-6)
    assert cm_strip == pytest.approx(targets.cm_alpha, abs=1e-6)


# --------------------------------------------------------------------------- #
# B5 — the targets are reached, with panel authority inside its limit
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,builder", [("cruciform", bc.build_body_correction),
                     ("strip", bc.build_strip_body_correction)])
def test_b5_targets_met_within_ratio_bound(name, builder, targets, request):
    """A flat-plate cruciform can only legitimately supply a SMALL increment; the
    WT2 ratio is the diagnostic for being pushed past that.

    Solved from the body-UNCORRECTED model, so the achieved values are a real
    result of the solve rather than the committed cards read back to themselves.
    """
    _cc, bulk, aero, gi, _w = request.getfixturevalue(f"{name}_uncorrected")
    res = builder(bulk, horiz_eid=6000, vert_eid=7000, targets=targets,
                  aero=aero, grid_index=gi)
    assert res.converged
    assert max(abs(v) for v in res.residual.values()) < 1e-9
    assert res.ratio_max < bc.RATIO_WARN
    for field in ("cm_alpha", "cm0", "cn_beta", "cl_beta"):
        assert getattr(res.achieved, field) == pytest.approx(
            getattr(targets, field), abs=1e-9), field


# --------------------------------------------------------------------------- #
# B6 — the trim actually moves, in the destabilising direction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b6_body_reduces_pitch_stability(name, bare_trim, request):
    """The fuselage increment is destabilising: |Cm_alpha| falls, but the airplane
    stays solidly stable (the increment is ~12 % of the bare value)."""
    trims = request.getfixturevalue(
        "cruciform_trims" if name == "cruciform" else "strip_trim")
    r = trims[0] if name == "cruciform" else trims
    cm_body = r.rigid_derivs["ANGLEA"]["CMY"]
    cm_bare = bare_trim.rigid_derivs["ANGLEA"]["CMY"]
    assert cm_bare < cm_body < 0                    # less stable, still stable
    assert cm_body - cm_bare == pytest.approx(0.20, abs=0.01)


@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b6_angle_of_attack_falls_by_the_body_lift(name, bare_trim, request):
    """Body panels add lift, so the airplane trims at a lower alpha — by far more
    than solver noise, and by a similar amount under both mechanisms (the two
    variants are matched on body-lift share)."""
    trims = request.getfixturevalue(
        "cruciform_trims" if name == "cruciform" else "strip_trim")
    r = trims[0] if name == "cruciform" else trims
    d_alpha = np.degrees(r.trim_vars["ANGLEA"] - bare_trim.trim_vars["ANGLEA"])
    assert -0.20 < d_alpha < -0.05


@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b6_trimmed_incidence_stays_inside_the_baked_region(name, request):
    """The committed flying-surface correction is only valid over -4..8 deg, and
    the flagship bulk is frozen, so the body must not push the trim out of it."""
    trims = request.getfixturevalue(
        "cruciform_trims" if name == "cruciform" else "strip_trim")
    results = trims if name == "cruciform" else [trims]
    for r in results:
        alpha_deg = np.degrees(r.trim_vars["ANGLEA"])
        assert -4.0 < alpha_deg < 8.0


# --------------------------------------------------------------------------- #
# B7 — monitor coverage must follow the mesh
# --------------------------------------------------------------------------- #
def test_b7_whole_airplane_monitor_including_body_equals_weight(cruciform_trims,
                                                                weight):
    """MONPNT1 over all 372 boxes recovers n*W."""
    for r, n in zip(cruciform_trims, (1.0, 2.5)):
        assert r.monitor_loads["MALLARB"].aero[2] == pytest.approx(
            n * weight, rel=1e-6)


def test_b7_flying_only_monitor_falls_short_by_the_body_load(cruciform_trims,
                                                              cruciform, weight):
    """The bulk's AELIST 1400 predates the body panels and now under-reports.

    Kept deliberately alongside the extended one: the difference is exactly the
    body resultant, which makes "your monitor must cover the boxes you added" a
    measured fact rather than a warning in a document.
    """
    _cc, _bulk, aero, _gi, _w = cruciform
    r = cruciform_trims[0]
    flying_only = r.monitor_loads["MALLAR"].aero[2]
    all_boxes = r.monitor_loads["MALLARB"].aero[2]
    body_fz = r.box_forces.reshape(-1, 3)[_body_idx(aero), 2].sum()
    assert all_boxes - flying_only == pytest.approx(body_fz, rel=1e-9)
    assert flying_only < weight            # the shortfall is real, not cosmetic


def test_b7_balanced_monpnt3_still_nets_to_zero(cruciform_trims, weight):
    """Aero + inertia + reaction over every load-carrying grid still cancels —
    the injected body load lands inside the cut because GRID 900 is in SET1 1310."""
    for r in cruciform_trims:
        assert abs(r.monitor_loads["MALLEA"].totals[2]) < 1e-6 * weight


# --------------------------------------------------------------------------- #
# B8 — the body load reaches the structure
# --------------------------------------------------------------------------- #
def test_b8_injection_echo_reports_both_panels(cruciform_trims):
    echo = cruciform_trims[0].load_injection_echo
    assert [e["source"] for e in echo] == ["SPLINE0 9400", "SPLINE0 9500"]
    assert all(e["master_grid"] == MASTER_GRID for e in echo)
    assert [e["n_boxes"] for e in echo] == [16, 32]


def test_b8_f06_carries_the_injected_loads_block(cruciform, cruciform_trims):
    cc, bulk, _aero, _gi, _w = cruciform
    text = _build_f06_sol144_text(cc, bulk, cruciform_trims[0], subcase_id=1)
    assert "I N J E C T E D   A E R O   L O A D S" in text
    assert "SPLINE0 9400" in text


def test_b8_export_carries_the_master_grid_load(cruciform, cruciform_trims):
    """The FORCE/MOMENT handoff includes the body's share at GRID 900."""
    _cc, bulk, _aero, _gi, _w = cruciform
    text = build_aero_load_cards_text(bulk, cruciform_trims[0], sid=101)
    lines = text.splitlines()
    assert any(ln.startswith("FORCE") and f", {MASTER_GRID}," in ln for ln in lines)
    assert any(ln.startswith("MOMENT") and f", {MASTER_GRID}," in ln for ln in lines)


# --------------------------------------------------------------------------- #
# B9 — the airplane is still a sane airplane
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["cruciform", "strip"])
def test_b9_divergence_margin_survives_the_body(name, request):
    trims = request.getfixturevalue(
        "cruciform_trims" if name == "cruciform" else "strip_trim")
    r = trims[0] if name == "cruciform" else trims
    assert r.q_div > 10.0 * Q_CRUISE
