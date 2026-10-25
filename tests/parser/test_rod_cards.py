"""#38 rod element — parser gate G8: CROD / PROD / CONROD fields, defaults and
validation errors (design note ``docs/30_future/designs/rod_element_crod.md`` D7)."""

import pytest

from sbeam.parser.bdf_reader import parse_bdf

HEAD = """\
SOL 101
SUBCASE 1
  SPC = 1
BEGIN BULK
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
GRID, 3, , 2.0, 0.0, 0.0
MAT1, 1, 2.0e11, 8.0e10, 0.25, 7850.0
PBAR, 1, 1, 1.0e-4, 1.0e-8, 1.0e-8, 2.0e-8
PBUSH, 5, K, 1.0e6, 1.0e6, 1.0e6, 1.0e3, 1.0e3, 1.0e3
SPC1, 1, 123456, 1
"""


def _parse(tmp_path, body: str):
    f = tmp_path / "deck.bdf"
    f.write_text(HEAD + body + "ENDDATA\n")
    return parse_bdf(str(f))[1]


class TestFields:
    def test_prod_and_crod_free_field(self, tmp_path):
        bulk = _parse(tmp_path, "PROD, 2, 1, 1.0e-4, 2.0e-8, 2.0e-3, 0.3\nCROD, 7, 2, 1, 2\n")
        prod = bulk.prods[2]
        assert (prod.mid, prod.A, prod.J, prod.c, prod.nsm) == (1, 1.0e-4, 2.0e-8, 2.0e-3, 0.3)
        crod = bulk.crods[7]
        assert (crod.pid, crod.ga, crod.gb) == (2, 1, 2)

    def test_prod_defaults(self, tmp_path):
        bulk = _parse(tmp_path, "PROD, 2, 1, 1.0e-4\nCROD, 7, 2, 1, 2\n")
        prod = bulk.prods[2]
        assert (prod.J, prod.c, prod.nsm) == (0.0, 0.0, 0.0)

    def test_conrod_fields_and_defaults(self, tmp_path):
        bulk = _parse(tmp_path, "CONROD, 8, 2, 3, 1, 5.0e-4, 1.0e-7, 5.0e-3, 0.1\n"
                                "CONROD, 9, 1, 3, 1, 5.0e-4\n")
        c = bulk.conrods[8]
        assert (c.ga, c.gb, c.mid, c.A, c.J, c.c, c.nsm) == (2, 3, 1, 5.0e-4, 1.0e-7, 5.0e-3, 0.1)
        assert (bulk.conrods[9].J, bulk.conrods[9].c, bulk.conrods[9].nsm) == (0.0, 0.0, 0.0)

    def test_fixed_field(self, tmp_path):
        bulk = _parse(tmp_path,
                      "PROD    2       1       1.0-4   2.0-8   2.0-3\n"
                      "CROD    7       2       1       2\n"
                      "CONROD  8       2       3       1       5.0-4   1.0-7\n")
        assert bulk.prods[2].J == 2.0e-8 and bulk.crods[7].gb == 2
        assert bulk.conrods[8].A == 5.0e-4 and bulk.conrods[8].c == 0.0


class TestValidation:
    @pytest.mark.parametrize("body, msg", [
        ("PROD, 2, 1, 1.0e-4\nCROD, 7, 2, 9, 2\n", r"CROD 7: grid GA=9 not found"),
        ("PROD, 2, 1, 1.0e-4\nCROD, 7, 2, 1, 9\n", r"CROD 7: grid GB=9 not found"),
        ("PROD, 2, 1, 1.0e-4\nCROD, 7, 2, 1, 1\n", r"CROD 7: GA and GB must be different"),
        ("CROD, 7, 2, 1, 2\n", r"CROD 7: property PID=2 not found \(PROD\)"),
        ("PROD, 2, 4, 1.0e-4\nCROD, 7, 2, 1, 2\n", r"CROD 7: PROD 2 material MID=4 not found"),
        ("CONROD, 8, 1, 2, 4, 1.0e-4\n", r"CONROD 8: material MID=4 not found"),
        ("CONROD, 8, 1, 1, 1, 1.0e-4\n", r"CONROD 8: GA and GB must be different"),
        ("PROD, 2, 1, 0.0\n", r"PROD 2: A must be positive"),
        ("PROD, 2, 1, 1.0e-4, -1.0\n", r"PROD 2: J must be non-negative"),
        ("CONROD, 8, 1, 2, 1, -1.0e-4\n", r"CONROD 8: A must be positive"),
        ("PROD, 1, 1, 1.0e-4\n", r"Duplicate PID 1"),
        ("PROD, 2, 1, 1.0e-4\nPROD, 2, 1, 1.0e-4\n", r"Duplicate PID 2"),
    ])
    def test_errors(self, tmp_path, body, msg):
        with pytest.raises(ValueError, match=msg):
            _parse(tmp_path, body)

    def test_pbar_cannot_reuse_a_prod_pid(self, tmp_path):
        with pytest.raises(ValueError, match=r"Duplicate PID 2"):
            _parse(tmp_path, "PROD, 2, 1, 1.0e-4\nPBAR, 2, 1, 1.0e-4\n")

    @pytest.mark.parametrize("first, second, msg", [
        ("CBAR, 7, 1, 1, 2, 0.0, 1.0, 0.0\n", "CROD, 7, 2, 2, 3\n",
         r"CROD 7: duplicate element ID \(already defined by CBAR 7\)"),
        ("CROD, 7, 2, 1, 2\n", "CONROD, 7, 2, 3, 1, 1.0e-4\n",
         r"CONROD 7: duplicate element ID \(already defined by CROD 7\)"),
        ("CONROD, 7, 1, 2, 1, 1.0e-4\n", "CBAR, 7, 1, 2, 3, 0.0, 1.0, 0.0\n",
         r"CBAR 7: duplicate element ID \(already defined by CONROD 7\)"),
        ("CBUSH, 7, 5, 1, 2\n", "CROD, 7, 2, 2, 3\n",
         r"CROD 7: duplicate element ID \(already defined by CBUSH 7\)"),
        ("CBAR, 7, 1, 1, 2, 0.0, 1.0, 0.0\n", "CBAR, 7, 1, 2, 3, 0.0, 1.0, 0.0\n",
         r"CBAR 7: duplicate element ID \(already defined by CBAR 7\)"),
    ])
    def test_element_ids_share_one_space(self, tmp_path, first, second, msg):
        with pytest.raises(ValueError, match=msg):
            _parse(tmp_path, "PROD, 2, 1, 1.0e-4\n" + first + second)

    def test_valid_mixed_deck_parses(self, tmp_path):
        bulk = _parse(tmp_path, "PROD, 2, 1, 1.0e-4\nCBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0\n"
                                "CROD, 2, 2, 2, 3\nCONROD, 3, 1, 3, 1, 1.0e-4\n")
        assert set(bulk.cbars) == {1} and set(bulk.crods) == {2} and set(bulk.conrods) == {3}
