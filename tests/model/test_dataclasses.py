"""Tests for Step 2: BDF card dataclasses."""


from sbeam.model.grid import Grid
from sbeam.model.element import Cbar, Plotel, Rbe3
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Force, Moment, Load, Eigrl
from sbeam.model.constraint import Spc, Spc1
from sbeam.model.mass import Conm2
from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl, CaseControl


class TestGrid:
    def test_basic(self):
        g = Grid(gid=1, x=0.0, y=1.0, z=2.0)
        assert g.gid == 1
        assert g.x == 0.0
        assert g.y == 1.0
        assert g.z == 2.0
        assert g.ps == ""

    def test_with_ps(self):
        g = Grid(gid=10, x=1.0, y=0.0, z=0.0, ps="123456")
        assert g.ps == "123456"


class TestCbar:
    def test_basic(self):
        e = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0)
        assert e.eid == 1
        assert e.pid == 10
        assert e.ga == 1
        assert e.gb == 2
        assert e.x1 == 0.0
        assert e.x2 == 0.0
        assert e.x3 == 1.0
        assert e.offt == "GGG"
        assert e.pa == ""
        assert e.pb == ""

    def test_pin_releases(self):
        e = Cbar(eid=2, pid=10, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0, pa="456", pb="456")
        assert e.pa == "456"
        assert e.pb == "456"


class TestPlotel:
    def test_basic(self):
        p = Plotel(eid=100, g1=1, g2=2)
        assert p.eid == 100
        assert p.g1 == 1
        assert p.g2 == 2


class TestRbe3:
    def test_basic(self):
        r = Rbe3(eid=200, refgrid=1, refc="123")
        assert r.eid == 200
        assert r.refgrid == 1
        assert r.refc == "123"
        assert r.wt_gc == []

    def test_with_components(self):
        r = Rbe3(eid=201, refgrid=5, refc="123", wt_gc=[(1.0, "123", [2, 3, 4])])
        assert len(r.wt_gc) == 1


class TestPbar:
    def test_basic(self):
        p = Pbar(pid=10, mid=1, A=0.01, I1=1e-5, I2=1e-5, J=2e-5)
        assert p.pid == 10
        assert p.mid == 1
        assert p.A == 0.01
        assert p.I1 == 1e-5
        assert p.I2 == 1e-5
        assert p.J == 2e-5
        assert p.nsm == 0.0

    def test_recovery_points(self):
        p = Pbar(pid=10, mid=1, A=0.01, I1=1e-5, I2=1e-5, J=2e-5,
                 c1=0.05, c2=0.05, d1=-0.05, d2=0.05)
        assert p.c1 == 0.05
        assert p.c2 == 0.05
        assert p.d1 == -0.05

    def test_defaults(self):
        p = Pbar(pid=1, mid=1, A=1.0, I1=1.0, I2=1.0, J=1.0)
        for attr in ("nsm", "c1", "c2", "d1", "d2", "e1", "e2", "f1", "f2"):
            assert getattr(p, attr) == 0.0


class TestMat1:
    def test_basic(self):
        m = Mat1(mid=1, E=200e9, G=77e9, nu=0.3, rho=7800.0)
        assert m.mid == 1
        assert m.E == 200e9
        assert m.G == 77e9
        assert m.nu == 0.3
        assert m.rho == 7800.0


class TestForce:
    def test_basic(self):
        f = Force(sid=1, gid=5, cid=0, f=1000.0, n1=0.0, n2=1.0, n3=0.0)
        assert f.sid == 1
        assert f.gid == 5
        assert f.f == 1000.0
        assert f.n2 == 1.0


class TestMoment:
    def test_basic(self):
        m = Moment(sid=2, gid=5, cid=0, m=500.0, n1=0.0, n2=0.0, n3=1.0)
        assert m.sid == 2
        assert m.m == 500.0
        assert m.n3 == 1.0


class TestLoad:
    def test_basic(self):
        ld = Load(sid=10, s=1.0, components=[(1.0, 1), (2.0, 2)])
        assert ld.sid == 10
        assert ld.s == 1.0
        assert len(ld.components) == 2

    def test_default_components(self):
        ld = Load(sid=11, s=1.5)
        assert ld.components == []


class TestEigrl:
    def test_defaults(self):
        e = Eigrl(sid=1)
        assert e.v1 is None
        assert e.v2 is None
        assert e.nd is None
        assert e.norm == "MASS"

    def test_with_values(self):
        e = Eigrl(sid=1, v1=0.0, v2=100.0, nd=10, norm="MAX")
        assert e.v2 == 100.0
        assert e.nd == 10
        assert e.norm == "MAX"


class TestSpc:
    def test_basic(self):
        s = Spc(sid=1, g1=1, c1="123456")
        assert s.sid == 1
        assert s.g1 == 1
        assert s.c1 == "123456"
        assert s.d1 == 0.0
        assert s.g2 is None

    def test_two_grids(self):
        s = Spc(sid=1, g1=1, c1="123", g2=2, c2="456")
        assert s.g2 == 2
        assert s.c2 == "456"


class TestSpc1:
    def test_basic(self):
        s = Spc1(sid=1, c="123456", grids=[1, 2, 3])
        assert s.sid == 1
        assert s.c == "123456"
        assert s.grids == [1, 2, 3]

    def test_default_grids(self):
        s = Spc1(sid=2, c="3")
        assert s.grids == []


class TestConm2:
    def test_basic(self):
        c = Conm2(eid=1, gid=5, cid=0, m=10.0)
        assert c.eid == 1
        assert c.gid == 5
        assert c.cid == 0
        assert c.m == 10.0


class TestBulkData:
    def test_empty(self):
        bd = BulkData()
        assert bd.grids == {}
        assert bd.cbars == {}
        assert bd.plotels == {}
        assert bd.rbe3s == {}
        assert bd.pbars == {}
        assert bd.mat1s == {}
        assert bd.conm2s == {}
        assert bd.spcs == {}
        assert bd.spc1s == {}
        assert bd.forces == {}
        assert bd.moments == {}
        assert bd.loads == {}
        assert bd.eigrls == {}

    def test_add_cards(self):
        bd = BulkData()
        bd.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        bd.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
        bd.mat1s[1] = Mat1(mid=1, E=200e9, G=77e9, nu=0.3, rho=7800.0)
        bd.pbars[10] = Pbar(pid=10, mid=1, A=0.01, I1=1e-5, I2=1e-5, J=2e-5)
        bd.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0)
        bd.forces[1] = [Force(sid=1, gid=2, cid=0, f=1000.0, n1=0.0, n2=1.0, n3=0.0)]
        bd.spcs[1] = [Spc(sid=1, g1=1, c1="123456")]

        assert len(bd.grids) == 2
        assert len(bd.cbars) == 1
        assert bd.pbars[10].A == 0.01
        assert bd.forces[1][0].f == 1000.0

    def test_independent_instances(self):
        bd1 = BulkData()
        bd2 = BulkData()
        bd1.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        assert len(bd2.grids) == 0


class TestSubcaseControl:
    def test_defaults(self):
        sc = SubcaseControl(subcase_id=1)
        assert sc.subcase_id == 1
        assert sc.title == ""
        assert sc.load_sid is None
        assert sc.spc_sid is None
        assert sc.method_sid is None
        assert sc.displacement is False
        assert sc.spcforce is False
        assert sc.oload is False
        assert sc.force is False
        assert sc.stress is False

    def test_with_values(self):
        sc = SubcaseControl(subcase_id=1, title="STATIC RUN", load_sid=10, spc_sid=1,
                            displacement=True, spcforce=True)
        assert sc.title == "STATIC RUN"
        assert sc.load_sid == 10
        assert sc.displacement is True


class TestCaseControl:
    def test_defaults(self):
        cc = CaseControl(sol=101)
        assert cc.sol == 101
        assert cc.title == ""
        assert cc.subcases == []
        assert cc.include is None

    def test_with_subcases(self):
        sc = SubcaseControl(subcase_id=1, load_sid=10, spc_sid=1)
        cc = CaseControl(sol=101, title="TEST", subcases=[sc], include="model.dat")
        assert cc.sol == 101
        assert len(cc.subcases) == 1
        assert cc.include == "model.dat"
