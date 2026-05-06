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
