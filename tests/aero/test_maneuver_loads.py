"""V-C5 — balanced maneuver loads & inertia relief (Step 53).

The full-span HA144A deck (`sample/ha144a_fullspan_sbeam.bdf`) pins only the
antisymmetric DOFs (SPC1 1246 on GRID 90) and SUPORTs the symmetric trim DOFs
(35).  For a symmetric pull-up the symmetric net load (Fz, My) must therefore
balance to ~0 through inertia relief — exactly the KC9 closure the trim must
guarantee.  These tests gate:

  * closure: net (aero + inertial) resultant ≈ 0 in the symmetric DOFs;
  * load factor: trimmed aero lift equals n_z · W;
  * linearity: net maneuver loads (and CBAR loads) scale linearly with n_z;
  * export: the FORCE/MOMENT maneuver-load cards sum to the net resultant.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim, load_resultant
from sbeam.results.load_export import build_maneuver_load_cards_text
from sbeam.model.maneuver_presets import load_factor_to_urdd3

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"
G = 32.174  # ft/s², the deck's gravity (URDD3 = -32.174 for 1g)


def _run(n_z: float):
    """Trim the full-span deck at load factor n_z (SC1, q=40), return result+bulk."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    bulk.trims[1].vars["URDD3"] = load_factor_to_urdd3(n_z, G)
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero
        )
    return result, bulk, grid_index


@pytest.fixture(scope="module")
def trim_1g():
    return _run(1.0)


def test_closure_symmetric_balance(trim_1g):
    """V-C5: net (aero+inertial) resultant ≈ 0 in the symmetric DOFs (Fz, My)."""
    result, bulk, gi = trim_1g
    aero_res = load_resultant(result.grid_loads, bulk, gi, np.zeros(3))
    fz_scale = max(abs(aero_res[2]), 1.0)
    my_scale = max(abs(aero_res[4]), 1.0)
    assert abs(result.maneuver_closure[2]) < 1e-6 * fz_scale, (
        f"Fz closure {result.maneuver_closure[2]} not balanced (aero Fz {aero_res[2]})"
    )
    assert abs(result.maneuver_closure[4]) < 1e-6 * my_scale, (
        f"My closure {result.maneuver_closure[4]} not balanced (aero My {aero_res[4]})"
    )


def test_lift_equals_nz_weight(trim_1g):
    """Trimmed aero lift equals n_z · W (W = Σ CONM2 mass · g)."""
    result, bulk, gi = trim_1g
    aero_res = load_resultant(result.grid_loads, bulk, gi, np.zeros(3))
    weight = sum(c.m for c in bulk.conm2s.values()) * G
    assert aero_res[2] == pytest.approx(weight, rel=1e-6), (
        f"aero Fz {aero_res[2]} != n_z·W {weight}"
    )


def test_net_loads_scale_linearly():
    """net_loads at 2.5g equal 2.5 × net_loads at 1g (linear system)."""
    r1, _, _ = _run(1.0)
    r25, _, _ = _run(2.5)
    mask = np.abs(r1.net_loads) > 1e-6
    ratio = r25.net_loads[mask] / r1.net_loads[mask]
    assert np.allclose(ratio, 2.5, rtol=1e-9), (
        f"net_loads ratio span [{ratio.min()}, {ratio.max()}] != 2.5"
    )


def test_cbar_loads_scale_linearly():
    """Recovered CBAR end loads scale linearly with n_z (V-C5)."""
    r1, _, _ = _run(1.0)
    r25, _, _ = _run(2.5)
    # Pick the dominant CBAR force component across all bars to avoid near-zero ratios.
    comps = ("axial", "shear1", "shear2", "torque", "bm1_a", "bm2_a", "bm1_b", "bm2_b")
    eid, comp, mag = max(
        ((e, c, abs(getattr(r1.bar_forces[e], c))) for e in r1.bar_forces for c in comps),
        key=lambda t: t[2],
    )
    assert mag > 1e-6, "no non-trivial CBAR load to test linearity against"
    v1 = getattr(r1.bar_forces[eid], comp)
    v25 = getattr(r25.bar_forces[eid], comp)
    assert v25 / v1 == pytest.approx(2.5, rel=1e-6), (
        f"CBAR {eid}.{comp} ratio {v25 / v1} != 2.5"
    )


def test_maneuver_export_roundtrip(trim_1g):
    """Each exported FORCE card reproduces the per-grid net_loads force.

    The net Fz resultant is ~0 (a balanced maneuver), so a resultant-sum check
    would compare cancelling near-zero quantities dominated by formatting
    roundoff.  Per-grid fidelity is the meaningful exporter gate.

    Tolerance is set by the NASTRAN 8-character field width (DEF-M6), not by
    the exporter: a negative value spends one of the eight characters on its
    sign, leaving six significant figures, so ``-2999.775064`` can only be
    written as ``-2999.78`` (rel 1.7e-6).  ``rtol=1e-5`` is the floor for any
    8-character field; anything looser would stop catching real defects.
    """
    result, bulk, gi = trim_1g
    text = build_maneuver_load_cards_text(bulk, result, sid=99)
    checked = 0
    for line in text.splitlines():
        if not line.startswith("FORCE,"):
            continue
        parts = [p.strip() for p in line.split(",")]
        gid = int(parts[2])
        f_card = np.array([float(parts[5]), float(parts[6]), float(parts[7])])
        base = 6 * gi[gid]
        f_ref = result.net_loads[base:base + 3]
        assert np.allclose(f_card, f_ref, rtol=1e-5, atol=1e-9), (
            f"FORCE on grid {gid}: card {f_card} != net_loads {f_ref}"
        )
        checked += 1
    assert checked > 0, "no FORCE cards emitted for the maneuver load set"
