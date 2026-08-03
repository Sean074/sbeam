"""P12 S5 — pre-launch/pre-export validation of SOL 144 authoring."""

from pathlib import Path

import pytest

from sbeam.model.maneuver import Mloads
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.viewer.sol144_authoring import (
    IncrementSpec, snapshot_family_ids, validate_sol144_authoring,
)

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample"


@pytest.fixture()
def fullspan():
    return parse_bdf(SAMPLE_DIR / "ha144a_fullspan_mloads.bdf")


@pytest.fixture()
def massset():
    return parse_bdf(SAMPLE_DIR / "ha144a_mloads_massset.bdf")


def _errors(bulk, cc, **kw):
    errors, _ = validate_sol144_authoring(bulk, cc, **kw)
    return errors


def _warnings(bulk, cc, **kw):
    _, warns = validate_sol144_authoring(bulk, cc, **kw)
    return warns


def test_clean_direct_deck_has_no_errors(fullspan):
    cc, bulk = fullspan
    assert _errors(bulk, cc) == []


def test_clean_modal_deck_has_no_errors(massset):
    cc, bulk = massset
    assert _errors(bulk, cc) == []


def test_non_sol144_is_ignored(fullspan):
    _, bulk = fullspan
    cc = CaseControl(sol=101, subcases=[SubcaseControl(subcase_id=1)])
    assert validate_sol144_authoring(bulk, cc) == ([], [])


def test_subcase_without_driver(fullspan):
    cc, bulk = fullspan
    cc.subcases[0].trim_sid = None
    assert any("needs a driver" in e for e in _errors(bulk, cc))


def test_mloads_with_trim_conflicts(fullspan):
    cc, bulk = fullspan
    cc.subcases[1].trim_sid = 1
    assert any("cannot combine" in e for e in _errors(bulk, cc))


def test_load_refused(fullspan):
    cc, bulk = fullspan
    cc.subcases[0].load_sid = 5
    assert any("LOAD does not combine" in e for e in _errors(bulk, cc))


def test_dangling_trim_reference(fullspan):
    cc, bulk = fullspan
    cc.subcases[0].trim_sid = 999
    assert any("TRIM 999 not found" in e for e in _errors(bulk, cc))


def test_dangling_massset_reference(massset):
    cc, bulk = massset
    cc.subcases[0].massset_sid = 999
    assert any("MASSSET 999" in e for e in _errors(bulk, cc))


def test_trim_label_not_defined(fullspan):
    cc, bulk = fullspan
    bulk.trims[1].vars["NOPE"] = 1.0
    assert any("label 'NOPE'" in e for e in _errors(bulk, cc))


def test_fully_prescribed_trim_warns(fullspan):
    cc, bulk = fullspan
    trim = bulk.trims[1]
    for lbl in ("ANGLEA", "ELEV"):
        trim.vars[lbl] = 0.0
    assert any("all trim variables are prescribed" in w
               for w in _warnings(bulk, cc))


def test_modal_needs_rhoref(massset):
    cc, bulk = massset
    bulk.trims[1].rhoref = 0.0
    assert any("needs RHOREF" in e for e in _errors(bulk, cc))


def test_mloads_needs_suport(massset):
    cc, bulk = massset
    bulk.supports.clear()
    assert any("SUPORT" in e for e in _errors(bulk, cc))


def test_modal_rejects_rigid_command_label(massset):
    cc, bulk = massset
    comd = bulk.mldcomds[11]
    comd.commands[0] = ("ANGLEA", comd.commands[0][1])
    errs = _errors(bulk, cc)
    assert any("rigid-state label 'ANGLEA'" in e for e in errs)


def test_method_must_be_eigrl(massset):
    cc, bulk = massset
    ml = bulk.mloads[10]
    bulk.mloads[10] = Mloads(sid=10, mldtrim=ml.mldtrim, mldtime=ml.mldtime,
                             mldcomd=ml.mldcomd, mldprnt=ml.mldprnt,
                             method=777)
    assert any("METHOD 777" in e for e in _errors(bulk, cc))


def test_mldtime_window_checked(massset):
    cc, bulk = massset
    bulk.mldtimes[1].tend = bulk.mldtimes[1].t0
    assert any("TEND > T0" in e for e in _errors(bulk, cc))


def test_sparse_modal_table_warns(massset):
    cc, bulk = massset
    # The sample's 3-point clamped-linear command tables under the modal solver
    # trip the ringing advisory.
    assert any("cosine ramp" in w for w in _warnings(bulk, cc))


def test_fixed_phi_massset_note(massset):
    cc, bulk = massset
    assert any("fixed-Φ" in w for w in _warnings(bulk, cc))


def test_aelist_outside_caero_range(fullspan):
    cc, bulk = fullspan
    sid = next(iter(bulk.aelists))
    bulk.aelists[sid].elements.append(999999)
    assert any("outside every CAERO1 range" in e for e in _errors(bulk, cc))


def test_unresolved_increments_block_export(fullspan):
    cc, bulk = fullspan
    spec = IncrementSpec(mloads_sid=1, label="ELEV",
                         points=[(0.0, 0.0), (1.0, 0.1)])
    errs = _errors(bulk, cc, unresolved_increments=[spec])
    assert any("unresolved increment command" in e for e in errs)


def test_authored_duplicate_of_file_sid_blocks_export(fullspan):
    cc, bulk = fullspan
    file_sids = snapshot_family_ids(bulk)
    errs = _errors(bulk, cc, file_sids=file_sids, authored={"trim": {1}})
    assert any("Save it as a new SID" in e for e in errs)
    # A genuinely new SID does not trip the gate.
    assert _errors(bulk, cc, file_sids=file_sids, authored={"trim": {50}}) == []
