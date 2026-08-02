"""V-SEC6 — MONSECT section cuts across MASSSET payload cases (Step 60 + Phase 2).

`sample/cessna210_flagship_massset.bdf` runs one TRIM at three payload
conditions whose difference is **wing fuel** (CONM2 overlays on the wing EA
grids 11/12/111/112).  A right-wing section cut therefore shows the effect a
loads engineer actually cares about, and it needs no extra cards: the inertia
column follows the active mass case automatically.

The gate is that classic effect — **wing-fuel bending relief**.  Aero root
bending grows steeply with weight, the wing-fuel inertia relief grows with it
and opposes it, so the *net* root bending grows far more slowly than the airload
alone.  A cut that silently ignored the mass case, or got the inertia sign
wrong, could not reproduce that ordering.
"""
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.section_cuts import labelled
from sbeam.solver.sol144 import AeroCache, run_sol144_trim

BDF_PATH = (Path(__file__).parent.parent.parent / "sample"
            / "cessna210_flagship_massset.bdf")

# Subcase -> mass case, lightest first (the deck documents these weights).
CASES = [(1, "FERRY"), (2, "CRUISE"), (3, "MTOW")]


@pytest.fixture(scope="module")
def sweep():
    cc, bulk = parse_bdf(str(BDF_PATH))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        cache = AeroCache(bulk, gi, seed=aero)
        results = {sc.subcase_id: run_sol144_trim(bulk, sc, aero, aero_cache=cache)
                   for sc in cc.subcases}
    return results, bulk


def _root(result, name="SECRW"):
    """(labelled totals, aero, inertia) at the inboard-most station."""
    sc = result.section_loads[name]
    st = sc.stations[0]
    return (labelled(st.totals, sc.comp_map), labelled(st.aero, sc.comp_map),
            labelled(st.inertia, sc.comp_map))


def test_cuts_present_for_every_mass_case(sweep):
    results, _bulk = sweep
    for sid, label in CASES:
        r = results[sid]
        assert r.massset_label == label
        assert set(r.section_loads) == {"SECRW", "SECRWA"}
        assert [s.n_members for s in r.section_loads["SECRW"].stations] == [2, 2, 1, 0]


def test_vsec6_wing_fuel_bending_relief(sweep):
    """Aero bending rises with weight; wing-fuel inertia opposes it; net rises less."""
    results, _bulk = sweep
    aero_mx, inert_mx, net_mx, mass = [], [], [], []
    for sid, _label in CASES:
        tot, aer, inr = _root(results[sid])
        aero_mx.append(aer[4])          # Mx = bending about the chordwise axis
        inert_mx.append(inr[4])
        net_mx.append(tot[4])
        mass.append(results[sid].massset_mass)

    assert mass == sorted(mass)                     # cases really are ordered by weight
    assert aero_mx == sorted(aero_mx)               # heavier ⇒ more airload
    # Inertia relief opposes the airload and grows with the wing fuel.
    assert all(v < 0 for v in inert_mx)
    assert [abs(v) for v in inert_mx] == sorted(abs(v) for v in inert_mx)
    # The relief is the point: net bending grows far more slowly than the airload.
    assert (net_mx[-1] - net_mx[0]) < 0.5 * (aero_mx[-1] - aero_mx[0])


def test_inertia_column_is_the_only_mass_case_difference(sweep):
    """A mass case enters the cut solely through the inertia column's magnitude.

    Both aero and inertia change between cases (a heavier airplane trims at a
    higher alpha), so the invariant is structural, not numeric: the contributions
    decompose exactly, and the reaction column stays zero on a cut that spans no
    constrained grid.
    """
    results, _bulk = sweep
    for sid, _label in CASES:
        sc = results[sid].section_loads["SECRW"]
        for st in sc.stations:
            assert st.totals == pytest.approx(st.aero + st.inertia + st.reaction,
                                              abs=1e-9)
            assert np.allclose(st.reaction, 0.0)


def test_aero_only_cut_carries_no_inertia(sweep):
    """An AELIST-type MONSECT is aero-only — the mass case cannot move it.

    Its totals differ from the structural cut's aero column near a station:
    the box partition and the splined-grid partition split differently at the
    cut plane.  They coincide only over a whole collection (V-SEC7).
    """
    results, _bulk = sweep
    for sid, _label in CASES:
        sc = results[sid].section_loads["SECRWA"]
        assert sc.listtype == "AELIST"
        for st in sc.stations:
            assert np.allclose(st.inertia, 0.0)
            assert np.allclose(st.reaction, 0.0)
            assert st.totals == pytest.approx(st.aero, abs=1e-12)


def test_tip_station_is_zero_in_every_case(sweep):
    """V-SEC4 across mass cases — station 6.50 is outboard of the tip grid."""
    results, _bulk = sweep
    for sid, _label in CASES:
        for name in ("SECRW", "SECRWA"):
            st = results[sid].section_loads[name].stations[-1]
            assert st.n_members == 0
            assert np.all(st.totals == 0.0)
