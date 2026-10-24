"""G1 — the rate columns are rigid-body kinematics, derived independently (#8, DEF-M15).

Design note ``docs/30_future/designs/lateral_cases_aileron_rudder.md`` §2.1.  A rigid
body rate about a basic axis gives every box collocation point a body velocity
``v = axis × (r − ref)`` (translations: the unit vector); the relative wind is ``−v``,
and with the ``D_jx`` sign convention fixed by ANGLEA (``−n_z``) the physical-rate
normalwash is ``+n̂·v/V``.  ``build_dj_rigidrate`` must reproduce that for DOFs 2–6
on every deck, with the velocity field built here from ``assembly/rigid_body.py`` —
never from ``build_djx``, ``rigid_rate_scales`` or the label table, so a sign error in
any of those cannot pass by agreeing with itself (the pre-#8 failure mode).
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_dj_rigidrate, build_djx, rigid_rate_scales
from sbeam.assembly.coord_transform import get_transform
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.rigid_body import build_rigid_vectors_g
from sbeam.model.aero import require_aeros
from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_file

SAMPLE = Path(__file__).parent.parent.parent / "sample"
V = 70.0
DOFS = [2, 3, 4, 5, 6]


def _load(name, run_file):
    path = SAMPLE / name
    if run_file:
        _cc, bulk = parse_bdf(str(path))
    else:
        bulk = parse_bulk_file(str(path))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    aeros = require_aeros(bulk)
    ref = (np.asarray(get_transform(aeros.rcsid, bulk.cord2rs)[0], dtype=float)
           if aeros.rcsid else np.zeros(3))
    return bulk, aero, ref


@pytest.fixture(scope="module", params=[
    ("cessna210_flagship_trim.bdf", True),   # wing + HTP + vertical fin, dihedral, RCSID off origin
    ("val_vlm_rect_ar8.bdf", False),         # planar wing, RCSID 0
    ("val_vlm_dihedral.bdf", False),         # canted normals
], ids=lambda p: p[0])
def deck(request):
    return _load(*request.param)


def _velocity_field_at_colloc(bulk, aero, ref, dof):
    """Unit rigid-body velocity at every collocation point, from rigid_body.py.

    The rigid vectors are defined on grids; a one-grid throwaway model placed at
    each collocation point reads the same primitive at the box location.
    """
    v = np.zeros((len(aero.boxes), 3))
    for box in aero.boxes:
        b = BulkData()
        b.grids[1] = Grid(gid=1, x=float(box.colloc[0]), y=float(box.colloc[1]), z=float(box.colloc[2]))
        phi = build_rigid_vectors_g(b, {1: 0}, [dof], ref)
        v[box.k] = phi[0:3, 0]
    return v


def test_physical_rate_columns_are_the_normal_projected_body_velocity(deck):
    """Column k of build_dj_rigidrate == (1/V)·n̂·v_k(r_colloc), DOFs 2–6."""
    bulk, aero, ref = deck
    got = build_dj_rigidrate(aero.boxes, DOFS, bulk, V)
    normals = np.array([b.normal for b in aero.boxes])
    for k, dof in enumerate(DOFS):
        v = _velocity_field_at_colloc(bulk, aero, ref, dof)
        expected = np.einsum("ij,ij->i", normals, v) / V
        np.testing.assert_allclose(got[:, k], expected, rtol=1e-12, atol=1e-15,
                                   err_msg=f"DOF {dof}")


def test_surge_column_is_zero(deck):
    bulk, aero, _ = deck
    assert not np.any(build_dj_rigidrate(aero.boxes, [1], bulk, V)[:, 0])


def test_scales_follow_from_the_identity_not_the_other_way_round():
    """The sign table is a consequence: DOFs 2/4/6 negative, 3 negative, 5 positive."""
    bulk = parse_bulk_file(str(SAMPLE / "val_vlm_rect_ar8.bdf"))
    s = rigid_rate_scales(bulk, V)
    a = require_aeros(bulk)
    assert s == {1: 0.0, 2: -1 / V, 3: -1 / V, 4: -a.bref / (2 * V),
                 5: a.cref / (2 * V), 6: -a.bref / (2 * V)}


def test_vertical_fin_sees_no_pitch_rate_and_sees_roll_rate_through_its_height():
    """Flagship fin (36 boxes, normal +y, above the roll axis): PITCH column exactly
    zero, ROLL column (2/b)·n_y·(z − z_ref) — the pre-#8 column loaded the fin under
    pitch rate (CY = 1.88 per unit PITCH) and ignored it under roll rate."""
    bulk, aero, ref = _load("cessna210_flagship_trim.bdf", True)
    djx = build_djx(aero.boxes, ["PITCH", "ROLL", "YAW"], bulk, id_to_k=aero.require_box_id_to_k())
    fin = [b.k for b in aero.boxes if abs(b.normal[1]) > 0.9]
    assert len(fin) == 36
    assert not np.any(djx[fin, 0])
    b_ref = require_aeros(bulk).bref
    expected_roll = [(2.0 / b_ref) * aero.boxes[k].normal[1] * (aero.boxes[k].colloc[2] - ref[2]) for k in fin]
    np.testing.assert_allclose(djx[fin, 1], expected_roll, rtol=1e-12)
    expected_yaw = [-(2.0 / b_ref) * aero.boxes[k].normal[1] * (aero.boxes[k].colloc[0] - ref[0]) for k in fin]
    np.testing.assert_allclose(djx[fin, 2], expected_yaw, rtol=1e-12)


def test_roll_column_is_about_the_rcsid_origin_not_y_zero():
    """D3: shift the RCSID origin sideways and the ROLL column shifts with it."""
    bulk = parse_bulk_file(str(SAMPLE / "val_vlm_rect_ar8.bdf"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    base = build_djx(aero.boxes, ["ROLL"], bulk)[:, 0]
    from sbeam.model.coordinate_system import Cord2r
    bulk.cord2rs[77] = Cord2r(cid=77, rid=0, a=(0.0, 1.5, 0.0), b=(0.0, 1.5, 1.0), c=(1.0, 1.5, 0.0))
    bulk.aeros.rcsid = 77
    shifted = build_djx(aero.boxes, ["ROLL"], bulk)[:, 0]
    b_ref = require_aeros(bulk).bref
    nz = np.array([b.normal[2] for b in aero.boxes])
    np.testing.assert_allclose(shifted - base, (2.0 / b_ref) * 1.5 * nz, rtol=1e-12)
