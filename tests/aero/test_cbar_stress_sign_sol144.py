"""DEF-M21 (#37) gate G6: CBAR stress continuity on the trimmed HA144A wing.

SOL 144 shares ``recover_bar_stresses`` with SOL 101, so the fix must hold on
the aeroelastic path too. Every shared node of the trimmed HA144A carries a
load (splined aero and CONM2 inertia through the RBAR'd chord grids, the
SUPORT reaction at grid 90), so plain stress continuity (G3) cannot hold
there. The aeroelastic form of the gate is the jump condition: across a
collinear, same-section, same-orientation pair the fibre stress read from
end B of the inboard element and end A of the outboard one differ by exactly
the stress of the net nodal load at the shared grid, i.e. the sum of the two
elements' nodal moments there. A wrong end-B face would leave a residual of
twice the end moment; on an unloaded node the jump is zero and G3 is recovered.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver.sol101 import _element_local_forces
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"
# Bending-only fields in the NASTRAN layout (#21); the jump is taken on the total = axial + bending.
PAIRS = {"C": ("sa1", "sb1"), "D": ("sa2", "sb2"), "E": ("sa3", "sb3"), "F": ("sa4", "sb4")}


@pytest.fixture(scope="module")
def trimmed():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    return result, bulk, grid_index


def _collinear_same_section_pairs(bulk):
    """(inboard eid, outboard eid) sharing GB→GA with equal PID, direction and v."""
    pairs = []
    by_ga = {}
    for c in bulk.cbars.values():
        by_ga.setdefault(c.ga, []).append(c)
    for left in bulk.cbars.values():
        for right in by_ga.get(left.gb, []):
            if right.pid != left.pid:
                continue
            ga, gb, gc = bulk.grids[left.ga], bulk.grids[left.gb], bulk.grids[right.gb]
            d1 = np.array([gb.x - ga.x, gb.y - ga.y, gb.z - ga.z])
            d2 = np.array([gc.x - gb.x, gc.y - gb.y, gc.z - gb.z])
            if np.linalg.norm(np.cross(d1, d2)) > 1e-9 * np.linalg.norm(d1) * np.linalg.norm(d2):
                continue
            if (left.x1, left.x2, left.x3) != (right.x1, right.x2, right.x3):
                continue
            pairs.append((left.eid, right.eid))
    return pairs


def test_ha144a_has_collinear_pairs(trimmed):
    _, bulk, _ = trimmed
    pairs = _collinear_same_section_pairs(bulk)
    # Fuselage 101→102→100→103 and both wing runs 110→120, 210→220.
    assert len(pairs) >= 5


def test_stress_jump_equals_nodal_load_on_trimmed_airplane(trimmed):
    result, bulk, gi = trimmed
    pairs = _collinear_same_section_pairs(bulk)
    scale = max(abs(v) for bs in result.bar_stresses.values()
                for v in (bs.sa1, bs.sb1, bs.sa2, bs.sb2, bs.sa3, bs.sb3, bs.sa4, bs.sb4))
    assert scale > 0.0
    loaded_nodes = 0
    for left, right in pairs:
        cl, cr = bulk.cbars[left], bulk.cbars[right]
        pbar = bulk.pbars[cl.pid]
        fl = _element_local_forces(cl, bulk.grids, bulk.pbars, bulk.mat1s, result.displacements, gi)
        fr = _element_local_forces(cr, bulk.grids, bulk.pbars, bulk.mat1s, result.displacements, gi)
        # Net nodal load at the shared grid, element frame (both elements share it).
        n_my = fl[10] + fr[4]
        n_mz = fl[11] + fr[5]
        n_p = fl[6] + fr[0]
        if abs(n_my) + abs(n_mz) > 1e-9 * (abs(fl[10]) + abs(fl[11])):
            loaded_nodes += 1
        bl, br = result.bar_stresses[left], result.bar_stresses[right]
        pts = {"C": (pbar.c1, pbar.c2), "D": (pbar.d1, pbar.d2),
               "E": (pbar.e1, pbar.e2), "F": (pbar.f1, pbar.f2)}
        for pt, (sa, sb) in PAIRS.items():
            y, z = pts[pt]
            # Face moments: Mz_A(right) − Mz_B(left) = −fr[5] − fl[11] = −n_mz, etc.
            expected_jump = (-n_p) / pbar.A - (-n_mz) * y / pbar.I1 + (-n_my) * z / pbar.I2
            jump = (br.axial + getattr(br, sa)) - (bl.axial + getattr(bl, sb))
            assert jump == pytest.approx(expected_jump, rel=1e-9, abs=1e-9 * scale), (left, right, pt)
    # The gate is only meaningful if the trimmed model actually loads shared nodes.
    assert loaded_nodes >= 1


def test_end_a_unchanged_on_sol144(trimmed):
    """End-A totals equal the pre-#37 raw-nodal formula (1e-14: #21 reorders the sum)."""
    result, bulk, gi = trimmed
    for cbar in bulk.cbars.values():
        pbar = bulk.pbars[cbar.pid]
        f = _element_local_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, result.displacements, gi)
        bs = result.bar_stresses[cbar.eid]
        for (y, z), attr in (((pbar.c1, pbar.c2), "sa1"), ((pbar.d1, pbar.d2), "sa2"),
                             ((pbar.e1, pbar.e2), "sa3"), ((pbar.f1, pbar.f2), "sa4")):
            old = 0.0
            old += f[6] / pbar.A
            old += f[5] * y / pbar.I1
            old -= f[4] * z / pbar.I2
            assert bs.axial + getattr(bs, attr) == pytest.approx(old, rel=1e-14, abs=1e-14)
