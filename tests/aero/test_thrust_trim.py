"""V-THR — applied structural load in the SOL 144 trim RHS (#6, gates G1–G7, G10).

Design note ``docs/30_future/designs/thrust_in_trim_applied_load.md``.  The deck
``sample/val_thrust_trim.bdf`` is the AR 8 wing + a horizontal tail with an elevator on a
stiff spine, an engine grid 0.5 below the nose on an RBAR pylon, ``SUPORT 135`` (surge,
plunge, pitch free) and one trim card shared by three subcases: no load, thrust through a
``LOAD`` combination, thrust as a direct ``FORCE`` set.

Every reference number is recomputed from the parsed deck or from the solver's own
operators (the VAL2 discipline): the applied-load resultant from the load vector, the
Schur reduction from ``build_trim_schur`` fed the applied load alone, the rigid 2×2 solve
from the solver's rigid derivatives on a stiffened copy of the deck.
"""

import csv
import dataclasses
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.assembly.reduction import expand_to_g
from sbeam.model.constraint import Spc1, Suport
from sbeam.model.load import Grav, Load
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver import sol144 as S
from sbeam.solver.maneuver_modal import run_maneuver_modal
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.solver.sol144 import AeroCache, run_sol144_diverg, run_sol144_trim
from sbeam.solver.sol144_trim_solve import build_trim_schur, recover_u_a
from sbeam.solver.sol144_util import load_resultant

REPO = Path(__file__).parent.parent.parent
DECK = REPO / "sample/val_thrust_trim.bdf"
THRUST = 40.0          # FORCE 701 magnitude, along -x (forward)
ARM = 0.5              # engine grid 0.5 below the reference line
ARM_CG = 0.45          # engine grid 0.45 below the CG (z_cg = -0.05)
MASS = 10.0            # CONM2 total
Q, SREF, CREF = 51.0, 8.0, 1.0


def _rigid_2x2(rigid, dcm):
    """[CZ_α CZ_δe; CM_α CM_δe]·[Δα; Δδe] = [0; −ΔCm] on the solver's rigid derivatives."""
    A = np.array([[rigid["ANGLEA"]["CZ"], rigid["ELEV"]["CZ"]],
                  [rigid["ANGLEA"]["CMY"], rigid["ELEV"]["CMY"]]])
    return np.linalg.solve(A, [0.0, -dcm])


def _stiffened(bulk, factor=1e6):
    b = dataclasses.replace(bulk)
    b.mat1s = {mid: dataclasses.replace(m, E=m.E * factor, G=m.G * factor) for mid, m in bulk.mat1s.items()}
    return b


def _suport_35(bulk):
    """The ordinary recipe: SUPORT 35, SPC 1246, no URDD1 label."""
    b = dataclasses.replace(bulk)
    b.supports = [Suport(gid=90, dofs="35")]
    b.spc1s = {1: [Spc1(sid=1, c="1246", grids=[90])]}
    b.aestats = {k: v for k, v in bulk.aestats.items() if v.label != "URDD1"}
    return b


def _parse():
    cc, bulk = parse_bdf(str(DECK))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
    return cc, bulk, aero, gi


def _run_all(cc, bulk, aero):
    cache = AeroCache(bulk, build_grid_index(bulk), seed=aero)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return {sc.subcase_id: run_sol144_trim(bulk, sc, aero, aero_cache=cache) for sc in cc.subcases}


@pytest.fixture(scope="module")
def model():
    return _parse()


@pytest.fixture(scope="module")
def trims(model):
    cc, bulk, aero, _ = model
    assert [sc.load_sid for sc in cc.subcases] == [None, 710, 701]
    return _run_all(cc, bulk, aero)


def _ref(bulk):
    return np.array([bulk.grids[90].x, bulk.grids[90].y, bulk.grids[90].z])


# ---------------------------------------------------------------------------
# The applied load itself
# ---------------------------------------------------------------------------

def test_applied_load_resultant_is_thrust_and_its_nose_up_moment(model, trims):
    """FORCE 701 at the engine grid: Fx = -T, My = +T·d about the reference (nose-up,
    a low thrust line pitches up); carried verbatim on the result."""
    cc, bulk, aero, gi = model
    f = assemble_load_vector(bulk, 710)
    res = load_resultant(f, bulk, gi, _ref(bulk))
    np.testing.assert_allclose(res, [-THRUST, 0, 0, 0, THRUST * ARM, 0], atol=1e-12)
    r = trims[2]
    assert r.load_sid == 710 and trims[1].load_sid is None and trims[1].applied_loads is None
    np.testing.assert_array_equal(r.applied_loads, f)
    np.testing.assert_allclose(r.net_loads, r.grid_loads + r.inertial_loads + f, atol=1e-12)


# ---------------------------------------------------------------------------
# G1 — exact Schur identity on the elastic deck
# ---------------------------------------------------------------------------

def _stages_up_to_rhs(bulk, subcase, aero):
    """Run the trim stages through the RHS assembly and return the state."""
    cache = AeroCache(bulk, build_grid_index(bulk), seed=aero)
    st = S._TrimState(bulk=bulk, subcase=subcase, aero=aero, aero_cache=cache)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for stage in (S._stage_validate_inputs, S._stage_resolve_massset_and_mach,
                      S._stage_build_labels, S._stage_resolve_ref_geometry,
                      S._stage_echo_chordcp, S._stage_build_downwash_and_reduce):
            stage(st)
    return st


def test_trim_shift_is_the_schur_reduction_of_the_applied_load_alone(model, trims):
    """δ(with) − δ(without) = schur_A⁻¹·(f_r − K_rl K_ll⁻¹ f_l) with f = the applied load
    and nothing else — the load enters the trim equation exactly like the aero baseline,
    elastic coupling included.  Same for the displacements through recover_u_a."""
    cc, bulk, aero, gi = model
    st = _stages_up_to_rhs(bulk, cc.subcases[1], aero)
    f_only = st.red.reduce_vector(st.applied_loads)
    schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_l = build_trim_schur(
        st.K_aa, st.Q_aa, st.Q_ax_a, st.M_ax_a, f_only, st.q_dyn,
        st.suport_local, st.free_label_cols)
    d_free = np.linalg.solve(schur_A, schur_b)
    r1, r2 = trims[1], trims[2]
    for i, lbl in enumerate(st.free_labels):
        if lbl.startswith("URDD"):
            continue               # solved in basic, reported in RCSID — checked in G4
        assert r2.trim_vars[lbl] - r1.trim_vars[lbl] == pytest.approx(d_free[i], rel=1e-10), lbl
    du_a = recover_u_a(K_ll_lu, C_ax_l, f_l, d_free, l_idx, st.K_aa.shape[0])
    du_g = expand_to_g(du_a, st.T, st.free_local, len(st.red_dofs))
    np.testing.assert_allclose(r2.displacements - r1.displacements, du_g,
                               rtol=1e-10, atol=1e-14 * np.abs(r1.displacements).max())


# ---------------------------------------------------------------------------
# G2 — rigid closed form on a stiffened copy
# ---------------------------------------------------------------------------

def test_rigid_closed_form_free_surge_is_the_thrust_moment_about_the_cg(model, trims):
    """With surge free the thrust also accelerates the aircraft, and the inertia
    relief of that acceleration acts at the CG; the moment the trim balances is
    therefore the thrust moment about the CG, ΔCm = T·(z_cg − z_T)/(q S c) — the
    textbook statement.  Gate on a stiffened copy (E, G × 1e6) so only the rigid
    closed form remains; Δδe > 0 (TE-down, nose-down) for a low thrust line."""
    cc, bulk, aero, gi = model
    r = _run_all(cc, _stiffened(bulk), aero)
    assert r[1].massset_cg[2] == pytest.approx(-0.05)
    dcm = THRUST * ARM_CG / (Q * SREF * CREF)
    assert dcm == pytest.approx(0.044118, abs=1e-6)
    d_alpha, d_elev = _rigid_2x2(r[1].rigid_derivs, dcm)
    assert r[2].trim_vars["ANGLEA"] - r[1].trim_vars["ANGLEA"] == pytest.approx(d_alpha, rel=1e-6)
    assert r[2].trim_vars["ELEV"] - r[1].trim_vars["ELEV"] == pytest.approx(d_elev, rel=1e-6)
    assert d_elev > 0
    # The shipped (flexible-spine) deck is within 1e-3 of the rigid number; the
    # Schur identity (G1) is its exact gate.
    assert trims[2].trim_vars["ELEV"] - trims[1].trim_vars["ELEV"] == pytest.approx(d_elev, rel=1e-3)


def test_rigid_closed_form_suport_35_is_the_thrust_moment_about_the_reference(model):
    """With the thrust x-component reacted at the SPC grid (the reference point) there
    is no surge-inertia relief: the trim balances T·(z_ref − z_T)/(q S c)."""
    cc, bulk, aero, gi = model
    r = _run_all(cc, _stiffened(_suport_35(bulk)), aero)
    dcm = THRUST * ARM / (Q * SREF * CREF)
    assert dcm == pytest.approx(0.049020, abs=1e-6)
    d_alpha, d_elev = _rigid_2x2(r[1].rigid_derivs, dcm)
    assert r[2].trim_vars["ANGLEA"] - r[1].trim_vars["ANGLEA"] == pytest.approx(d_alpha, rel=1e-6)
    assert r[2].trim_vars["ELEV"] - r[1].trim_vars["ELEV"] == pytest.approx(d_elev, rel=1e-6)


# ---------------------------------------------------------------------------
# G3 — linearity
# ---------------------------------------------------------------------------

def test_direct_force_set_equals_the_load_combination_bit_for_bit(trims):
    r2, r3 = trims[2], trims[3]
    assert r2.trim_vars == r3.trim_vars
    np.testing.assert_array_equal(r2.displacements, r3.displacements)
    np.testing.assert_array_equal(r2.net_loads, r3.net_loads)
    np.testing.assert_array_equal(r2.applied_loads, r3.applied_loads)


def test_doubling_the_thrust_doubles_every_shift(model, trims):
    cc, bulk, aero, gi = model
    doubled = dataclasses.replace(bulk)
    doubled.forces = {sid: [dataclasses.replace(fc, f=fc.f * 2.0) for fc in lst] for sid, lst in bulk.forces.items()}
    r = _run_all(cc, doubled, aero)
    for lbl in ("ANGLEA", "ELEV", "URDD1"):
        d1 = trims[2].trim_vars[lbl] - trims[1].trim_vars[lbl]
        d2 = r[2].trim_vars[lbl] - r[1].trim_vars[lbl]
        assert d2 == pytest.approx(2.0 * d1, rel=1e-10), lbl
    np.testing.assert_allclose(r[2].displacements - r[1].displacements,
                               2.0 * (trims[2].displacements - trims[1].displacements),
                               rtol=1e-10, atol=1e-16)


# ---------------------------------------------------------------------------
# G4 — closure and the surge balance
# ---------------------------------------------------------------------------

def test_closure_vanishes_and_surge_acceleration_is_thrust_over_mass(trims):
    """SUPORT 135: all six closure components ≈ 0 and m·URDD1 = T + Fx_aero exactly
    (URDD1 is in the z-down RCSID, x forward: positive = accelerating forward)."""
    for sid in (1, 2, 3):
        r = trims[sid]
        scale = np.abs(r.net_loads).max() * 8.0
        assert np.abs(r.maneuver_closure).max() < 1e-9 * scale, (sid, r.maneuver_closure)
    r = trims[2]
    fx_aero = r.total_cx * r.q * SREF
    assert r.trim_vars["URDD1"] == pytest.approx((THRUST + fx_aero) / MASS, rel=1e-12)
    assert trims[1].trim_vars["URDD1"] == pytest.approx(0.0, abs=1e-14)
    assert r.total_cl == pytest.approx(trims[1].total_cl, rel=1e-12)   # lift still = weight
    # Aero balances the thrust moment about the CG (surge free): −T·(z_cg − z_T)/(qSc).
    assert r.total_cm - trims[1].total_cm == pytest.approx(-(THRUST * ARM_CG) / (Q * SREF * CREF), rel=1e-9)


def test_ordinary_suport_35_reacts_the_thrust_x_at_the_spc(model, trims):
    """The common recipe (SUPORT 35, SPC 1246): the thrust x-component is reacted at
    the SPC grid — visible in the every-grid MONPNT3 reaction column and in the closure
    Fx — while only its moment enters the pitch trim; the Schur identity still holds.
    The pitch answer differs from the free-surge case by exactly the surge-inertia
    relief m·a_x·(z_ref − z_cg), which the free-surge deck carries and this one cannot."""
    cc, bulk, aero, gi = model
    b35 = _suport_35(bulk)
    r = _run_all(cc, b35, aero)
    for sid in (1, 2):
        assert "URDD1" not in r[sid].trim_vars
    r2 = r[2]
    fx_aero = r2.total_cx * r2.q * SREF
    assert r2.monitor_loads["MALL"].reaction[0] == pytest.approx(THRUST - fx_aero, rel=1e-10)
    assert r2.maneuver_closure[0] == pytest.approx(-THRUST + fx_aero, rel=1e-10)   # reacted, not trimmed
    scale = np.abs(r2.net_loads).max() * 8.0
    assert abs(r2.maneuver_closure[2]) < 1e-9 * scale and abs(r2.maneuver_closure[4]) < 1e-9 * scale
    # Schur identity on this variant too.
    st = _stages_up_to_rhs(b35, cc.subcases[1], aero)
    schur_A, schur_b, *_ = build_trim_schur(
        st.K_aa, st.Q_aa, st.Q_ax_a, st.M_ax_a, st.red.reduce_vector(st.applied_loads),
        st.q_dyn, st.suport_local, st.free_label_cols)
    d_free = np.linalg.solve(schur_A, schur_b)
    for i, lbl in enumerate(st.free_labels):
        assert r[2].trim_vars[lbl] - r[1].trim_vars[lbl] == pytest.approx(d_free[i], rel=1e-10), lbl
    # Surge-inertia relief: the free-surge trims see m·a_x at the CG, 0.05 below the
    # reference — a nose-down moment of 10·4·0.05 = 2 that the SPC'd recipe reacts
    # at the reference instead: moment about the reference (20) vs about the CG (18).
    d_free_surge = trims[2].trim_vars["ELEV"] - trims[1].trim_vars["ELEV"]
    d_spc = r[2].trim_vars["ELEV"] - r[1].trim_vars["ELEV"]
    assert d_spc > d_free_surge > 0
    assert d_spc / d_free_surge == pytest.approx(ARM / ARM_CG, rel=1e-3)


# ---------------------------------------------------------------------------
# G5 — load path: section cut and every-grid monitor
# ---------------------------------------------------------------------------

def test_nose_cut_carries_the_thrust_and_whole_airplane_monitor_closes(trims):
    r = trims[2]
    cut = r.section_loads["SECNOSE"]
    assert cut.axis == 1 and cut.side == "NEG" and len(cut.stations) == 2
    for stn in cut.stations:
        assert stn.n_members == 2                       # grids 10 and 70
        np.testing.assert_allclose(stn.applied, [-THRUST, 0, 0, 0, THRUST * ARM, 0], atol=1e-12 * THRUST)
        np.testing.assert_allclose(stn.totals, stn.aero + stn.inertia + stn.reaction + stn.applied, atol=1e-12)
    for stn in trims[1].section_loads["SECNOSE"].stations:
        assert stn.applied is None
    m = r.monitor_loads["MALL"]
    np.testing.assert_allclose(m.applied, [-THRUST, 0, 0, 0, THRUST * ARM, 0], atol=1e-12 * THRUST)
    scale = np.abs(r.net_loads).max() * 8.0
    assert np.abs(m.totals).max() < 1e-9 * scale        # aero + inertia + applied + reaction = 0
    assert trims[1].monitor_loads["MALL"].applied is None
    assert r.monitor_loads["MAERO"].applied is None     # a MONPNT1 is aero-only by definition


# ---------------------------------------------------------------------------
# G6 — derivatives are sensitivities; a constant load leaves them alone
# ---------------------------------------------------------------------------

def test_derivatives_and_intercepts_are_untouched_by_the_load(trims):
    for sid in (2, 3):
        assert trims[sid].rigid_derivs == trims[1].rigid_derivs
        assert trims[sid].restrained_derivs == trims[1].restrained_derivs
        assert trims[sid].unrestrained_derivs == trims[1].unrestrained_derivs
        assert trims[sid].unrestrained_intercepts == trims[1].unrestrained_intercepts
        assert trims[sid].hinge_moments["ELEV"]["ANGLEA"] == trims[1].hinge_moments["ELEV"]["ANGLEA"]


# ---------------------------------------------------------------------------
# G7 — refusals
# ---------------------------------------------------------------------------

def _with_grav(bulk):
    b = dataclasses.replace(bulk)
    b.gravs = {900: Grav(sid=900, cid=0, g=9.81, n1=0.0, n2=0.0, n3=-1.0)}
    b.loads = dict(bulk.loads)
    b.loads[720] = Load(sid=720, s=1.0, components=[(1.0, 701), (1.0, 900)])
    return b


def test_grav_in_a_trim_load_set_is_refused(model):
    cc, bulk, aero, gi = model
    b = _with_grav(bulk)
    for sid in (900, 720):
        sc = dataclasses.replace(cc.subcases[1], load_sid=sid)
        with pytest.raises(ValueError, match=r"GRAV \[900\].*URDD3"):
            run_sol144_trim(b, sc, aero)


def test_load_in_an_mloads_subcase_is_refused_by_both_transient_solvers(model):
    cc, bulk, aero, gi = model
    sc = SubcaseControl(subcase_id=9, mloads_sid=1, load_sid=701, spc_sid=1)
    with pytest.raises(ValueError, match=r"MLOADS=1 and LOAD=701"):
        run_maneuver_qs(bulk, sc, aero)
    with pytest.raises(ValueError, match=r"MLOADS=1 and LOAD=701"):
        run_maneuver_modal(bulk, sc, aero)


def test_load_in_a_diverg_only_subcase_is_refused(model):
    cc, bulk, aero, gi = model
    sc = SubcaseControl(subcase_id=9, diverg_sid=1, load_sid=701, spc_sid=1)
    with pytest.raises(ValueError, match=r"LOAD=701 with DIVERG=1"):
        run_sol144_diverg(bulk, sc, aero)


# ---------------------------------------------------------------------------
# G10 — CLI end to end
# ---------------------------------------------------------------------------

def test_cli_writes_the_applied_block_and_columns(tmp_path):
    deck = tmp_path / DECK.name
    deck.write_text(DECK.read_text())
    out = subprocess.run([sys.executable, "-m", "sbeam.main", str(deck)], capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0, out.stderr
    f06 = (tmp_path / "val_thrust_trim.f06").read_text()
    assert f06.count("A P P L I E D   S T R U C T U R A L   L O A D") == 2
    assert "LOAD = 710   RESULTANT ABOUT THE REFERENCE POINT" in f06
    assert "SOURCE: AERO + INERTIA + REACTION + APPLIED" in f06
    with open(tmp_path / "val_thrust_trim.monitor_loads.csv") as fh:
        rows = list(csv.DictReader(fh))
    assert "Fz_applied" in rows[0]
    assert {r["case"] for r in rows} == {"1", "2", "3"}
    with open(tmp_path / "val_thrust_trim.section_loads.csv") as fh:
        rows = [r for r in csv.DictReader(fh) if r["name"] == "SECNOSE" and r["case"] == "2"]
    assert float(rows[0]["c1_applied"]) == pytest.approx(-THRUST)
    man = (tmp_path / "val_thrust_trim.maneuver_loads.bdf").read_text()
    assert "aero + inertia relief) — subcase 1" in man
    assert "aero + inertia relief + applied LOAD) — subcase 2" in man
    assert "applied LOAD=710" in man
