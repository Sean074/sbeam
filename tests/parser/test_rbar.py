"""Tests for RBAR card parsing (Step 37)."""

import pytest
from sbeam.parser.bdf_reader import parse_bulk_data


_FIXED_SIMPLE = """\
GRID    1               0.0     0.0     0.0
GRID    2               1.0     0.0     0.0
RBAR    1       1       2
"""

_FREE_SIMPLE = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
RBAR, 1, 1, 2
"""

_FREE_EXPLICIT_DEFAULT = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
RBAR, 1, 1, 2, 123456,
"""

_MISSING_GA = """\
GRID, 2, , 1.0, 0.0, 0.0
RBAR, 1, 99, 2
"""

_MISSING_GB = """\
GRID, 1, , 0.0, 0.0, 0.0
RBAR, 1, 1, 99
"""

_SAME_GA_GB = """\
GRID, 1, , 0.0, 0.0, 0.0
RBAR, 1, 1, 1
"""

_NON_DEFAULT_CNA = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
RBAR, 1, 1, 2, 123
"""

_NON_BLANK_CNB = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
RBAR, 1, 1, 2, 123456, 456
"""

_DUPLICATE_EID = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
GRID, 3, , 2.0, 0.0, 0.0
RBAR, 1, 1, 2
RBAR, 1, 1, 3
"""


class TestRbarParseFixedField:
    @pytest.fixture(autouse=True)
    def bulk(self):
        self._bulk = parse_bulk_data(_FIXED_SIMPLE.splitlines())

    def test_rbar_in_bulk(self):
        assert 1 in self._bulk.rbars

    def test_eid(self):
        assert self._bulk.rbars[1].eid == 1

    def test_ga(self):
        assert self._bulk.rbars[1].ga == 1

    def test_gb(self):
        assert self._bulk.rbars[1].gb == 2

    def test_cna_defaults_to_123456(self):
        assert self._bulk.rbars[1].cna == "123456"

    def test_cnb_defaults_to_blank(self):
        assert self._bulk.rbars[1].cnb == ""


class TestRbarParseFreeField:
    @pytest.fixture(autouse=True)
    def bulk(self):
        self._bulk = parse_bulk_data(_FREE_SIMPLE.splitlines())

    def test_rbar_in_bulk(self):
        assert 1 in self._bulk.rbars

    def test_ga(self):
        assert self._bulk.rbars[1].ga == 1

    def test_gb(self):
        assert self._bulk.rbars[1].gb == 2

    def test_cna_default(self):
        assert self._bulk.rbars[1].cna == "123456"

    def test_cnb_default(self):
        assert self._bulk.rbars[1].cnb == ""


class TestRbarParseExplicitDefault:
    def test_explicit_123456_accepted(self):
        bulk = parse_bulk_data(_FREE_EXPLICIT_DEFAULT.splitlines())
        assert bulk.rbars[1].cna == "123456"
        assert bulk.rbars[1].cnb == ""


class TestRbarParseValidation:
    def test_missing_ga_raises(self):
        with pytest.raises(ValueError, match="GA="):
            parse_bulk_data(_MISSING_GA.splitlines())

    def test_missing_gb_raises(self):
        with pytest.raises(ValueError, match="GB="):
            parse_bulk_data(_MISSING_GB.splitlines())

    def test_same_ga_gb_raises(self):
        with pytest.raises(ValueError):
            parse_bulk_data(_SAME_GA_GB.splitlines())

    def test_non_default_cna_raises(self):
        with pytest.raises(ValueError, match="Phase 1"):
            parse_bulk_data(_NON_DEFAULT_CNA.splitlines())

    def test_non_blank_cnb_raises(self):
        with pytest.raises(ValueError, match="Phase 1"):
            parse_bulk_data(_NON_BLANK_CNB.splitlines())

    def test_duplicate_eid_raises(self):
        with pytest.raises(ValueError, match="Duplicate"):
            parse_bulk_data(_DUPLICATE_EID.splitlines())
