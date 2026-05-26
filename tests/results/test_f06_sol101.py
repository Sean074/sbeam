"""Tests for Step 12: .f06 output writer."""

import os
import re
import tempfile
import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Force
from sbeam.model.constraint import Spc1
from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.solver.sol101 import run_sol101
from sbeam.results.f06_writer import write_f06_sol101


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_cantilever():
    E = 2e11
    I = 8.333e-4
    G = E / (2 * 1.3)
    A = 0.05
    J = 2 * I
    L = 1.0
    P = 1000.0

    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=L,   y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=E, G=G, nu=0.3, rho=7850.0)
    bulk.pbars[10] = Pbar(pid=10, mid=1, A=A, I1=I, I2=I, J=J,
                          c1=0.1, c2=0.0)
    bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    bulk.forces[10] = [Force(sid=10, gid=2, cid=0, f=P, n1=0.0, n2=1.0, n3=0.0)]

    cc = CaseControl(
        sol=101,
        title="Cantilever Test",
        subcases=[SubcaseControl(subcase_id=1, load_sid=10, spc_sid=1,
                                 displacement=True, spcforce=True, force=True, stress=True)],
    )
    result = run_sol101(bulk, cc.subcases[0])
    return bulk, cc, result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestF06Sol101:
    def setup_method(self):
        self.bulk, self.cc, self.result = make_cantilever()
        self.tmpfile = tempfile.NamedTemporaryFile(
            suffix=".f06", delete=False, mode="w"
        )
        self.tmpfile.close()
        write_f06_sol101(self.tmpfile.name, self.cc, self.bulk, self.result, subcase_id=1)
        with open(self.tmpfile.name, "r") as fh:
            self.content = fh.read()

    def teardown_method(self):
        try:
            os.unlink(self.tmpfile.name)
        except Exception:
            pass

    def test_contains_displacement_header(self):
        # f06 uses spaced-letter NASTRAN style: "D I S P L A C E M E N T"
        assert "D I S P L A C E M E N T" in self.content or "DISPLACEMENT" in self.content

    def test_contains_spcforce_header(self):
        assert "S I N G L E - P O I N T" in self.content or "SPCFORCE" in self.content.upper()

    def test_contains_bar_forces_header(self):
        # Matches "F O R C E S   I N   B A R" or similar
        assert ("B A R" in self.content or "BAR" in self.content.upper()) and \
               ("F O R C E S" in self.content or "FORCES" in self.content.upper())

    def test_contains_bar_stresses_header(self):
        assert "S T R E S S E S" in self.content or "STRESS" in self.content.upper()

    def test_numeric_values_round_trip(self):
        """Parse tip Ty from DISPLACEMENT section and check it matches the result."""
        # grid 2, Ty = result.displacements[7]
        expected = self.result.displacements[7]

        # Find the displacement line for grid ID 2
        # Format: "             2     G   0.000000E+00 2.000080E-06 ..."
        pattern = re.compile(
            r'^\s+2\s+G\s+([-\d.E+]+)\s+([-\d.E+]+)',
            re.MULTILINE,
        )
        matches = pattern.findall(self.content)
        assert len(matches) > 0, "Could not find grid 2 displacement line"
        # matches[0] = (T1_str, T2_str)
        ty_parsed = float(matches[0][1])
        assert ty_parsed == pytest.approx(expected, rel=1e-5)

    def test_file_not_empty(self):
        assert len(self.content) > 100

    def test_end_of_job_marker(self):
        assert "END OF JOB" in self.content

    def test_bar_stress_only_c_point_when_d_e_f_zero(self):
        """With only c1 set, only one stress row per element (point C) should appear."""
        # Extract the BAR STRESSES block
        stress_start = self.content.find("S T R E S S E S   I N   B A R")
        stress_block = self.content[stress_start:]
        # The existing cantilever PBAR has c1=0.1, d1=d2=e1=e2=f1=f2=0
        # So only one row (C) should appear per element
        pt_lines = [l for l in stress_block.splitlines() if "   C  " in l or "   D  " in l or "   E  " in l or "   F  " in l]
        assert len(pt_lines) == 1, f"Expected 1 recovery point row, got {len(pt_lines)}: {pt_lines}"
        assert "   C  " in pt_lines[0]


def make_cantilever_all_recovery_pts():
    """Cantilever with all four PBAR recovery points defined."""
    E = 2e11
    I = 8.333e-4
    G = E / (2 * 1.3)
    A = 0.05
    J = 2 * I
    L = 1.0
    P = 1000.0

    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=L,   y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=E, G=G, nu=0.3, rho=7850.0)
    bulk.pbars[10] = Pbar(pid=10, mid=1, A=A, I1=I, I2=I, J=J,
                          c1=0.1, c2=0.0,
                          d1=-0.1, d2=0.0,
                          e1=0.0,  e2=0.05,
                          f1=0.0,  f2=-0.05)
    bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    bulk.forces[10] = [Force(sid=10, gid=2, cid=0, f=P, n1=0.0, n2=1.0, n3=0.0)]

    cc = CaseControl(
        sol=101,
        title="Cantilever All Recovery Pts",
        subcases=[SubcaseControl(subcase_id=1, load_sid=10, spc_sid=1,
                                 displacement=True, spcforce=True, force=True, stress=True)],
    )
    result = run_sol101(bulk, cc.subcases[0])
    return bulk, cc, result


class TestF06BarStressAllRecoveryPoints:
    def setup_method(self):
        self.bulk, self.cc, self.result = make_cantilever_all_recovery_pts()
        self.tmpfile = tempfile.NamedTemporaryFile(
            suffix=".f06", delete=False, mode="w"
        )
        self.tmpfile.close()
        write_f06_sol101(self.tmpfile.name, self.cc, self.bulk, self.result, subcase_id=1)
        with open(self.tmpfile.name, "r") as fh:
            self.content = fh.read()

    def teardown_method(self):
        try:
            os.unlink(self.tmpfile.name)
        except Exception:
            pass

    def _stress_block(self):
        start = self.content.find("S T R E S S E S   I N   B A R")
        return self.content[start:]

    def test_all_four_recovery_points_present(self):
        block = self._stress_block()
        for pt in ("C", "D", "E", "F"):
            assert f"   {pt}  " in block, f"Recovery point {pt} not found in stress block"

    def test_exactly_four_stress_rows_for_single_element(self):
        block = self._stress_block()
        pt_lines = [l for l in block.splitlines()
                    if any(f"   {p}  " in l for p in ("C", "D", "E", "F"))]
        assert len(pt_lines) == 4, f"Expected 4 recovery point rows, got {len(pt_lines)}"

    def test_axial_only_on_first_row(self):
        """EID and axial stress appear on the first (C) row; continuation rows have blanks."""
        block = self._stress_block()
        pt_lines = [l for l in block.splitlines()
                    if any(f"   {p}  " in l for p in ("C", "D", "E", "F"))]
        c_line = next(l for l in pt_lines if "   C  " in l)
        assert "1" in c_line[:20]  # EID appears on C row
        for l in pt_lines:
            if "   C  " not in l:
                assert l[:20].strip() == "", f"Non-C row should have blank EID prefix: {l!r}"

    def test_d_point_stress_numeric_roundtrip(self):
        """Parse the D-point SA stress from f06 and compare to result.bar_stresses."""
        block = self._stress_block()
        pt_lines = [l for l in block.splitlines() if "   D  " in l]
        assert len(pt_lines) == 1
        # Format: "...    D  <_fmt(sa)><_fmt(sb)>"
        # _fmt produces 13-char fields; find them after "   D  "
        d_idx = pt_lines[0].index("   D  ")
        vals_str = pt_lines[0][d_idx + 6:]  # skip "   D  "
        sa_parsed = float(vals_str[:13].strip())
        expected = self.result.bar_stresses[1].sa_d
        assert sa_parsed == pytest.approx(expected, rel=1e-5)
