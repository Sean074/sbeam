"""#38 rod element — f06 gate (G7, output part): the ``FORCES / STRESSES IN ROD
ELEMENTS`` blocks appear for CROD and CONROD with the NASTRAN labels (design
note D6), sit on their data (DEF-M13 invariant), and are absent from a rodless
listing."""

import re
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.f06_writer import _FIELD_W, build_f06_sol101_text
from sbeam.solver.sol101 import run_sol101
from tests.assembly.test_rod_element import MIXED_DECK

SAMPLE = Path(__file__).resolve().parents[2] / "sample"


@pytest.fixture(scope="module")
def mixed_f06(tmp_path_factory) -> str:
    f = tmp_path_factory.mktemp("f06") / "mixed.bdf"
    f.write_text(MIXED_DECK)
    cc, bulk = parse_bdf(str(f))
    return build_f06_sol101_text(cc, bulk, run_sol101(bulk, cc.subcases[0]), 1)


def _block(text: str, title: str) -> list[str]:
    lines = text.splitlines()
    i = next(k for k, l in enumerate(lines) if title in l)
    return lines[i:i + 6]


class TestRodBlocks:
    @pytest.mark.parametrize("title", [
        "F O R C E S   I N   R O D   E L E M E N T S      ( C R O D )",
        "F O R C E S   I N   R O D   E L E M E N T S      ( C O N R O D )",
        "S T R E S S E S   I N   R O D   E L E M E N T S      ( C R O D )",
        "S T R E S S E S   I N   R O D   E L E M E N T S      ( C O N R O D )",
    ])
    def test_blocks_present_once(self, mixed_f06, title):
        assert mixed_f06.count(title) == 1

    def test_force_header_labels(self, mixed_f06):
        blk = _block(mixed_f06, "F O R C E S   I N   R O D   E L E M E N T S      ( C R O D )")
        assert blk[2].split() == ["ELEMENT", "AXIAL"]
        assert blk[3].split() == ["ID.", "FORCE", "TORQUE"]
        assert blk[4].split()[0] == "2"
        assert len(re.findall(r"-?\d\.\d{6}E[+-]\d\d", blk[4])) == 2

    def test_stress_header_labels_and_blank_margins(self, mixed_f06):
        blk = _block(mixed_f06, "S T R E S S E S   I N   R O D   E L E M E N T S      ( C O N R O D )")
        assert blk[2].split() == ["ELEMENT", "AXIAL", "SAFETY", "TORSIONAL", "SAFETY"]
        assert blk[3].split() == ["ID.", "STRESS", "MARGIN", "STRESS", "MARGIN"]
        assert blk[4].split()[0] == "3"
        assert len(re.findall(r"-?\d\.\d{6}E[+-]\d\d", blk[4])) == 2

    @pytest.mark.parametrize("title, labels", [
        ("F O R C E S   I N   R O D   E L E M E N T S      ( C R O D )", ("FORCE", "TORQUE")),
        ("S T R E S S E S   I N   R O D   E L E M E N T S      ( C R O D )", ("STRESS", "STRESS")),
    ])
    def test_numeric_labels_sit_on_their_data(self, mixed_f06, title, labels):
        """DEF-M13 invariant: the _FIELD_W characters ending at each label parse as a float."""
        blk = _block(mixed_f06, title)
        header, data = blk[3], blk[4]
        ends = [m.end() for m in re.finditer(r"\S+", header) if m.group(0) in labels]
        assert len(ends) == len(labels)
        for end in ends:
            float(data[end - _FIELD_W:end])

    def test_rod_blocks_follow_the_cbar_blocks(self, mixed_f06):
        i_bar = mixed_f06.index("S T R E S S E S   I N   B A R   E L E M E N T S")
        i_rod = mixed_f06.index("F O R C E S   I N   R O D   E L E M E N T S")
        assert i_bar < i_rod

    def test_rodless_listing_has_no_rod_block(self):
        cc, bulk = parse_bdf(str(SAMPLE / "val_cantilever_static.bdf"))
        text = build_f06_sol101_text(cc, bulk, run_sol101(bulk, cc.subcases[0]), 1)
        assert "R O D   E L E M E N T S" not in text
