import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# 5-element cantilever — mirrors the sample/simple_beam.bdf layout
_CANTILEVER = """\
$ 5-element cantilever, 6 nodes at 2 m spacing
GRID, 1, ,  0.0, 0.0, 0.0
GRID, 2, ,  2.0, 0.0, 0.0
GRID, 3, ,  4.0, 0.0, 0.0
GRID, 4, ,  6.0, 0.0, 0.0
GRID, 5, ,  8.0, 0.0, 0.0
GRID, 6, , 10.0, 0.0, 0.0
PBAR, 1, 1, 0.1, 8.333e-4, 8.333e-4, 1.406e-3
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
CBAR, 2, 1, 2, 3, 0.0, 1.0, 0.0
CBAR, 3, 1, 3, 4, 0.0, 1.0, 0.0
CBAR, 4, 1, 4, 5, 0.0, 1.0, 0.0
CBAR, 5, 1, 5, 6, 0.0, 1.0, 0.0
""".splitlines()

# CBAR with pin releases (moment hinges at both ends)
_PINNED_CBAR = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
PBAR, 1, 1, 0.1, 8.333e-4, 8.333e-4, 1.406e-3
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 10, 1, 1, 2, 0.0, 1.0, 0.0
+, 456, 456
""".splitlines()

# Model with PLOTEL and CONM2
_MIXED = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
PBAR, 1, 1, 0.1, 8.333e-4, 8.333e-4, 1.406e-3
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR,   1, 1, 1, 2, 0.0, 1.0, 0.0
PLOTEL, 10, 1, 2
CONM2,  20, 2, 0, 50.0
""".splitlines()


@pytest.fixture(scope="module")
def cantilever():
    return parse_bulk_data(_CANTILEVER)


@pytest.fixture(scope="module")
def pinned():
    return parse_bulk_data(_PINNED_CBAR)


@pytest.fixture(scope="module")
def mixed():
    return parse_bulk_data(_MIXED)


# ---------------------------------------------------------------------------
# CBAR — basic 5-element cantilever
# ---------------------------------------------------------------------------

class TestCbarCantilever:
    def test_cbar_count(self, cantilever):
        assert len(cantilever.cbars) == 5

    def test_cbar_eids_present(self, cantilever):
        for eid in range(1, 6):
            assert eid in cantilever.cbars

    def test_cbar_pid(self, cantilever):
        for eid in range(1, 6):
            assert cantilever.cbars[eid].pid == 1

    def test_cbar_connectivity(self, cantilever):
        expected = {1: (1, 2), 2: (2, 3), 3: (3, 4), 4: (4, 5), 5: (5, 6)}
        for eid, (ga, gb) in expected.items():
            bar = cantilever.cbars[eid]
            assert bar.ga == ga
            assert bar.gb == gb

    def test_cbar_orientation_vector(self, cantilever):
        for eid in range(1, 6):
            bar = cantilever.cbars[eid]
            assert bar.x1 == pytest.approx(0.0)
            assert bar.x2 == pytest.approx(1.0)
            assert bar.x3 == pytest.approx(0.0)

    def test_cbar_default_pin_flags(self, cantilever):
        for eid in range(1, 6):
            assert cantilever.cbars[eid].pa == ""
            assert cantilever.cbars[eid].pb == ""

    def test_cbar_default_offt(self, cantilever):
        for eid in range(1, 6):
            assert cantilever.cbars[eid].offt == "GGG"


# ---------------------------------------------------------------------------
# CBAR — pin releases via continuation line
# ---------------------------------------------------------------------------

class TestCbarPinFlags:
    def test_pin_flag_pa(self, pinned):
        assert pinned.cbars[10].pa == "456"

    def test_pin_flag_pb(self, pinned):
        assert pinned.cbars[10].pb == "456"


# ---------------------------------------------------------------------------
# CBAR — cross-reference validation
# ---------------------------------------------------------------------------

class TestCbarValidation:
    def test_missing_ga_raises(self):
        lines = [
            "GRID, 2, , 1.0, 0.0, 0.0",   # GA=1 is absent
            "PBAR, 1, 1, 0.1, 8.333e-4, 8.333e-4, 1.406e-3",
            "MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0",
            "CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0",
        ]
        with pytest.raises(ValueError, match="GA=1"):
            parse_bulk_data(lines)

    def test_missing_gb_raises(self):
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",   # GB=2 is absent
            "PBAR, 1, 1, 0.1, 8.333e-4, 8.333e-4, 1.406e-3",
            "MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0",
            "CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0",
        ]
        with pytest.raises(ValueError, match="GB=2"):
            parse_bulk_data(lines)

    def test_missing_pbar_raises(self):
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "GRID, 2, , 1.0, 0.0, 0.0",
            # no PBAR defined — PID=99 not found
            "CBAR, 1, 99, 1, 2, 0.0, 1.0, 0.0",
        ]
        with pytest.raises(ValueError, match="PID=99"):
            parse_bulk_data(lines)

    def test_201_cbars_raises(self):
        lines = []
        for i in range(1, 203):    # 202 grids for 201 elements
            lines.append(f"GRID, {i}, , {float(i - 1)}, 0.0, 0.0")
        lines.append("PBAR, 1, 1, 0.1, 8.333e-4, 8.333e-4, 1.406e-3")
        lines.append("MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0")
        for i in range(1, 202):    # 201 CBAR elements — one over the limit
            lines.append(f"CBAR, {i}, 1, {i}, {i + 1}, 0.0, 1.0, 0.0")
        with pytest.raises(ValueError, match="200"):
            parse_bulk_data(lines)


# ---------------------------------------------------------------------------
# PLOTEL
# ---------------------------------------------------------------------------

class TestPlotel:
    def test_plotel_exists(self, mixed):
        assert 10 in mixed.plotels

    def test_plotel_fields(self, mixed):
        p = mixed.plotels[10]
        assert p.eid == 10
        assert p.g1 == 1
        assert p.g2 == 2


# ---------------------------------------------------------------------------
# CONM2
# ---------------------------------------------------------------------------

class TestConm2:
    def test_conm2_exists(self, mixed):
        assert 20 in mixed.conm2s

    def test_conm2_fields(self, mixed):
        c = mixed.conm2s[20]
        assert c.eid == 20
        assert c.gid == 2
        assert c.cid == 0
        assert c.m == pytest.approx(50.0)

    def test_conm2_default_inertia_zero(self, mixed):
        c = mixed.conm2s[20]
        assert c.i11 == pytest.approx(0.0)
        assert c.i22 == pytest.approx(0.0)
        assert c.i33 == pytest.approx(0.0)

    def test_conm2_inertia_free_field(self):
        """Inertia tensor fields parsed correctly from free-field (all on one line)."""
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "CONM2, 5, 1, 0, 10.0, 0.0, 0.0, 0.0, 1.1, 2.2, 3.3, 4.4, 5.5, 6.6",
        ]
        bulk = parse_bulk_data(lines)
        c = bulk.conm2s[5]
        assert c.i11 == pytest.approx(1.1)
        assert c.i21 == pytest.approx(2.2)
        assert c.i22 == pytest.approx(3.3)
        assert c.i31 == pytest.approx(4.4)
        assert c.i32 == pytest.approx(5.5)
        assert c.i33 == pytest.approx(6.6)

    def test_conm2_inertia_fixed_field_continuation(self):
        """Inertia tensor fields parsed from fixed-field continuation line."""
        # GRID in free-field; CONM2 + continuation in fixed-field (8-char columns)
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "CONM2   30      1       0       10.0    0.0     0.0     0.0",
            "+       1.1     2.2     3.3     4.4     5.5     6.6",
        ]
        bulk = parse_bulk_data(lines)
        c = bulk.conm2s[30]
        assert c.i11 == pytest.approx(1.1)
        assert c.i21 == pytest.approx(2.2)
        assert c.i22 == pytest.approx(3.3)
        assert c.i31 == pytest.approx(4.4)
        assert c.i32 == pytest.approx(5.5)
        assert c.i33 == pytest.approx(6.6)

    def test_conm2_nonzero_cid_stored(self):
        """CID != 0 is stored without warning (CORD2R now supported)."""
        lines = [
            "GRID, 1, , 0.0, 0.0, 0.0",
            "CONM2, 1, 1, 5, 10.0",
        ]
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            bulk = parse_bulk_data(lines)
        assert bulk.conm2s[1].cid == 5
