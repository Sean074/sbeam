"""Flagship realistic-airplane SOL 144 sample family (Step 65).

Gates `sample/cessna210_flagship_bulk.bdf` and its three thin case-control drivers —
the only decks in the repo that combine corrected aerodynamics, multi-subcase static
trim, mass cases, monitor points and a transient maneuver on one realistic airplane.

The model and the solves are module-scoped fixtures and shared across the gates
(originally forced by the pre-P9 pure-Python AIC build, ~8 s at 324 boxes; the
vectorized build is ~100× faster, but sharing immutable results is still right).

Gate map (T-numbers as in the Step 65 plan):
  T1  the three drivers parse via INCLUDE; 324 boxes; no box-ID collision; every box
      splined; no warnings
  T2  regenerating the correction from the CSV reproduces the committed cards
  T3  both trims close; lift = n*W; corrected CL_alpha in band
  T3b both trimmed incidences fall inside the baked correction region
  T4  MASSSET sweep: ANGLEA monotone in weight, and wing-root bending per unit weight
      FALLS with wing fuel (inertia relief)
  T5  MLOADS: t=0 is the trim; a command held at trim moves nothing; the ramp holds
  T6  MLOADS x MASSSET (first coverage of the pairing anywhere)
  T7  the fin ATTACH resolves from file and transfers side force + yaw moment
  T8  divergence dynamic pressure keeps a wide margin over the cruise q
"""

import math
import warnings
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sbeam.aero import section_data as sd
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.body_correction import split_total_rows
from sbeam.aero.panel import build_box_id_map
from sbeam.aero.spline import build_spline_operators
from sbeam.assembly.load_vector import build_grid_index
from sbeam.gpwg import compute_gpwg
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.solver.sol144 import run_sol144_trim

_SAMPLE = Path(__file__).parent.parent.parent / "sample"
BULK_PATH = _SAMPLE / "cessna210_flagship_bulk.bdf"
TRIM_PATH = _SAMPLE / "cessna210_flagship_trim.bdf"
MASSSET_PATH = _SAMPLE / "cessna210_flagship_massset.bdf"
MLOADS_PATH = _SAMPLE / "cessna210_flagship_mloads.bdf"
CSV_PATH = _SAMPLE / "cessna210_flagship_section_data.csv"

N_BOXES = 324
G = 9.81
Q_CRUISE = 2334.0
CAERO_EIDS = [1000, 2000, 3000, 4000, 5000]
FIN_EID = 5000
FIN_GRID = 30
WING_ROOT_GRID = 10


# --------------------------------------------------------------------------- #
# Fixtures — one parse and one AIC build for the whole module
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def model():
    """(case control, bulk, aero model) for the trim driver."""
    cc, bulk = parse_bdf(str(TRIM_PATH))
    aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    return cc, bulk, aero


@pytest.fixture(scope="module")
def trims(model):
    """The 1g and 2.5g trim results."""
    cc, bulk, aero = model
    return [run_sol144_trim(bulk, sc, aero) for sc in cc.subcases]


@pytest.fixture(scope="module")
def section_df():
    """The FLYING-surface rows of the section table.

    Since Step 66 the CSV also carries a ``TOTAL`` block — the total-aircraft
    targets for the body-panel correction (see `test_cessna210_flagship_body.py`).
    The flying-surface synthesiser only accepts ``var`` in {ALPHA, BETA}, so the
    two blocks must be split before use; this is the same thing the viewer does at
    `aero_correction_view.py`.
    """
    flying, _totals = split_total_rows(pd.read_csv(CSV_PATH))
    return flying


@pytest.fixture(scope="module")
def baked_alpha_deg():
    """Reference incidence the committed correction was synthesised about.

    Read out of the provenance header the viewer export writes, so the test cannot
    drift away from the cards it is checking.
    """
    for line in BULK_PATH.read_text().splitlines():
        if "condition" in line and "alpha" in line:
            return float(line.split("alpha")[1].split("deg")[0].strip())
    pytest.fail("no correction provenance header found in the flagship bulk deck")


@pytest.fixture(scope="module")
def maneuver():
    """The ramped MLOADS run plus its initial-condition trim."""
    cc, bulk = parse_bdf(str(MLOADS_PATH))
    aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    ic = run_sol144_trim(bulk, cc.subcases[0], aero)
    mr = run_maneuver_qs(bulk, cc.subcases[1], aero)
    return cc, bulk, aero, ic, mr


# --------------------------------------------------------------------------- #
# T1 — the family loads
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", [TRIM_PATH, MASSSET_PATH, MLOADS_PATH])
def test_t1_drivers_parse_via_include(path):
    """Each thin driver pulls the shared bulk in through a case-control INCLUDE."""
    cc, bulk = parse_bdf(str(path))
    assert cc.include == "cessna210_flagship_bulk.bdf"
    assert cc.sol == 144
    assert len(cc.subcases) >= 2
    assert sorted(bulk.caero1s) == CAERO_EIDS


def test_t1_mesh_and_box_ids(model):
    """324 boxes, and every NASTRAN box ID unique across the five surfaces."""
    _cc, bulk, aero = model
    assert len(aero.boxes) == N_BOXES
    # 96 + 96 + 48 + 48 + 36; the 1000-spacing keeps each surface in its own decade
    per_surface = {eid: sum(b.caero_eid == eid for b in aero.boxes) for eid in CAERO_EIDS}
    assert per_surface == {1000: 96, 2000: 96, 3000: 48, 4000: 48, 5000: 36}
    id_map = build_box_id_map(aero.boxes)        # raises on any collision
    assert len(id_map) == N_BOXES
    assert min(id_map) == 1000 and max(id_map) == 5035
    assert bulk.aeros.symxz == 0 and bulk.aeros.symxy == 0      # full span


def test_t1_every_box_is_splined_without_warnings(model):
    """Zero spline-coverage warnings, and no box left kinematically unattached.

    The four SPLINE2s carry EA-only collinear SET1s, so DTHY must be 0.0; with a
    detached torsion DOF the beam-spline system is singular and this raises.
    """
    _cc, bulk, aero = model
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ops = build_spline_operators(bulk, aero.boxes, build_grid_index(bulk))
    assert [str(w.message) for w in caught] == []
    slope = np.abs(ops.g_slope).sum(axis=1)
    disp = np.abs(ops.g_disp).reshape(N_BOXES, 3, -1).sum(axis=(1, 2))
    assert not np.any(slope == 0.0), "box with no structural normalwash coupling"
    assert not np.any(disp == 0.0), "box with no structural displacement coupling"


def test_t1_gpwg_mass_and_cg(model):
    """Baseline weight and CG are the documented design point: 1081 kg at 22% MAC."""
    _cc, bulk, _aero = model
    r = compute_gpwg(bulk)
    x_le_mac, mac = 2.0698, 1.4707
    assert r.total_mass == pytest.approx(1081.0, abs=0.5)
    assert (r.cg_x - x_le_mac) / mac * 100 == pytest.approx(22.0, abs=0.1)
    assert r.cg_y == pytest.approx(0.0, abs=1e-12)         # symmetric mass set


# --------------------------------------------------------------------------- #
# T2 — the committed correction is reproducible from the CSV
# --------------------------------------------------------------------------- #
def test_t2_committed_cards_regenerate_from_csv(model, section_df, baked_alpha_deg):
    """Re-running the synthesiser on the CSV reproduces the cards baked into the deck.

    This is what makes the pre-baked correction trustworthy: the CSV is the source of
    truth and the committed W2GJ/AECORR pairs are derivable from it, not hand-tuned.
    """
    _cc, bulk, aero = model
    res = sd.build_from_section_data_multi(
        aero.boxes, aero.ajj, section_df, mach=0.0,
        incidence_deg=baked_alpha_deg, sid_w2gj_base=9100, sid_aecorr_base=9200)
    assert res.skipped == []
    assert sorted(res.correction.cards) == CAERO_EIDS

    for eid, (w2, ac) in res.correction.cards.items():
        assert w2.sid in bulk.w2gjs, f"W2GJ {w2.sid} (CAERO {eid}) not committed"
        assert ac.sid in bulk.aecorrs, f"AECORR {ac.sid} (CAERO {eid}) not committed"
        # Tolerance is set by the card text, not by the maths: the correction export
        # writes "%.6E" (7 significant digits), so an O(0.1) coefficient round-trips
        # through the deck with ~5e-8 of absolute error.  Tightening past that would
        # be testing the file format, not the synthesiser.  (Field width on these
        # cards is the open defect DEF-M12.)
        np.testing.assert_allclose(
            bulk.w2gjs[w2.sid].data, w2.data, rtol=1e-6, atol=1e-7,
            err_msg=f"committed W2GJ {w2.sid} differs from the CSV regeneration")
        np.testing.assert_allclose(
            bulk.aecorrs[ac.sid].target, ac.target, rtol=1e-6, atol=1e-7,
            err_msg=f"committed AECORR {ac.sid} differs from the CSV regeneration")


def test_t2_section_data_is_3d_informed_not_2d_polars(section_df):
    """The wing table integrates to a finite-wing slope, not a 2D section slope.

    This is the deck's central lesson.  A VLM strip already carries the finite-wing
    downwash, so feeding it a raw 2D polar slope (~0.105/deg, i.e. 6.0/rad) through WT2
    double-counts the lift.  The committed table is anchored to the model's own 3D strip
    loading and scaled to the Helmbold target for AR 7.72, so its area-weighted mean sits
    near 4.86/rad — well below the 2D value.
    """
    wing = section_df[(section_df.caero == 1000) & (section_df.a_hi == 8.0)]
    cn_a = wing.cn_a.to_numpy()
    assert cn_a.max() < 0.095, "wing cn_a reaches 2D-polar magnitude — downwash double-count"
    # tapered, not flat: the tip station must roll off well below the root
    assert cn_a[-1] < 0.6 * cn_a.max()
    # washout: a0 becomes less negative outboard
    a0 = wing.a0.to_numpy()
    assert a0[0] < a0[-1], "no washout in a0"
    assert np.all(np.diff(a0) >= 0.0)
    # the wing is cambered at the root (a NACA-2412-like alpha_L0) and has camber moment
    assert a0[0] == pytest.approx(-2.5, abs=1e-9)
    assert np.all(wing.cm0.to_numpy() < 0.0)


# --------------------------------------------------------------------------- #
# T3 / T3b — the trims
# --------------------------------------------------------------------------- #
def test_t3_both_trims_close_on_weight(model, trims):
    """Trimmed lift equals n*W from the GPWG mass, at 1g and at 2.5g."""
    _cc, bulk, _aero = model
    weight = compute_gpwg(bulk).total_mass * G
    for r, n in zip(trims, (1.0, 2.5)):
        lift = r.total_cl * r.q * bulk.aeros.sref
        assert lift == pytest.approx(n * weight, rel=1e-6)
        assert r.q == pytest.approx(Q_CRUISE)
        assert r.trim_mode == "determined"


def test_t3_corrected_lift_slope_in_band(trims):
    """Corrected whole-model CZ_alpha lands in the 5.2 +- 0.5 /rad design band."""
    rigid = trims[0].rigid_derivs["ANGLEA"]["CZ"]
    assert rigid == pytest.approx(5.2, abs=0.5)


def test_t3_elastic_effect_is_visible_but_modest(trims):
    """The wing is calibrated to show aeroelastic feedback without being floppy.

    The pre-flagship PBAR values put the elastic-restrained slope +0.44% off rigid,
    which leaves the deck with no aeroelasticity to demonstrate; the calibrated wing
    sits in a 2-6% band.
    """
    r = trims[0]
    rigid = r.rigid_derivs["ANGLEA"]["CZ"]
    restrained = r.restrained_derivs["ANGLEA"]["CZ"]
    ratio = restrained / rigid - 1.0
    assert 0.02 < ratio < 0.06, f"elastic/rigid CZ_alpha shift {ratio:+.3%} outside band"


def test_t3_pull_up_needs_more_incidence_and_more_up_elevator(trims):
    """2.5g trims to a larger incidence and a more nose-up elevator than 1g."""
    a1, a2 = (math.degrees(r.trim_vars["ANGLEA"]) for r in trims)
    e1, e2 = (math.degrees(r.trim_vars["ELEV"]) for r in trims)
    assert a2 > a1 > 0.0
    assert e2 < e1 < 0.0                       # more trailing-edge-up with load factor
    per_g = (e2 - e1) / 1.5
    assert -8.0 < per_g < -1.0, f"elevator gradient {per_g:.2f} deg/g is implausible"


def test_t3b_both_trims_land_inside_the_baked_correction_region(trims, section_df):
    """Guard on the single-region correction.

    `section_data` v1 bakes ONE operating region per surface, and nothing in the solver
    warns when a trim wanders outside it.  Both trimmed incidences must therefore sit
    inside the committed -4..8 deg block, or the correction is being extrapolated.
    """
    for r, name in zip(trims, ("1g", "2.5g")):
        alpha_deg = math.degrees(r.trim_vars["ANGLEA"])
        region = sd.operating_region(section_df, 1000, 0.0, alpha_deg)
        assert region == (-4.0, 8.0), (
            f"{name} trim alpha {alpha_deg:.3f} deg falls outside the baked wing "
            f"region (got {region}) — the committed correction is being extrapolated")


def test_t8_divergence_margin(trims):
    """Divergence stays an order of magnitude above the cruise dynamic pressure."""
    q_div = min(x for x in np.atleast_1d(trims[0].q_div) if x > 0)
    assert q_div / trims[0].q >= 10.0, f"divergence margin only {q_div / trims[0].q:.1f}x"


# --------------------------------------------------------------------------- #
# T4 — the mass-case sweep
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def massset_sweep():
    cc, bulk = parse_bdf(str(MASSSET_PATH))
    aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    return [run_sol144_trim(bulk, sc, aero) for sc in cc.subcases]


def test_t4_mass_cases_have_the_documented_weights(massset_sweep):
    labels = [r.massset_label for r in massset_sweep]
    masses = [r.massset_mass for r in massset_sweep]
    assert labels == ["FERRY", "CRUISE", "MTOW"]
    assert masses == pytest.approx([996.0, 1201.0, 1560.0], abs=0.5)


def test_t4_heavier_cases_trim_to_more_incidence(massset_sweep):
    """Same q, more weight, more lift needed, more incidence — strictly monotone."""
    alphas = [r.trim_vars["ANGLEA"] for r in massset_sweep]
    assert alphas[0] < alphas[1] < alphas[2]


def test_t4_wing_fuel_relieves_wing_root_bending(massset_sweep):
    """Inertia relief: wing-root bending PER UNIT WEIGHT falls as fuel enters the wing.

    Wing fuel is carried outboard of the root cut, so its weight cancels part of the
    lift there.  It is why a loads engineer certifies the zero-fuel case rather than
    the MTOW one, and no other test in the suite covers it.
    """
    ratios = []
    for r in massset_sweep:
        mon = r.monitor_loads["MWROOT"]
        ratios.append(abs(mon.totals[3]) / (r.massset_mass * G))
    ferry, cruise, mtow = ratios
    assert cruise < ferry, "half fuel did not relieve the wing root"
    assert mtow < cruise, "full fuel did not relieve the wing root further"


def test_t4_monitor_points_separate_aero_from_balance(massset_sweep):
    """Whole-aircraft MONPNT1 returns n*W (aero only); MONPNT3 returns ~0 (balanced)."""
    for r in massset_sweep:
        weight = r.massset_mass * G
        aero_only = r.monitor_loads["MALLAR"].totals[2]
        balanced = r.monitor_loads["MALLEA"].totals[2]
        assert aero_only == pytest.approx(weight, rel=1e-6)
        assert abs(balanced) < 1e-6 * weight


# --------------------------------------------------------------------------- #
# T5 — the transient
# --------------------------------------------------------------------------- #
def test_t5a_initial_sample_is_the_trim(maneuver):
    """t = 0 reproduces the SUBCASE 1 static trim: the IC is that trim."""
    _cc, _bulk, _aero, ic, mr = maneuver
    first = mr.steps[0]
    assert first.t == pytest.approx(0.0)
    scale = np.abs(ic.displacements).max()
    assert np.abs(first.displacements - ic.displacements).max() < 1e-6 * scale
    for label, value in ic.trim_vars.items():
        # ELEV at t=0 is read off the committed absolute TABLED1, so it can only
        # match the solved trim to the precision that table is authored at (8
        # decimals).  Every other label is held at its trim value exactly.
        tol = 1e-7 if label == "ELEV" else 1e-12
        assert first.trim_vars[label] == pytest.approx(value, abs=tol)
    assert first.Fz_aero == pytest.approx(ic.total_cl * ic.q * 16.24, rel=1e-6)


def test_t5b_command_held_at_trim_produces_no_motion(maneuver):
    """A command table that just holds the trimmed elevator must move nothing at all.

    This isolates the integrator and the table lookup from the physics: if the absolute
    MLDCOMD table is read correctly and the IC really is an equilibrium, every sample of
    a constant-at-trim run equals the trim to machine precision.
    """
    cc, bulk, aero, ic, _mr = maneuver
    e_trim = ic.trim_vars["ELEV"]
    held = deepcopy(bulk)
    held.tabled1s[300].ys = [e_trim] * len(held.tabled1s[300].ys)
    mr = run_maneuver_qs(held, cc.subcases[1], aero)
    drift = max(np.abs(s.displacements - ic.displacements).max() for s in mr.steps)
    assert drift < 1e-10 * np.abs(ic.displacements).max()
    assert all(s.trim_vars["ELEV"] == pytest.approx(e_trim, abs=1e-15) for s in mr.steps)


def test_t5c_ramp_is_tracked_and_settles(maneuver):
    """The elevator follows the absolute table and the response settles once it holds.

    The command table is committed in the deck, so this also gates the two-pass
    authoring: the baked first point must still be the trimmed elevator angle.
    """
    _cc, bulk, _aero, ic, mr = maneuver
    table = bulk.tabled1s[300]
    assert table.ys[0] == pytest.approx(ic.trim_vars["ELEV"], abs=5e-6), (
        "TABLED1 300 no longer starts at the trimmed ELEV — re-run the trim driver "
        "and re-bake the first table point (MLDCOMD tables are ABSOLUTE)")
    held_value = table.ys[-1]
    assert held_value == pytest.approx(table.ys[0] + math.radians(2.0), abs=1e-5)

    last, prev = mr.steps[-1], mr.steps[-2]
    assert last.trim_vars["ELEV"] == pytest.approx(held_value, abs=1e-12)
    scale = np.abs(last.displacements).max()
    assert np.abs(last.displacements - prev.displacements).max() < 1e-3 * scale
    # a nose-up pull raises the aero load above the 1g trim
    assert last.Fz_aero > mr.steps[0].Fz_aero


# --------------------------------------------------------------------------- #
# T6 — MLOADS x MASSSET (first coverage of the pairing anywhere)
# --------------------------------------------------------------------------- #
def test_t6_mloads_with_massset_is_exact_when_the_table_matches_the_case(maneuver):
    """The transient honours the mass case — but the command table is case-specific.

    MLDCOMD tables are ABSOLUTE, so the committed TABLED1 (authored for the baseline
    trim) does NOT start at the MTOW case's trimmed elevator: run it as-is and the
    airplane takes a step input at t = 0.  That is a deck-authoring property, not a
    solver defect, and this test pins both halves of it down: re-author the table for
    the mass case and the initial condition is reproduced to machine precision.
    """
    cc, bulk, aero, _ic, _mr = maneuver
    sc_trim = replace(cc.subcases[0], massset_sid=30)
    sc_mloads = replace(cc.subcases[1], massset_sid=30)
    ic = run_sol144_trim(bulk, sc_trim, aero)
    assert ic.massset_label == "MTOW"

    # (a) the committed baseline table is NOT valid for this mass case
    stale = run_maneuver_qs(bulk, sc_mloads, aero)
    assert stale.steps[0].trim_vars["ELEV"] != pytest.approx(
        ic.trim_vars["ELEV"], abs=1e-9)

    # (b) authored for this case, the pairing is exact
    e_trim = ic.trim_vars["ELEV"]
    tuned = deepcopy(bulk)
    tuned.tabled1s[300].ys = [e_trim, e_trim + math.radians(2.0),
                              e_trim + math.radians(2.0)]
    mr = run_maneuver_qs(tuned, sc_mloads, aero)
    first = mr.steps[0]
    assert np.abs(first.displacements - ic.displacements).max() < 1e-10
    assert first.Fz_aero == pytest.approx(ic.massset_mass * G, rel=1e-6)
    assert len(mr.steps) == len(stale.steps)


# --------------------------------------------------------------------------- #
# T7 — the fin ATTACH, exercised from file for the first time
# --------------------------------------------------------------------------- #
def test_t7_fin_attach_resolves_from_file(model):
    """The ATTACH card covers all 36 fin boxes and slaves them to the fin-root grid."""
    _cc, bulk, aero = model
    attach = [a for a in bulk.attaches.values() if a.caero == FIN_EID]
    assert len(attach) == 1
    card = attach[0]
    assert (card.id1, card.id2) == (5000, 5035)
    assert card.grid == FIN_GRID
    assert card.cid == 0                       # ATTACH requires the basic frame

    ops = build_spline_operators(bulk, aero.boxes, build_grid_index(bulk))
    gi = build_grid_index(bulk)
    fin = [k for k, b in enumerate(aero.boxes) if b.caero_eid == FIN_EID]
    assert len(fin) == 36
    # every fin box is driven by, and only by, the master grid's six DOFs
    master = slice(6 * gi[FIN_GRID], 6 * gi[FIN_GRID] + 6)
    for k in fin:
        row = ops.g_slope[k]
        assert np.abs(row[master]).sum() > 0.0
        others = np.abs(row).sum() - np.abs(row[master]).sum()
        assert others == pytest.approx(0.0, abs=1e-12)


def test_t7_fin_attach_transfers_side_force_and_yaw_moment(model):
    """A sideslipped fin delivers exact side force plus roll/yaw to the master grid.

    Before DEF-M11 a vertical ATTACH panel transferred nothing at all, because g_disp
    carried only its z-row.  The transfer is now the exact rigid-body identity
    F = sum(f_j), M = sum(r_j x f_j), so the fin's own side force must arrive at the
    root grid undiminished and bring a non-zero yaw moment with it.
    """
    _cc, bulk, aero = model
    ops = build_spline_operators(bulk, aero.boxes, build_grid_index(bulk))
    gi = build_grid_index(bulk)
    fin = [k for k, b in enumerate(aero.boxes) if b.caero_eid == FIN_EID]

    beta = math.radians(5.0)
    wash = np.array([-(beta * b.normal[1]) for b in aero.boxes]) + aero.wg
    cp = aero.ajj_inv_corr @ wash
    forces = np.zeros(3 * len(aero.boxes))
    for k in fin:
        forces[3 * k:3 * k + 3] = aero.boxes[k].normal * (cp[k] * aero.boxes[k].area * Q_CRUISE)

    loads = ops.g_load.T @ forces
    base = 6 * gi[FIN_GRID]
    fy_direct = sum(forces[3 * k + 1] for k in fin)
    assert abs(fy_direct) > 100.0, "fin developed no side force at beta = 5 deg"
    assert loads[base + 1] == pytest.approx(fy_direct, rel=1e-10)   # exact transfer
    assert abs(loads[base + 5]) > 1e-6, "no yaw moment reached the fin root"
    assert abs(loads[base + 3]) > 1e-6, "no roll moment reached the fin root"
    # the fin is planar in XZ: it carries no vertical load
    assert loads[base + 2] == pytest.approx(0.0, abs=1e-9)
