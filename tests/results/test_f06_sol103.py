"""Tests for Step 16: .f06 output for SOL 103."""

import os
import tempfile
import re

import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Eigrl
from sbeam.model.constraint import Spc1
from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.solver.sol103 import run_sol103
from sbeam.results.f06_writer import write_f06_sol103


@pytest.fixture(scope="module")
def cantilever_result():
    bulk = BulkData()
    L_total = 1.0
    n_elem = 10
    le = L_total / n_elem
    for i in range(n_elem + 1):
        gid = i + 1
        bulk.grids[gid] = Grid(gid=gid, x=i * le, y=0.0, z=0.0)
    bulk.pbars[10] = Pbar(pid=10, mid=100, A=0.05, I1=8.333e-4, I2=8.333e-4, J=1.406e-3)
    bulk.mat1s[100] = Mat1(mid=100, E=2.0e11, G=7.692e10, nu=0.3, rho=7850.0)
    for eid in range(1, n_elem + 1):
        bulk.cbars[eid] = Cbar(eid=eid, pid=10, ga=eid, gb=eid + 1,
                               x1=0.0, x2=1.0, x3=0.0)
    bulk.eigrls[20] = Eigrl(sid=20, nd=3, norm="MASS")
    bulk.spc1s[10] = [Spc1(sid=10, c="123456", grids=[1])]

    cc = CaseControl(
        sol=103,
        title="Test cantilever modal",
        subcases=[SubcaseControl(subcase_id=1, spc_sid=10, method_sid=20)],
    )
    result = run_sol103(bulk, cc)
    return bulk, cc, result


@pytest.fixture(scope="module")
def f06_text(cantilever_result):
    bulk, cc, result = cantilever_result
    with tempfile.NamedTemporaryFile(suffix=".f06", delete=False, mode="w") as f:
        path = f.name
    try:
        write_f06_sol103(path, cc, bulk, result)
        with open(path) as f:
            text = f.read()
    finally:
        os.unlink(path)
    return text, result


class TestF06Sol103Headers:
    def test_real_eigenvalue_header(self, f06_text):
        text, _ = f06_text
        assert "REAL   EIGENVALUE" in text or "R E A L   E I G E N V A L U E" in text

    def test_eigenvector_header(self, f06_text):
        text, _ = f06_text
        assert "EIGENVECTOR" in text or "E I G E N V E C T O R" in text

    def test_sol_103_header(self, f06_text):
        text, _ = f06_text
        assert "SOL 103" in text


class TestF06Sol103Values:
    def test_first_frequency_roundtrip(self, f06_text):
        """First frequency in file matches result within 1e-4 relative."""
        text, result = f06_text
        # Find a floating-point number in scientific notation after "FREQ"
        match = re.search(r"FREQ\s*=\s*([0-9Ee.+\-]+)", text)
        assert match is not None, "Could not find FREQ = ... in f06 output"
        freq_from_file = float(match.group(1))
        assert freq_from_file == pytest.approx(result.frequencies_hz[0], rel=1e-4)

    def test_mode_count_matches(self, f06_text):
        """Number of EIGENVECTOR sections equals number of modes."""
        text, result = f06_text
        # Writer uses spaced format: "E I G E N V E C T O R"
        n_sections = text.count("E I G E N V E C T O R")
        assert n_sections == len(result.frequencies_hz)
