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
from sbeam.model.coordinate_system import Cord2r
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

    def test_bar_stress_undefined_points_print_zero(self):
        """NASTRAN layout (#21): all four points print; D, E, F left at (0, 0)
        carry 0.0 bending on both rows, and SA-MAX/MIN still include them."""
        stress_start = self.content.find("S T R E S S E S   I N   B A R")
        rows = _data_rows(self.content[stress_start:])
        assert len(rows) == 2
        sa_row, sb_row = rows
        bs = self.result.bar_stresses[1]
        assert sa_row[0] == pytest.approx(bs.sa1, rel=1e-5)
        assert sa_row[1:4] == [0.0, 0.0, 0.0]
        assert sb_row[1:4] == [0.0, 0.0, 0.0]
        # Root fibre C is compressed (+P in +y), so the row max is the 0.0 point.
        assert bs.sa1 < 0 and sa_row[5] == pytest.approx(bs.axial, abs=1e-6)
        assert sa_row[6] == pytest.approx(bs.axial + bs.sa1, rel=1e-5)


def _data_rows(block: str) -> list[list[float]]:
    """The 13-wide numeric cells of each data row of a CBAR stress block, in order."""
    rows = []
    for line in block.splitlines()[4:]:
        if not line.strip():
            break
        cells = [line[16 + 13 * k:16 + 13 * (k + 1)] for k in range(7)]
        rows.append([float(c) for c in cells if c.strip()])
    return rows


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

    def test_nastran_two_line_header(self):
        """G6 (#21): the NASTRAN-95 / MSC header text and order."""
        lines = self._stress_block().splitlines()
        assert lines[2].split() == ["ELEMENT", "SA1", "SA2", "SA3", "SA4", "AXIAL", "SA-MAX", "SA-MIN", "M.S.-T"]
        assert lines[3].split() == ["ID.", "SB1", "SB2", "SB3", "SB4", "STRESS", "SB-MAX", "SB-MIN", "M.S.-C"]

    def test_two_rows_per_element(self):
        """Row 1 carries EID + SA1–4 + AXIAL + SA-MAX/MIN; row 2 SB1–4 + SB-MAX/MIN
        with the EID and AXIAL cells blank."""
        lines = []
        for l in self._stress_block().splitlines()[4:]:
            if not l.strip():
                break
            lines.append(l)
        assert len(lines) == 2
        assert lines[0][:14].strip() == "1"
        assert lines[1][:14].strip() == ""
        assert lines[1][16 + 13 * 4:16 + 13 * 5].strip() == ""
        rows = _data_rows(self._stress_block())
        assert len(rows[0]) == 7 and len(rows[1]) == 6

    def test_numeric_roundtrip_all_cells(self):
        """Every printed cell parses back to its BarStress field (G6)."""
        rows = _data_rows(self._stress_block())
        bs = self.result.bar_stresses[1]
        exp_a = [bs.sa1, bs.sa2, bs.sa3, bs.sa4, bs.axial, bs.sa_max, bs.sa_min]
        exp_b = [bs.sb1, bs.sb2, bs.sb3, bs.sb4, bs.sb_max, bs.sb_min]
        for got, exp in zip(rows[0], exp_a):
            assert got == pytest.approx(exp, rel=1e-5, abs=1e-9)
        for got, exp in zip(rows[1], exp_b):
            assert got == pytest.approx(exp, rel=1e-5, abs=1e-9)
        # D = (−0.1, 0) is the tension fibre under +P in +y.
        assert bs.sa2 > 0 and bs.sa2 == pytest.approx(-bs.sa1, rel=1e-12)


# ---------------------------------------------------------------------------
# Q1 — SPC reactions are reported in the grid's CD output frame
#
# NASTRAN's "global" output system is the assembly of the per-grid CD frames,
# not basic CID 0.  Reactions are recovered in basic (the frame the SPC acts
# in) and rotated at write time, exactly like the displacement block.
# ---------------------------------------------------------------------------

def _spcforce_row(content: str, gid: int) -> list[float]:
    """Return the six SPCFORCE components written for ``gid``."""
    start = content.find("S I N G L E - P O I N T")
    assert start >= 0, "SPCFORCE block not found"
    block = content[start:]
    prefix = f"{gid:>14}     G  "
    line = next((l for l in block.splitlines() if l.startswith(prefix)), None)
    assert line is not None, f"No SPCFORCE row for grid {gid}"
    vals = line[len(prefix):]
    return [float(vals[13 * i:13 * (i + 1)]) for i in range(6)]


def _write(bulk, cc, result) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".f06", delete=False, mode="w")
    tmp.close()
    try:
        write_f06_sol101(tmp.name, cc, bulk, result, subcase_id=1)
        with open(tmp.name) as fh:
            return fh.read()
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


class TestSpcForceCdFrame:
    """SPCFORCE output frame (backlog Q1)."""

    def test_cd_zero_is_basic(self):
        """With CD = 0 the written row is the raw basic-frame reaction."""
        bulk, cc, result = make_cantilever()
        row = _spcforce_row(_write(bulk, cc, result), 1)
        for i in range(6):
            assert row[i] == pytest.approx(result.reactions[1][i], rel=1e-5, abs=1e-9)

    def test_cd_rotation_applied(self):
        """CD = 90 deg about Z: local X = global Y, local Y = -global X."""
        bulk, cc, result = make_cantilever()
        bulk.cord2rs[1] = Cord2r(cid=1, rid=0, a=(0.0, 0.0, 0.0),
                                 b=(0.0, 0.0, 1.0), c=(0.0, 1.0, 0.0))
        bulk.grids[1].cd = 1
        row = _spcforce_row(_write(bulk, cc, result), 1)

        basic = result.reactions[1]
        # The tip load is +Y, so the basic reaction at the root is dominated by
        # Fy and Mz — Fy must reappear as the local T1 component.
        assert abs(basic[1]) > 1.0
        expected = [basic[1], -basic[0], basic[2],
                    basic[4], -basic[3], basic[5]]
        for i in range(6):
            assert row[i] == pytest.approx(expected[i], rel=1e-5, abs=1e-9)

    def test_stored_reactions_left_in_basic(self):
        """The rotation is presentation-only — Sol101Result stays in basic CID 0.

        ``results/section_cuts.py`` and the monitor-point integrators consume
        ``result.reactions`` as basic-frame vectors; rotating the stored values
        would corrupt them.
        """
        bulk, cc, result = make_cantilever()
        bulk.cord2rs[1] = Cord2r(cid=1, rid=0, a=(0.0, 0.0, 0.0),
                                 b=(0.0, 0.0, 1.0), c=(0.0, 1.0, 0.0))
        bulk.grids[1].cd = 1
        before = result.reactions[1].copy()
        _write(bulk, cc, result)
        assert result.reactions[1] == pytest.approx(before)
