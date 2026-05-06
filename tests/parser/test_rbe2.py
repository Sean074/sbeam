"""Tests for RBE2 card parsing (Step 36)."""

import pytest
from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.model.bulk_data import BulkData


_FIXED_SIMPLE = """\
GRID    1               0.0     0.0     0.0
GRID    2               1.0     0.0     0.0
RBE2    1       1       123456  2
"""

_FREE_SIMPLE = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
RBE2, 1, 1, 123456, 2
"""

_MULTI_GM_SINGLE_LINE = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
GRID, 3, , 2.0, 0.0, 0.0
GRID, 4, , 3.0, 0.0, 0.0
RBE2, 1, 1, 123456, 2, 3, 4
"""

_MULTI_GM_CONTINUATION = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
GRID, 3, , 2.0, 0.0, 0.0
GRID, 4, , 3.0, 0.0, 0.0
GRID, 5, , 4.0, 0.0, 0.0
GRID, 6, , 5.0, 0.0, 0.0
RBE2, 1, 1, 123456, 2, 3, 4
+, 5, 6
"""

_PARTIAL_DOF = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
RBE2, 5, 1, 12, 2
"""

_MISSING_GN = """\
GRID, 2, , 1.0, 0.0, 0.0
RBE2, 1, 99, 123456, 2
"""

_MISSING_GM = """\
GRID, 1, , 0.0, 0.0, 0.0
RBE2, 1, 1, 123456, 99
"""

_INVALID_CM = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
RBE2, 1, 1, 789, 2
"""


class TestRbe2ParseFixedField:
    @pytest.fixture(autouse=True)
    def bulk(self):
        self._bulk = parse_bulk_data(_FIXED_SIMPLE.splitlines())

    def test_rbe2_in_bulk(self):
        assert 1 in self._bulk.rbe2s

    def test_eid(self):
        assert self._bulk.rbe2s[1].eid == 1

    def test_gn(self):
        assert self._bulk.rbe2s[1].gn == 1

    def test_cm(self):
        assert self._bulk.rbe2s[1].cm == "123456"

    def test_gm_list(self):
        assert self._bulk.rbe2s[1].gm == [2]


class TestRbe2ParseFreeField:
    @pytest.fixture(autouse=True)
    def bulk(self):
        self._bulk = parse_bulk_data(_FREE_SIMPLE.splitlines())

    def test_rbe2_in_bulk(self):
        assert 1 in self._bulk.rbe2s

    def test_gn(self):
        assert self._bulk.rbe2s[1].gn == 1

    def test_cm(self):
        assert self._bulk.rbe2s[1].cm == "123456"

    def test_gm_list(self):
        assert self._bulk.rbe2s[1].gm == [2]


class TestRbe2ParseMultiGmSingleLine:
    def test_gm_list(self):
        bulk = parse_bulk_data(_MULTI_GM_SINGLE_LINE.splitlines())
        assert bulk.rbe2s[1].gm == [2, 3, 4]


class TestRbe2ParseContinuation:
    def test_gm_list(self):
        bulk = parse_bulk_data(_MULTI_GM_CONTINUATION.splitlines())
        assert bulk.rbe2s[1].gm == [2, 3, 4, 5, 6]


class TestRbe2ParsePartialDof:
    def test_cm(self):
        bulk = parse_bulk_data(_PARTIAL_DOF.splitlines())
        assert bulk.rbe2s[5].cm == "12"


class TestRbe2ParseValidation:
    def test_missing_gn_raises(self):
        with pytest.raises(ValueError, match="GN="):
            parse_bulk_data(_MISSING_GN.splitlines())

    def test_missing_gm_raises(self):
        with pytest.raises(ValueError, match="GM="):
            parse_bulk_data(_MISSING_GM.splitlines())

    def test_invalid_cm_raises(self):
        with pytest.raises(ValueError):
            parse_bulk_data(_INVALID_CM.splitlines())
