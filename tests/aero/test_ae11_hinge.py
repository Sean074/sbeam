"""AE11 — D_jx YAW column, AESURF hinge-axis control column, and hinge-moment
recovery.

Three defects in the lateral/control columns of `build_djx`
(`sbeam/aero/integration.py`) plus a new hinge-moment output
(`sbeam/solver/sol144.py::_compute_hinge_moments`):

  1. YAW used the ROLL column `−(2/bref)·y_ctrl`; the correct yaw-rate sidewash
     on a vertical surface is `−(2/bref)·(x_ctrl − x_ref)·n_y`, vanishing on
     horizontal (z-normal) panels.
  2. AESURF control column ignored the hinge `cid1`; it is now
     `−(ĥ × n)·x̂·eff` about the actual hinge axis `ĥ = cid1` y-axis, which
     reduces to `−n_z·eff` for a spanwise hinge (no HA144A regression).
  3. Hinge-moment derivatives recovered as the moment of the box forces about
     the hinge axis — validated here by an independent closed-form resultant.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Aeros, Caero1, Paero1, Aesurf, Aelist
from sbeam.model.coordinate_system import Cord2r
from sbeam.aero.panel import mesh_caero1
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_djx
from sbeam.solver.sol144 import _compute_hinge_moments
from sbeam.assembly.coord_transform import _get_transform
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.assembly.load_vector import build_grid_index

SAMPLE = Path(__file__).parent.parent.parent / "sample"


def _box_nastran_ids(bulk, boxes):
    """{global k: NASTRAN box id} using build_djx's id convention."""
    out = {}
    for box in boxes:
        caero = bulk.caero1s[box.caero_eid]
        nch = (caero.nchord if caero.nchord > 0
               else len(bulk.aefacts[caero.lchord].data) - 1)
        out[box.k] = box.caero_eid + box.i_span * nch + box.j_chord
    return out


# --------------------------------------------------------------------------- #
# YAW column — vertical fin + horizontal wing
# --------------------------------------------------------------------------- #
def _build_two_panel_bulk():
    """Horizontal wing (z-normal) at x∈[0,1] and a vertical fin (y-normal) at
    x∈[5,6], so YAW must load the fin and ignore the wing."""
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=8.0, sref=8.0,
                       symxz=0, symxy=0)
    bulk.paero1s[1000] = Paero1(pid=1000)
    # Horizontal wing: span along +y → z-normal boxes
    bulk.caero1s[1100] = Caero1(eid=1100, pid=1000, cp=0, nspan=2, nchord=1,
                                lspan=0, lchord=0, igid=1,
                                p1=(0.0, 0.0, 0.0), x12=1.0,
                                p4=(0.0, 4.0, 0.0), x43=1.0)
    # Vertical fin: span along +z → y-normal boxes
    bulk.caero1s[2100] = Caero1(eid=2100, pid=1000, cp=0, nspan=2, nchord=1,
                                lspan=0, lchord=0, igid=1,
                                p1=(5.0, 0.0, 0.0), x12=1.0,
                                p4=(5.0, 0.0, 4.0), x43=1.0)
    return bulk


def _mesh_all(bulk):
    boxes, k0 = [], 0
    for eid in sorted(bulk.caero1s):
        bx = mesh_caero1(bulk.caero1s[eid], bulk.paero1s[1000], bulk.aefacts,
                         bulk.cord2rs, start_k=k0)
        boxes.extend(bx)
        k0 += len(bx)
    return boxes


class TestYawColumn:
    @pytest.fixture(scope="class")
    def ops(self):
        bulk = _build_two_panel_bulk()
        boxes = _mesh_all(bulk)
        return bulk, boxes

    def test_yaw_matches_vertical_sidewash_formula(self, ops):
        """YAW[k] == −(2/bref)·(x_ctrl − x_ref)·n_y for every box (x_ref=0)."""
        bulk, boxes = ops
        b_ref = bulk.aeros.bref
        djx = build_djx(boxes, ["YAW"], bulk)[:, 0]
        expected = np.array([
            -(2.0 / b_ref) * box.colloc[0] * box.normal[1] for box in boxes
        ])
        assert np.allclose(djx, expected, atol=1e-12), (
            f"YAW column {djx} != derived sidewash {expected}"
        )

    def test_yaw_loads_fin_ignores_wing(self, ops):
        """The fin (y-normal) carries the column; the wing (z-normal) sees ~0."""
        bulk, boxes = ops
        djx = build_djx(boxes, ["YAW"], bulk)[:, 0]
        wing = [box.k for box in boxes if box.caero_eid == 1100]
        fin  = [box.k for box in boxes if box.caero_eid == 2100]
        # Wing boxes are z-normal (n_y ≈ 0) → YAW column ≈ 0
        assert np.allclose(djx[wing], 0.0, atol=1e-12)
        # Fin boxes are y-normal and downstream (x>0) → non-zero loading
        assert np.max(np.abs(djx[fin])) > 1e-6
        # On a y-normal fin box, |YAW| == (2/bref)·|x_ctrl|
        for k in fin:
            box = boxes[k]
            assert abs(box.normal[1]) > 0.99       # truly y-normal
            assert np.isclose(abs(djx[k]),
                              (2.0 / bulk.aeros.bref) * abs(box.colloc[0]),
                              atol=1e-12)

    def test_yaw_differs_from_roll(self, ops):
        """YAW is no longer a copy of the ROLL column."""
        bulk, boxes = ops
        djx = build_djx(boxes, ["ROLL", "YAW"], bulk)
        assert not np.allclose(djx[:, 0], djx[:, 1])


# --------------------------------------------------------------------------- #
# AESURF hinge-axis control column
# --------------------------------------------------------------------------- #
class TestAesurfHingeAxis:
    def test_ha144a_spanwise_hinge_no_regression(self):
        """HA144A ELEV hinge (CORD2R 1) is spanwise → new column == old −n_z·eff
        to machine precision."""
        _cc, bulk = parse_bdf(str(SAMPLE / "ha144a_fullspan_sbeam.bdf"))
        gi = build_grid_index(bulk)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            aero = build_aero_model(bulk, grid_index=gi)
        new = build_djx(aero.boxes, ["ELEV"], bulk)[:, 0]

        aesurf = next(a for a in bulk.aesurfs.values() if a.label.upper() == "ELEV")
        ids = _box_nastran_ids(bulk, aero.boxes)
        id_to_k = {v: k for k, v in ids.items()}
        old = np.zeros(len(aero.boxes))
        for bid in bulk.aelists[aesurf.alid1].elements:
            k = id_to_k.get(bid)
            if k is not None:
                old[k] = -aero.boxes[k].normal[2] * aesurf.eff
        assert np.array_equal(new, old), "spanwise-hinge column changed — HA144A regression"

    def test_swept_hinge_uses_cross_product(self):
        """A swept (non-spanwise) hinge must use −(ĥ × n)·x̂, differing from −n_z."""
        bulk = _build_two_panel_bulk()
        # Drop the fin; keep only the horizontal wing as the control surface
        del bulk.caero1s[2100]
        boxes = _mesh_all(bulk)
        # Hinge CID swept 30° about z: y-axis = (−sin, cos, 0)
        th = np.deg2rad(30.0)
        c, s = np.cos(th), np.sin(th)
        # CORD2R: A=origin, B=A+z_axis, C in x-z plane. z stays global z;
        # x-axis rotated so the y-axis (=z×x) is (−sin, cos, 0).
        bulk.cord2rs[7] = Cord2r(cid=7, rid=0,
                                 a=(0.0, 0.0, 0.0),
                                 b=(0.0, 0.0, 1.0),
                                 c=(c, s, 0.0))
        all_ids = sorted(_box_nastran_ids(bulk, boxes).values())
        bulk.aelists[900] = Aelist(sid=900, elements=all_ids)
        bulk.aesurfs[505] = Aesurf(id=505, label="FLAP", cid1=7, alid1=900, eff=1.0)

        djx = build_djx(boxes, ["FLAP"], bulk)[:, 0]
        _o, R = _get_transform(7, bulk.cord2rs)
        h_hat = R[:, 1]
        expected = np.array([-np.cross(h_hat, box.normal)[0] for box in boxes])
        naive = np.array([-box.normal[2] for box in boxes])
        assert np.allclose(djx, expected, atol=1e-12)
        assert not np.allclose(djx, naive), "swept hinge collapsed to the naive −n_z column"


# --------------------------------------------------------------------------- #
# Hinge-moment recovery — independent closed-form resultant
# --------------------------------------------------------------------------- #
class TestHingeMoment:
    def test_uniform_cp_closed_form(self):
        """Flat z-normal control surface, hinge along y at x_hinge, uniform Cp:
        the recovered hinge moment equals the closed-form resultant
        HM = −Σ area·Cp·(x_force − x_hinge)."""
        bulk = _build_two_panel_bulk()
        del bulk.caero1s[2100]                       # horizontal wing only
        # finer chordwise mesh so the lever arm varies across the surface
        bulk.caero1s[1100] = Caero1(eid=1100, pid=1000, cp=0, nspan=2, nchord=3,
                                    lspan=0, lchord=0, igid=1,
                                    p1=(0.0, 0.0, 0.0), x12=2.0,
                                    p4=(0.0, 4.0, 0.0), x43=2.0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            aero = build_aero_model(bulk)            # no splines needed

        ids = _box_nastran_ids(bulk, aero.boxes)
        all_ids = sorted(ids.values())
        bulk.aelists[900] = Aelist(sid=900, elements=all_ids)
        # Hinge at x = 1.0, spanwise y-axis (CORD2R origin carries x_hinge)
        x_hinge = 1.0
        bulk.cord2rs[8] = Cord2r(cid=8, rid=0,
                                 a=(x_hinge, 0.0, 0.0),
                                 b=(x_hinge, 0.0, 1.0),
                                 c=(x_hinge + 1.0, 0.0, 0.0))
        bulk.aesurfs[505] = Aesurf(id=505, label="FLAP", cid1=8, alid1=900, eff=1.0)

        # Uniform Cp field → box force F_j = Cp·area·normal (force/q units)
        cp = 0.7
        n_box = len(aero.boxes)
        f_box = np.zeros(3 * n_box)
        for j, box in enumerate(aero.boxes):
            f_box[3 * j:3 * j + 3] = cp * box.area * box.normal

        hm = _compute_hinge_moments(aero, np.zeros((n_box, 0)), [], bulk, f_box)
        recovered = hm["FLAP"]["total"]

        # Closed form: HM = Σ (r−o)×F · ŷ = −Σ (x_force − x_hinge)·F_z
        closed = -sum(
            (box.force_point[0] - x_hinge) * cp * box.area * box.normal[2]
            for box in aero.boxes
        )
        assert np.isclose(recovered, closed, atol=1e-10, rtol=1e-10), (
            f"hinge moment {recovered} != closed-form resultant {closed}"
        )
        assert abs(recovered) > 1e-6                 # non-trivial
