"""#58 gate: AEROS ACSID must be parallel to basic, and the "must be" rules hold.

sbeam takes the freestream along basic +x and never reads ACSID. An ACSID whose axes are
parallel to basic (only its origin moved, as HA144A's CORD2R 1 at x = 12.5) is therefore
equivalent to ACSID = 0. A rotated ACSID would put NASTRAN's flow elsewhere, so it is
refused, including through a CORD2R RID chain.

Rule-3 sweep, documented rules that were not enforced: a GRID SEID, the CBAR G0
orientation form (read as the vector (G0, 0, 0)), and a negative AEROS/TRIM/DIVERG Mach
(β = √(1−M²) is even in M, so it ran as |M|).
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver.sol144 import run_sol144_trim

REPO = Path(__file__).resolve().parents[2]

_BASE = ["GRID, 1, , 0.0, 0.0, 0.0", "GRID, 2, , 1.0, 0.0, 0.0",
         "MAT1, 30, 2.0e11, 8.0e10, 0.25, 7850.0",
         "PBAR, 10, 30, 1.0e-4, 1.0e-8, 1.0e-8, 2.0e-8"]
# CORD2R: A (origin), B (on +z), C (in the +x half of the xz plane)
_TRANSLATED = ["CORD2R, 7, 0, 5., 2., 1., 5., 2., 2.", "+, 6., 2., 1."]
_ROTATED_Z90 = ["CORD2R, 6, 0, 0., 0., 0., 0., 0., 1.", "+, 0., 1., 0."]
_AEROS = "AEROS, {acsid}, 0, 1.0, 8.0, 8.0, 0, 0"


@pytest.mark.parametrize("frames, acsid", [
    (_ROTATED_Z90, 6),
    (_ROTATED_Z90 + ["CORD2R, 9, 6, 3., 0., 0., 3., 0., 1.", "+, 4., 0., 0."], 9),
], ids=["rotated", "translated-inside-rotated"])
def test_rotated_acsid_is_refused(frames, acsid):
    with pytest.raises(ValueError, match=rf"AEROS ACSID={acsid}: CORD2R {acsid} is rotated"):
        parse_bulk_data(_BASE + frames + [_AEROS.format(acsid=acsid)])


@pytest.mark.parametrize("frames, acsid", [
    (_TRANSLATED, 7),
    (_TRANSLATED + ["CORD2R, 8, 7, 1., 1., 1., 1., 1., 2.", "+, 2., 1., 1."], 8),
], ids=["translated", "translated-chain"])
def test_translated_acsid_is_accepted(frames, acsid):
    assert parse_bulk_data(_BASE + frames + [_AEROS.format(acsid=acsid)]).aeros.acsid == acsid


def _trim(bulk):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
        return run_sol144_trim(bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)


def test_ha144a_translated_acsid_equals_basic():
    """The validation benchmark keeps MSC's AEROS, 1, 100: its ACSID is basic moved to
    x = 12.5, and the trim must not depend on it."""
    _cc, bulk = parse_bdf(str(REPO / "sample/ha144a_fullspan_sbeam.bdf"))
    assert bulk.aeros.acsid == 1
    with_acsid = _trim(bulk)
    bulk.aeros.acsid = 0
    basic = _trim(bulk)
    assert with_acsid.trim_vars == pytest.approx(basic.trim_vars, rel=1e-12, abs=1e-14)
    assert np.allclose(with_acsid.displacements, basic.displacements, rtol=1e-12, atol=1e-15)


@pytest.mark.parametrize("card, match", [
    (["GRID, 3, , 2.0, 0.0, 0.0, , , 5"], r"GRID 3: SEID=5 not supported"),
    (["CBAR, 1, 10, 1, 2, 3", "GRID, 3, , 0.0, 1.0, 0.0"], r"CBAR 1: field 6 is the integer 3, which NASTRAN reads as the grid G0"),
    ([_AEROS.format(acsid=0) + ", -0.3"], r"AEROS card: MACH=-0.3 must be non-negative"),
    (["TRIM, 1, -0.5, 1000.0, ANGLEA, 0.1"], r"TRIM 1: MACH=-0.5 must be non-negative"),
    (["DIVERG, 1, 2, 0.3, -0.5"], r"DIVERG 1: every Mach must be non-negative"),
], ids=["GRID-SEID", "CBAR-G0", "AEROS-Mach", "TRIM-Mach", "DIVERG-Mach"])
def test_documented_rules_are_enforced(card, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_BASE + card)


def test_allowed_neighbours_still_parse():
    bulk = parse_bulk_data(_BASE + ["GRID, 3, , 2.0, 0.0, 0.0, , , 0",
                                    "CBAR, 1, 10, 1, 2, 0., 1., 0."])
    assert bulk.cbars[1].x2 == 1.0
