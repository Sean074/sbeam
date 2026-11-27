"""Elastic CX and CY derivatives (#90): MSC prints all six coefficients per column.

Independent prediction: with the structure made very stiff, the elastic restrained and
unrestrained columns tend to the rigid one, which was always computed for CX and CY.  The
fin of the lateral deck gives a non-zero CY for SIDES and RUD.
"""
import warnings

import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol144 import run_sol144_trim
from tests.samples import sample_path

DECK = sample_path("val_lateral_aileron_rudder.bdf")


def _trim(stiffen: float):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(DECK)
        for mat in bulk.mat1s.values():
            mat.E *= stiffen
            mat.G *= stiffen
        gi = build_grid_index(bulk)
        aero = build_aero_model(bulk, grid_index=gi, mach=bulk.trims[1].mach)
        return run_sol144_trim(bulk, cc.subcases[0], aero)


@pytest.fixture(scope="module")
def stiff():
    return _trim(1.0e8)


@pytest.mark.parametrize("label", ["SIDES", "RUD"])
def test_side_force_derivative_is_present(stiff, label):
    assert abs(stiff.rigid_derivs[label]["CY"]) > 1e-3


@pytest.mark.parametrize("coeff", ["CX", "CY"])
@pytest.mark.parametrize("label", ["SIDES", "RUD", "AIL"])
def test_stiff_structure_restrained_equals_rigid(stiff, label, coeff):
    rigid = stiff.rigid_derivs[label][coeff]
    assert stiff.restrained_derivs[label][coeff] == pytest.approx(rigid, rel=1e-5, abs=1e-9)


@pytest.mark.parametrize("label", ["SIDES", "RUD", "AIL"])
def test_unrestrained_force_is_the_suport_reaction_only(stiff, label):
    """Unrestrained derivatives are the SUPORT (r-set) reactions (AAUG eq. 2-122).  This
    deck's SUPORT is 46 (roll, yaw) and y is SPC'd, so CX and CY are zero by construction,
    while the roll and yaw moments tend to the rigid ones."""
    un, rg = stiff.unrestrained_derivs[label], stiff.rigid_derivs[label]
    assert (un["CX"], un["CY"]) == (0.0, 0.0)
    for coeff in ("CMX", "CMZ"):
        assert un[coeff] == pytest.approx(rg[coeff], rel=1e-4, abs=1e-9)


def test_flexible_side_force_differs_from_rigid():
    """The elastic column is computed, not copied: at the deck's own stiffness it moves."""
    flex = _trim(1.0)
    assert flex.restrained_derivs["SIDES"]["CY"] != pytest.approx(
        flex.rigid_derivs["SIDES"]["CY"], rel=1e-9)
