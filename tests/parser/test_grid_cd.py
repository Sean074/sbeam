"""GRID CD is refused wherever it would change the answer (#65).

MSC Nastran 2024.1 Quick Reference Guide, PDF p.1944: CD is the "coordinate system in
which the displacements, degrees-of-freedom, constraints, and solution vectors are defined
at the grid point."  CBAR X1-X3 are "in the displacement coordinate system at GA" (p.1360)
and so are CBUSH Xi (p.1378).  sbeam solves in basic and uses CD only to rotate printed
results, so a card that names a direction at a CD grid is refused.  A whole triad of
components (123, 456, 123456) is the same set of motions in every frame and is accepted.
"""
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

_BASE = [
    "CORD2R, 5, 0, 0., 0., 0., 0., 0., 1.", "+, 0., 1., 0.",     # 90 deg about z
    "GRID, 1, , 0., 0., 0.", "GRID, 2, , 1., 0., 0., 5", "GRID, 3, , 2., 0., 0.",
    "MAT1, 1, 2.e11, , .3", "PBAR, 1, 1, .01, 1.e-6, 1.e-6, 1.e-6",
    "CBAR, 1, 1, 1, 2, 0., 1., 0.", "CBAR, 2, 1, 3, 2, 0., 1., 0.",
]


def _parse(*cards, base=_BASE):
    return parse_bulk_data(list(base) + list(cards))


def test_audit_probe_is_refused():
    """Audit S1: GRID 2 with CD 5 and SPC1 1 1 2 constrained basic T1, not CD-x."""
    with pytest.raises(ValueError, match=r"GRID 2: CD=5 is used only to print results in that "
                                         r"frame, but SPC1 1 names components 1 at it"):
        _parse("SPC1, 1, 1, 2")


@pytest.mark.parametrize("card, named", [
    ("SPC, 1, 2, 35", "SPC 1 names components 35"),
    ("SPC, 1, 1, 123456, , 2, 2", "SPC 1 names components 2"),
    ("SUPORT, 2, 35", "SUPORT names components 35"),
    ("RBE2, 9, 1, 12, 2", "RBE2 9 names components 12"),
    ("RBE2, 9, 2, 3, 1", "RBE2 9 names components 3"),
    ("RBE3, 9, , 2, 12, 1.0, 123, 1, 3", "RBE3 9 names components 12"),
    ("RBE3, 9, , 1, 123456, 1.0, 12, 2, 3", "RBE3 9 names components 12"),
    ("CBAR, 3, 1, 2, 1, 0., 1., 0.", "CBAR 3 takes its orientation vector at this grid"),
    ("CBUSH, 3, 7, 2, 1", "CBUSH 3 takes its spring axes at this grid"),
    ("CBUSH, 3, 7, 1, 2", "CBUSH 3 takes its spring axes at this grid"),
])
def test_a_direction_at_a_cd_grid_is_refused(card, named):
    extra = ["PBUSH, 7, K, 1.e6, 2.e6, 3.e6"] if card.startswith("CBUSH") else []
    with pytest.raises(ValueError, match=f"GRID 2: CD=5 .* but {named}"):
        _parse(card, *extra)


def test_permanent_constraint_on_the_grid_itself_is_refused():
    base = [c.replace("GRID, 2, , 1., 0., 0., 5", "GRID, 2, , 1., 0., 0., 5, 3") for c in _BASE]
    with pytest.raises(ValueError, match="but its own PS field names components 3"):
        _parse(base=base)


@pytest.mark.parametrize("card", [
    "SPC1, 1, 123456, 2", "SPC1, 1, 123, 2", "SPC1, 1, 456, 2", "SPC, 1, 2, 123456",
    "SUPORT, 2, 123456", "RBE2, 9, 1, 123456, 2", "RBE2, 9, 2, 123, 3",
    "RBE3, 9, , 2, 123456, 1.0, 123, 1, 3", "RBAR, 9, 1, 2",
    "FORCE, 1, 2, 0, 1., 0., 0., 1.", "CONM2, 9, 2, 0, 1.0", "CROD, 9, 8, 1, 2",
], ids=lambda c: c.split(",")[0] + c.split(",")[-2].strip())
def test_whole_triads_and_frame_free_cards_are_accepted(card):
    """A whole triad of components is the same constraint in every frame; FORCE and
    CONM2 carry their own CID; a rod has no orientation."""
    extra = ["PROD, 8, 1, 1.e-4"] if card.startswith("CROD") else []
    assert _parse(card, *extra).grids[2].cd == 5


def test_end_b_of_a_cbar_may_carry_a_cd():
    """The orientation vector is taken at GA only (QRG p.1360); _BASE has grid 2 at GB."""
    assert set(_parse().cbars) == {1, 2}
