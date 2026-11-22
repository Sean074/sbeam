"""Signed per-box data in MSC's element frame (#84).

MSC's CAERO1 element system is right-handed with x along the airstream and y from P1
toward P4 (QRG 2024.1 PDF p.1344, remark 4, Figure 9-5), so its normal z = x × y depends
on the point order: a port wing or a fin drawn root to tip has the normal −z or −y.
The downwash w_j is the "normal velocity" of each box (AAUG 2023.1 PDF p.30, eq 2-1/2-2)
and W2GJ is its static part (p.144), so W2GJ, AECORR/CHORDCP targets and the printed
ΔCp are signed along that normal.  sbeam solves with a normal whose dominant component
is positive; before #84 it also read the cards along it, so the same W2GJ on a port wing
gave the same lift whichever way the wing was drawn.
"""
import warnings

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.parser.bdf_reader import parse_bulk_data

_W = 0.01


def _surface(p1, p4, w2gj=None):
    cards = ["AEROS, 0, 0, 1.0, 10.0, 10.0", "PAERO1, 1",
             "CAERO1, 100, 1, 0, 4, 2, 0, 0, 1",
             f"+, {p1[0]!r}, {p1[1]!r}, {p1[2]!r}, 1., {p4[0]!r}, {p4[1]!r}, {p4[2]!r}, 1."]
    if w2gj is not None:
        cards += ["W2GJ, 1, 100", "+, " + ", ".join([repr(w2gj)] * 8)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return build_aero_model(parse_bulk_data(cards), mach=0.0)


@pytest.mark.parametrize("p1, p4, sign", [
    ((0., 0., 0.), (0., 5., 0.), 1.0),     # starboard wing, root to tip: z_elem = +z
    ((0., 0., 0.), (0., -5., 0.), -1.0),   # port wing, root to tip: z_elem = −z
    ((0., -5., 0.), (0., 0., 0.), 1.0),    # port wing, tip to root: z_elem = +z
    ((0., 0., 0.), (0., 0., 5.), -1.0),    # fin, root to tip: z_elem = x × z = −y
    ((0., 0., 5.), (0., 0., 0.), 1.0),     # fin, tip to root: z_elem = +y
])
def test_msc_sign_follows_figure_9_5(p1, p4, sign):
    model = _surface(p1, p4)
    assert {b.msc_sign for b in model.boxes} == {sign}
    # sbeam's own normal is the same either way: +z for a wing, +y for a fin
    assert {tuple(np.round(b.normal, 12)) for b in model.boxes} in (
        {(0.0, 0.0, 1.0)}, {(0.0, 1.0, 0.0)})


def _baseline_fz(model):
    cp = model.ajj_inv_corr @ model.wg
    return float((model.skj @ cp)[2::3].sum())


def test_port_wing_w2gj_is_signed_by_point_order():
    """The same positive incidence is +W2GJ drawn tip to root and −W2GJ root to tip."""
    tip_to_root = _baseline_fz(_surface((0., -5., 0.), (0., 0., 0.), w2gj=_W))
    root_to_tip = _baseline_fz(_surface((0., 0., 0.), (0., -5., 0.), w2gj=-_W))
    assert tip_to_root > 0.0
    assert root_to_tip == pytest.approx(tip_to_root, rel=1e-12)
    # Before #84 the two needed the same sign: the same card now gives opposite lift
    same_card = _baseline_fz(_surface((0., 0., 0.), (0., -5., 0.), w2gj=_W))
    assert same_card == pytest.approx(-tip_to_root, rel=1e-12)


def test_fin_w2gj_is_signed_by_point_order():
    """A fin drawn root to tip: +W2GJ pushes along MSC's −y, i.e. a force toward −y."""
    def fy(p1, p4, w):
        model = _surface(p1, p4, w2gj=w)
        return float((model.skj @ (model.ajj_inv_corr @ model.wg))[1::3].sum())
    up = fy((0., 0., 0.), (0., 0., 5.), _W)
    down = fy((0., 0., 5.), (0., 0., 0.), _W)
    assert up == pytest.approx(-down, rel=1e-12)
    assert up < 0.0 < down
