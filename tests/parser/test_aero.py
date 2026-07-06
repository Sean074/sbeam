import math

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

# ---------------------------------------------------------------------------
# AEROS — reference geometry + symmetry flags
# ---------------------------------------------------------------------------

_AEROS_FREE = """\
AEROS, 0, 0, 10.0, 40.0, 400.0, 1, 0
""".splitlines()

_AEROS_DEFAULTS = """\
AEROS, , , 5.0, 20.0, 100.0
""".splitlines()

_AEROS_ANTISYM = """\
AEROS, 2, 3, 10.0, 40.0, 400.0, -1, -1
""".splitlines()

# Fixed-field (8-char column) format — columns are 1-based, width 8:
# col  1-8   : AEROS   (keyword)
# col  9-16  : ACSID   = 0 (blank → 0)
# col 17-24  : RCSID   = 0 (blank → 0)
# col 25-32  : CREF    = 10.0
# col 33-40  : BREF    = 40.0
# col 41-48  : SREF    = 400.0
# col 49-56  : SYMXZ   = 1
# col 57-64  : SYMXY   = 0 (blank → 0)
_AEROS_FIXED = "AEROS                   10.0    40.0    400.0   1"


@pytest.fixture(scope="module")
def free_bulk():
    return parse_bulk_data(_AEROS_FREE)


@pytest.fixture(scope="module")
def defaults_bulk():
    return parse_bulk_data(_AEROS_DEFAULTS)


@pytest.fixture(scope="module")
def antisym_bulk():
    return parse_bulk_data(_AEROS_ANTISYM)


class TestAerosRoundTrip:
    def test_aeros_present(self, free_bulk):
        assert free_bulk.aeros is not None

    def test_acsid(self, free_bulk):
        assert free_bulk.aeros.acsid == 0

    def test_rcsid(self, free_bulk):
        assert free_bulk.aeros.rcsid == 0

    def test_cref(self, free_bulk):
        assert free_bulk.aeros.cref == pytest.approx(10.0)

    def test_bref(self, free_bulk):
        assert free_bulk.aeros.bref == pytest.approx(40.0)

    def test_sref(self, free_bulk):
        assert free_bulk.aeros.sref == pytest.approx(400.0)

    def test_symxz_sym(self, free_bulk):
        assert free_bulk.aeros.symxz == 1

    def test_symxy_zero(self, free_bulk):
        assert free_bulk.aeros.symxy == 0


class TestAerosDefaults:
    def test_acsid_defaults_to_zero(self, defaults_bulk):
        assert defaults_bulk.aeros.acsid == 0

    def test_rcsid_defaults_to_zero(self, defaults_bulk):
        assert defaults_bulk.aeros.rcsid == 0

    def test_symxz_defaults_to_zero(self, defaults_bulk):
        assert defaults_bulk.aeros.symxz == 0

    def test_symxy_defaults_to_zero(self, defaults_bulk):
        assert defaults_bulk.aeros.symxy == 0

    def test_cref_parsed(self, defaults_bulk):
        assert defaults_bulk.aeros.cref == pytest.approx(5.0)


class TestAerosAntisym:
    def test_symxz_antisym(self, antisym_bulk):
        assert antisym_bulk.aeros.symxz == -1

    def test_symxy_antisym(self, antisym_bulk):
        assert antisym_bulk.aeros.symxy == -1

    def test_acsid_nonzero(self, antisym_bulk):
        assert antisym_bulk.aeros.acsid == 2

    def test_rcsid_nonzero(self, antisym_bulk):
        assert antisym_bulk.aeros.rcsid == 3


class TestAerosFixedField:
    def test_fixed_field_parses(self):
        bulk = parse_bulk_data([_AEROS_FIXED])
        assert bulk.aeros is not None
        assert bulk.aeros.cref == pytest.approx(10.0)
        assert bulk.aeros.bref == pytest.approx(40.0)
        assert bulk.aeros.sref == pytest.approx(400.0)
        assert bulk.aeros.symxz == 1


class TestAerosValidation:
    def test_duplicate_aeros_raises(self):
        lines = """\
AEROS, 0, 0, 10.0, 40.0, 400.0, 1, 0
AEROS, 0, 0, 5.0, 20.0, 100.0, 0, 0
""".splitlines()
        with pytest.raises(ValueError, match="Duplicate AEROS"):
            parse_bulk_data(lines)

    def test_missing_aeros_with_caero1_raises(self):
        """CAERO1 present without AEROS must raise ValueError."""
        lines = """\
CAERO1, 100, 1, , 4, 10, , , 1
+, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0
""".splitlines()
        with pytest.raises(ValueError, match="no AEROS card"):
            parse_bulk_data(lines)


# ---------------------------------------------------------------------------
# AEFACT
# ---------------------------------------------------------------------------

_AEFACT_SIMPLE = """\
AEFACT, 10, 0.0, 0.25, 0.5, 0.75, 1.0
""".splitlines()

_AEFACT_MULTI_CONT = """\
AEFACT, 20, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6
+, 0.7, 0.8, 0.9, 1.0
""".splitlines()


class TestAefactRoundTrip:
    def test_simple_single_line(self):
        bulk = parse_bulk_data(_AEFACT_SIMPLE)
        af = bulk.aefacts[10]
        assert af.sid == 10
        assert af.data == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])

    def test_multi_continuation(self):
        bulk = parse_bulk_data(_AEFACT_MULTI_CONT)
        af = bulk.aefacts[20]
        assert af.sid == 20
        assert len(af.data) == 11
        assert af.data[0] == pytest.approx(0.0)
        assert af.data[-1] == pytest.approx(1.0)

    def test_duplicate_sid_raises(self):
        lines = """\
AEFACT, 10, 0.0, 1.0
AEFACT, 10, 0.0, 0.5, 1.0
""".splitlines()
        with pytest.raises(ValueError, match="Duplicate AEFACT"):
            parse_bulk_data(lines)


# ---------------------------------------------------------------------------
# PAERO1
# ---------------------------------------------------------------------------

class TestPaero1RoundTrip:
    def test_pid_stored(self):
        bulk = parse_bulk_data(["PAERO1, 1"])
        assert 1 in bulk.paero1s
        assert bulk.paero1s[1].pid == 1

    def test_duplicate_pid_raises(self):
        lines = "PAERO1, 1\nPAERO1, 1".splitlines()
        with pytest.raises(ValueError, match="Duplicate PAERO1"):
            parse_bulk_data(lines)


# ---------------------------------------------------------------------------
# CAERO1
# ---------------------------------------------------------------------------

_CAERO1_NSPAN = """\
AEROS, 0, 0, 2.0, 4.0, 8.0, 1, 0
PAERO1, 1
CAERO1, 100, 1, , 4, 2, , , 0
+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0
""".splitlines()

_CAERO1_LSPAN = """\
AEROS, 0, 0, 2.0, 4.0, 8.0, 0, 0
PAERO1, 1
AEFACT, 10, 0.0, 0.5, 1.0
CAERO1, 200, 1, , 0, 1, 10, 0, 0
+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0
""".splitlines()


class TestCaero1RoundTrip:
    def test_nspan_nchord_form(self):
        bulk = parse_bulk_data(_CAERO1_NSPAN)
        c = bulk.caero1s[100]
        assert c.eid == 100
        assert c.pid == 1
        assert c.cp == 0
        assert c.nspan == 4
        assert c.nchord == 2
        assert c.lspan == 0
        assert c.lchord == 0
        assert c.igid == 0
        assert c.p1 == pytest.approx((0.0, 0.0, 0.0))
        assert c.x12 == pytest.approx(2.0)
        assert c.p4 == pytest.approx((0.0, 4.0, 0.0))
        assert c.x43 == pytest.approx(2.0)

    def test_lspan_form(self):
        bulk = parse_bulk_data(_CAERO1_LSPAN)
        c = bulk.caero1s[200]
        assert c.nspan == 0
        assert c.lspan == 10
        assert c.nchord == 1
        assert c.lchord == 0

    def test_aefact_referenced_by_lspan_stored(self):
        bulk = parse_bulk_data(_CAERO1_LSPAN)
        assert 10 in bulk.aefacts
        assert len(bulk.aefacts[10].data) == 3


class TestCaero1Validation:
    def test_missing_paero1_raises(self):
        lines = """\
AEROS, 0, 0, 2.0, 4.0, 8.0, 0, 0
CAERO1, 100, 1, , 4, 2, , , 0
+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0
""".splitlines()
        with pytest.raises(ValueError, match="PID=1 not found in PAERO1"):
            parse_bulk_data(lines)

    def test_missing_aefact_lspan_raises(self):
        lines = """\
AEROS, 0, 0, 2.0, 4.0, 8.0, 0, 0
PAERO1, 1
CAERO1, 100, 1, , 0, 1, 99, 0, 0
+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0
""".splitlines()
        with pytest.raises(ValueError, match="LSPAN=99 not found in AEFACT"):
            parse_bulk_data(lines)

    def test_duplicate_eid_raises(self):
        lines = """\
AEROS, 0, 0, 2.0, 4.0, 8.0, 0, 0
PAERO1, 1
CAERO1, 100, 1, , 4, 1, , , 0
+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0
CAERO1, 100, 1, , 4, 1, , , 0
+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0
""".splitlines()
        with pytest.raises(ValueError, match="Duplicate CAERO1"):
            parse_bulk_data(lines)

    def test_nspan_and_lspan_both_nonzero_raises(self):
        lines = """\
AEROS, 0, 0, 2.0, 4.0, 8.0, 0, 0
PAERO1, 1
AEFACT, 10, 0.0, 0.5, 1.0
CAERO1, 100, 1, , 4, 1, 10, 0, 0
+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0
""".splitlines()
        with pytest.raises(ValueError, match="NSPAN and LSPAN cannot both be non-zero"):
            parse_bulk_data(lines)

    def test_missing_continuation_raises(self):
        lines = """\
AEROS, 0, 0, 2.0, 4.0, 8.0, 0, 0
PAERO1, 1
CAERO1, 100, 1, , 4, 1, , , 0
""".splitlines()
        with pytest.raises(ValueError, match="continuation line required"):
            parse_bulk_data(lines)


# ---------------------------------------------------------------------------
# W2GJ — per-box normalwash slopes
# ---------------------------------------------------------------------------

_W2GJ_BASE = """\
AEROS, 0, 0, 2.0, 4.0, 8.0, 1, 0
PAERO1, 1
AEFACT, 10, 0.0, 0.5, 1.0
CAERO1, 100, 1, , , 2, 10, , 0
+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0
""".splitlines()


class TestW2gjParser:
    def test_single_line_round_trip(self):
        lines = _W2GJ_BASE + "W2GJ, 1, 100, 0.1, 0.2, 0.1, 0.2".splitlines()
        bulk = parse_bulk_data(lines)
        assert 1 in bulk.w2gjs
        w = bulk.w2gjs[1]
        assert w.sid == 1
        assert w.caero_eid == 100
        assert w.data == pytest.approx([0.1, 0.2, 0.1, 0.2])

    def test_multi_continuation_accumulates(self):
        lines = _W2GJ_BASE + """\
W2GJ, 2, 100, 0.1, 0.2
+, 0.3, 0.4
""".splitlines()
        bulk = parse_bulk_data(lines)
        assert bulk.w2gjs[2].data == pytest.approx([0.1, 0.2, 0.3, 0.4])

    def test_duplicate_sid_raises(self):
        lines = _W2GJ_BASE + """\
W2GJ, 3, 100, 0.1, 0.1, 0.1, 0.1
W2GJ, 3, 100, 0.2, 0.2, 0.2, 0.2
""".splitlines()
        with pytest.raises(ValueError, match="Duplicate W2GJ SID"):
            parse_bulk_data(lines)

    def test_caero_eid_stored(self):
        lines = _W2GJ_BASE + "W2GJ, 5, 100, 0.0, 0.0, 0.0, 0.0".splitlines()
        bulk = parse_bulk_data(lines)
        assert bulk.w2gjs[5].caero_eid == 100


# ---------------------------------------------------------------------------
# CHORDCP — injected steady-pressure distribution (Step 54)
# ---------------------------------------------------------------------------


class TestChordcpParser:
    def test_round_trip_and_degrees_to_radians(self):
        lines = _W2GJ_BASE + """\
CHORDCP, 1, 100, 2.0, 0.6
+, 0.5, 0.4, 0.3, 0.2
""".splitlines()
        bulk = parse_bulk_data(lines)
        c = bulk.chordcps[1]
        assert c.sid == 1
        assert c.caero_eid == 100
        assert c.alpha_ref == pytest.approx(math.radians(2.0))
        assert c.mach == pytest.approx(0.6)
        assert c.data == pytest.approx([0.5, 0.4, 0.3, 0.2])

    def test_data_on_parent_line_and_continuation(self):
        lines = _W2GJ_BASE + """\
CHORDCP, 2, 100, 0.0, , 0.5, 0.4
+, 0.3, 0.2
""".splitlines()
        bulk = parse_bulk_data(lines)
        c = bulk.chordcps[2]
        assert c.alpha_ref == 0.0
        assert c.mach == 0.0
        assert c.data == pytest.approx([0.5, 0.4, 0.3, 0.2])

    def test_missing_alphref_raises(self):
        lines = _W2GJ_BASE + """\
CHORDCP, 3, 100
+, 0.5, 0.4, 0.3, 0.2
""".splitlines()
        with pytest.raises(ValueError, match="ALPHREF.*required"):
            parse_bulk_data(lines)

    def test_missing_data_raises(self):
        lines = _W2GJ_BASE + "CHORDCP, 4, 100, 1.0".splitlines()
        with pytest.raises(ValueError, match="no Cp data"):
            parse_bulk_data(lines)

    def test_duplicate_sid_raises(self):
        lines = _W2GJ_BASE + """\
CHORDCP, 5, 100, 1.0, , 0.5, 0.4, 0.3, 0.2
CHORDCP, 5, 100, 1.0, , 0.5, 0.4, 0.3, 0.2
""".splitlines()
        with pytest.raises(ValueError, match="Duplicate CHORDCP SID"):
            parse_bulk_data(lines)
