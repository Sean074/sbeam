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

    @pytest.mark.skip(reason="Requires CAERO1 parser from S40")
    def test_missing_aeros_with_caero1_raises(self):
        """CAERO1 present without AEROS must raise ValueError.

        This test is activated in S40 when _handle_caero1 is wired into the reader.
        The guard `if bulk.caero1s and bulk.aeros is None` is already in place in
        parse_bulk_data — this test just needs CAERO1 to be parseable.
        """
        lines = """\
CAERO1, 100, 1, , 4, 10, , , 1
+, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0
""".splitlines()
        with pytest.raises(ValueError, match="no AEROS card"):
            parse_bulk_data(lines)
