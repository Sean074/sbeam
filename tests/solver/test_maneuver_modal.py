"""Step 62/63 — modal transient maneuver solver mechanics: acceptance gates.

Since Step 63 the modal solver is the FREE-FLIGHT solver (rigid states are
integrated, not prescribed), so the Step 62 ELEV-ramp identity gates against
``run_maneuver_qs`` no longer apply — the two solvers integrate different
physics whenever the command history unbalances the aircraft.  The reworked
gates in this file cover the solver *mechanics* against free-flight-consistent
references:

  * hold-at-trim = the Step 53 static balanced solution (zero-command
    equilibrium — now a statement about the full coupled free system);
  * NMODES convergence toward the FULL-BASIS free-flight solution
    (mode-acceleration recovery, monotone peak-bar-force error decay);
  * mode-acceleration ≥ mode-displacement on truncated bases;
  * truncated equilibrium start exact (t0 sample truncation-independent);
  * ζ > 0 decays the ELASTIC modal tail (the rigid states are excluded — a
    steady pull-up carries a secular attitude drift no damping removes);
  * ELEV-ramp closure ≈ 0 on both mass variants (the free-flight
    self-balancing identity; the physics gates live in
    ``test_maneuver_freeflight.py``);
  * fixed-Φ MASSSET machinery (hold-at-trim on the mass case; fixed vs
    re-solved basis approximation; D4 CG-shift warning);
  * solver selection (D1) and the f06 basis/FREE FLIGHT summary block.

Fixture family: the full-span HA144A deck in two mass configurations — the
``rho`` variant (CBAR distributed mass; nothing condensed) and the CONM2-only
variant (18 massless rotational DOFs condensed).  Free flight needs the true
airspeed, so ``_build`` stamps RHOREF onto TRIM 1; and MLDCOMD tables are
ABSOLUTE, so ELEV command tables are authored as trim value + increment
(two-pass, mirroring the documented deck-authoring practice).
"""

import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.mass import Massset, Conm2
from sbeam.model.maneuver import Tabled1, Mldtime, Mldcomd, Mldtrim, Mloads
from sbeam.model.maneuver_presets import load_factor_to_urdd3
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.solver.maneuver_modal import (
    ManeuverBasisCache,
    run_maneuver_modal,
)
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"
G = 32.174  # ft/s²
RHOREF = 0.002377  # slug/ft³ — free flight needs V = sqrt(2q/rho)

# CBAR density for the fully-mass-covered variant: consistent-mass rotary
# terms put mass on every free DOF, so the basis condenses nothing.
RHO = 0.05


def _build(n_z=2.0, rho=None, tend=0.3, dt=0.01, tout=0.05,
           nmodes=0, method=-1, zeta=0.0):
    """Parse the deck and register the MLOADS card set programmatically.

    No MLDCOMD yet — command tables are absolute, so they are registered by
    ``_command_elev`` after the trim ELEV value is known (two-pass authoring).
    """
    _cc, bulk = parse_bdf(str(BDF_PATH))
    bulk.trims[1].vars["URDD3"] = load_factor_to_urdd3(n_z, G)
    bulk.trims[1].rhoref = RHOREF
    if rho:
        for mat in bulk.mat1s.values():
            mat.rho = rho
    gi = build_grid_index(bulk)
    bulk.mldtrims[1] = Mldtrim(sid=1, trim_sid=1)
    bulk.mldtimes[1] = Mldtime(sid=1, t0=0.0, tend=tend, dt=dt, tout=tout)
    bulk.mloads[1] = Mloads(
        sid=1, mldtrim=1, mldtime=1, mldcomd=0, mldprnt=0,
        nmodes=nmodes, method=method, zeta=zeta)
    return bulk, gi


def _aero_and_trim_elev(bulk, gi):
    """AeroModel + the trim ELEV value (pass 1 of the two-pass authoring)."""
    aero = build_aero_model(bulk, grid_index=gi)
    ic = run_sol144_trim(
        bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    return aero, float(ic.trim_vars["ELEV"])


def _command_elev(bulk, elev0, times, deltas):
    """Register an absolute ELEV table = trim value + increment history."""
    bulk.tabled1s[7] = Tabled1(
        tid=7, xs=list(times), ys=[elev0 + d for d in deltas])
    bulk.mldcomds[1] = Mldcomd(sid=1, commands=[("ELEV", 7)])
    bulk.mloads[1].mldcomd = 1


# Increment histories (added to the trim ELEV — see _command_elev).
ELEV_RAMP = ([0.0, 0.1, 1.0], [0.0, 0.05, 0.05])   # ramp-and-hold, unbalancing

# Cosine-smoothed ramp for the convergence table: a clamped-linear ramp's
# slope discontinuities ring the highest retained modes (Phase G0 risk item 3)
# and put an ω-independent ringing floor under every truncated solution —
# convergence with NMODES is only visible on a smooth command.
_TS = np.linspace(0.0, 0.2, 41)
ELEV_SMOOTH = (
    list(_TS) + [1.0],
    list(0.05 * 0.5 * (1.0 - np.cos(np.pi * _TS / 0.2))) + [0.05],
)


def _run_modal(rho=None, elev_tab=ELEV_RAMP, massset_sid=None, **kw):
    """One free-flight modal run with a trim-consistent ELEV command."""
    bulk, gi = _build(rho=rho, **kw)
    sc = SubcaseControl(subcase_id=1, spc_sid=1, massset_sid=massset_sid)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero, elev0 = _aero_and_trim_elev(bulk, gi)
        if elev_tab is not None:
            _command_elev(bulk, elev0, *elev_tab)
        mod = run_maneuver_modal(bulk, sc, aero)
    return mod, bulk, gi


def _rel(a, b, floor=1e-30):
    return float(np.max(np.abs(a - b)) / max(floor, float(np.max(np.abs(b)))))


_BAR_ATTRS = None


def _bar_matrix(steps):
    """All CBAR force components of all steps as one array (shared attr order)."""
    global _BAR_ATTRS
    rows = []
    for s in steps:
        row = []
        for eid in sorted(s.bar_forces):
            bf = s.bar_forces[eid]
            if _BAR_ATTRS is None:
                _BAR_ATTRS = sorted(
                    k for k, v in vars(bf).items() if isinstance(v, float))
            row += [getattr(bf, k) for k in _BAR_ATTRS]
        rows.append(row)
    return np.array(rows)


def _max_closure(steps):
    return max(float(np.linalg.norm(s.closure)) for s in steps)


def _load_scale(steps):
    return max(1.0, max(float(np.max(np.abs(s.net_loads))) for s in steps))


# ---------------------------------------------------------------------------
# Gate 1 — free-flight self-balancing closure on both mass variants
# ---------------------------------------------------------------------------

def test_elev_ramp_closure_rho_deck():
    """Full basis + distributed mass: closure ≈ 0 through an unbalancing ELEV
    ramp — the free-flight recovery mirrors the coupled EOM term-for-term, so
    the residual is the discrete Newmark residual (~round-off)."""
    mod, _bulk, _gi = _run_modal(rho=RHO, tend=0.5)
    assert mod.basis_info["n_massless"] == 0
    assert mod.basis_info["free_flight"] is True
    assert _max_closure(mod.steps) <= 1e-8 * _load_scale(mod.steps)


def test_elev_ramp_closure_conm2_only_deck():
    """CONM2-only deck: 18 condensed DOFs leave the (second-order) aero
    coupling to the massless static content as a documented small residual."""
    mod, _bulk, _gi = _run_modal(rho=None, tend=0.5)
    assert mod.basis_info["n_massless"] == 18
    assert _max_closure(mod.steps) <= 1e-4 * _load_scale(mod.steps)


# ---------------------------------------------------------------------------
# Gate 2 — NMODES convergence + mode-acceleration superiority
# ---------------------------------------------------------------------------

def _peak_bar_err(mod_steps, ref_steps):
    ref = _bar_matrix(ref_steps)
    return float(np.max(np.abs(_bar_matrix(mod_steps) - ref))
                 / np.max(np.abs(ref)))


@pytest.fixture(scope="module")
def convergence_runs():
    """Modal runs at NMODES ∈ {2, 4, 8, all}; the reference is the FULL-BASIS
    free-flight solution (rho deck, smooth command — see ELEV_SMOOTH)."""
    bulk, gi = _build(rho=RHO)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero, elev0 = _aero_and_trim_elev(bulk, gi)
        _command_elev(bulk, elev0, *ELEV_SMOOTH)
        cache = ManeuverBasisCache(bulk, aero)
        runs = {}
        for nm in (2, 4, 8, 0):
            bulk.mloads[1].nmodes = nm
            runs[nm] = run_maneuver_modal(bulk, sc, aero, basis_cache=cache)
        bulk.mloads[1].nmodes = 4
        runs["md4"] = run_maneuver_modal(
            bulk, sc, aero, basis_cache=cache, recovery="displacement")
    return runs, cache


def test_convergence_monotone_peak_bar_force(convergence_runs):
    """Peak-bar-force error vs the full basis decays monotonically."""
    runs, _cache = convergence_runs
    ref = runs[0].steps
    errs = {nm: _peak_bar_err(runs[nm].steps, ref) for nm in (2, 4, 8)}
    assert errs[2] >= errs[4] >= errs[8]
    assert errs[2] > 1e-6                        # truncation is actually visible


def test_mode_acceleration_beats_mode_displacement(convergence_runs):
    """≥10× on truncated (NMODES=4) bar forces vs the full-basis reference."""
    runs, _cache = convergence_runs
    ref = runs[0].steps
    err_ma = _peak_bar_err(runs[4].steps, ref)
    err_md = _peak_bar_err(runs["md4"].steps, ref)
    assert err_md >= 10.0 * err_ma


def test_basis_cache_builds_once(convergence_runs):
    """D3: five modal runs, one eigensolve."""
    _runs, cache = convergence_runs
    assert cache.n_builds == 1


def test_truncated_equilibrium_start_is_exact(convergence_runs):
    """The t0 sample is truncation-independent (mode-acceleration at
    equilibrium is K_eff⁻¹·F; commands start at the trim value)."""
    runs, _cache = convergence_runs
    a, b = runs[2].steps[0], runs[0].steps[0]
    assert _rel(a.displacements, b.displacements) <= 1e-9
    assert _rel(a.net_loads, b.net_loads) <= 1e-9


# ---------------------------------------------------------------------------
# Gate 3 — hold-at-trim fixed point and modal damping
# ---------------------------------------------------------------------------

def test_hold_at_trim_reproduces_step53():
    """No commands: the coupled free system sits at the trim equilibrium —
    every sample = the Step 53 static balanced net load, Δξ stays 0."""
    bulk, gi = _build(rho=RHO, tend=0.2)
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
        assert np.max(np.abs(s.net_loads - ic.net_loads)) <= 1e-8 * scale
        assert float(np.max(np.abs(s.modal_coords))) <= 1e-10


def test_zeta_decays_elastic_oscillation():
    """ζ > 0 shrinks the late-time ELASTIC ringing.  Under free flight the
    elastic coordinates also track the slow (undamped-by-ζ) rigid transient,
    so the metric is the second difference of the elastic tail — a high-pass
    that isolates the modal ringing from the short-period drift."""
    def _late_osc(zeta):
        mod, _bulk, _gi = _run_modal(rho=RHO, tend=1.2, dt=0.005,
                                     tout=0.02, zeta=zeta)
        n_r = mod.basis_info["n_r"]
        xi_e = np.array([s.modal_coords[n_r:] for s in mod.steps])
        tail = xi_e[2 * len(xi_e) // 3:]
        d2 = tail[2:] - 2.0 * tail[1:-1] + tail[:-2]
        return float(np.max(np.abs(d2)))

    osc_undamped = _late_osc(0.0)
    osc_damped = _late_osc(0.05)
    assert osc_damped < 0.5 * osc_undamped


# ---------------------------------------------------------------------------
# Gate 4 — fixed-Φ mass-case gates (Step 60 MASSSET)
# ---------------------------------------------------------------------------

def _add_fuel_overlay(bulk, frac):
    """MASSSET 100: symmetric overlay CONM2s adding ``frac`` of the inboard
    wing masses (CONM2 311/411, one per side)."""
    eids = []
    for i, src in enumerate((311, 411)):
        base = bulk.conm2s[src]
        eid = 9111 + i
        bulk.conm2s[eid] = Conm2(eid=eid, gid=base.gid, cid=base.cid,
                                 m=base.m * frac)
        bulk.overlay_conm2_eids.add(eid)
        eids.append(eid)
    bulk.masssets[100] = Massset(sid=100, label="FUEL", add=eids)


def test_fixed_phi_hold_at_trim_and_closure():
    """Off-baseline MASSSET, all modes: the fixed-Φ machinery is exact —
    zero-command holds the mass case's own Step 53 trim, and an ELEV ramp
    keeps closure ≈ 0 (Φ spans the a-set, so no truncation error)."""
    bulk, gi = _build(rho=RHO, tend=0.3)
    _add_fuel_overlay(bulk, 0.10)
    sc = SubcaseControl(subcase_id=1, spc_sid=1, massset_sid=100)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1,
                                 massset_sid=100), aero)
        hold = run_maneuver_modal(bulk, sc, aero)
        _command_elev(bulk, float(ic.trim_vars["ELEV"]), *ELEV_RAMP)
        ramp = run_maneuver_modal(bulk, sc, aero)
    scale = float(np.max(np.abs(ic.net_loads)))
    for s in hold.steps:
        assert np.max(np.abs(s.net_loads - ic.net_loads)) <= 1e-8 * scale
    assert _max_closure(ramp.steps) <= 1e-8 * _load_scale(ramp.steps)
    assert ramp.massset_sid == 100


def test_fixed_phi_approximation_gate():
    """+10 % fuel overlay, truncated basis: peak-CBAR-force error of the
    fixed-Φ solution vs a re-solved-modes reference stays ≤ ~2 %."""
    NM = 8
    bulk, gi = _build(rho=RHO, nmodes=NM)
    _add_fuel_overlay(bulk, 0.10)
    sc = SubcaseControl(subcase_id=1, spc_sid=1, massset_sid=100)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1,
                                 massset_sid=100), aero)
        _command_elev(bulk, float(ic.trim_vars["ELEV"]), *ELEV_RAMP)
        fixed = run_maneuver_modal(bulk, sc, aero)
        # Re-solved reference: a cache pre-seeded with the basis built FROM
        # the overlay mass (what a per-case eigensolve would produce).
        resolved_cache = ManeuverBasisCache(bulk, aero)
        resolved_cache._cache[(sc.spc_sid, 0)] = _build_basis_overlay(
            bulk, sc, aero)
        resolved = run_maneuver_modal(bulk, sc, aero,
                                      basis_cache=resolved_cache)
    peak_fixed = float(np.max(np.abs(_bar_matrix(fixed.steps))))
    peak_resolved = float(np.max(np.abs(_bar_matrix(resolved.steps))))
    assert abs(peak_fixed - peak_resolved) / peak_resolved <= 0.02


def _build_basis_overlay(bulk, subcase, aero):
    """Basis eigensolved on the OVERLAY mass (test-only re-solve reference)."""
    from sbeam.solver.modal_basis import (
        assemble_aset_operators, build_maneuver_basis)
    ops = assemble_aset_operators(bulk, subcase, aero)   # massset kept
    return build_maneuver_basis(bulk, ops, None, nmodes=0)


def test_cg_shift_warning_fires_above_5pct_cref():
    """D4: > 5 % c_ref CG shift warns; a small overlay does not."""
    for frac, expect in ((2.0, True), (0.01, False)):
        bulk, gi = _build(rho=None, tend=0.05, dt=0.01, tout=0.05)
        _add_fuel_overlay(bulk, frac)
        sc = SubcaseControl(subcase_id=1, spc_sid=1, massset_sid=100)
        sc.mloads_sid = 1
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            aero = build_aero_model(bulk, grid_index=gi)
            run_maneuver_modal(bulk, sc, aero)
        fired = any("fixed-Phi mean axis" in str(w.message) for w in rec)
        assert fired == expect, f"frac={frac}"


# ---------------------------------------------------------------------------
# Gate 5 — solver selection (D1)
# ---------------------------------------------------------------------------

def test_selects_modal_truth_table():
    ml = Mloads(sid=1, mldtrim=1, mldtime=1)
    assert not ml.selects_modal
    assert replace(ml, nmodes=4).selects_modal
    assert replace(ml, method=900).selects_modal
    assert replace(ml, method=-1).selects_modal       # all-defaults sentinel
    assert replace(ml, zeta=0.02).selects_modal


def test_parser_method_sentinel():
    """METHOD=-1 parses; METHOD=-2 rejects; the all-zeros card stays legacy."""
    from sbeam.parser.bdf_reader import _handle_mloads
    from sbeam.model.bulk_data import BulkData

    bulk = BulkData()
    _handle_mloads(["MLOADS", "1", "10", "20", "0", "0", "0", "-1"], bulk)
    assert bulk.mloads[1].method == -1
    assert bulk.mloads[1].selects_modal
    with pytest.raises(ValueError, match="METHOD"):
        _handle_mloads(["MLOADS", "2", "10", "20", "0", "0", "0", "-2"], bulk)
    _handle_mloads(["MLOADS", "3", "10", "20"], bulk)
    assert not bulk.mloads[3].selects_modal


def test_direct_solver_no_longer_warns_on_all_zeros():
    """The increment-1 ignored-warning is retired (behavior change, CHANGELOG)."""
    bulk, gi = _build(rho=None, tend=0.05, dt=0.01, tout=0.05, method=0)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        aero = build_aero_model(bulk, grid_index=gi)
        run_maneuver_qs(bulk, sc, aero)
    assert not any("NMODES" in str(w.message) for w in rec)


# ---------------------------------------------------------------------------
# f06 basis-summary block
# ---------------------------------------------------------------------------

def test_f06_basis_summary_line_modal_only():
    from sbeam.parser.case_control import CaseControl
    from sbeam.results.f06_writer import build_f06_sol144_maneuver_text

    bulk, gi = _build(rho=RHO, tend=0.05, dt=0.01, tout=0.05)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    cc = CaseControl(sol=144)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        mod = run_maneuver_modal(bulk, sc, aero)
        bulk.mloads[1].method = 0
        ref = run_maneuver_qs(bulk, sc, aero)
    txt_mod = build_f06_sol144_maneuver_text(cc, bulk, mod, 1)
    txt_ref = build_f06_sol144_maneuver_text(cc, bulk, ref, 1)
    assert "MODAL SOLVER: RIGID MODES" in txt_mod
    assert "FREE FLIGHT: V =" in txt_mod
    assert "MODAL SOLVER" not in txt_ref
    assert "FREE FLIGHT" not in txt_ref
