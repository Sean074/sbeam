"""Step 62 — modal transient maneuver solver: acceptance gates.

Fixture family: the full-span HA144A deck (same model the maneuver_qs and
modal-basis suites use), in two mass configurations:

  * ``rho`` variant — CBAR distributed mass added (MAT1 rho > 0) so every
    a-set DOF carries mass and the basis eigensolve condenses nothing.  On
    this deck the full-basis modal solution is an exact change of coordinates
    of the direct l-set solver: the identity gate asserts ≤ 1e−6 relative
    (measured ~1e−14) on every recovered quantity.
  * CONM2-only variant — 18 massless rotational DOFs are condensed out of the
    basis, so even "all modes" cannot span the l-set; mode-acceleration
    recovers the massless static content through K_eff⁻¹ and the residual is
    the (second-order) aero coupling to it: the near-identity gate documents
    the measured order (~1e−5 net loads).

Gates (backlog Step 62):
  full-basis identity; NMODES convergence (monotone peak-bar-force error
  decay); mode-acceleration ≥ 10× better than mode-displacement; hold-at-trim
  = Step 53; ζ > 0 decays energy; fixed-Φ exactness (MASSSET, all modes);
  fixed-Φ approximation (+10 % fuel, truncated, vs a re-solved-modes
  reference); dispatch/selection; job-level basis cache builds Φ once;
  equilibrium start exact under truncation; D4 CG-shift warning.
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

# CBAR density for the fully-mass-covered variant: consistent-mass rotary
# terms put mass on every free DOF, so the basis condenses nothing.
RHO = 0.05


def _build(n_z=2.0, rho=None, elev_tab=None, tend=0.3, dt=0.01, tout=0.05,
           nmodes=0, method=-1, zeta=0.0):
    """Parse the deck and register the MLOADS card set programmatically."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    bulk.trims[1].vars["URDD3"] = load_factor_to_urdd3(n_z, G)
    if rho:
        for mat in bulk.mat1s.values():
            mat.rho = rho
    gi = build_grid_index(bulk)
    bulk.mldtrims[1] = Mldtrim(sid=1, trim_sid=1)
    bulk.mldtimes[1] = Mldtime(sid=1, t0=0.0, tend=tend, dt=dt, tout=tout)
    commands = []
    if elev_tab is not None:
        bulk.tabled1s[7] = Tabled1(tid=7, xs=list(elev_tab[0]), ys=list(elev_tab[1]))
        commands = [("ELEV", 7)]
        bulk.mldcomds[1] = Mldcomd(sid=1, commands=commands)
    bulk.mloads[1] = Mloads(
        sid=1, mldtrim=1, mldtime=1, mldcomd=1 if commands else 0,
        nmodes=nmodes, method=method, zeta=zeta)
    return bulk, gi


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


def _run_pair(rho=None, **kw):
    """Direct-solver reference and modal solution on the same deck."""
    bulk, gi = _build(rho=rho, elev_tab=ELEV_RAMP, **kw)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ref = run_maneuver_qs(bulk, sc, aero)
        mod = run_maneuver_modal(bulk, sc, aero)
    return mod, ref


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


# ---------------------------------------------------------------------------
# Gate 1 — full-basis identity (exact on the fully-mass-covered deck)
# ---------------------------------------------------------------------------

def test_full_basis_identity_rho_deck():
    """All modes + distributed mass: every quantity matches the direct solver.

    The re-based modal system is an exact change of coordinates of the l-set
    ODE when nothing is condensed, so this holds to round-off (≤1e−6 asserted,
    ~1e−14 measured).
    """
    mod, ref = _run_pair(rho=RHO)
    assert mod.basis_info["n_massless"] == 0
    assert len(mod.steps) == len(ref.steps)
    for a, b in zip(mod.steps, ref.steps):
        assert _rel(a.displacements, b.displacements) <= 1e-6
        assert _rel(a.net_loads, b.net_loads) <= 1e-6
        assert _rel(a.grid_loads, b.grid_loads) <= 1e-6
        assert _rel(a.inertial_loads, b.inertial_loads) <= 1e-6
        assert abs(a.Fz_aero - b.Fz_aero) <= 1e-6 * max(1.0, abs(b.Fz_aero))
        assert abs(a.My_aero - b.My_aero) <= 1e-6 * max(1.0, abs(b.My_aero))
        assert a.trim_vars == b.trim_vars
    assert _rel(_bar_matrix(mod.steps), _bar_matrix(ref.steps)) <= 1e-6


def test_near_identity_conm2_only_deck():
    """CONM2-only deck: 18 condensed DOFs leave a documented small residual.

    The mass-carrying dynamics match and mode-acceleration recovers the
    massless static content; the remaining aero-coupling residual is ~1e−5 on
    net loads (asserted with margin at 1e−4).
    """
    mod, ref = _run_pair(rho=None)
    assert mod.basis_info["n_massless"] == 18
    for a, b in zip(mod.steps, ref.steps):
        assert _rel(a.net_loads, b.net_loads) <= 1e-4
        assert _rel(a.displacements, b.displacements) <= 5e-3


# ---------------------------------------------------------------------------
# Gate 2 — NMODES convergence + mode-acceleration superiority
# ---------------------------------------------------------------------------

def _peak_bar_err(mod_steps, ref_steps):
    ref = _bar_matrix(ref_steps)
    return float(np.max(np.abs(_bar_matrix(mod_steps) - ref))
                 / np.max(np.abs(ref)))


@pytest.fixture(scope="module")
def convergence_runs():
    """Modal runs at NMODES ∈ {2, 4, 8, all} + the direct reference (rho deck,
    smooth command — see ELEV_SMOOTH)."""
    bulk, gi = _build(rho=RHO, elev_tab=ELEV_SMOOTH)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ref = run_maneuver_qs(bulk, sc, aero)
        cache = ManeuverBasisCache(bulk, aero)
        runs = {}
        for nm in (2, 4, 8, 0):
            bulk.mloads[1].nmodes = nm
            runs[nm] = run_maneuver_modal(bulk, sc, aero, basis_cache=cache)
        bulk.mloads[1].nmodes = 4
        runs["md4"] = run_maneuver_modal(
            bulk, sc, aero, basis_cache=cache, recovery="displacement")
    return runs, ref, cache


def test_convergence_monotone_peak_bar_force(convergence_runs):
    """Peak-bar-force error decays monotonically with retained modes."""
    runs, ref, _cache = convergence_runs
    errs = {nm: _peak_bar_err(runs[nm].steps, ref.steps) for nm in (2, 4, 8, 0)}
    assert errs[2] >= errs[4] >= errs[8] >= errs[0]
    assert errs[0] <= 1e-6                       # full basis = identity gate
    assert errs[2] > 1e-6                        # truncation is actually visible


def test_mode_acceleration_beats_mode_displacement(convergence_runs):
    """≥10× on truncated (NMODES=4) bar forces."""
    runs, ref, _cache = convergence_runs
    err_ma = _peak_bar_err(runs[4].steps, ref.steps)
    err_md = _peak_bar_err(runs["md4"].steps, ref.steps)
    assert err_md >= 10.0 * err_ma


def test_basis_cache_builds_once(convergence_runs):
    """D3: five modal runs, one eigensolve."""
    _runs, _ref, cache = convergence_runs
    assert cache.n_builds == 1


def test_truncated_equilibrium_start_is_exact(convergence_runs):
    """The t0 sample equals the direct solver's static start even at NMODES=2
    (mode-acceleration at equilibrium is K_eff⁻¹·F, truncation-independent)."""
    runs, ref, _cache = convergence_runs
    a, b = runs[2].steps[0], ref.steps[0]
    assert _rel(a.displacements, b.displacements) <= 1e-9
    assert _rel(a.net_loads, b.net_loads) <= 1e-9


# ---------------------------------------------------------------------------
# Gate 3 — hold-at-trim fixed point and modal damping
# ---------------------------------------------------------------------------

def test_hold_at_trim_reproduces_step53():
    """No commands: every modal sample = the Step 53 static balanced net load."""
    bulk, gi = _build(rho=RHO, elev_tab=None, tend=0.2)
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


def test_zeta_decays_elastic_oscillation():
    """ζ > 0 shrinks the late-time oscillation about the settled state."""
    def _late_osc(zeta):
        bulk, gi = _build(rho=RHO, elev_tab=ELEV_RAMP, tend=1.2, dt=0.005,
                          tout=0.02, zeta=zeta)
        sc = SubcaseControl(subcase_id=1, spc_sid=1)
        sc.mloads_sid = 1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            aero = build_aero_model(bulk, grid_index=gi)
            mod = run_maneuver_modal(bulk, sc, aero)
        xi = np.array([s.modal_coords for s in mod.steps])
        tail = xi[2 * len(xi) // 3:]
        return float(np.max(np.abs(tail - tail[-1])))

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


def test_fixed_phi_exactness_gate():
    """Off-baseline MASSSET, all modes: matches the direct solver on the same
    mass case ≤ 1e−6 — the fixed-Φ error is pure truncation."""
    bulk, gi = _build(rho=RHO, elev_tab=ELEV_RAMP)
    _add_fuel_overlay(bulk, 0.10)
    sc = SubcaseControl(subcase_id=1, spc_sid=1, massset_sid=100)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ref = run_maneuver_qs(bulk, sc, aero)
        mod = run_maneuver_modal(bulk, sc, aero)
    for a, b in zip(mod.steps, ref.steps):
        assert _rel(a.displacements, b.displacements) <= 1e-6
        assert _rel(a.net_loads, b.net_loads) <= 1e-6
    assert _rel(_bar_matrix(mod.steps), _bar_matrix(ref.steps)) <= 1e-6
    assert mod.massset_sid == 100


def test_fixed_phi_approximation_gate():
    """+10 % fuel overlay, truncated basis: peak-CBAR-force error of the
    fixed-Φ solution vs a re-solved-modes reference stays ≤ ~2 %."""
    NM = 8
    bulk, gi = _build(rho=RHO, elev_tab=ELEV_RAMP, nmodes=NM)
    _add_fuel_overlay(bulk, 0.10)
    sc = SubcaseControl(subcase_id=1, spc_sid=1, massset_sid=100)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
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
        bulk, gi = _build(rho=None, elev_tab=None, tend=0.05, dt=0.01, tout=0.05)
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
    bulk, gi = _build(rho=None, elev_tab=None, tend=0.05, dt=0.01, tout=0.05,
                      method=0)
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

    bulk, gi = _build(rho=RHO, elev_tab=None, tend=0.05, dt=0.01, tout=0.05)
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
    assert "MODAL SOLVER" not in txt_ref
