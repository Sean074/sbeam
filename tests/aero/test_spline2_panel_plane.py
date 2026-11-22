"""SPLINE2 takes its plane from the panel and only its axis from CID (#74).

MSC Nastran 2024.1 Quick Reference Guide, PDF p.2849, SPLINE2 remark 2: "The spline
axis for panels is the projection of the y-axis of coordinate system CID, projected onto
the plane of the panel."  sbeam used the CID z-axis as the deflection and force
direction, so a dihedral wing splined with CID 0 lost the side force of every box, and a
CID whose z-axis was slightly off the panel normal (the flagship wing, 0.024 deg) put a
spurious chordwise force on the structure.
"""
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_skj
from sbeam.aero.spline import _covered_gk_for_range
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol144 import run_sol144_trim

REPO = Path(__file__).parent.parent.parent
DIHEDRAL = REPO / "sample" / "val_dihedral_trim.bdf"

# Every repo deck that runs a SPLINE2: the rigid-body gate below covers them all
_SPLINE2_DECKS = sorted(
    p for folder in ("sample", "tests/integration/bdf") for p in (REPO / folder).glob("*.bdf")
    if "\nSPLINE2" in p.read_text() or "INCLUDE" in p.read_text()
)


def _model(path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(str(path))
        grid_index = build_grid_index(bulk)
        aero = build_aero_model(bulk, grid_index=grid_index)
    return cc, bulk, grid_index, aero


def _dihedral_with_cid(tmp_path, cid_right, cid_left, extra=""):
    """The dihedral sample with its two SPLINE2 CIDs replaced."""
    text = DIHEDRAL.read_text()
    text = text.replace("0.0, 1.0, 2\n", f"0.0, 1.0, {cid_right}\n")
    text = text.replace("0.0, 1.0, 3\n", f"0.0, 1.0, {cid_left}\n")
    assert f"1.0, {cid_right}\n" in text and f"1.0, {cid_left}\n" in text
    text = text.replace("ENDDATA", extra + "ENDDATA")
    deck = tmp_path / "dihedral.bdf"
    deck.write_text(text)
    return deck


def _spline2_boxes(bulk, aero):
    ks = []
    for sp in bulk.spline2s.values():
        ks += _covered_gk_for_range(sp.caero, sp.id1, sp.id2, aero.boxes, aero.box_id_to_k)
    return sorted(ks)


def _rigid_modes(bulk, grid_index):
    """The six rigid-body motions about the basic origin, as g-set columns."""
    modes = np.zeros((6 * len(grid_index), 6))
    for gid, i in grid_index.items():
        g = bulk.grids[gid]
        r = np.array([g.x, g.y, g.z])
        for d in range(3):
            omega = np.eye(3)[d]
            modes[6 * i + d, d] = 1.0
            modes[6 * i:6 * i + 3, 3 + d] = np.cross(omega, r)
            modes[6 * i + 3 + d, 3 + d] = 1.0
    return modes


class TestDihedralWithCidZero:
    """The audit's reproduction: MSC-legal CID 0 on a 10 deg dihedral wing."""

    @pytest.fixture(scope="class")
    def transfer(self, tmp_path_factory):
        deck = _dihedral_with_cid(tmp_path_factory.mktemp("d0"), 0, 0)
        _cc, bulk, grid_index, aero = _model(deck)
        f_box = (build_skj(aero.boxes) @ np.ones(len(aero.boxes))).reshape(-1, 3)
        return bulk, grid_index, aero, f_box

    @pytest.mark.parametrize("side, sign", [("right", 1.0), ("left", -1.0)])
    def test_side_force_reaches_the_structure(self, transfer, side, sign):
        """Unit pressure on one semi-span: the grids receive the boxes' force in full.

        Before #74: box Fy = -/+0.6946, grid Fy = 0 (100 % of the side force lost)."""
        _bulk, _gi, aero, f_box = transfer
        on_side = np.array([sign * b.force_point[1] > 0 for b in aero.boxes])
        f_side = np.where(on_side[:, None], f_box, 0.0)
        f_grid = (aero.require_g_load().T @ f_side.ravel()).reshape(-1, 6)[:, :3].sum(axis=0)
        assert f_side.sum(axis=0) == pytest.approx([0.0, -sign * 0.69459271, 3.93923099], abs=1e-7)
        assert f_grid == pytest.approx(f_side.sum(axis=0), abs=1e-12)

    def test_moment_about_the_origin_is_transferred(self, transfer):
        bulk, grid_index, aero, f_box = transfer
        on_right = np.array([b.force_point[1] > 0 for b in aero.boxes])
        f_side = np.where(on_right[:, None], f_box, 0.0)
        m_box = sum(np.cross(b.force_point, f) for b, f in zip(aero.boxes, f_side))
        f_g = (aero.require_g_load().T @ f_side.ravel()).reshape(-1, 6)
        m_grid = np.zeros(3)
        for gid, i in grid_index.items():
            g = bulk.grids[gid]
            m_grid += np.cross([g.x, g.y, g.z], f_g[i, :3]) + f_g[i, 3:]
        assert m_grid == pytest.approx(m_box, abs=1e-11)

    def test_trim_agrees_with_the_hand_canted_deck(self, tmp_path):
        """CID 0 puts the spline axis through the basic origin, 0.25 forward of the
        spar, so the two decks are different splines of the same wing and agree to
        the spline's own accuracy (3e-5 here), not to round-off."""
        cc0, bulk0, _gi, aero0 = _model(_dihedral_with_cid(tmp_path, 0, 0))
        cc, bulk, _gi, aero = _model(DIHEDRAL)
        a0 = run_sol144_trim(bulk0, cc0.subcases[0], aero0).trim_vars["ANGLEA"]
        a = run_sol144_trim(bulk, cc.subcases[0], aero).trim_vars["ANGLEA"]
        assert a0 == pytest.approx(a, rel=1e-4)


def test_only_the_y_axis_of_cid_is_read(tmp_path):
    """An uncanted CID at the canted CID's origin, y along basic y, projects onto the
    same axis, so the operators equal the hand-canted deck's (to the 8 digits its
    CORD2R cards carry)."""
    flat = ("CORD2R, 12, 0, 0.25, 0.0, 0.0, 0.25, 0.0, 1.0\n+, 1.25, 0.0, 0.0\n"
            "CORD2R, 13, 0, 0.25, 0.0, 0.0, 0.25, 0.0, 1.0\n+, -0.75, 0.0, 0.0\n")
    _cc, _b, _gi, flat_aero = _model(_dihedral_with_cid(tmp_path, 12, 13, flat))
    _cc, _b, _gi, canted_aero = _model(DIHEDRAL)
    assert flat_aero.g_slope == pytest.approx(canted_aero.g_slope, abs=1e-7)
    assert flat_aero.g_disp == pytest.approx(canted_aero.g_disp, abs=1e-7)


def test_cid_y_axis_normal_to_the_panel_is_refused(tmp_path):
    """A y-axis along the panel normal has no projection to act as the axis."""
    normal_y = ("CORD2R, 12, 0, 0.25, 0.0, 0.0, 1.25, 0.0, 0.0\n"
                "+, 0.25, 0.98480775, 0.17364818\n")   # z = basic x, x = the span axis ⇒ y = n
    deck = _dihedral_with_cid(tmp_path, 12, 3, normal_y)
    with pytest.raises(ValueError, match=r"SPLINE2 1601: the y-axis of CID 12 is normal to "
                                         r"the panel \(CAERO1 1100\)"):
        _model(deck)


@pytest.mark.parametrize("path", _SPLINE2_DECKS, ids=lambda p: p.name)
def test_rigid_body_motion_is_reproduced_on_every_repo_deck(path):
    """Invariant gate: a rigid motion of the grids moves each SPLINE2 box along its own
    normal by n.(t + w x r) and gives it the incidence w_y n_z - w_z n_y.

    This holds only when the spline's deflection direction is the box normal.  The
    flagship wing failed it at 4e-4 before #74 (its CID z-axis was 0.024 deg off the
    panel normal)."""
    try:
        _cc, bulk, grid_index, aero = _model(path)
    except ValueError:
        pytest.skip("not a runnable deck (bulk-only overlay or a refused MSC original)")
    ks = _spline2_boxes(bulk, aero)
    if not ks:
        pytest.skip("no SPLINE2")
    modes = _rigid_modes(bulk, grid_index)
    disp = (aero.g_disp @ modes).reshape(len(aero.boxes), 3, 6)
    slope = aero.g_slope @ modes
    scale = max(1.0, float(np.abs(disp).max()))
    for k in ks:
        box = aero.boxes[k]
        n = box.normal
        for d in range(6):
            t = np.eye(3)[d] if d < 3 else np.zeros(3)
            omega = np.eye(3)[d - 3] if d >= 3 else np.zeros(3)
            u = t + np.cross(omega, box.force_point)
            assert disp[k, :, d] == pytest.approx((n @ u) * n, abs=1e-9 * scale), (k, d)
            assert slope[k, d] == pytest.approx(omega[1] * n[2] - omega[2] * n[1], abs=1e-9), (k, d)
