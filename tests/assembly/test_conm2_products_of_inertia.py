"""CONM2 products of inertia follow NASTRAN's sign (#66).

MSC Nastran 2024.1 Quick Reference Guide, PDF p.1449-1450, CONM2 remark 5: the fields
are I21 = ∫ρ x1 x2 dV, I31 = ∫ρ x1 x3 dV, I32 = ∫ρ x2 x3 dV and the inertia matrix is
[[I11, -I21, -I31], [-I21, I22, -I32], [-I31, -I32, I33]]: "The negative signs for the
off-diagonal terms are supplied automatically."  sbeam used the fields unnegated.

The gate needs no sign convention of its own: a body made of point masses has a 6x6 mass
that sbeam already assembles from offset CONM2s with no inertia fields, and one CONM2
carrying that body's NASTRAN-defined inertia must give the same matrix.
"""
import numpy as np
import pytest

from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.model.mass import Conm2
from sbeam.parser.bdf_reader import parse_bulk_data

# Point masses (m, x1, x2, x3) of a body with all three products of inertia non-zero
_POINTS = [(2.0, 0.3, 0.4, -0.2), (1.5, -0.5, 0.1, 0.6), (0.7, 0.2, -0.8, 0.9),
           (1.1, -0.1, -0.3, -0.7)]


_CORD = ["CORD2R, 5, 0, 0., 0., 0., 0.3, 0.2, 1.0", "+, 1.0, 0.4, -0.1"]


def _mass(conm2s):
    bulk = parse_bulk_data(["GRID, 1, , 0., 0., 0."] + _CORD)
    bulk.conm2s = {c.eid: c for c in conm2s}
    return assemble_global_mass(bulk).toarray()


def _body():
    """Total mass, CG and the QRG's Iij about the CG, by direct summation."""
    m = sum(p[0] for p in _POINTS)
    cg = sum(p[0] * np.array(p[1:]) for p in _POINTS) / m
    i = dict.fromkeys(("i11", "i21", "i22", "i31", "i32", "i33"), 0.0)
    for mk, *xyz in _POINTS:
        x1, x2, x3 = np.array(xyz) - cg
        i["i11"] += mk * (x2 ** 2 + x3 ** 2)
        i["i22"] += mk * (x1 ** 2 + x3 ** 2)
        i["i33"] += mk * (x1 ** 2 + x2 ** 2)
        i["i21"] += mk * x1 * x2
        i["i31"] += mk * x1 * x3
        i["i32"] += mk * x2 * x3
    return m, cg, {k: float(v) for k, v in i.items()}


def _point_masses(cid=0):
    return [Conm2(eid=10 + k, gid=1, cid=cid, m=m, x1=x, x2=y, x3=z)
            for k, (m, x, y, z) in enumerate(_POINTS)]


def _one_conm2(cid=0, sign=1.0, offset=True):
    m, cg, i = _body()
    for k in ("i21", "i31", "i32"):
        i[k] *= sign
    x1, x2, x3 = (float(c) for c in cg) if offset else (0.0, 0.0, 0.0)
    return [Conm2(eid=1, gid=1, cid=cid, m=m, x1=x1, x2=x2, x3=x3, **i)]


def test_the_body_has_all_three_products():
    _m, _cg, i = _body()
    assert min(abs(i["i21"]), abs(i["i31"]), abs(i["i32"])) > 0.05


def test_one_conm2_equals_its_point_masses():
    """Before #66 the rotational block differed in all three off-diagonal terms."""
    assert _mass(_one_conm2()) == pytest.approx(_mass(_point_masses()), abs=1e-12)


def test_the_old_sign_does_not():
    """Negated fields (the pre-#66 porting rule) are a different body."""
    diff = _mass(_one_conm2(sign=-1.0)) - _mass(_point_masses())
    assert np.abs(diff).max() > 0.1


def test_in_a_rotated_cid():
    """The same equivalence with offsets and inertia given in a rotated CORD2R."""
    assert _mass(_one_conm2(cid=5)) == pytest.approx(_mass(_point_masses(cid=5)), abs=1e-12)


def test_rotational_block_is_the_qrg_matrix():
    _m, _cg, i = _body()
    block = _mass(_one_conm2(offset=False))[3:, 3:]   # no offset: the block is I about the CG
    assert block == pytest.approx(np.array([
        [i["i11"], -i["i21"], -i["i31"]],
        [-i["i21"], i["i22"], -i["i32"]],
        [-i["i31"], -i["i32"], i["i33"]],
    ]), abs=1e-12)


def test_the_parser_reads_the_fields_in_qrg_order():
    """QRG p.1449: continuation I11 I21 I22 I31 I32 I33."""
    c = parse_bulk_data(["GRID, 1, , 0., 0., 0.", "CONM2, 2, 1, 0, 49.7",
                         "+, 16.2, 1.5, 16.2, 2.5, 3.5, 7.8"]).conm2s[2]
    assert (c.i11, c.i21, c.i22, c.i31, c.i32, c.i33) == (16.2, 1.5, 16.2, 2.5, 3.5, 7.8)
