"""#55 gate: a card sbeam cannot honour refuses the deck instead of being skipped.

Before #55 any keyword that was neither handled nor in ``_UNSUPPORTED_CARDS`` was skipped
with a ``UserWarning``. ``DMI,W2GJ`` therefore dropped HA144A's 0.1° wing incidence, a
typo such as ``FROCE`` dropped a load, and ``PARAM,AUNITS`` (URDD* in g) left a 1 g trim
at 1 model-unit/s². Now:

- the DMI family and TABDMP1 are listed as unsupported;
- every other unknown keyword is refused, with the nearest supported keyword suggested;
- only ``_HARMLESS_CARDS`` (listing control) are ignored with a warning;
- PARAM stays warn-by-default, but AUNITS ≠ 1 and COUPMASS ≤ 0 (lumped mass; sbeam is
  always consistent) are refused, like WTMASS (#39).
"""

import warnings
from pathlib import Path

import pytest

from sbeam.parser import bdf_reader
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data

REPO = Path(__file__).resolve().parents[2]
_GRIDS = ["GRID, 1, , 0.0, 0.0, 0.0", "GRID, 2, , 1.0, 0.0, 0.0"]

# HA144A's own DMI cards (sample/HA144A.bdf, MSC listing 7-1)
_HA144A_DMI = ["DMI, W2GJ, 0, 2, 1, , 40, 1", "DMI, W2GJ, 1, 9, .0017453, THRU, 40"]


@pytest.mark.parametrize("cards, match", [
    (_HA144A_DMI, r"DMI x2 \(direct matrix input \(for W2GJ/WKK aero corrections use the "
                  r"native W2GJ/WKK cards\)\)"),
    (["DMIG, K2GG, 0, 6, 1, 0"], r"DMIG x1"),
    (["DMIJ, FA2J, 0, 2, 1"], r"DMIJ x1 \(aero direct matrix input"),
    (["TABDMP1, 1, CRIT", "+, 0.0, 0.02, 100.0, 0.02, ENDT"], r"TABDMP1 x1 \(modal damping"),
], ids=["DMI-W2GJ", "DMIG", "DMIJ", "TABDMP1"])
def test_matrix_and_damping_cards_are_refused(cards, match):
    with pytest.raises(ValueError, match=r"Unsupported bulk data card\(s\): .*" + match):
        parse_bulk_data(_GRIDS + cards)


@pytest.mark.parametrize("card, match", [
    ("FROCE, 10, 2, 0, 1.0, 0.0, 0.0, -1.0", r"FROCE x1 \(did you mean FORCE\?\)"),
    # large field is read since #64; an unknown keyword in it is still refused, without the *
    ("FROCE*, 10, 2, 0, 1.0", r"FROCE x1 \(did you mean FORCE\?\)"),
    ("NSML, 1, PBAR, 10, 2.5", r"NSML x1"),
    ("AELINK, 1, ELEV, , AILL, 1.0", r"AELINK x1"),
], ids=["typo", "large-field", "nonstructural-mass", "aelink"])
def test_unknown_cards_are_refused(card, match):
    with pytest.raises(ValueError, match=r"Unknown bulk data card\(s\): " + match):
        parse_bulk_data(_GRIDS + [card])


def test_all_unknown_and_unsupported_cards_are_listed_once():
    with pytest.raises(ValueError) as exc:
        parse_bulk_data(_GRIDS + ["FROCE, 10, 2", "FROCE, 11, 2", "ZZZ, 1"] + _HA144A_DMI)
    msg = str(exc.value)
    assert "DMI x2" in msg and "FROCE x2" in msg and "ZZZ x1" in msg
    assert "02_card_reference.md" in msg


@pytest.mark.parametrize("keyword", sorted(bdf_reader._HARMLESS_CARDS))
def test_harmless_cards_warn_and_parse(keyword):
    with pytest.warns(UserWarning, match=rf"BDF card '{keyword}' ignored"):
        bulk = parse_bulk_data(_GRIDS + [keyword])
    assert set(bulk.grids) == {1, 2}


def test_harmless_and_refused_sets_do_not_overlap_handled_cards():
    harmless = set(bdf_reader._HARMLESS_CARDS)
    assert not harmless & bdf_reader.HANDLED_CARDS
    assert not harmless & set(bdf_reader._UNSUPPORTED_CARDS)


@pytest.mark.parametrize("param, match", [
    ("PARAM, AUNITS, .031081", r"PARAM,AUNITS,0.031081 is not supported"),
    ("PARAM, COUPMASS, -1", r"PARAM,COUPMASS,-1 asks for lumped mass"),
    ("PARAM, COUPMASS, 0", r"PARAM,COUPMASS,0 asks for lumped mass"),
    ("PARAM, COUPMASS", r"PARAM,COUPMASS,-1 asks for lumped mass"),
], ids=["AUNITS", "COUPMASS--1", "COUPMASS-0", "COUPMASS-blank"])
def test_answer_changing_params_are_refused(param, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_GRIDS + [param])


@pytest.mark.parametrize("param", ["PARAM, AUNITS, 1.0", "PARAM, COUPMASS, 1"])
def test_params_that_ask_for_what_sbeam_does_are_accepted(param):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        parse_bulk_data(_GRIDS + [param])


def test_other_params_still_warn():
    with pytest.warns(UserWarning, match=r"Unknown BDF card 'PARAM,GRDPNT' — skipped"):
        parse_bulk_data(_GRIDS + ["PARAM, GRDPNT, 1"])


def test_ha144a_archive_still_stops_at_wtmass_first():
    """The archive listing carries WTMASS, AUNITS and three DMIs; WTMASS comes first in
    the deck and is raised as it is read."""
    with pytest.raises(ValueError, match=r"PARAM,WTMASS,0.031081 is not supported"):
        parse_bdf(REPO / "sample/HA144A.bdf")
