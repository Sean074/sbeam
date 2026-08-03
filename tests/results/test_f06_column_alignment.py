"""DEF-M13 — general gate: f06 column headers must sit on their data.

DEF-M7 found a 15-character header hand-spaced over 13-character ``_fmt`` data
in the maneuver time-history table; DEF-M13 then measured the identical drift in
five more blocks.  Rather than pin each block's spacing individually, this gate
states the invariant directly:

    for every header line in a real f06 listing, the ``_FIELD_W`` characters
    ending at each column label must parse as a float on the data row below.

A header laid out on ``_hdr`` passes by construction.  A hand-spaced literal at
14 or 15 characters fails as soon as enough columns accumulate the drift, which
is exactly how the defect reached production unnoticed.
"""

import re
import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim
from sbeam.results.f06_writer import build_f06_sol144_text, _FIELD_W

SAMPLE = Path(__file__).parent.parent.parent / "sample"

# Column labels whose data cells are plain _fmt floats.  Deliberately not every
# label in the listing — metadata rows (LABEL:, CID =, SOURCE:) are prose, and
# the PT / TYPE columns hold a letter code, not a number.
_NUMERIC_LABELS = {
    "T1", "T2", "T3", "R1", "R2", "R3",
    "F1", "F2", "F3", "M1", "M2", "M3",
    "FX", "FY", "FZ", "MX", "MY", "MZ",
    "AXIAL FORCE", "SHEAR-1", "SHEAR-2", "TORQUE",
    "BENDING-1 A", "BENDING-2 A", "BENDING-1 B", "BENDING-2 B",
    "AXIAL", "SA(END-A)", "SB(END-B)",
    "DELTA-CP",
}


@pytest.fixture(scope="module")
def f06_text():
    """Full-span HA144A trim with AEROF/APRES on — the widest block coverage."""
    _cc, bulk = parse_bdf(str(SAMPLE / "ha144a_fullspan_sbeam.bdf"))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero
        )
    sc = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1, aerof=True, apres=True)
    cc = CaseControl(sol=144, title="DEF-M13 alignment gate", subcases=[sc])
    return build_f06_sol144_text(cc, bulk, result, 1)


def _label_end_columns(header: str) -> list[tuple[str, int]]:
    """Numeric column labels in a header, with the index just past each label."""
    found = []
    for m in re.finditer(r"\S+(?: \S+)*", header):
        label = m.group(0)
        if label in _NUMERIC_LABELS:
            found.append((label, m.end()))
    return found


def _looks_like_data(line: str) -> bool:
    """A row carrying at least two _fmt-style floats."""
    return len(re.findall(r"-?\d\.\d{6}E[+-]\d\d", line)) >= 2


def test_every_header_cell_sits_on_a_float(f06_text):
    """The _FIELD_W characters ending at each label must parse as a float."""
    lines = f06_text.splitlines()
    checked = 0
    for i, line in enumerate(lines):
        cols = _label_end_columns(line)
        if not cols:
            continue
        # First data row within the next few lines (blank lines may intervene).
        data = next((l for l in lines[i + 1:i + 4] if _looks_like_data(l)), None)
        if data is None:
            continue
        for label, end in cols:
            cell = data[end - _FIELD_W:end]
            assert len(cell) == _FIELD_W, (
                f"header {label!r} at col {end} runs past the data row:\n"
                f"  header: {line!r}\n  data:   {data!r}"
            )
            try:
                float(cell)
            except ValueError:
                pytest.fail(
                    f"column {label!r} (ends col {end}) does not sit on its data: "
                    f"cell {cell!r} is not a float\n"
                    f"  header: {line!r}\n  data:   {data!r}"
                )
            checked += 1
    # Guard the gate itself: if the parser stops recognising headers this test
    # would pass vacuously.
    assert checked >= 30, f"only {checked} header cells checked — gate went blind"


def test_headers_never_abut(f06_text):
    """Adjacent _hdr cells keep at least one space between labels."""
    for line in f06_text.splitlines():
        cols = _label_end_columns(line)
        if len(cols) < 2:
            continue
        for (la, ea), (lb, eb) in zip(cols, cols[1:]):
            gap = (eb - len(lb)) - ea
            assert gap >= 1, f"labels {la!r} and {lb!r} abut in header: {line!r}"
