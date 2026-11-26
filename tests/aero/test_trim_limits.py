"""TRIMVAR / TRIMWGT / TRIMINEQ are checked and acted on, or refused (#77).

Audit findings P6, A11, A12, M10 (2026-11-16).  These are sbeam-defined cards, so the
rules here are sbeam's own.
"""
import warnings

import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Trim, Trimcon, Trimobj, Trimvar
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver.sol144 import run_sol144_trim
from tests.samples import sample_path

HA144A = sample_path("ha144a_fullspan_sbeam.bdf")
_LABELS = ["AESTAT, 501, ANGLEA", "AESTAT, 502, PITCH", "AESURF, 505, ELEV, 1, 1"]


def _parse(*cards):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parse_bulk_data(["AESTAT, 501, ANGLEA", "AESTAT, 502, PITCH", *cards])


class TestTrimvarCard:
    @pytest.mark.parametrize("card", [
        "TRIMVAR 1       ANGLEA                                          0.0",
        "TRIMVAR,1,ANGLEA", "TRIMVAR,1,ANGLEA,,,,,,0.0",
    ], ids=["fixed", "free-short", "free-blank"])
    def test_blank_bounds_are_unbounded(self, card):
        """Fixed-field pads to nine fields; a blank bound read as 0.0 pinned the variable."""
        tv = _parse(card).trimvars[1]
        assert (tv.lb, tv.ub) == (-1.0e30, 1.0e30)

    @pytest.mark.parametrize("bounds", ["0.3, -0.3", "0.1, 0.1"])
    def test_lower_bound_must_be_below_upper(self, bounds):
        with pytest.raises(ValueError, match=r"TRIMVAR 1 \(ANGLEA\): LB=.* must be less than UB"):
            _parse(f"TRIMVAR, 1, ANGLEA, {bounds}")

    def test_zaero_layout_is_read(self):
        """#87: ZAERO's IDVAR LABEL LOWER UPPER TRIMLNK DMI SYM INITIAL (ZUM 9.2 PDF p.511),
        the manual's own example less the TRIMLNK and DMI sbeam refuses."""
        tv = _parse("TRIMVAR, 100, ANGLEA, -50.0, 50.0, , , SYM, 0.1",
                    "+, NONE, NONE, NONE, NONE, NONE, NONE").trimvars[100]
        assert (tv.lb, tv.ub, tv.init) == (-50.0, 50.0, 0.1)

    @pytest.mark.parametrize("card, match", [
        ("TRIMVAR, 1, ANGLEA, -1., 1., 10", "TRIMLNK"),
        ("TRIMVAR, 1, ANGLEA, -1., 1., , AFORCE", "DMI"),
        ("TRIMVAR, 1, ANGLEA, -1., 1., , , BOTH", "SYM"),
    ])
    def test_unsupported_zaero_fields_are_refused(self, card, match):
        with pytest.raises(ValueError, match=match):
            _parse(card)

    def test_user_derivatives_are_refused(self):
        with pytest.raises(ValueError, match="user-input stability derivatives"):
            _parse("TRIMVAR, 1, ANGLEA, -1., 1.", "+, 0.01")

    def test_two_cards_on_one_label_are_refused(self):
        with pytest.raises(ValueError, match="TRIMVAR 2: label 'ANGLEA' already has bounds "
                                             "on TRIMVAR 1"):
            _parse("TRIMVAR, 1, ANGLEA, -1., 1.", "TRIMVAR, 2, ANGLEA, -2., 2.")


class TestLabelsAreCrossReferenced:
    """The card reference's own examples used CL and CM, which the solver dropped."""

    @pytest.mark.parametrize("card, name", [
        ("TRIMVAR, 1, ANGLA, -1., 1.", "TRIMVAR 1: label 'ANGLA'"),
        ("TRIMWGT, 20, ANGLEA, 1.0, CL, 0.5", "TRIMWGT 20: label 'CL'"),
        ("TRIMINEQ, 30, CM, LE, 0.02", "TRIMINEQ 30: label 'CM'"),
    ])
    def test_unknown_label_is_refused(self, card, name):
        with pytest.raises(ValueError, match=f"{name} not defined in any AESTAT or AESURF"):
            _parse(card)

    def test_known_labels_are_accepted(self):
        bulk = _parse("TRIMVAR, 1, ANGLEA, -1., 1.", "TRIMWGT, 20, ANGLEA, 1.0, PITCH, 0.5",
                      "TRIMINEQ, 30, PITCH, LE, 0.02", "TRIMINEQ, 30, PITCH, GE, -0.02")
        assert bulk.trimobjs[20].labels == ["ANGLEA", "PITCH"]
        assert len(bulk.trimcons[30]) == 2

    def test_trimcon_under_two_sids_is_refused(self):
        """No command selects a TRIMINEQ set: both were applied to every trim."""
        with pytest.raises(ValueError, match=r"TRIMINEQ cards use 2 different SIDs \(30, 31\)"):
            _parse("TRIMINEQ, 30, PITCH, LE, 0.02", "TRIMINEQ, 31, ANGLEA, GE, 0.0")


class TestTrimobjCard:
    def test_empty_objective_is_refused(self):
        with pytest.raises(ValueError, match="TRIMWGT 20: no LABEL/WEIGHT pair"):
            _parse("TRIMWGT, 20")

    def test_repeated_label_is_refused(self):
        with pytest.raises(ValueError, match="TRIMWGT 20: label 'PITCH' is listed twice"):
            _parse("TRIMWGT, 20, PITCH, 1.0, PITCH, 2.0")

    def test_negative_weight_is_refused(self):
        with pytest.raises(ValueError, match="weight -1 on 'PITCH' must be >= 0"):
            _parse("TRIMWGT, 20, PITCH, -1.0")


def _ha144a():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _cc, bulk = parse_bdf(str(HA144A))
        aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    return bulk, aero


def _trim(bulk, aero, **subcase):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(bulk, SubcaseControl(subcase_id=1, spc_sid=1, **subcase), aero)


@pytest.fixture(scope="module")
def determined():
    bulk, aero = _ha144a()
    return _trim(bulk, aero, trim_sid=1).trim_vars


class TestLimitsHoldOnEveryTrim:
    """The limits were enforced only inside the optimiser."""

    def test_determined_trim_outside_a_trimvar_bound_is_refused(self, determined):
        bulk, aero = _ha144a()
        elev = determined["ELEV"]
        bulk.trimvars[1] = Trimvar(id=1, label="ELEV", init=0.0, lb=elev + 0.01, ub=elev + 1.0)
        with pytest.raises(ValueError, match=r"TRIM 1: ELEV = .* is outside the TRIMVAR 1 bounds"):
            _trim(bulk, aero, trim_sid=1)

    def test_determined_trim_inside_its_bounds_is_unchanged(self, determined):
        bulk, aero = _ha144a()
        elev = determined["ELEV"]
        bulk.trimvars[1] = Trimvar(id=1, label="ELEV", init=0.0, lb=elev - 0.01, ub=elev + 0.01)
        assert _trim(bulk, aero, trim_sid=1).trim_vars == determined

    def test_determined_trim_violating_a_trimcon_is_refused(self, determined):
        bulk, aero = _ha144a()
        bulk.trimcons[5] = [Trimcon(sid=5, label="ANGLEA", sense="LE",
                                    rhs=determined["ANGLEA"] - 0.01)]
        with pytest.raises(ValueError, match=r"TRIM 1: ANGLEA = .* violates TRIMINEQ 5 "
                                             r"\(ANGLEA LE"):
            _trim(bulk, aero, trim_sid=1)

    def test_prescribed_value_outside_its_bound_is_refused(self):
        bulk, aero = _ha144a()
        bulk.trimvars[1] = Trimvar(id=1, label="URDD3", init=0.0, lb=-10.0, ub=10.0)
        with pytest.raises(ValueError, match=r"URDD3 = -32.174 is outside the TRIMVAR 1 bounds"):
            _trim(bulk, aero, trim_sid=1)


class TestObjectiveMustDetermineTheTrim:
    def _over_determined(self, labels):
        bulk, aero = _ha144a()
        bulk.trims[99] = Trim(sid=99, mach=0.9, q=40.0, vars={"URDD3": -32.174, "URDD5": 0.0})
        bulk.trimobjs[99] = Trimobj(sid=99, labels=labels, weights=[1.0] * len(labels))
        return bulk, aero

    def test_objective_on_prescribed_labels_only_is_refused(self):
        """It used to fall back, silently, to unit weights on every free variable."""
        bulk, aero = self._over_determined(["URDD3"])
        with pytest.raises(ValueError, match=r"TRIMWGT 99 \(URDD3\) does not determine the "
                                             "over-determined trim"):
            _trim(bulk, aero, trim_sid=99, trimobj_sid=99)

    def test_objective_on_one_free_label_determines_one_redundancy(self, determined):
        bulk, aero = self._over_determined(["PITCH"])
        res = _trim(bulk, aero, trim_sid=99, trimobj_sid=99)
        assert res.trim_vars["PITCH"] == pytest.approx(0.0, abs=1e-6)
        assert res.trim_vars["ELEV"] == pytest.approx(determined["ELEV"], rel=1e-4)
