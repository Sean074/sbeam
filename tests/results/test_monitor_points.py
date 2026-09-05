"""MON2 / MON3 — monitor-point integrated-load unit tests.

MON2 (MONPNT1): aero-only box-force integration, 3-component carry-through, parity.
MON3 (MONPNT3): aero + inertia + reaction g-set grid summation about a reference.
"""
import types

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.aero.panel import mesh_caero1, build_box_id_map
from sbeam.results.monitor_points import integrate_monpnt1, integrate_monpnt3


# Rectangular planar wing: CAERO1 1001, 4 span × 2 chord = 8 boxes, IDs 1001-1008.
_WING = """\
AEROS,0,0,2.0,8.0,16.0,0,0
PAERO1,1
CAERO1,1001,1,,4,2,,,0
+,0.0,0.0,0.0,2.0,8.0,0.0,2.0,0.0
AELIST,200,1001,THRU,1008
AECOMP,WINGAERO,AELIST,200
MONPNT1,MW,WING,123456,WINGAERO,0,0.0,0.0,0.0
""".splitlines()


@pytest.fixture
def wing_bulk():
    return parse_bulk_data(_WING)


@pytest.fixture
def wing_boxes(wing_bulk):
    caero = wing_bulk.caero1s[1001]
    paero = wing_bulk.paero1s[1]
    boxes = mesh_caero1(caero, paero, wing_bulk.aefacts, wing_bulk.cord2rs)
    # Stands in for an AeroModel: integrate_monpnt1 resolves AELIST box IDs
    # through the shared, collision-checked map (F1).
    return types.SimpleNamespace(
        boxes=boxes, require_box_id_to_k=lambda: build_box_id_map(boxes))


def test_monpnt1_uniform_fz_sum(wing_bulk, wing_boxes):
    n = len(wing_boxes.boxes)
    box_forces = np.zeros((n, 3))
    box_forces[:, 2] = 10.0  # uniform Fz per box
    mon = wing_bulk.monpnt1s["MW"]
    ml = integrate_monpnt1(mon, wing_bulk, wing_boxes, box_forces)
    assert ml.totals[2] == pytest.approx(n * 10.0, rel=1e-12)
    # Moment about origin matches Σ force_point × F directly.
    M = np.zeros(3)
    for k, b in enumerate(wing_boxes.boxes):
        M += np.cross(b.force_point, box_forces[k])
    assert ml.totals[3:] == pytest.approx(M, rel=1e-12, abs=1e-12)


def test_monpnt1_three_component_carry_through(wing_bulk, wing_boxes):
    """A canted force vector must survive integration (no Fz-only projection)."""
    n = len(wing_boxes.boxes)
    box_forces = np.zeros((n, 3))
    box_forces[:, 1] = 3.0   # Fy
    box_forces[:, 2] = 4.0   # Fz
    mon = wing_bulk.monpnt1s["MW"]
    ml = integrate_monpnt1(mon, wing_bulk, wing_boxes, box_forces)
    assert ml.totals[1] == pytest.approx(n * 3.0, rel=1e-12)
    assert ml.totals[2] == pytest.approx(n * 4.0, rel=1e-12)


def test_monpnt1_parity_doubles(wing_bulk, wing_boxes):
    n = len(wing_boxes.boxes)
    box_forces = np.zeros((n, 3))
    box_forces[:, 2] = 10.0
    mon = wing_bulk.monpnt1s["MW"]
    base = integrate_monpnt1(mon, wing_bulk, wing_boxes, box_forces)
    wing_bulk.aeros.symxz = 1            # half-model build fed directly
    doubled = integrate_monpnt1(mon, wing_bulk, wing_boxes, box_forces)
    assert doubled.parity == 2.0
    assert doubled.whole_airplane is True
    assert doubled.totals[2] == pytest.approx(2.0 * base.totals[2], rel=1e-12)


def test_monpnt1_cp_frame_transform(wing_bulk, wing_boxes):
    """With a CORD2R that rotates basic +z onto local +x, Fz maps to the x slot."""
    # Build a CORD2R (cid 9) whose z-axis points along basic +x: a 90° rotation.
    lines = _WING + [
        "CORD2R,9,0,0.0,0.0,0.0,1.0,0.0,0.0",
        "+,1.0,0.0,1.0",
        "MONPNT1,MCP,WING,123456,WINGAERO,9,0.0,0.0,0.0",
    ]
    bulk = parse_bulk_data(lines)
    n = len(wing_boxes.boxes)
    box_forces = np.zeros((n, 3))
    box_forces[:, 2] = 10.0
    ml = integrate_monpnt1(bulk.monpnt1s["MCP"], bulk, wing_boxes, box_forces)
    # basic +z becomes local +x in this frame.
    assert ml.totals[0] == pytest.approx(n * 10.0, rel=1e-9)
    assert ml.totals[2] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# MON3 — MONPNT3 over structural grids
# ---------------------------------------------------------------------------

_GRIDS = """\
GRID,100,,0.0,0.0,0.0
GRID,110,,0.0,4.0,0.0
GRID,120,,0.0,8.0,0.0
SET1,300,100,110,120
AECOMP,WINGGRID,SET1,300
MONPNT3,MWING,WING,123456,WINGGRID,0,0.0,0.0,0.0
""".splitlines()


@pytest.fixture
def grid_model():
    bulk = parse_bulk_data(_GRIDS)
    grid_index = {gid: i for i, gid in enumerate(sorted(bulk.grids))}
    return bulk, grid_index


def _gset(grid_index):
    return np.zeros(6 * len(grid_index))


def test_monpnt3_aero_sum_and_moment(grid_model):
    bulk, gi = grid_model
    grid_loads = _gset(gi)
    # Put Fz=5 at each of the three grids (y = 0, 4, 8).
    for gid in (100, 110, 120):
        grid_loads[6 * gi[gid] + 2] = 5.0
    mon = bulk.monpnt3s["MWING"]
    ml = integrate_monpnt3(mon, bulk, grid_loads, None, gi, {})
    assert ml.totals[2] == pytest.approx(15.0, rel=1e-12)
    # Mx about origin = Σ y·Fz = (0+4+8)*5 = 60.
    assert ml.aero[3] == pytest.approx(60.0, rel=1e-12)
    assert ml.inertia[2] == pytest.approx(0.0, abs=1e-12)
    assert ml.reaction[2] == pytest.approx(0.0, abs=1e-12)


def test_monpnt3_inertia_and_reaction_breakdown(grid_model):
    bulk, gi = grid_model
    grid_loads = _gset(gi)
    inertial = _gset(gi)
    grid_loads[6 * gi[110] + 2] = 10.0      # aero Fz at mid grid
    inertial[6 * gi[110] + 2] = -3.0        # inertia relief
    reactions = {100: np.array([0.0, 0.0, 2.0, 0.0, 0.0, 0.0])}  # reaction at root
    mon = bulk.monpnt3s["MWING"]
    ml = integrate_monpnt3(mon, bulk, grid_loads, inertial, gi, reactions)
    assert ml.aero[2] == pytest.approx(10.0, rel=1e-12)
    assert ml.inertia[2] == pytest.approx(-3.0, rel=1e-12)
    assert ml.reaction[2] == pytest.approx(2.0, rel=1e-12)
    assert ml.totals[2] == pytest.approx(9.0, rel=1e-12)


def test_monpnt3_reaction_only_counts_collection_grids(grid_model):
    bulk, gi = grid_model
    grid_loads = _gset(gi)
    # A reaction at a grid NOT in the SET1 must be ignored.
    reactions = {999: np.array([0.0, 0.0, 100.0, 0.0, 0.0, 0.0])}
    mon = bulk.monpnt3s["MWING"]
    ml = integrate_monpnt3(mon, bulk, grid_loads, None, gi, reactions)
    assert ml.reaction[2] == pytest.approx(0.0, abs=1e-12)
