"""#60 gate: every dependent DOF of a rigid element has a valid source, or the deck is refused.

Before #60, ``_build_rigid_transform`` skipped four cases without a word:

1. an RBE3 REFC DOF that no Ci covers (``REFC=123456`` with ``Ci=123``, the usual NASTRAN
   RBE3) was left out of the constraint, so the reference grid's rotations were free;
2. REFC weights summing to zero were skipped the same way;
3. a DOF made dependent by two rigid elements kept only the last one's row of T;
4. an RBE3 independent DOF that another element made dependent lost its column in
   ``T[:, red_dofs]``, so the RBE3 row no longer summed to one.

All four now refuse. An RBE3 whose independent grids are offset from REFGRID warns: sbeam
has no lever arm there, NASTRAN does.

The physics gate: sample/beam_vib1.bdf (RBAR since #60) carries a 10 000 kg mass 1.0 m off
the tip. A rigid link with a point mass is exactly the mass at the tip with CONM2 X2 = 1.0
(the offset-CONM2 path is verified by val_cantilever_offset_mass_modes), so the two
spectra must agree to round-off.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.assembly.rbe3 import build_rbe3_transformation
from sbeam.model.bulk_data import BulkData
from sbeam.model.element import Rbar, Rbe2, Rbe3
from sbeam.model.grid import Grid
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol103 import run_sol103

REPO = Path(__file__).resolve().parents[2]


def _bulk(*positions: tuple[float, float, float]) -> BulkData:
    bulk = BulkData()
    for gid, (x, y, z) in enumerate(positions, 1):
        bulk.grids[gid] = Grid(gid=gid, x=x, y=y, z=z)
    return bulk


def _build(bulk: BulkData):
    return build_rbe3_transformation(bulk, {g: i for i, g in enumerate(sorted(bulk.grids))})


_ORIGIN = (0.0, 0.0, 0.0)


@pytest.mark.parametrize("refc, groups, match", [
    ("123456", [(1.0, "123", [2, 3])], r"RBE3 9: REFC DOF 4, 5, 6 is not in any Ci"),
    ("123", [(1.0, "12", [2, 3])], r"RBE3 9: REFC DOF 3 is not in any Ci"),
    ("123", [(1.0, "123", [2]), (-1.0, "123", [3])], r"RBE3 9: the weights for REFC DOF 1 sum to zero"),
], ids=["rotations-uncovered", "one-uncovered", "zero-weight"])
def test_rbe3_without_a_source_is_refused(refc, groups, match):
    bulk = _bulk(_ORIGIN, _ORIGIN, _ORIGIN)
    bulk.rbe3s[9] = Rbe3(eid=9, refgrid=1, refc=refc, wt_gc=groups)
    with pytest.raises(ValueError, match=match):
        _build(bulk)


def test_rbe3_covered_by_separate_groups_is_accepted():
    bulk = _bulk(_ORIGIN, _ORIGIN, _ORIGIN)
    bulk.rbe3s[9] = Rbe3(eid=9, refgrid=1, refc="123456",
                         wt_gc=[(1.0, "123", [2, 3]), (1.0, "456", [2, 3])])
    T, dep, _red = _build(bulk)
    assert dep == list(range(6))
    assert np.allclose(T[:6].sum(axis=1), 1.0)


def test_dof_dependent_in_two_elements_is_refused():
    bulk = _bulk(_ORIGIN, _ORIGIN, _ORIGIN)
    bulk.rbe3s[9] = Rbe3(eid=9, refgrid=1, refc="123", wt_gc=[(1.0, "123", [2])])
    bulk.rbe2s[5] = Rbe2(eid=5, gn=3, cm="1", gm=[1])
    with pytest.raises(ValueError, match=r"RBE2 5 \(GM 1, C1\): this DOF is already a dependent "
                                         r"DOF of RBE3 9 \(REFGRID 1, C1\)"):
        _build(bulk)


@pytest.mark.parametrize("other", ["RBE2", "RBAR"])
def test_rbe3_independent_that_is_dependent_elsewhere_is_refused(other):
    bulk = _bulk(_ORIGIN, _ORIGIN, _ORIGIN)
    bulk.rbe3s[9] = Rbe3(eid=9, refgrid=1, refc="123", wt_gc=[(1.0, "123", [2, 3])])
    if other == "RBE2":
        bulk.rbe2s[5] = Rbe2(eid=5, gn=3, cm="2", gm=[2])
    else:
        bulk.rbars[5] = Rbar(eid=5, ga=3, gb=2)
    with pytest.raises(ValueError, match=rf"RBE3 9: independent grid 2 DOF . is a dependent DOF of {other} 5"):
        _build(bulk)


def test_rbe3_dependency_on_unused_dof_is_allowed():
    """Grid 2's DOF 6 is dependent elsewhere, but REFC=123 never reads it."""
    bulk = _bulk(_ORIGIN, _ORIGIN, _ORIGIN)
    bulk.rbe3s[9] = Rbe3(eid=9, refgrid=1, refc="123", wt_gc=[(1.0, "123456", [2, 3])])
    bulk.rbe2s[5] = Rbe2(eid=5, gn=3, cm="6", gm=[2])
    _build(bulk)


def test_offset_rbe3_warns_and_collocated_does_not():
    bulk = _bulk(_ORIGIN, (0.0, 1.0, 0.0), _ORIGIN)
    bulk.rbe3s[9] = Rbe3(eid=9, refgrid=1, refc="123", wt_gc=[(1.0, "123", [2, 3])])
    with pytest.warns(UserWarning, match=r"RBE3 9: independent grid 2 is 1 from REFGRID 1; "
                                         r"sbeam averages same-numbered DOFs with no lever arm"):
        _build(bulk)
    bulk.grids[2] = Grid(gid=2, x=0.0, y=0.0, z=0.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _build(bulk)


def _frequencies(cc, bulk) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.asarray(run_sol103(bulk, cc.subcases[0]).frequencies_hz)


def test_beam_vib1_rbar_matches_offset_conm2():
    cc, bulk = parse_bdf(str(REPO / "sample/beam_vib1.bdf"))
    f_rbar = _frequencies(cc, bulk)

    # Same mass at the tip with the offset in the CONM2; node 7 clamped and unloaded
    del bulk.rbars[20]
    bulk.conm2s[30].gid, bulk.conm2s[30].x2 = 6, 1.0
    bulk.spc1s[1][0].grids.append(7)
    f_conm2 = _frequencies(cc, bulk)

    assert np.allclose(f_rbar, f_conm2, rtol=1e-9)
    # The lever arm is in: the RBE3 this deck had until #60 gave 1.0334/11.80/37.28 Hz
    assert np.allclose(f_rbar[:5], [1.0168, 1.0239, 9.1735, 9.5743, 20.861], atol=5e-4)
