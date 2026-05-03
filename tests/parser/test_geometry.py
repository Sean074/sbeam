import warnings

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# 3-node, 2-element cantilever snippet
# Properties and materials are listed before elements (standard BDF order)
_FREE_FIELD = """\
$ 3-node, 2-element cantilever — geometry and properties test
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
GRID, 3, , 2.0, 0.0, 0.0
PBAR, 10, 100, 0.05, 8.333e-4, 8.333e-4, 1.406e-3
+,    0.15811, 0.15811, -0.15811, 0.15811, -0.15811, -0.15811, 0.15811, -0.15811
MAT1, 100, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 10, 1, 2, 0.0, 1.0, 0.0
CBAR, 2, 10, 2, 3, 0.0, 1.0, 0.0
ENDDATA
""".splitlines()

# Fixed-field format: each field is 8 characters wide
# keyword(8) | field2(8) | field3(8) | ...
_FIXED_FIELD = [
    #        GID             CP              X               Y               Z
    "GRID           1               0.0       0.0       0.0",
    "GRID           2               1.0       0.0       0.0",
    # PID            MID             A               I1              I2              J
    "PBAR          10     100     1.0     2.0     3.0     4.0",
    # MID            E               G               NU              RHO
    "MAT1         100   100.0    50.0     0.3     1.0",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bulk_free():
    return parse_bulk_data(_FREE_FIELD)


@pytest.fixture(scope="module")
def bulk_fixed():
    return parse_bulk_data(_FIXED_FIELD)


# ---------------------------------------------------------------------------
# Free-field: GRIDs
# ---------------------------------------------------------------------------

class TestFreeFieldGrids:
    def test_grid_count(self, bulk_free):
        assert len(bulk_free.grids) == 3

    def test_grid_gids_present(self, bulk_free):
        assert 1 in bulk_free.grids
        assert 2 in bulk_free.grids
        assert 3 in bulk_free.grids

    def test_grid_1_coordinates(self, bulk_free):
        g = bulk_free.grids[1]
        assert g.x == pytest.approx(0.0)
        assert g.y == pytest.approx(0.0)
        assert g.z == pytest.approx(0.0)

    def test_grid_2_coordinates(self, bulk_free):
        g = bulk_free.grids[2]
        assert g.x == pytest.approx(1.0)
        assert g.y == pytest.approx(0.0)
        assert g.z == pytest.approx(0.0)

    def test_grid_3_coordinates(self, bulk_free):
        g = bulk_free.grids[3]
        assert g.x == pytest.approx(2.0)
        assert g.y == pytest.approx(0.0)
        assert g.z == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Free-field: PBAR
# ---------------------------------------------------------------------------

class TestFreeFieldPbar:
    def test_pbar_exists(self, bulk_free):
        assert 10 in bulk_free.pbars

    def test_pbar_ids(self, bulk_free):
        p = bulk_free.pbars[10]
        assert p.pid == 10
        assert p.mid == 100

    def test_pbar_section_properties(self, bulk_free):
        p = bulk_free.pbars[10]
        assert p.A  == pytest.approx(0.05)
        assert p.I1 == pytest.approx(8.333e-4)
        assert p.I2 == pytest.approx(8.333e-4)
        assert p.J  == pytest.approx(1.406e-3)

    def test_pbar_recovery_points(self, bulk_free):
        p = bulk_free.pbars[10]
        assert p.c1 == pytest.approx( 0.15811)
        assert p.c2 == pytest.approx( 0.15811)
        assert p.d1 == pytest.approx(-0.15811)
        assert p.d2 == pytest.approx( 0.15811)
        assert p.e1 == pytest.approx(-0.15811)
        assert p.e2 == pytest.approx(-0.15811)
        assert p.f1 == pytest.approx( 0.15811)
        assert p.f2 == pytest.approx(-0.15811)


# ---------------------------------------------------------------------------
# Free-field: MAT1
# ---------------------------------------------------------------------------

class TestFreeFieldMat1:
    def test_mat1_exists(self, bulk_free):
        assert 100 in bulk_free.mat1s

    def test_mat1_ids(self, bulk_free):
        assert bulk_free.mat1s[100].mid == 100

    def test_mat1_values(self, bulk_free):
        m = bulk_free.mat1s[100]
        assert m.E   == pytest.approx(2.0e11)
        assert m.G   == pytest.approx(7.692e10)
        assert m.nu  == pytest.approx(0.3)
        assert m.rho == pytest.approx(7850.0)


# ---------------------------------------------------------------------------
# Fixed-field format
# ---------------------------------------------------------------------------

class TestFixedFieldParsing:
    def test_grid_count(self, bulk_fixed):
        assert len(bulk_fixed.grids) == 2

    def test_grid_1_coordinates(self, bulk_fixed):
        g = bulk_fixed.grids[1]
        assert g.x == pytest.approx(0.0)
        assert g.y == pytest.approx(0.0)
        assert g.z == pytest.approx(0.0)

    def test_grid_2_x_coordinate(self, bulk_fixed):
        assert bulk_fixed.grids[2].x == pytest.approx(1.0)

    def test_pbar_section_properties(self, bulk_fixed):
        p = bulk_fixed.pbars[10]
        assert p.A  == pytest.approx(1.0)
        assert p.I1 == pytest.approx(2.0)
        assert p.I2 == pytest.approx(3.0)
        assert p.J  == pytest.approx(4.0)

    def test_mat1_values(self, bulk_fixed):
        m = bulk_fixed.mat1s[100]
        assert m.E   == pytest.approx(100.0)
        assert m.G   == pytest.approx(50.0)
        assert m.nu  == pytest.approx(0.3)
        assert m.rho == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Error and warning behaviour
# ---------------------------------------------------------------------------

class TestDuplicateGID:
    def test_duplicate_gid_raises(self):
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "GRID, 1, , 5.0, 0.0, 0.0",
        ]
        with pytest.raises(ValueError, match="Duplicate GID 1"):
            parse_bulk_data(lines)


class TestUnknownCard:
    def test_unknown_card_warns(self):
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "UNKNWN, 42, some, data",
        ]
        with pytest.warns(UserWarning, match="UNKNWN"):
            parse_bulk_data(lines)

    def test_unknown_card_data_not_stored(self):
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "UNKNWN, 42, some, data",
        ]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bulk = parse_bulk_data(lines)
        assert len(bulk.grids) == 1
        assert len(bulk.cbars) == 0
