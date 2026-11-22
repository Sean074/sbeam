"""CAERO1 interference groups: one per deck (#76).

MSC Nastran 2024.1 Quick Reference Guide, PDF p.1343: "IGID Interference group
identification; aerodynamic elements with different IGIDs are uncoupled."  sbeam builds
one AIC over every panel and never read the field, so a second group ran coupled.
"""
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

_BASE = ["AEROS, 0, 0, 1.0, 8.0, 8.0, 0, 0", "PAERO1, 1"]


def _caero(eid, igid, y0):
    return [f"CAERO1, {eid}, 1, 0, 2, 2, 0, 0, {igid}",
            f"+, 0.0, {y0}, 0.0, 1.0, 0.0, {y0 + 2.0}, 0.0, 1.0"]


def test_two_groups_are_refused_naming_them():
    """Audit M6: IGID = 2 on one surface was accepted and every surface still interfered."""
    with pytest.raises(ValueError, match=r"CAERO1 cards use 2 interference groups \(IGID 1: "
                                         r"CAERO1 1100, 3100; IGID 2: CAERO1 2100\)"):
        parse_bulk_data(_BASE + _caero(1100, 1, 0.0) + _caero(2100, 2, 2.0) + _caero(3100, 1, 4.0))


@pytest.mark.parametrize("igid", ["1", "7", ""])
def test_one_group_is_accepted_whatever_its_id(igid):
    bulk = parse_bulk_data(_BASE + _caero(1100, igid, 0.0) + _caero(2100, igid, 2.0))
    assert len({c.igid for c in bulk.caero1s.values()}) == 1
