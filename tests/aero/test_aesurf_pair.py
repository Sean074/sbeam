"""G6–G8 — the AESURF CID1/CID2 pair loads both halves (#9, DEF-M16).

Design note ``docs/30_future/designs/lateral_cases_aileron_rudder.md`` §2.2–2.3, D1.
An antisymmetric aileron is ONE label: CID1 = starboard half, CID2 = port half, both
hinge +y pointing outboard.  Positive deflection is lift-increasing on each half about
its own axis, so positive AIL = starboard TE-down, port TE-up = roll toward port =
+CMX in the basic frame.  Built on the AR 8 rectangular wing (`val_vlm_rect_ar8`:
b = 8, c = 1, CAERO1 1000 starboard / 2000 port, 20 × 8 boxes each).
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import aesurf_hinges, build_djx
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Aelist, Aesurf
from sbeam.model.coordinate_system import Cord2r
from sbeam.parser.bdf_reader import parse_bulk_file
from sbeam.solver.sol144 import compute_hinge_moments, compute_rigid_derivs

SAMPLE = Path(__file__).parent.parent.parent / "sample"
X_HINGE = 0.75                      # aft 2 of 8 chord rows: flap chord ratio E = 0.25
OUTER = range(12, 20)               # outer 8 of 20 strips on each half (η 0.6 … 1.0)
AFT = (6, 7)


def _boxes(eid):
    return [eid + i * 8 + j for i in OUTER for j in AFT]


def _hinges(bulk):
    # Starboard hinge: z = +Z, x = +X ⇒ y = +Y (outboard on the starboard wing).
    bulk.cord2rs[11] = Cord2r(cid=11, a=(X_HINGE, 0.0, 0.0), b=(X_HINGE, 0.0, 1.0), c=(X_HINGE + 1.0, 0.0, 0.0))
    # Port hinge: z = +Z, x = −X ⇒ y = −Y (outboard on the port wing).
    bulk.cord2rs[12] = Cord2r(cid=12, a=(X_HINGE, 0.0, 0.0), b=(X_HINGE, 0.0, 1.0), c=(X_HINGE - 1.0, 0.0, 0.0))
    bulk.aelists[301] = Aelist(sid=301, elements=_boxes(1000))
    bulk.aelists[302] = Aelist(sid=302, elements=_boxes(2000))


@pytest.fixture(scope="module")
def wing():
    bulk = parse_bulk_file(str(SAMPLE / "val_vlm_rect_ar8.bdf"))
    _hinges(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    return bulk, aero


def _pair(bulk):
    bulk.aesurfs.clear()
    bulk.aesurfs[601] = Aesurf(id=601, label="AIL", cid1=11, alid1=301, cid2=12, alid2=302)


def _two_labels(bulk):
    bulk.aesurfs.clear()
    bulk.aesurfs[601] = Aesurf(id=601, label="AILS", cid1=11, alid1=301)
    bulk.aesurfs[602] = Aesurf(id=602, label="AILP", cid1=12, alid1=302)


# ---------------------------------------------------------------------------
# G6 — one pair ≡ two single-half surfaces
# ---------------------------------------------------------------------------

def test_pair_column_is_the_sum_of_the_two_half_columns(wing):
    bulk, aero = wing
    k = aero.require_box_id_to_k()
    _pair(bulk)
    pair = build_djx(aero.boxes, ["AIL"], bulk, id_to_k=k)[:, 0]
    _two_labels(bulk)
    two = build_djx(aero.boxes, ["AILS", "AILP"], bulk, id_to_k=k)
    np.testing.assert_allclose(pair, two[:, 0] + two[:, 1], rtol=0, atol=1e-15)
    assert np.count_nonzero(pair) == 32           # 16 boxes per half, both halves loaded


def test_pair_hinge_moment_is_the_sum_of_the_halves(wing):
    bulk, aero = wing
    k = aero.require_box_id_to_k()
    _pair(bulk)
    djx = build_djx(aero.boxes, ["AIL"], bulk, id_to_k=k)
    f_unit = aero.skj @ (aero.ajj_inv_corr @ djx[:, 0])        # loading at unit AIL
    hm_pair = compute_hinge_moments(aero, djx, ["AIL"], bulk, f_unit)["AIL"]
    _two_labels(bulk)
    hm_two = compute_hinge_moments(aero, djx, ["AIL"], bulk, f_unit)
    assert hm_pair["total"] == pytest.approx(hm_two["AILS"]["total"] + hm_two["AILP"]["total"], rel=1e-12)
    assert hm_pair["AIL"] == pytest.approx(hm_pair["total"], rel=1e-12)
    # Mirrored geometry with mirrored axes: both halves carry the same-sign hinge moment.
    assert np.sign(hm_two["AILS"]["total"]) == np.sign(hm_two["AILP"]["total"]) != 0
    assert hm_pair["total"] < 0.0        # TE-down load on the starboard half opposes positive rotation


def test_aesurf_hinges_reports_two_halves_with_outboard_axes(wing):
    bulk, aero = wing
    _pair(bulk)
    halves = aesurf_hinges(bulk.aesurfs[601], bulk, aero.require_box_id_to_k())
    assert len(halves) == 2 and [len(h.ks) for h in halves] == [16, 16]
    np.testing.assert_allclose(halves[0].h_hat, [0, 1, 0], atol=1e-15)
    np.testing.assert_allclose(halves[1].h_hat, [0, -1, 0], atol=1e-15)
    _two_labels(bulk)
    assert len(aesurf_hinges(bulk.aesurfs[601], bulk, aero.require_box_id_to_k())) == 1


# ---------------------------------------------------------------------------
# G7 — antisymmetry, decoupling and the D1 sign
# ---------------------------------------------------------------------------

def test_pair_column_is_antisymmetric_in_y(wing):
    bulk, aero = wing
    _pair(bulk)
    col = build_djx(aero.boxes, ["AIL"], bulk, id_to_k=aero.require_box_id_to_k())[:, 0]
    k = aero.require_box_id_to_k()
    for i in OUTER:
        for j in AFT:
            s, p = k[1000 + i * 8 + j], k[2000 + i * 8 + j]
            assert aero.boxes[s].colloc[1] == pytest.approx(-aero.boxes[p].colloc[1])
            assert col[s] == pytest.approx(-col[p], abs=1e-15)
            assert col[s] == pytest.approx(-1.0)      # starboard: −n_z·eff = TE-down (lift-increasing)


def test_positive_aileron_rolls_toward_port_and_nothing_else(wing):
    """D1 sign gate — the first absolute lateral sign pinned in the repo: positive AIL
    (starboard TE-down, port TE-up) gives +CMX in basic (x aft: roll toward port) with no
    lift, pitch, sideforce or yaw on a planar wing."""
    bulk, aero = wing
    _pair(bulk)
    djx = build_djx(aero.boxes, ["AIL"], bulk, id_to_k=aero.require_box_id_to_k())
    d = compute_rigid_derivs(aero, djx, ["AIL"], bulk, 0.0, np.zeros(3))["AIL"]
    assert d["CMX"] > 0.05
    for c in ("CZ", "CMY", "CY", "CMZ", "CX"):
        assert abs(d[c]) < 1e-9, (c, d[c])


# ---------------------------------------------------------------------------
# G8 — parser cross-checks
# ---------------------------------------------------------------------------

_BASE = (SAMPLE / "val_vlm_rect_ar8.bdf").read_text()
_CARDS = """
CORD2R, 11, 0, 0.75, 0.0, 0.0, 0.75, 0.0, 1.0
+, 1.75, 0.0, 0.0
CORD2R, 12, 0, 0.75, 0.0, 0.0, 0.75, 0.0, 1.0
+, -0.25, 0.0, 0.0
AELIST, 301, 1102, 1103
AELIST, 302, 2102, 2103
"""


@pytest.mark.parametrize("card,msg", [
    ("AESURF, 601, AIL, 11, 301, 12, 302", None),                       # the pair parses
    ("AESURF, 601, AIL, 11, 301, 12", "CID2=12 and ALID2=0 must be given together"),
    ("AESURF, 601, AIL, 11, 301, , 302", "CID2=0 and ALID2=302 must be given together"),
    ("AESURF, 601, AIL, 99, 301", "hinge CID1=99 not found in CORD2R"),
    ("AESURF, 601, AIL, 11, 301, 98, 302", "hinge CID2=98 not found in CORD2R"),
    ("AESURF, 601, AIL, 11, 301, 12, 301", r"appear in both ALID1=301 and ALID2=301"),
    ("AESURF, 601, AIL, 11, 301, 12, 777", "ALID2=777 not found in AELIST"),
])
def test_parser_checks_both_hinge_halves(tmp_path, card, msg):
    deck = tmp_path / "ail.bdf"
    deck.write_text(_BASE.replace("ENDDATA", _CARDS + card + "\nENDDATA"))
    if msg is None:
        bulk = parse_bulk_file(str(deck))
        assert bulk.aesurfs[601].cid2 == 12 and bulk.aesurfs[601].alid2 == 302
    else:
        with pytest.raises(ValueError, match=msg):
            parse_bulk_file(str(deck))
