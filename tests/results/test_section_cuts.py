"""V-SEC unit gates for MONSECT section cuts (Monitor Phase 2).

These exercise the integrand directly on synthetic g-set loads — no trim solve —
so a failure here is the plane test, the reference point, the moment transfer or
the component labelling, and nothing else.  The solver-level gates (V-SEC2/3/5/6)
live in ``tests/aero/test_section_cuts_sol144.py``.
"""
import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.results.section_cuts import (
    compute_section_cut, compute_section_cuts, component_map, component_names,
    labelled,
)

# A 10-unit cantilever along +y: 11 grids at y = 0..10, all in basic CID 0.
# The SET1 collection is the whole beam; the MONSECT cuts it at half-unit
# stations so no station ever lands on a grid.
_L = 10.0
_GRIDS = "\n".join(f"GRID,{100 + i},,0.0,{float(i)},0.0" for i in range(11))
_BDF = f"""\
{_GRIDS}
AEROS,0,0,1.0,20.0,20.0,0,0
SET1,300,100,101,102,103,104,105,106,107,108,109,110
AECOMP,BEAM,SET1,300
MONSECT,SECB,CANTILEVER,BEAM,0
+,0.5,2.5,4.5,6.5,8.5,10.5
""".splitlines()


@pytest.fixture(scope="module")
def bulk():
    return parse_bulk_data(_BDF)


@pytest.fixture(scope="module")
def grid_index(bulk):
    return {gid: i for i, gid in enumerate(sorted(bulk.grids))}


def _tip_load(bulk, grid_index, p=3.0):
    """g-set load: a single vertical force P at the tip grid (y = L)."""
    load = np.zeros(6 * len(bulk.grids))
    load[6 * grid_index[110] + 2] = p
    return load


def test_vsec1_tip_load_shear_and_bending(bulk, grid_index):
    """V-SEC1 — tip point load: V = P inboard of the tip, M = P(L−s) exactly.

    Closed form, so this is a machine-precision gate on the whole integrand.
    """
    p = 3.0
    cut = compute_section_cut(
        bulk.monsects["SECB"], bulk, None, None, _tip_load(bulk, grid_index, p),
        None, grid_index,
    )
    names = component_names(cut.axis)
    assert names == ("N", "Vx", "Vz", "Mt", "Mx", "Mz")
    for st in cut.stations:
        lab = labelled(st.totals, cut.comp_map)
        if st.station > _L:
            assert np.allclose(lab, 0.0)          # V-SEC4 — nothing outboard
            assert st.n_members == 0
            continue
        assert lab[2] == pytest.approx(p, abs=1e-12)                    # Vz
        assert lab[4] == pytest.approx(p * (_L - st.station), abs=1e-12)  # Mx (bending)
        assert lab[0] == pytest.approx(0.0, abs=1e-12)                  # N
        assert lab[3] == pytest.approx(0.0, abs=1e-12)                  # Mt


def test_vsec1_uniform_load_matches_discrete_free_body(bulk, grid_index):
    """V-SEC1b — uniformly lumped load vs the free-body sum computed independently."""
    w = 0.7
    load = np.zeros(6 * len(bulk.grids))
    for i in range(11):
        load[6 * grid_index[100 + i] + 2] = w
    cut = compute_section_cut(bulk.monsects["SECB"], bulk, None, None, load,
                              None, grid_index)
    for st in cut.stations:
        outboard = [float(i) for i in range(11) if i > st.station]
        lab = labelled(st.totals, cut.comp_map)
        assert lab[2] == pytest.approx(w * len(outboard), abs=1e-12)
        assert lab[4] == pytest.approx(
            sum(w * (y - st.station) for y in outboard), abs=1e-12)


def test_reference_point_rides_the_axis(bulk, grid_index):
    """The moment reference is the cut-plane intercept, not the CID origin."""
    cut = compute_section_cut(bulk.monsects["SECB"], bulk, None,
                              None, _tip_load(bulk, grid_index), None, grid_index)
    for st in cut.stations:
        assert np.allclose(st.ref, [0.0, st.station, 0.0])


def test_side_neg_integrates_the_other_half(bulk, grid_index):
    """POS + NEG over the same station must reconstruct the whole collection."""
    import copy
    neg = copy.deepcopy(bulk.monsects["SECB"])
    neg.side = "NEG"
    load = _tip_load(bulk, grid_index)
    pos_cut = compute_section_cut(bulk.monsects["SECB"], bulk, None, None, load,
                                  None, grid_index)
    neg_cut = compute_section_cut(neg, bulk, None, None, load, None, grid_index)
    for sp, sn in zip(pos_cut.stations, neg_cut.stations):
        # Same reference point, so the two halves' resultants simply add.
        assert np.allclose(sp.totals + sn.totals, _whole_resultant(load, bulk, sp.ref))


def _whole_resultant(load, bulk, ref):
    F = np.zeros(3)
    M = np.zeros(3)
    for i, gid in enumerate(sorted(bulk.grids)):
        f = load[6 * i: 6 * i + 3]
        g = bulk.grids[gid]
        M += load[6 * i + 3: 6 * i + 6] + np.cross(
            np.array([g.x, g.y, g.z]) - ref, f)
        F += f
    return np.concatenate([F, M])


def test_vsec8_normal_override_matches_geometry(grid_index):
    """V-SEC8 — a tilted cut plane reassigns exactly the grids geometry says it should."""
    bdf = _BDF[:-2] + [
        "MONSECT,SECT,TILTED,BEAM,0,2",
        "+,4.5",
        "+,NORMAL,0.5,1.0,0.0",
    ]
    b = parse_bulk_data(bdf)
    gi = {gid: i for i, gid in enumerate(sorted(b.grids))}
    load = np.zeros(6 * len(b.grids))
    for i in range(11):
        load[6 * gi[100 + i] + 2] = 1.0
    cut = compute_section_cut(b.monsects["SECT"], b, None, None, load, None, gi)
    st = cut.stations[0]
    # n̂ = (0.5, 1, 0)/|…|; every grid is at x = 0, so s_g = y_g/√1.25.  The plane
    # passes through the reference line at station 4.5, i.e. y = 4.5·√1.25… —
    # count the grids the geometry actually puts outboard.
    n = np.array([0.5, 1.0, 0.0]) / np.linalg.norm([0.5, 1.0, 0.0])
    expected = sum(1 for i in range(11) if (np.array([0.0, i, 0.0]) @ n) > 4.5)
    assert st.n_members == expected
    assert labelled(st.totals, cut.comp_map)[2] == pytest.approx(float(expected))
    # The distinguishing property of the override: the reference point stays on
    # the reference line (the EA), and lies on the tilted plane.
    assert st.ref[0] == pytest.approx(0.0) and st.ref[2] == pytest.approx(0.0)
    assert st.ref @ n == pytest.approx(4.5)


def test_vsec10_on_plane_grid_warns_and_counts_inboard(grid_index):
    """V-SEC10 — a station on a grid warns, and that grid is excluded from the cut."""
    bdf = _BDF[:-2] + ["MONSECT,SECO,ON GRID,BEAM,0", "+,5.0"]
    b = parse_bulk_data(bdf)
    gi = {gid: i for i, gid in enumerate(sorted(b.grids))}
    load = np.zeros(6 * len(b.grids))
    for i in range(11):
        load[6 * gi[100 + i] + 2] = 1.0
    with pytest.warns(UserWarning, match="INBOARD side"):
        cut = compute_section_cut(b.monsects["SECO"], b, None, None, load, None, gi)
    # Grids at y = 6..10 are outboard; the grid at y = 5 is not.
    assert cut.stations[0].n_members == 5


def test_component_map_is_a_permutation():
    for axis in (1, 2, 3):
        assert sorted(component_map(axis)) == [0, 1, 2, 3, 4, 5]
        names = component_names(axis)
        assert names[0] == "N" and names[3] == "Mt"
        # Every other label names the CID axis it acts along/about.
        assert set(names[1:3]) | set(names[4:6]) == {
            f"V{c}" for c in "xyz" if c != "xyz"[axis - 1]
        } | {f"M{c}" for c in "xyz" if c != "xyz"[axis - 1]}


def test_running_load_derivative(bulk, grid_index):
    """d/ds is the backward difference; undefined at the first station."""
    cut = compute_section_cut(bulk.monsects["SECB"], bulk, None, None,
                              _tip_load(bulk, grid_index), None, grid_index)
    assert cut.stations[0].d_ds is None
    # Tip load: Vz constant, so dMx/ds = −P between interior stations.
    assert cut.stations[2].d_ds[4] == pytest.approx(-3.0, abs=1e-12)
    assert cut.stations[2].d_ds[2] == pytest.approx(0.0, abs=1e-12)


def test_half_model_is_not_doubled(grid_index):
    """The parity decision: a SYMXZ half model is annotated, never scaled."""
    bdf = [ln.replace("AEROS,0,0,1.0,20.0,20.0,0,0",
                      "AEROS,0,0,1.0,20.0,20.0,1,0") for ln in _BDF]
    b = parse_bulk_data(bdf)
    gi = {gid: i for i, gid in enumerate(sorted(b.grids))}
    load = np.zeros(6 * len(b.grids))
    load[6 * gi[110] + 2] = 3.0
    cut = compute_section_cut(b.monsects["SECB"], b, None, None, load, None, gi)
    assert cut.half_model is True
    assert labelled(cut.stations[0].totals, cut.comp_map)[2] == pytest.approx(3.0)


def test_compute_section_cuts_maps_every_card(bulk, grid_index):
    out = compute_section_cuts(bulk, None, None, _tip_load(bulk, grid_index),
                               None, grid_index)
    assert set(out) == set(bulk.monsects)
