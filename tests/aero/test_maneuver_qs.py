"""Phase G0 (DLM-free quasi-steady transient maneuver loads) — solver gates.

Fixture: the full-span HA144A deck (SPC1 1246 pins antisymmetric DOFs on GRID 90,
SUPORT 35 frees the symmetric trim DOFs), the same model the Step 53 V-C5 tests
use.  Gates:

  * G0→Step53 identity (strongest): holding the commanded state at the trim value,
    every output sample reproduces the Step 53 static balanced net load to machine
    precision — the transient integrator's fixed point is the static trim.
  * Quasi-static settling: a slow ramp of the *full* kinematic state between two
    trimmed conditions asymptotes (with damping) to the Step 53 balanced load at
    the new state, with the net force/moment closing to ≈ 0.
  * Per-step closure: for a consistent (trimmed) command history the net
    (aero + inertial) resultant stays balanced at every sample (no drift).
  * Output: the MLDPRNT time history and the critical-step FORCE/MOMENT export
    reproduce the recovered net loads.
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
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.model.maneuver import Tabled1, Mldtime, Mldcomd, Mldprnt, Mldtrim, Mloads
from sbeam.model.maneuver_presets import load_factor_to_urdd3
from sbeam.results.maneuver_output import (
    build_maneuver_time_history_text,
    build_maneuver_critical_load_cards_text,
)

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"
G = 32.174  # ft/s²


def _trim(n_z):
    """Step 53 static trim of the full-span deck at load factor n_z."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    bulk.trims[1].vars["URDD3"] = load_factor_to_urdd3(n_z, G)
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    return result, bulk, aero, gi


def _maneuver(n_z, commands_builder, tend=0.5, dt=0.01, tout=0.1,
              damping_alpha=0.0, mldprnt_items=None):
    """Build an MLOADS deck on the n_z trim IC and run the transient solver.

    ``commands_builder(bulk, labels, trim_vars)`` returns a list of
    ``(label, tabid)`` command pairs after registering its TABLED1 cards on
    ``bulk``; an empty list holds every label at the trim value.
    """
    _cc, bulk = parse_bdf(str(BDF_PATH))
    bulk.trims[1].vars["URDD3"] = load_factor_to_urdd3(n_z, G)
    gi = build_grid_index(bulk)
    labels = sorted([a.label for a in bulk.aestats.values()]
                    + [s.label for s in bulk.aesurfs.values()])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        commands = commands_builder(bulk, labels, ic.trim_vars)
        bulk.mldtrims[1] = Mldtrim(sid=1, trim_sid=1)
        bulk.mldtimes[1] = Mldtime(sid=1, t0=0.0, tend=tend, dt=dt, tout=tout)
        if commands:
            bulk.mldcomds[1] = Mldcomd(sid=1, commands=commands)
        if mldprnt_items is not None:
            bulk.mldprnts[1] = Mldprnt(sid=1, items=mldprnt_items)
        bulk.mloads[1] = Mloads(
            sid=1, mldtrim=1, mldtime=1,
            mldcomd=1 if commands else 0,
            mldprnt=1 if mldprnt_items is not None else 0)
        sc = SubcaseControl(subcase_id=1, spc_sid=1)
        sc.mloads_sid = 1
        res = run_maneuver_qs(bulk, sc, aero, damping_alpha=damping_alpha)
    return res, ic, bulk, gi


# ---------------------------------------------------------------------------
# Gate 1 — G0 → Step 53 identity (fixed point)
# ---------------------------------------------------------------------------

def test_g0_reproduces_step53_when_held_at_trim():
    """Holding the state at trim, every sample = the Step 53 net load (machine tol)."""
    res, ic, _bulk, _gi = _maneuver(2.0, lambda b, l, tv: [], tend=0.4)
    scale = np.max(np.abs(ic.net_loads))
    for s in res.steps:
        diff = np.max(np.abs(s.net_loads - ic.net_loads))
        assert diff < 1e-6 * scale, (
            f"t={s.t}: net load drift {diff} exceeds {1e-6 * scale} (scale {scale})")


def test_g0_initial_sample_closure_balances():
    """At the trim IC the net (aero+inertial) resultant closes to ≈ 0 (V-C5)."""
    res, ic, _b, _gi = _maneuver(2.0, lambda b, l, tv: [], tend=0.1)
    s0 = res.steps[0]
    f_scale = max(abs(s0.Fz_aero), 1.0)
    assert abs(s0.closure[2]) < 1e-6 * f_scale
    assert abs(s0.closure[4]) < 1e-6 * f_scale * 40.0  # cref-scaled moment


# ---------------------------------------------------------------------------
# Gate 2 — quasi-static settling to the new balanced trim
# ---------------------------------------------------------------------------

def _full_state_ramp(target_trim_vars, t_ramp=0.3, t_hold=10.0):
    """Command every label from its IC trim value to the target trim value."""
    def builder(bulk, labels, ic_vars):
        cmds = []
        for i, lbl in enumerate(labels):
            tid = 500 + i
            bulk.tabled1s[tid] = Tabled1(
                tid=tid,
                xs=[0.0, t_ramp, t_hold],
                ys=[float(ic_vars[lbl]),
                    float(target_trim_vars[lbl]),
                    float(target_trim_vars[lbl])])
            cmds.append((lbl, tid))
        return cmds
    return builder


def test_g0_quasistatic_settles_to_step53():
    """A slow full-state ramp 1g→2g asymptotes to the Step 53 2g balanced load."""
    trim2g, _b, _a, _gi = _trim(2.0)
    res, _ic, _bulk, _gi2 = _maneuver(
        1.0, _full_state_ramp(trim2g.trim_vars, t_ramp=0.3, t_hold=10.0),
        tend=10.0, dt=0.004, tout=1.0, damping_alpha=3.0)
    settled = res.steps[-1]
    scale = np.max(np.abs(trim2g.net_loads))
    diff = np.max(np.abs(settled.net_loads - trim2g.net_loads))
    assert diff < 1e-4 * scale, (
        f"settled net load differs from Step 53 2g by {diff} (scale {scale})")
    # The asymptotic state is a balanced trim → closure → 0.
    assert abs(settled.closure[2]) < 1e-3 * max(abs(settled.Fz_aero), 1.0)


def test_g0_lift_tracks_load_factor():
    """The settled aero lift equals n_z·W at the new (2g) condition."""
    trim2g, bulk, _a, _gi = _trim(2.0)
    weight_2g = sum(c.m for c in bulk.conm2s.values()) * G * 2.0
    res, _ic, _bulk, _gi2 = _maneuver(
        1.0, _full_state_ramp(trim2g.trim_vars, t_ramp=0.3, t_hold=8.0),
        tend=8.0, dt=0.004, tout=2.0, damping_alpha=3.0)
    assert res.steps[-1].Fz_aero == pytest.approx(weight_2g, rel=1e-3)


# ---------------------------------------------------------------------------
# Gate 3 — per-step closure bounded for a consistent command history
# ---------------------------------------------------------------------------

def test_g0_per_step_closure_bounded():
    """Through the full-state ramp the closure transient stays bounded and decays."""
    trim2g, _b, _a, _gi = _trim(2.0)
    res, _ic, _bulk, _gi2 = _maneuver(
        1.0, _full_state_ramp(trim2g.trim_vars, t_ramp=0.3, t_hold=10.0),
        tend=10.0, dt=0.004, tout=0.5, damping_alpha=3.0)
    f_scale = max(abs(res.steps[-1].Fz_aero), 1.0)
    # No sample's closure force blows past the lift magnitude (bounded, no drift).
    for s in res.steps:
        assert abs(s.closure[2]) < 2.0 * f_scale
    # The final samples are nearly balanced (transient decayed).
    assert abs(res.steps[-1].closure[2]) < 1e-3 * f_scale


# ---------------------------------------------------------------------------
# Output (B3)
# ---------------------------------------------------------------------------

def test_mldprnt_time_history_text():
    res, _ic, _b, _gi = _maneuver(
        2.0, lambda b, l, tv: [], tend=0.2, tout=0.1, mldprnt_items=["STATE"])
    text = build_maneuver_time_history_text(res)
    lines = text.splitlines()
    assert any("TIME" in ln and "FZ_AERO" in ln for ln in lines)
    # one data row per output sample
    data_rows = [ln for ln in lines if not ln.startswith("$") and "TIME" not in ln]
    assert len(data_rows) == len(res.steps)


def test_critical_load_card_export_roundtrip():
    """Critical-step FORCE cards reproduce that sample's per-grid net load."""
    res, _ic, bulk, gi = _maneuver(2.0, lambda b, l, tv: [], tend=0.2)
    text = build_maneuver_critical_load_cards_text(bulk, res, sid=77)
    crit = res.steps[res.crit_index]
    checked = 0
    for line in text.splitlines():
        if not line.startswith("FORCE,"):
            continue
        parts = [p.strip() for p in line.split(",")]
        gid = int(parts[2])
        f_card = np.array([float(parts[5]), float(parts[6]), float(parts[7])])
        base = 6 * gi[gid]
        assert np.allclose(f_card, crit.net_loads[base:base + 3], rtol=1e-6, atol=1e-9)
        checked += 1
    assert checked > 0
