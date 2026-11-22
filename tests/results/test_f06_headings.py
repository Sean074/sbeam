"""TITLE / SUBTITLE / LABEL page headings (#90; QRG 2024.1 PDF p.679, p.658, p.471)."""
import warnings

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.f06_writer import build_f06_gpwg_text, build_f06_sol103_text
from sbeam.solver.sol103 import run_sol103

_DECK = """SOL 103
TITLE = RUN TITLE
SUBTITLE = RUN SUBTITLE
LABEL = RUN LABEL
SUBCASE 1
  METHOD = 1
  SPC = 1
SUBCASE 2
  TITLE = OWN TITLE
  SUBTITLE = OWN SUBTITLE
  LABEL = OWN LABEL
  METHOD = 1
  SPC = 1
BEGIN BULK
PARAM, GRDPNT, 0
EIGRL, 1, , , 2
GRID, 1, , 0., 0., 0.
GRID, 2, , 1., 0., 0.
MAT1, 1, 1.e7, , 0.3, 0.1
PBAR, 1, 1, 0.1, 1.e-3, 1.e-3, 2.e-3
CBAR, 1, 1, 1, 2, 0., 0., 1.
SPC1, 1, 123456, 1
ENDDATA
"""


@pytest.fixture(scope="module")
def deck(tmp_path_factory):
    path = tmp_path_factory.mktemp("h") / "h.bdf"
    path.write_text(_DECK)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(path)
        return cc, bulk, {sc.subcase_id: run_sol103(bulk, sc) for sc in cc.subcases}


def _head(text):
    return text.split("R E A L   E I G E N V A L U E S")[0]


def test_run_title_and_subtitle_head_a_subcase_without_its_own(deck):
    cc, bulk, res = deck
    head = _head(build_f06_sol103_text(cc, bulk, res[1], 1))
    assert "RUN TITLE" in head and "RUN SUBTITLE" in head
    assert "RUN LABEL" not in head          # a run LABEL heads no subcase (p.471 remark 2)


def test_subcase_headings_override(deck):
    cc, bulk, res = deck
    head = _head(build_f06_sol103_text(cc, bulk, res[2], 2))
    assert all(h in head for h in ("OWN TITLE", "OWN SUBTITLE", "OWN LABEL"))
    assert "RUN TITLE" not in head and "RUN SUBTITLE" not in head


def test_run_label_heads_the_gpwg_block(deck):
    cc, bulk, _res = deck
    text = build_f06_gpwg_text(bulk, cc)
    assert "RUN LABEL" in text and "W E I G H T   G E N E R A T O R" in text
