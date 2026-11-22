"""CBUSH spring location and rigid links (#97).

MSC places the spring of a two-grid CBUSH at P = GA + S·(GB − GA) and joins it to the
grids by rigid links: "For noncoincident grids, internal rigid links connect the bush
location to the grid locations.  This results in coupling between translational and
rotational degrees-of-freedom at the grids even when no rotational springs or dampers
are specified on the PBUSH" (MSC Nastran 2024.1 QRG PDF p.1381, remark 11; S on
p.1378, Figure 9-20 on p.1380).  Before #97 sbeam had no arm, so a lateral spring between
separated grids resisted a rigid rotation: the issue's probe gave ∓4.0e6 at Ty.
"""
import math

import numpy as np
import pytest

from sbeam.assembly.stiffness import cbush_stiffness_global
from sbeam.model.load import Eigrl
from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver.sol101 import recover_cbush_forces
from sbeam.solver.sol103 import run_sol103

_PBUSH_ALL = "PBUSH, 10, K, 1.e6, 2.e6, 3.e6, 1.e3, 2.e3, 3.e3"


def _bulk(*cards, xb=(2.0, 0.0, 0.0)):
    return parse_bulk_data(["GRID, 1, , 0., 0., 0.",
                            f"GRID, 2, , {xb[0]!r}, {xb[1]!r}, {xb[2]!r}",
                            _PBUSH_ALL, *cards])


def _k(bulk, eid=1):
    return cbush_stiffness_global(bulk.cbushs[eid], bulk.grids, bulk.pbushs, bulk.cord2rs)


def _rigid_motions(bulk):
    """The six rigid-body motions of grids 1 and 2 as 12-vectors (basic, about the origin)."""
    motions = []
    for axis in np.eye(3):
        motions.append(np.tile(np.r_[axis, 0.0, 0.0, 0.0], 2))          # translation
    for axis in np.eye(3):
        u = []
        for gid in (1, 2):
            g = bulk.grids[gid]
            u.append(np.r_[np.cross(axis, [g.x, g.y, g.z]), axis])      # rotation
        motions.append(np.concatenate(u))
    return motions


def test_issue_probe_rigid_rotation_gives_no_force():
    """#97 probe: 1 rad about basic z through grid 1 gave -4.0e6 / +4.0e6 at Ty."""
    bulk = _bulk("CBUSH, 1, 10, 1, 2, 0., 1., 0.")
    u = np.r_[0, 0, 0, 0, 0, 1.0, 0, 2.0, 0, 0, 0, 1.0]
    f = _k(bulk) @ u
    assert np.abs(f).max() < 1e-6 * 3.0e6 * 2.0


def test_lateral_spring_matches_the_hand_derived_matrix():
    """K2 alone, grids L apart on basic x, v = basic y, S = 0.5.

    Relative y-motion at P: d = uBy − uAy − (L/2)(θAz + θBz), so K = K2·g·gᵀ with
    g = [−1, −L/2, +1, −L/2] on (uAy, θAz, uBy, θBz): coupling K2·L/2, K2·L²/4.
    """
    L, k2 = 2.0, 2.0e6
    bulk = parse_bulk_data(["GRID, 1, , 0., 0., 0.", "GRID, 2, , 2., 0., 0.",
                            "PBUSH, 10, K, , 2.e6", "CBUSH, 1, 10, 1, 2, 0., 1., 0."])
    g = np.zeros(12)
    g[[1, 5, 7, 11]] = [-1.0, -L / 2, 1.0, -L / 2]
    expected = k2 * np.outer(g, g)
    np.testing.assert_allclose(_k(bulk), expected, rtol=0, atol=1e-9 * k2)
    assert expected[1, 5] == pytest.approx(k2 * L / 2)
    assert expected[5, 5] == pytest.approx(k2 * L**2 / 4)


def test_spring_location_s_moves_the_coupling():
    """S = 0.25: arms L/4 from GA and 3L/4 from GB, so g = [−1, −L/4, +1, −3L/4]."""
    L, k2 = 2.0, 2.0e6
    bulk = parse_bulk_data(["GRID, 1, , 0., 0., 0.", "GRID, 2, , 2., 0., 0.",
                            "PBUSH, 10, K, , 2.e6", "CBUSH, 1, 10, 1, 2, 0., 1., 0.",
                            "+, 0.25"])
    g = np.zeros(12)
    g[[1, 5, 7, 11]] = [-1.0, -L / 4, 1.0, -3 * L / 4]
    np.testing.assert_allclose(_k(bulk), k2 * np.outer(g, g), rtol=0, atol=1e-9 * k2)


@pytest.mark.parametrize("xb", [(2.0, 0.0, 0.0), (1.0, 1.5, -0.7), (-0.3, 0.2, 4.0)])
@pytest.mark.parametrize("s", ["", "0.", "0.3", "1.", "1.4"])
@pytest.mark.parametrize("axes", ["0.3, 1., 0.2", "CID"])
def test_every_rigid_motion_gives_no_force(xb, s, axes):
    """Invariant: all six rigid motions, every K, any S and any element axes."""
    cards = ["CORD2R, 7, 0, 0., 0., 0., 0.2, 0.5, 1.", "+, 1., 0.3, 0."]
    orient = ", , , , 7" if axes == "CID" else f", {axes}"
    cards.append(f"CBUSH, 1, 10, 1, 2{orient}")
    if s:
        cards.append(f"+, {s}")
    bulk = _bulk(*cards, xb=xb)
    K = _k(bulk)
    np.testing.assert_allclose(K, K.T, rtol=0, atol=1e-9 * 3.0e6)
    for u in _rigid_motions(bulk):
        assert np.abs(K @ u).max() < 1e-8 * 3.0e6 * (1.0 + np.abs(u).max())


def test_force_recovery_sees_no_rigid_motion():
    bulk = _bulk("CBUSH, 1, 10, 1, 2, 0., 1., 0.")
    gi = {1: 0, 2: 1}
    for u in _rigid_motions(bulk):
        f = recover_cbush_forces(bulk.cbushs[1], bulk.grids, bulk.pbushs, u, gi)
        assert np.abs(f).max() < 1e-6 * 3.0e6


def test_coincident_spring_is_unchanged():
    """A zero arm is an exact identity: the element is the plain [[K, −K], [−K, K]]."""
    bulk = _bulk("CBUSH, 1, 10, 1, 2, , , , 0", xb=(0.0, 0.0, 0.0))
    K6 = np.diag([1.e6, 2.e6, 3.e6, 1.e3, 2.e3, 3.e3])
    assert np.array_equal(_k(bulk), np.block([[K6, -K6], [-K6, K6]]))


def test_free_free_two_masses_have_six_rigid_modes_and_the_closed_form_elastic_ones():
    """SOL 103: two equal CONM2s (m, Jxx, Jyy, Jzz) L apart, joined at mid-span.

    Mirror symmetry about the mid-plane splits each bending plane into a rotation mode
    ω² = 2K6/Jzz (2K5/Jyy) and a shear mode ω² = 2K2/m + K2·L²/(2Jzz)
    (2K3/m + K3·L²/(2Jyy)); axial 2K1/m and torsion 2K4/Jxx.  Before #97 the shear
    "modes" grounded the rigid rotations about y and z.
    """
    m, jxx, jyy, jzz, L = 2.0, 0.5, 0.3, 0.4, 2.0
    k1, k2, k3, k4, k5, k6 = 1.e6, 2.e6, 3.e6, 1.e3, 2.e3, 3.e3
    bulk = _bulk("CBUSH, 1, 10, 1, 2, 0., 1., 0.",
                 f"CONM2, 11, 1, 0, {m}", f"+, {jxx}, 0., {jyy}, 0., 0., {jzz}",
                 f"CONM2, 12, 2, 0, {m}", f"+, {jxx}, 0., {jyy}, 0., 0., {jzz}")
    bulk.eigrls[20] = Eigrl(sid=20, nd=12, norm="MASS")
    result = run_sol103(bulk, SubcaseControl(subcase_id=1, method_sid=20))
    f = np.sort(np.asarray(result.frequencies_hz))
    assert np.all(np.abs(f[:6]) < 1e-4)
    omega2 = sorted([2 * k1 / m, 2 * k4 / jxx,
                     2 * k5 / jyy, 2 * k3 / m + k3 * L**2 / (2 * jyy),
                     2 * k6 / jzz, 2 * k2 / m + k2 * L**2 / (2 * jzz)])
    expected = [math.sqrt(w2) / (2 * math.pi) for w2 in omega2]
    np.testing.assert_allclose(f[6:], expected, rtol=1e-9)
