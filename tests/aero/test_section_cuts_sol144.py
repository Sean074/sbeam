"""V-SEC solver gates for MONSECT section cuts on the full-span HA144A deck.

The deck carries one MONSECT (``SECRW``, right-wing EA, stations 8/10/12/20 in
the SPLINE2 CID 2 frame).  The gates here tie the cut to physics computed a
different way:

  * **V-SEC2** — free-body equilibrium: the outboard resultant equals the CBAR
    internal force recovered from ``K·u``.  Independent of the summation the cut
    performs, so it pins the plane test, the reference point, the moment
    transfer and the on-plane convention all at once.
  * **V-SEC3** — a cut inboard of everything reproduces the whole-aircraft
    MONPNT3, i.e. Phase 2 degenerates to Phase 1.
  * **V-SEC4** — a station outboard of every member returns exactly zero.
  * **V-SEC5** — that whole-aircraft cut's net load is the maneuver closure (≈0).
"""
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.coord_transform import get_transform
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.stiffness import transform_matrix
from sbeam.model.aero import Monsect
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.results.section_cuts import component_names, labelled
from sbeam.solver.sol101 import _element_local_forces
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


def _run(bulk, aero):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)


@pytest.fixture(scope="module")
def trim():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
    return _run(bulk, aero), bulk, gi, aero


def _to_basic(cid, v6, bulk):
    _P, R = get_transform(cid, bulk.cord2rs)
    return R @ v6[:3], R @ v6[3:]


def test_section_cut_present_and_labelled(trim):
    result, _bulk, _gi, _aero = trim
    sc = result.section_loads["SECRW"]
    assert sc.listtype == "SET1" and sc.cid == 2 and sc.axis == 2 and sc.side == "POS"
    assert component_names(sc.axis) == ("N", "Vx", "Vz", "Mt", "Mx", "Mz")
    assert [s.station for s in sc.stations] == [8.0, 10.0, 12.0, 20.0]
    assert sc.half_model is False       # full-span deck: never parity-scaled


@pytest.mark.parametrize("station", [8.0, 10.0])
def test_vsec2_free_body_equals_cbar_internal_force(trim, station):
    """V-SEC2 — the load-bearing gate.

    At a station that crosses only CBAR 120, the resultant of everything
    outboard (summed from the applied aero + inertial grid loads) must equal the
    element's end-B internal force from ``K·u``, transferred to the cut
    reference.  Two independent routes to the same number.
    """
    result, bulk, gi, _aero = trim
    sc = result.section_loads["SECRW"]
    st = next(s for s in sc.stations if s.station == station)
    cut_F, cut_M = _to_basic(sc.cid, st.totals, bulk)

    cbar = bulk.cbars[120]
    f_local = _element_local_forces(cbar, bulk.grids, bulk.pbars, bulk.mat1s,
                                    result.displacements, gi)
    R3 = transform_matrix(cbar, bulk.grids)[:3, :3]     # rows = local axes in basic
    fb = R3.T @ f_local[6:9]
    mb = R3.T @ f_local[9:12]
    gb = bulk.grids[cbar.gb]
    rb = np.array([gb.x, gb.y, gb.z])
    bar_M = mb + np.cross(rb - st.ref, fb)

    scale = max(np.linalg.norm(fb), 1.0)
    assert cut_F == pytest.approx(fb, abs=1e-8 * scale)
    m_scale = max(np.linalg.norm(bar_M), 1.0)
    assert cut_M == pytest.approx(bar_M, abs=1e-8 * m_scale)


def test_vsec4_station_outboard_of_everything_is_zero(trim):
    """V-SEC4 — station 20 is outboard of the tip stringers (18.57): exact zero."""
    result, _bulk, _gi, _aero = trim
    st = next(s for s in result.section_loads["SECRW"].stations if s.station == 20.0)
    assert st.n_members == 0
    assert np.all(st.totals == 0.0)


def test_cut_load_decreases_outboard(trim):
    """Shear and bending must fall monotonically towards the tip on a 1g trim."""
    result, _bulk, _gi, _aero = trim
    sc = result.section_loads["SECRW"]
    vz = [labelled(s.totals, sc.comp_map)[2] for s in sc.stations]
    mx = [labelled(s.totals, sc.comp_map)[4] for s in sc.stations]
    assert vz[0] > 0.0 and mx[0] > 0.0          # right wing carries up-load
    assert all(a >= b for a, b in zip(vz, vz[1:]))
    assert all(a >= b for a, b in zip(mx, mx[1:]))


@pytest.fixture(scope="module")
def whole_aircraft_cut(trim):
    """A cut inboard of the entire model over the whole-aircraft AECOMP.

    The CID origin is parked far inboard (y = −1000) so a single POS cut at
    station 0 captures every grid, including the centreline ones a cut at y = 0
    would split.
    """
    _result, bulk, _gi, aero = trim
    extra = parse_bdf_lines([
        "CORD2R, 901, 0, 15.0, -1000.0, 0.0, 15.0, -1000.0, 1.0",
        "+, 16.0, -1000.0, 0.0",
    ])
    bulk.cord2rs.update(extra.cord2rs)
    saved = dict(bulk.monsects)
    bulk.monsects.clear()
    bulk.monsects["SECALL"] = Monsect(
        name="SECALL", label="WHOLE AIRCRAFT", comp="ALLGRID", cid=901,
        axis=2, side="POS", stations=[0.0],
    )
    result = _run(bulk, aero)
    bulk.monsects.clear()
    bulk.monsects.update(saved)
    return result, bulk


def parse_bdf_lines(lines):
    from sbeam.parser.bdf_reader import parse_bulk_data
    return parse_bulk_data(lines)


def test_vsec3_whole_aircraft_cut_equals_monpnt3(whole_aircraft_cut):
    """V-SEC3 — Phase 2 degenerates to Phase 1 over the same collection.

    The monitor reports about its own reference point, so its resultant is
    transferred to the cut reference before comparing — same sum, same physics,
    different moment centre.
    """
    result, bulk = whole_aircraft_cut
    sc = result.section_loads["SECALL"]
    st = sc.stations[0]
    assert st.n_members == len(bulk.set1s[1310].grids)

    cut_F, cut_M = _to_basic(sc.cid, st.totals, bulk)
    ml = result.monitor_loads["MALLEA"]
    mon_F = ml.totals[:3]
    mon_M = ml.totals[3:] + np.cross(ml.ref - st.ref, ml.totals[:3])

    assert cut_F == pytest.approx(mon_F, abs=1e-9)
    assert cut_M == pytest.approx(mon_M, abs=1e-6)


def test_vsec5_whole_aircraft_net_load_is_the_maneuver_closure(whole_aircraft_cut):
    """V-SEC5 — aero + inertia + reaction over the whole model balances to ≈0."""
    result, bulk = whole_aircraft_cut
    st = result.section_loads["SECALL"].stations[0]
    lift = abs(result.monitor_loads["MALLEA"].aero[2])
    assert lift > 1e3                       # the trim really is carrying load
    assert np.linalg.norm(st.totals[:3]) < 1e-6 * lift
    assert np.linalg.norm(st.totals[3:]) < 1e-6 * lift


def test_vsec7_aelist_cut_equals_set1_cut_aero_over_a_whole_collection(trim):
    """V-SEC7 — the two source types agree where the partition question vanishes.

    A cut inboard of everything integrates the whole collection either way, so
    the AELIST (box) and SET1 (splined-grid) cuts must agree by spline force and
    moment conservation.  Station by station they would NOT: near a cut plane the
    boxes and the grids their load splines to fall on different sides.
    """
    _result, bulk, _gi, aero = trim
    extra = parse_bdf_lines([
        "CORD2R, 902, 0, 15.0, -1000.0, 0.0, 15.0, -1000.0, 1.0",
        "+, 16.0, -1000.0, 0.0",
    ])
    bulk.cord2rs.update(extra.cord2rs)
    saved = dict(bulk.monsects)
    bulk.monsects.clear()
    for name, comp in (("SECG", "ALLGRID"), ("SECA", "ALLAERO")):
        bulk.monsects[name] = Monsect(name=name, label=name, comp=comp, cid=902,
                                      axis=2, side="POS", stations=[0.0])
    try:
        result = _run(bulk, aero)
    finally:
        bulk.monsects.clear()
        bulk.monsects.update(saved)

    grid_cut = result.section_loads["SECG"].stations[0]
    box_cut = result.section_loads["SECA"].stations[0]
    lift = abs(grid_cut.aero[2])
    assert lift > 1e3
    assert grid_cut.aero[:3] == pytest.approx(box_cut.totals[:3], abs=1e-6 * lift)
    # Moment carries the spline rotational-row numerics, as for MON1 vs MON3.
    m_scale = max(np.linalg.norm(grid_cut.aero[3:]), 1.0)
    assert grid_cut.aero[3:] == pytest.approx(box_cut.totals[3:], rel=1e-5,
                                              abs=1e-5 * m_scale)


def test_contributions_sum_to_totals(trim):
    """The aero/inertia/reaction split is a decomposition, not an approximation."""
    result, _bulk, _gi, _aero = trim
    for st in result.section_loads["SECRW"].stations:
        assert st.totals == pytest.approx(st.aero + st.inertia + st.reaction, abs=1e-9)
