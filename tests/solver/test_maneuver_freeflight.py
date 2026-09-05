"""Step 63 — free-flight rigid-body coupling: the G0-b physics gates.

The self-balancing maneuver on the full-span HA144A deck (METHOD=-1 modal
solver, rho variant so nothing is condensed).  Gates (backlog Step 63,
finalized 2026-08-02):

  1. zero-command free response stays at the trim equilibrium to round-off;
  2. ELEV ramp-and-hold: closure ≈ 0 at every dt (the recovery mirrors the
     discrete EOM term-for-term), and the SOLUTION converges O(dt²) under
     dt-halving (Newmark average-acceleration order);
  3. the settled steady state reproduces the Step 53 trim with
     {ELEV = held, PITCH = settled, URDD5 = 0} prescribed and ANGLEA/URDD3
     free (trim vars + net loads ≤ 1e−6 relative, full basis) — plus the
     settled kinematic identity ΔURDD3_basic ≈ V·Δθ̇ (α̇ = 0 in the pull-up);
  4. the short-period eigenpair of the assembled h-set system matches a rigid
     2-DOF hand calculation from the Step 53 AE8b unrestrained derivatives;
  5. mass-case physics sanity: heavier MASSSET (uniform SCALE, CG-neutral) ⇒
     lower steady load-factor increment for the same elevator command;
  6. commanding a rigid-state label under the modal solver is a hard error
     (solver and parser);
  7. free flight without RHOREF on the IC TRIM is a hard error;
  8. the shipped sample deck ``ha144a_mloads_massset.bdf`` runs end-to-end
     (three free-flight mass cases; NZ_REL trend; f06 FREE FLIGHT block).

Command tables are ABSOLUTE, so every ELEV table is authored trim value +
increment (two-pass), matching the documented deck-authoring practice.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.model.mass import Massset
from sbeam.model.aero import Trim
from sbeam.solver.maneuver_modal import ManeuverBasisCache, run_maneuver_modal
from sbeam.solver.sol144 import run_sol144_trim
from sbeam.solver.modal_basis import (
    assemble_aset_operators,
    build_hset_gafs,
    build_maneuver_basis,
)

from tests.solver.test_maneuver_modal import (
    RHO,
    RHOREF,
    _aero_and_trim_elev,
    _build,
    _command_elev,
    _load_scale,
    _max_closure,
)

SAMPLE_DECK = Path(__file__).parent.parent.parent / "sample" / "ha144a_mloads_massset.bdf"
ELEV_RAMP = ([0.0, 0.1, 60.0], [0.0, 0.05, 0.05])   # ramp-and-hold increment


# ---------------------------------------------------------------------------
# Gate 1 — zero-command free response = trim equilibrium
# ---------------------------------------------------------------------------

def test_zero_command_free_response_stays_at_equilibrium():
    """No MLDCOMD: the coupled free system starts and stays exactly at the
    Step 53 trim — Δξ ≈ 0, every label and every net load unchanged."""
    bulk, gi = _build(rho=RHO, tend=0.5)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        mod = run_maneuver_modal(bulk, sc, aero)
    scale = float(np.max(np.abs(ic.net_loads)))
    for s in mod.steps:
        assert float(np.max(np.abs(s.modal_coords))) <= 1e-10
        assert np.max(np.abs(s.net_loads - ic.net_loads)) <= 1e-6 * scale
        for lbl, v in ic.trim_vars.items():
            assert abs(s.trim_vars[lbl] - v) <= 1e-6 * max(1.0, abs(v))
        assert abs(s.nz_rel - 1.0) <= 1e-9


# ---------------------------------------------------------------------------
# Gate 2 — closure ≈ 0 at every dt; solution converges O(dt²)
# ---------------------------------------------------------------------------

def test_elev_ramp_closure_and_o_dt2_convergence():
    """Closure is the discrete Newmark residual (≈ round-off) at EVERY dt —
    stronger than the backlog's decay requirement — while the trajectory
    itself converges O(dt²): the sample-wise difference between successive
    dt-halvings shrinks ~4× (ratio ≥ 3 asserted).  A smooth (cosine) command
    with modal damping keeps unresolved high-mode ringing (ω·dt ≫ 1, which no
    dt in this range integrates accurately) out of the convergence metric —
    the same reasoning as the Step 62 NMODES convergence gate."""
    smooth_ts = np.linspace(0.0, 0.2, 41)
    smooth = (list(smooth_ts) + [1.0],
              list(0.05 * 0.5 * (1.0 - np.cos(np.pi * smooth_ts / 0.2))) + [0.05])
    runs = {}
    for dt in (0.01, 0.005, 0.0025):        # each divides tout exactly
        bulk, gi = _build(rho=RHO, tend=1.0, dt=dt, tout=0.1, zeta=0.02)
        sc = SubcaseControl(subcase_id=1, spc_sid=1)
        sc.mloads_sid = 1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            aero, elev0 = _aero_and_trim_elev(bulk, gi)
            _command_elev(bulk, elev0, *smooth)
            runs[dt] = run_maneuver_modal(bulk, sc, aero)
        assert _max_closure(runs[dt].steps) <= 1e-8 * _load_scale(runs[dt].steps)

    def _traj(mod):
        return np.array([[s.trim_vars["ANGLEA"], s.trim_vars["URDD3"],
                          s.trim_vars["URDD5"]] for s in mod.steps])

    err_coarse = float(np.max(np.abs(_traj(runs[0.01]) - _traj(runs[0.0025]))))
    err_fine = float(np.max(np.abs(_traj(runs[0.005]) - _traj(runs[0.0025]))))
    # Richardson vs the dt/4 reference: O(dt²) gives a ratio of
    # (16−1)/(4−1) = 5; assert ≥ 3 with margin (measured ~5).
    assert err_coarse >= 3.0 * err_fine
    assert err_fine > 0.0


# ---------------------------------------------------------------------------
# Gate 3 — settled steady state = Step 53 trim (ELEV/PITCH prescribed)
# ---------------------------------------------------------------------------

def test_settled_state_reproduces_step53_elev_prescribed():
    """Long ELEV hold with damping: take the settled sample, prescribe
    {ELEV = held, PITCH = settled, URDD5 = 0} in a fresh TRIM with
    ANGLEA/URDD3 free — the static trim must reproduce the settled trim vars
    and net loads ≤ 1e−6 relative (full basis).  Also the settled pull-up
    kinematics: ΔURDD3_basic = V·Δθ̇ (α̇ = 0 at fixed V)."""
    bulk, gi = _build(rho=RHO, tend=60.0, dt=0.01, tout=1.0, zeta=0.05)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero, elev0 = _aero_and_trim_elev(bulk, gi)
        _command_elev(bulk, elev0, *ELEV_RAMP)
        mod = run_maneuver_modal(bulk, sc, aero)
    end = mod.steps[-1]

    # Settled: URDD5 ≈ 0 and the last two samples agree.
    assert abs(end.trim_vars["URDD5"]) <= 1e-7
    prev = mod.steps[-2]
    for lbl in ("ANGLEA", "URDD3", "PITCH"):
        assert abs(end.trim_vars[lbl] - prev.trim_vars[lbl]) <= 1e-7 * max(
            1.0, abs(end.trim_vars[lbl]))

    # Kinematic identity of the steady pull-up: ΔURDD3 = V·Δθ̇, i.e.
    # Δḧ = −V·θ̇ in the z-down URDD sense — via the rate states directly.
    v_inf = mod.basis_info["v_inf"]
    d_urdd3 = end.xi_r_ddot[0]              # rigid DOF 3 (plunge) acceleration
    d_thetadot = end.xi_r_dot[1]            # rigid DOF 5 (pitch) rate
    assert abs(d_urdd3 - v_inf * d_thetadot) <= 1e-5 * max(1.0, abs(d_urdd3))

    # Step 53 trim with ELEV/PITCH prescribed, ANGLEA/URDD3 free, URDD5 = 0.
    bulk.trims[3] = Trim(
        sid=3, mach=bulk.trims[1].mach, q=bulk.trims[1].q,
        vars={"ELEV": end.trim_vars["ELEV"],
              "PITCH": end.trim_vars["PITCH"],
              "URDD5": 0.0},
        rhoref=RHOREF)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ref = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=9, spc_sid=1, trim_sid=3), aero)
    for lbl in ("ANGLEA", "URDD3"):
        assert abs(end.trim_vars[lbl] - ref.trim_vars[lbl]) <= 1e-6 * max(
            1.0, abs(ref.trim_vars[lbl])), lbl
    scale = float(np.max(np.abs(ref.net_loads)))
    assert float(np.max(np.abs(end.net_loads - ref.net_loads))) <= 1e-6 * scale


# ---------------------------------------------------------------------------
# Gate 4 — short-period eigenpair vs 2-DOF hand calc (AE8b derivatives)
# ---------------------------------------------------------------------------

def test_short_period_matches_2dof_handcalc():
    """The rigid-dominant oscillatory eigenpair of the assembled free-flight
    system matches a 2-DOF (plunge/pitch) hand calculation built from the
    Step 53 unrestrained (mean-axis) derivatives and the GPWG rigid mass —
    two completely independent code paths — to 5 %."""
    from sbeam.model.aero import require_aeros

    bulk, gi = _build(rho=RHO)
    q = bulk.trims[1].q
    v = float(np.sqrt(2.0 * q / RHOREF))
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        ops = assemble_aset_operators(bulk, sc, aero)
        basis = build_maneuver_basis(bulk, ops, None, nmodes=0)
        gafs = build_hset_gafs(bulk, ops, basis, aero, v, zeta=0.0)

    n_h, n_r = basis.n_h, basis.n_r
    M = basis.M_hh
    C = -q * gafs.B_hh
    K = basis.K_hh - q * gafs.Q_hh
    A = np.block([
        [np.zeros((n_h, n_h)), np.eye(n_h)],
        [-np.linalg.solve(M, K), -np.linalg.solve(M, C)],
    ])
    lam, vec = np.linalg.eig(A)
    rigid_part = (np.abs(vec[:n_r, :]).sum(0)
                  + np.abs(vec[n_h:n_h + n_r, :]).sum(0)) / np.abs(vec).sum(0)
    osc = np.abs(lam.imag) > 1e-3
    sp = lam[np.argmax(rigid_part * osc)]

    # 2-DOF hand calc: states (h, θ); α = θ − ḣ/V; q̂ = θ̇·c/(2V).
    aeros = require_aeros(bulk)
    S, c = aeros.sref, aeros.cref
    d = ic.unrestrained_derivs
    CZa, CMa = d["ANGLEA"]["CZ"], d["ANGLEA"]["CMY"]
    CZq, CMq = d["PITCH"]["CZ"], d["PITCH"]["CMY"]
    M_rr = basis.M_rr
    Ka = q * S * np.array([[0.0, CZa], [0.0, c * CMa]])
    Ca = q * S * np.array([
        [-CZa / v, CZq * c / (2.0 * v)],
        [-c * CMa / v, c * CMq * c / (2.0 * v)],
    ])
    A2 = np.block([
        [np.zeros((2, 2)), np.eye(2)],
        [np.linalg.solve(M_rr, Ka), np.linalg.solve(M_rr, Ca)],
    ])
    lam2 = np.linalg.eig(A2)[0]
    sp2 = lam2[np.argmax(np.abs(lam2.imag))]
    if sp.imag * sp2.imag < 0:
        sp2 = np.conj(sp2)

    assert abs(sp - sp2) / abs(sp2) <= 0.05


# ---------------------------------------------------------------------------
# Gate 5 — mass-case sanity: heavier ⇒ lower steady load-factor increment
# ---------------------------------------------------------------------------

def test_massset_heavier_gives_lower_steady_load_factor():
    """Uniform-SCALE mass cases (CG-neutral): the same ELEV increment settles
    at a strictly smaller |Δ load factor| the heavier the aircraft; the shared
    basis cache builds Φ exactly once across the sweep."""
    bulk, gi = _build(rho=RHO, tend=20.0, dt=0.01, tout=1.0, zeta=0.05)
    for sid, scl in ((110, 0.85), (120, 1.0), (130, 1.15)):
        bulk.masssets[sid] = Massset(sid=sid, label=f"S{scl}", scale=scl)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        cache = ManeuverBasisCache(bulk, aero)
        d_nz = {}
        for sid in (110, 120, 130):
            sc = SubcaseControl(subcase_id=1, spc_sid=1, massset_sid=sid)
            sc.mloads_sid = 1
            ic = run_sol144_trim(
                bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1,
                                     massset_sid=sid), aero)
            _command_elev(bulk, float(ic.trim_vars["ELEV"]),
                          [0.0, 0.1, 20.0], [0.0, 0.05, 0.05])
            mod = run_maneuver_modal(bulk, sc, aero, basis_cache=cache)
            d_nz[sid] = abs(mod.steps[-1].nz_rel - 1.0)
    assert d_nz[110] > d_nz[120] > d_nz[130] > 0.0
    assert cache.n_builds == 1


# ---------------------------------------------------------------------------
# Gates 6/7 — hard errors: rigid-state command, missing RHOREF
# ---------------------------------------------------------------------------

def test_mldcomd_rigid_label_raises_in_solver():
    bulk, gi = _build(rho=None, tend=0.05)
    from sbeam.model.maneuver import Mldcomd, Tabled1
    bulk.tabled1s[8] = Tabled1(tid=8, xs=[0.0, 1.0], ys=[0.1, 0.1])
    bulk.mldcomds[1] = Mldcomd(sid=1, commands=[("ANGLEA", 8)])
    bulk.mloads[1].mldcomd = 1
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        with pytest.raises(ValueError, match="ANGLEA"):
            run_maneuver_modal(bulk, sc, aero)


def test_mldcomd_rigid_label_raises_in_parser(tmp_path):
    """Deck-time mirror: a modal MLOADS whose MLDCOMD commands an AESTAT
    label fails at parse; the same deck with an all-zeros (direct-solver)
    MLOADS parses."""
    src = SAMPLE_DECK.read_text()
    bad = src.replace("MLDCOMD, 11, ELEV, 310", "MLDCOMD, 11, ANGLEA, 310")
    p = tmp_path / "bad.bdf"
    p.write_text(bad)
    with pytest.raises(ValueError, match="ANGLEA"):
        parse_bdf(str(p))
    ok = bad.replace("MLOADS, 10, 1, 1, 11, 1, 0, -1, 0.02",
                     "MLOADS, 10, 1, 1, 11, 1")
    p2 = tmp_path / "ok.bdf"
    p2.write_text(ok)
    parse_bdf(str(p2))   # direct solver may prescribe rigid states


def test_missing_rhoref_raises():
    bulk, gi = _build(rho=None, tend=0.05)
    bulk.trims[1].rhoref = 0.0
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        with pytest.raises(ValueError, match="RHOREF"):
            run_maneuver_modal(bulk, sc, aero)


# ---------------------------------------------------------------------------
# Gate 8 — shipped sample deck end-to-end
# ---------------------------------------------------------------------------

def test_sample_deck_free_flight_massset_sweep():
    """sample/ha144a_mloads_massset.bdf: three free-flight mass cases through
    the main-loop dispatch — closure ≈ 0 everywhere, NZ_REL strictly
    decreasing with mass at the end of the hold, f06 FREE FLIGHT block."""
    from sbeam.parser.case_control import CaseControl
    from sbeam.results.f06_writer import build_f06_sol144_maneuver_text
    from sbeam.solver.sol144 import AeroCache
    from sbeam.assembly.load_vector import build_grid_index

    cc, bulk = parse_bdf(str(SAMPLE_DECK))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        cache = AeroCache(bulk, gi, seed=aero)
        basis_cache = ManeuverBasisCache(bulk, aero)
        results = {}
        for sc in cc.subcases:
            assert bulk.mloads[sc.mloads_sid].selects_modal
            results[sc.subcase_id] = run_maneuver_modal(
                bulk, sc, aero, aero_cache=cache, basis_cache=basis_cache)
    assert basis_cache.n_builds == 1
    nz_end = {}
    for sc_id, mod in results.items():
        assert mod.basis_info["free_flight"] is True
        assert _max_closure(mod.steps) <= 1e-6 * _load_scale(mod.steps)
        nz_end[sc_id] = mod.steps[-1].nz_rel
    # Heavier (higher subcase id) ⇒ lower settled load factor.
    assert nz_end[1] > nz_end[2] > nz_end[3] > 1.0
    txt = build_f06_sol144_maneuver_text(
        CaseControl(sol=144), bulk, results[1], 1)
    assert "FREE FLIGHT: V =" in txt
    assert "NZ_REL" not in txt   # NZ_REL lives in the MLDPRNT export
