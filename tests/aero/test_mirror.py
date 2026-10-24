"""Tests for mirror_halfspan — unfolding a half-span deck to full-span."""

import pytest

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Aeros, Caero1, Paero1, Set1
from sbeam.model.grid import Grid
from sbeam.model.element import Cbar, Conrod, Crod
from sbeam.model.mass import Conm2
from sbeam.model.property import Prod
from sbeam.aero.aero_model import build_aero_model
from sbeam_tools.common.mirror import mirror_halfspan


def _half_deck() -> BulkData:
    """Minimal half-span model: one wing panel + a centerline and a tip grid."""
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=8.0, sref=8.0,
                       symxz=1, symxy=0)
    bulk.paero1s[1] = Paero1(pid=1)
    bulk.caero1s[1] = Caero1(
        eid=1, pid=1, cp=0, nspan=2, nchord=2, lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=1.0, p4=(0.0, 4.0, 0.0), x43=1.0,
    )
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)   # centerline
    bulk.grids[2] = Grid(gid=2, x=0.0, y=4.0, z=0.0)   # tip (off-centerline)
    bulk.cbars[10] = Cbar(eid=10, pid=1, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0)
    bulk.conm2s[100] = Conm2(eid=100, gid=2, cid=0, m=5.0, x2=0.3, i21=0.7)
    return bulk


class TestMirrorHalfspan:
    def test_rejects_full_span_input(self):
        bulk = _half_deck()
        bulk.aeros.symxz = 0
        with pytest.raises(ValueError, match="not a half-span"):
            mirror_halfspan(bulk)

    def test_clears_symmetry_flags(self):
        out = mirror_halfspan(_half_deck())
        assert out.aeros.symxz == 0
        assert out.aeros.symxy == 0

    def test_does_not_mutate_input(self):
        bulk = _half_deck()
        mirror_halfspan(bulk)
        assert bulk.aeros.symxz == 1          # original untouched
        assert len(bulk.caero1s) == 1

    def test_offcenter_grid_mirrored_centerline_shared(self):
        out = mirror_halfspan(_half_deck())
        # off = next power of 10 above max id (100) = 1000
        assert 1002 in out.grids
        assert out.grids[1002].y == pytest.approx(-4.0)
        assert 1001 not in out.grids          # centerline grid 1 not duplicated
        assert len(out.grids) == 3            # 1, 2, 1002

    def test_cbar_and_conm2_mirrored(self):
        out = mirror_halfspan(_half_deck())
        cb = out.cbars[1010]
        assert cb.ga == 1 and cb.gb == 1002   # centerline end shared, tip mirrored
        assert cb.x3 == 1.0
        cm = out.conm2s[1100]
        assert cm.gid == 1002
        assert cm.x2 == pytest.approx(-0.3)   # y offset reflected
        assert cm.i21 == pytest.approx(-0.7)  # product of inertia reflected

    def test_rods_mirrored_and_prod_shared(self):
        """#38: CROD/CONROD unfold like CBAR (no orientation vector); PROD is shared."""
        bulk = _half_deck()
        bulk.grids[3] = Grid(gid=3, x=0.0, y=2.0, z=-1.0)
        bulk.prods[7] = Prod(pid=7, mid=1, A=1e-4, J=1e-8)
        bulk.crods[20] = Crod(eid=20, pid=7, ga=1, gb=3)
        bulk.conrods[21] = Conrod(eid=21, ga=2, gb=3, mid=1, A=1e-4)
        out = mirror_halfspan(bulk)
        assert out.crods[1020].ga == 1 and out.crods[1020].gb == 1003
        assert out.conrods[1021].ga == 1002 and out.conrods[1021].gb == 1003
        assert out.crods[1020].pid == 7 and set(out.prods) == {7}
        assert set(out.crods) == {20, 1020} and set(out.conrods) == {21, 1021}

    def test_caero1_mirrored_and_buildable(self):
        out = mirror_halfspan(_half_deck())
        ca = out.caero1s[1001]
        assert ca.p4[1] == pytest.approx(-4.0)
        # Full-span model now builds (no SYMXZ guard) with doubled box count.
        model = build_aero_model(out)
        assert len(model.boxes) == 8          # 2 panels × (2×2) boxes

    def test_unsupported_card_raises(self):
        bulk = _half_deck()
        bulk.set1s[1] = Set1(sid=1, grids=[1, 2])
        with pytest.raises(NotImplementedError, match="SET1"):
            mirror_halfspan(bulk)
