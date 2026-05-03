import pytest

from sbeam.parser.case_control import parse_case_control
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_file

# ---------------------------------------------------------------------------
# Inline BDF strings for unit tests (parse_case_control)
# ---------------------------------------------------------------------------

_STATIC_CC = """\
$ SOL 101 single subcase with all output requests
SOL 101
TITLE = Static Run
SUBCASE 1
  TITLE = Cantilever Tip Load
  SPC   = 1
  LOAD  = 10
  DISPLACEMENT = ALL
  SPCFORCE     = ALL
  FORCE        = ALL
  STRESS       = ALL
BEGIN BULK
""".splitlines()

_MODAL_CC = """\
SOL 103
TITLE = Modal Analysis
SUBCASE 1
  TITLE = First 6 Modes
  SPC    = 2
  METHOD = 5
  DISPLACEMENT = ALL
BEGIN BULK
""".splitlines()

_MULTI_CC = """\
SOL 101
SUBCASE 1
  LOAD = 10
  SPC  = 1
SUBCASE 2
  LOAD = 20
  SPC  = 1
BEGIN BULK
""".splitlines()

_INCLUDE_CC = """\
SOL 101
TITLE = My Model
SUBCASE 1
  LOAD = 10
  SPC  = 1
  DISPLACEMENT = ALL
INCLUDE 'model.dat'
BEGIN BULK
""".splitlines()

# ---------------------------------------------------------------------------
# Inline BDF content for integration tests (parse_bdf via tmp_path)
# ---------------------------------------------------------------------------

_SINGLE_FILE_BDF = """\
SOL 101
SUBCASE 1
  SPC  = 1
  LOAD = 10
  DISPLACEMENT = ALL
BEGIN BULK
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
SPC1, 1, 123456, 1
FORCE, 10, 2, 0, 1000.0, 0.0, 1.0, 0.0
ENDDATA
"""

_RUN_BDF = """\
SOL 101
SUBCASE 1
  SPC  = 1
  LOAD = 10
  DISPLACEMENT = ALL
INCLUDE 'model.dat'
BEGIN BULK
ENDDATA
"""

_MODEL_DAT = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
SPC1, 1, 123456, 1
FORCE, 10, 2, 0, 1000.0, 0.0, 1.0, 0.0
ENDDATA
"""


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cc_static():
    return parse_case_control(_STATIC_CC)


@pytest.fixture(scope="module")
def cc_modal():
    return parse_case_control(_MODAL_CC)


@pytest.fixture(scope="module")
def cc_multi():
    return parse_case_control(_MULTI_CC)


@pytest.fixture(scope="module")
def cc_include():
    return parse_case_control(_INCLUDE_CC)


# ---------------------------------------------------------------------------
# SOL
# ---------------------------------------------------------------------------

class TestSolParsing:
    def test_sol_101_space_syntax(self):
        cc = parse_case_control(["SOL 101", "SUBCASE 1"])
        assert cc.sol == 101

    def test_sol_101_equals_syntax(self):
        cc = parse_case_control(["SOL = 101", "SUBCASE 1"])
        assert cc.sol == 101

    def test_sol_103_accepted(self, cc_modal):
        assert cc_modal.sol == 103

    def test_unsupported_sol_raises(self):
        with pytest.raises(ValueError, match="200"):
            parse_case_control(["SOL 200", "SUBCASE 1"])

    def test_no_sol_raises(self):
        with pytest.raises(ValueError, match="no SOL"):
            parse_case_control(["SUBCASE 1", "  LOAD = 10"])


# ---------------------------------------------------------------------------
# Global title
# ---------------------------------------------------------------------------

class TestGlobalTitle:
    def test_title_parsed(self, cc_static):
        assert cc_static.title == "Static Run"

    def test_title_with_spaces_preserved(self):
        cc = parse_case_control(["SOL 101", "TITLE = Beam with spaces", "SUBCASE 1"])
        assert cc.title == "Beam with spaces"


# ---------------------------------------------------------------------------
# Subcase parsing
# ---------------------------------------------------------------------------

class TestSubcaseParsing:
    def test_single_subcase_count(self, cc_static):
        assert len(cc_static.subcases) == 1

    def test_subcase_id(self, cc_static):
        assert cc_static.subcases[0].subcase_id == 1

    def test_subcase_title(self, cc_static):
        assert cc_static.subcases[0].title == "Cantilever Tip Load"

    def test_load_sid(self, cc_static):
        assert cc_static.subcases[0].load_sid == 10

    def test_spc_sid(self, cc_static):
        assert cc_static.subcases[0].spc_sid == 1


# ---------------------------------------------------------------------------
# Output request flags
# ---------------------------------------------------------------------------

class TestOutputRequests:
    def test_displacement_true(self, cc_static):
        assert cc_static.subcases[0].displacement is True

    def test_spcforce_true(self, cc_static):
        assert cc_static.subcases[0].spcforce is True

    def test_force_true(self, cc_static):
        assert cc_static.subcases[0].force is True

    def test_stress_true(self, cc_static):
        assert cc_static.subcases[0].stress is True

    def test_oload_defaults_false(self, cc_static):
        assert cc_static.subcases[0].oload is False


# ---------------------------------------------------------------------------
# METHOD (SOL 103)
# ---------------------------------------------------------------------------

class TestMethodSid:
    def test_method_sid_sol103(self, cc_modal):
        assert cc_modal.subcases[0].method_sid == 5

    def test_method_sid_defaults_none(self, cc_static):
        assert cc_static.subcases[0].method_sid is None


# ---------------------------------------------------------------------------
# Multiple subcases
# ---------------------------------------------------------------------------

class TestMultipleSubcases:
    def test_two_subcases_count(self, cc_multi):
        assert len(cc_multi.subcases) == 2

    def test_subcase_ids(self, cc_multi):
        assert cc_multi.subcases[0].subcase_id == 1
        assert cc_multi.subcases[1].subcase_id == 2

    def test_subcase1_load_sid(self, cc_multi):
        assert cc_multi.subcases[0].load_sid == 10

    def test_subcase2_load_sid(self, cc_multi):
        assert cc_multi.subcases[1].load_sid == 20


# ---------------------------------------------------------------------------
# INCLUDE path parsing
# ---------------------------------------------------------------------------

class TestIncludeParsing:
    def test_include_path_set(self, cc_include):
        assert cc_include.include == "model.dat"

    def test_include_single_quotes(self):
        cc = parse_case_control(["SOL 101", "INCLUDE 'data/model.dat'", "SUBCASE 1"])
        assert cc.include == "data/model.dat"

    def test_include_double_quotes(self):
        cc = parse_case_control(["SOL 101", 'INCLUDE "data/model.dat"', "SUBCASE 1"])
        assert cc.include == "data/model.dat"

    def test_include_unquoted(self):
        cc = parse_case_control(["SOL 101", "INCLUDE model.dat", "SUBCASE 1"])
        assert cc.include == "model.dat"

    def test_no_include_is_none(self, cc_static):
        assert cc_static.include is None


# ---------------------------------------------------------------------------
# Comment handling
# ---------------------------------------------------------------------------

class TestCommentHandling:
    def test_pure_comment_line_ignored(self):
        cc = parse_case_control([
            "$ this is a comment",
            "SOL 101",
            "SUBCASE 1",
        ])
        assert cc.sol == 101

    def test_inline_comment_stripped(self):
        cc = parse_case_control([
            "SOL 101 $ inline comment",
            "SUBCASE 1",
        ])
        assert cc.sol == 101


# ---------------------------------------------------------------------------
# Integration: parse_bdf — single file
# ---------------------------------------------------------------------------

class TestParseBdfSingleFile:
    def test_sol(self, tmp_path):
        bdf = tmp_path / "run.bdf"
        bdf.write_text(_SINGLE_FILE_BDF)
        cc, bulk = parse_bdf(str(bdf))
        assert cc.sol == 101

    def test_grid_count(self, tmp_path):
        bdf = tmp_path / "run.bdf"
        bdf.write_text(_SINGLE_FILE_BDF)
        cc, bulk = parse_bdf(str(bdf))
        assert len(bulk.grids) == 2

    def test_subcase_load_sid(self, tmp_path):
        bdf = tmp_path / "run.bdf"
        bdf.write_text(_SINGLE_FILE_BDF)
        cc, bulk = parse_bdf(str(bdf))
        assert cc.subcases[0].load_sid == 10

    def test_subcase_spc_sid(self, tmp_path):
        bdf = tmp_path / "run.bdf"
        bdf.write_text(_SINGLE_FILE_BDF)
        cc, bulk = parse_bdf(str(bdf))
        assert cc.subcases[0].spc_sid == 1


# ---------------------------------------------------------------------------
# Integration: parse_bdf — two-file model (INCLUDE)
# ---------------------------------------------------------------------------

class TestParseBdfTwoFile:
    def _write_files(self, tmp_path):
        run_bdf = tmp_path / "run.bdf"
        model_dat = tmp_path / "model.dat"
        run_bdf.write_text(_RUN_BDF)
        model_dat.write_text(_MODEL_DAT)
        return run_bdf

    def test_sol(self, tmp_path):
        run_bdf = self._write_files(tmp_path)
        cc, bulk = parse_bdf(str(run_bdf))
        assert cc.sol == 101

    def test_include_path_stored(self, tmp_path):
        run_bdf = self._write_files(tmp_path)
        cc, bulk = parse_bdf(str(run_bdf))
        assert cc.include == "model.dat"

    def test_grid_count(self, tmp_path):
        run_bdf = self._write_files(tmp_path)
        cc, bulk = parse_bdf(str(run_bdf))
        assert len(bulk.grids) == 2

    def test_subcase_load_sid(self, tmp_path):
        run_bdf = self._write_files(tmp_path)
        cc, bulk = parse_bdf(str(run_bdf))
        assert cc.subcases[0].load_sid == 10

    def test_subcase_spc_sid(self, tmp_path):
        run_bdf = self._write_files(tmp_path)
        cc, bulk = parse_bdf(str(run_bdf))
        assert cc.subcases[0].spc_sid == 1


# ---------------------------------------------------------------------------
# Integration: parse_bdf — error cases
# ---------------------------------------------------------------------------

class TestParseBdfErrors:
    def test_missing_include_raises(self, tmp_path):
        run_bdf = tmp_path / "run.bdf"
        run_bdf.write_text(_RUN_BDF)
        # model.dat intentionally not written
        with pytest.raises(FileNotFoundError, match="model.dat"):
            parse_bdf(str(run_bdf))

    def test_unsupported_sol_raises(self, tmp_path):
        bdf = tmp_path / "bad.bdf"
        bdf.write_text("SOL 200\nBEGIN BULK\nENDDATA\n")
        with pytest.raises(ValueError, match="200"):
            parse_bdf(str(bdf))


# ---------------------------------------------------------------------------
# parse_bulk_file — bulk-data-only loader (no case control required)
# ---------------------------------------------------------------------------

_BULK_ONLY_DAT = """\
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
SPC1, 1, 123456, 1
FORCE, 10, 2, 0, 1000.0, 0.0, 1.0, 0.0
"""

_BULK_WITH_HEADER = """\
BEGIN BULK
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
SPC1, 1, 123456, 1
FORCE, 10, 2, 0, 1000.0, 0.0, 1.0, 0.0
ENDDATA
"""


class TestParseBulkFile:
    def test_raw_dat_no_sol_no_exception(self, tmp_path):
        dat = tmp_path / "model.dat"
        dat.write_text(_BULK_ONLY_DAT)
        bulk = parse_bulk_file(str(dat))
        assert len(bulk.grids) == 2
        assert len(bulk.cbars) == 1

    def test_bdf_with_begin_bulk_header(self, tmp_path):
        bdf = tmp_path / "model.bdf"
        bdf.write_text(_BULK_WITH_HEADER)
        bulk = parse_bulk_file(str(bdf))
        assert len(bulk.grids) == 2
        assert len(bulk.cbars) == 1

    def test_grids_and_properties_correct(self, tmp_path):
        dat = tmp_path / "model.dat"
        dat.write_text(_BULK_ONLY_DAT)
        bulk = parse_bulk_file(str(dat))
        assert bulk.grids[1].x == 0.0
        assert bulk.grids[2].x == 1.0
        assert bulk.pbars[1].A == pytest.approx(0.01)
        assert bulk.mat1s[1].E == pytest.approx(2.0e11)
