import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# Two load sets (FORCE SID=10, MOMENT SID=20) combined by LOAD SID=100,
# one SPC1 set (SID=1), one EIGRL (SID=5)
_FULL = """\
GRID, 1, ,  0.0, 0.0, 0.0
GRID, 2, ,  1.0, 0.0, 0.0
GRID, 3, ,  2.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
CBAR, 2, 1, 2, 3, 0.0, 1.0, 0.0
SPC1, 1, 123456, 1
FORCE,  10, 3, 0, 1000.0, 0.0, 1.0, 0.0
MOMENT, 20, 3, 0,  250.0, 0.0, 0.0, 1.0
LOAD, 100, 1.0, 1.0, 10, 2.0, 20
EIGRL, 5, , , 6
""".splitlines()

# SPC card constraining two grid pairs on one line
_SPC_CARD = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
SPC, 1, 1, 123456, 0.0, 2, 123456, 0.0
""".splitlines()


@pytest.fixture(scope="module")
def full():
    return parse_bulk_data(_FULL)


@pytest.fixture(scope="module")
def spc_model():
    return parse_bulk_data(_SPC_CARD)


# ---------------------------------------------------------------------------
# SPC1
# ---------------------------------------------------------------------------

class TestSpc1:
    def test_spc1_set_exists(self, full):
        assert 1 in full.spc1s

    def test_spc1_dof_string(self, full):
        assert full.spc1s[1][0].c == "123456"

    def test_spc1_grids(self, full):
        assert full.spc1s[1][0].grids == [1]


# ---------------------------------------------------------------------------
# SPC
# ---------------------------------------------------------------------------

class TestSpc:
    def test_spc_set_exists(self, spc_model):
        assert 1 in spc_model.spcs

    def test_spc_first_pair(self, spc_model):
        spc = spc_model.spcs[1][0]
        assert spc.g1 == 1
        assert spc.c1 == "123456"

    def test_spc_second_pair(self, spc_model):
        spc = spc_model.spcs[1][0]
        assert spc.g2 == 2
        assert spc.c2 == "123456"


# ---------------------------------------------------------------------------
# FORCE
# ---------------------------------------------------------------------------

class TestForce:
    def test_force_set_exists(self, full):
        assert 10 in full.forces

    def test_force_fields(self, full):
        f = full.forces[10][0]
        assert f.sid == 10
        assert f.gid == 3
        assert f.cid == 0
        assert f.f == pytest.approx(1000.0)
        assert f.n1 == pytest.approx(0.0)
        assert f.n2 == pytest.approx(1.0)
        assert f.n3 == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# MOMENT
# ---------------------------------------------------------------------------

class TestMoment:
    def test_moment_set_exists(self, full):
        assert 20 in full.moments

    def test_moment_fields(self, full):
        m = full.moments[20][0]
        assert m.sid == 20
        assert m.gid == 3
        assert m.cid == 0
        assert m.m == pytest.approx(250.0)
        assert m.n1 == pytest.approx(0.0)
        assert m.n2 == pytest.approx(0.0)
        assert m.n3 == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# LOAD combination
# ---------------------------------------------------------------------------

class TestLoad:
    def test_load_exists(self, full):
        assert 100 in full.loads

    def test_load_overall_scale(self, full):
        assert full.loads[100].s == pytest.approx(1.0)

    def test_load_components(self, full):
        components = full.loads[100].components
        assert len(components) == 2
        assert components[0][0] == pytest.approx(1.0)
        assert components[0][1] == 10
        assert components[1][0] == pytest.approx(2.0)
        assert components[1][1] == 20


# ---------------------------------------------------------------------------
# EIGRL
# ---------------------------------------------------------------------------

class TestEigrl:
    def test_eigrl_exists(self, full):
        assert 5 in full.eigrls

    def test_eigrl_nd(self, full):
        assert full.eigrls[5].nd == 6

    def test_eigrl_default_bounds(self, full):
        e = full.eigrls[5]
        assert e.v1 is None
        assert e.v2 is None

    def test_eigrl_default_norm(self, full):
        assert full.eigrls[5].norm == "MASS"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_invalid_dof_zero_raises(self):
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "SPC1, 1, 0, 1",
        ]
        with pytest.raises(ValueError, match="invalid DOF"):
            parse_bulk_data(lines)

    def test_missing_load_component_raises(self):
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "GRID, 2, , 1.0, 0.0, 0.0",
            "PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5",
            "MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0",
            "CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0",
            "LOAD, 100, 1.0, 1.0, 999",
        ]
        with pytest.raises(ValueError, match="999"):
            parse_bulk_data(lines)
