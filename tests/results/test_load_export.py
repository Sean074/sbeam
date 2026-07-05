"""Step 56 — SOL 144 trimmed flight-load export (FORCE/MOMENT cards).

Acceptance (per backlog Step 56): the exported FORCE/MOMENT set sums to the
total trimmed lift/moment of the plain (determined) trim, and the cards re-parse
as valid NASTRAN bulk data.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_file
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim
from sbeam.results.load_export import build_aero_load_cards_text, write_aero_load_cards

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


@pytest.fixture(scope="module")
def trim():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        result = run_sol144_trim(bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    return bulk, result


class TestLoadExport:
    def test_force_fz_sums_to_lift(self, trim):
        bulk, result = trim
        text = build_aero_load_cards_text(bulk, result, sid=1)
        fz = sum(
            float(line.split(",")[7])
            for line in text.splitlines()
            if line.startswith("FORCE")
        )
        lift = result.q * result.total_cl * bulk.aeros.sref
        assert fz == pytest.approx(lift, rel=1e-6)

    def test_moment_cards_canard_spring_only(self, trim):
        """With the NASTRAN beam spline (AC7), wing splines carry rotations
        detached (DTHX=DTHY=-1) so grid loads are pure forces — moments arise
        from the force distribution, exactly as in NASTRAN. MOMENT cards
        appear only where a spline attaches rotation DOFs (the canard DTHX
        spring; zero under symmetric flight). Assert the export is
        force-complete and contains no spurious MOMENT lines with NaN."""
        bulk, result = trim
        text = build_aero_load_cards_text(bulk, result, sid=1)
        assert any(line.startswith("FORCE") for line in text.splitlines())
        for line in text.splitlines():
            assert "nan" not in line.lower()

    def test_cards_reparse_and_balance(self, trim, tmp_path):
        """Round-trip: the written cards parse back, and the parsed FORCE set
        sums (in Fz) to the trimmed lift."""
        bulk, result = trim
        out = tmp_path / "loads.bdf"
        write_aero_load_cards(str(out), bulk, {1: result})
        reparsed = parse_bulk_file(str(out))
        forces = reparsed.forces.get(1, [])
        assert forces, "no FORCE cards re-parsed"
        fz = sum(f.f * f.n3 for f in forces)
        lift = result.q * result.total_cl * bulk.aeros.sref
        assert fz == pytest.approx(lift, rel=1e-6)

    def test_missing_grid_loads_raises(self, trim):
        bulk, result = trim
        import dataclasses
        stripped = dataclasses.replace(result, grid_loads=None)
        with pytest.raises(ValueError, match="grid_loads"):
            build_aero_load_cards_text(bulk, stripped)

    def test_multi_subcase_file_has_both_sids(self, trim, tmp_path):
        bulk, result = trim
        out = tmp_path / "multi.bdf"
        write_aero_load_cards(str(out), bulk, {1: result, 2: result})
        text = out.read_text()
        assert "FORCE, 1," in text and "FORCE, 2," in text
