"""HA144A rigid longitudinal stability/control derivatives vs an independent source.

The ASTROS*/ZAERO Applications Manual (DTIC ADA370433, §3.1 "Forward Swept Wing
in Level Flight", Table 3.1.1, M=0.9) tabulates the MSC/NASTRAN longitudinal
derivatives for the HA144A FSW + canard airplane.  Its **rigid-airplane** column
is reproduced here in full:

    Derivative   NASTRAN (1/rad)   sbeam label / component
    -----------  ---------------   -----------------------
    C_Zα           5.071           ANGLEA  CZ
    C_Mα          −2.871           ANGLEA  CMY
    C_Zq          12.074           PITCH   CZ   (pitch-rate)
    C_Mq          −9.954           PITCH   CMY
    C_Zδe          0.2461          ELEV    CZ   (elevator)
    C_Mδe          0.5715          ELEV    CMY

sbeam already computes all six (see `_compute_rigid_derivs`); before this file the
suite gated only C_Zα and C_Mα (in `test_ae1_restrained_derivs.py`).  These tests
lock the other four — pitch-rate (C_Zq, C_Mq) and control (C_Zδe, C_Mδe) — against
the document so the documented, already-correct rigid column is regression-guarded.

Scope notes:
  * This is the RIGID column.  The flexible (UNRESTRAINED) columns of Table 3.1.1
    are the open AE8 work — sbeam does not yet compute the mean-axis set; those
    targets are recorded in `test_ae1_restrained_derivs.py`.
  * sbeam stores CZ positive (the manual prints CZα as +5.071); CMY carries the
    nose-up-positive sign of the table.
"""

import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"

# ADA370433 Table 3.1.1, MSC/NASTRAN "Value for Rigid Airplane" column (M=0.9).
# {sbeam label: {component: target}} — components are CZ (force) and CMY (moment).
NASTRAN_RIGID = {
    "ANGLEA": {"CZ": 5.071, "CMY": -2.871},   # C_Zα, C_Mα
    "PITCH":  {"CZ": 12.074, "CMY": -9.954},  # C_Zq, C_Mq
    "ELEV":   {"CZ": 0.2461, "CMY": 0.5715},  # C_Zδe, C_Mδe
}

# The manual rounds to 4 significant figures; sbeam reproduces each to <0.02%.
# 0.5% leaves headroom for box-count/spline differences while still being a
# meaningful regression guard.
REL_TOL = 0.005


@pytest.fixture(scope="module")
def rigid_derivs():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero
        )
    return result.rigid_derivs


@pytest.mark.parametrize("label", sorted(NASTRAN_RIGID))
@pytest.mark.parametrize("comp", ["CZ", "CMY"])
def test_rigid_derivative_matches_nastran(rigid_derivs, label, comp):
    target = NASTRAN_RIGID[label][comp]
    got = rigid_derivs[label][comp]
    assert got == pytest.approx(target, rel=REL_TOL), (
        f"rigid {label} {comp} = {got:.5f} not within {REL_TOL:.1%} of "
        f"ADA370433 Table 3.1.1 NASTRAN {target}"
    )


def test_urdd_columns_have_no_rigid_aero_sensitivity(rigid_derivs):
    """The inertial (URDD) labels carry no rigid aerodynamic derivative — the
    rigid aero force/moment is insensitive to a unit acceleration (the inertial
    coupling enters through M_ax, not the aero column)."""
    for label in ("URDD3", "URDD5"):
        assert rigid_derivs[label]["CZ"] == pytest.approx(0.0, abs=1e-9)
        assert rigid_derivs[label]["CMY"] == pytest.approx(0.0, abs=1e-9)
