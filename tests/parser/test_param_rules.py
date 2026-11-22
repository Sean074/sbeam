"""PARAMs that change NASTRAN's answer are refused; listed output PARAMs are named (#69).

Completes the #55 sweep (audit S18, 2026-11-16).  Page numbers are PDF pages of the MSC
Nastran 2024.1 Quick Reference Guide, Parameters section.
"""
import warnings

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.parser.case_control import parse_case_control

_GRID = ["GRID, 1, , 0., 0., 0."]


@pytest.mark.parametrize("param, why", [
    ("PARAM, INREL, -1", "requests inertia relief"),       # p.888
    ("PARAM, INREL, -2", "requests inertia relief"),
    ("PARAM, G, 0.02", "uniform structural damping"),      # p.884
    ("PARAM, W3, 62.8", "structural damping to viscous"),  # p.956
    ("PARAM, W4, 62.8", "structural damping to viscous"),
    ("PARAM, LMODES, 20", "number of lowest modes"),       # p.895
])
def test_answer_changing_param_is_refused(param, why):
    """Each was skipped with the unknown-card warning and the run continued."""
    name, value = (t.strip() for t in param.split(",")[1:])
    with pytest.raises(ValueError, match=f"PARAM,{name},{value} is not supported: .*{why}"):
        parse_bulk_data(_GRID + [param])


@pytest.mark.parametrize("param", ["PARAM, INREL, 0", "PARAM, G, 0.0", "PARAM, W3, 0.",
                                   "PARAM, W4, 0.", "PARAM, LMODES, 0", "PARAM, INREL"])
def test_the_nastran_default_is_accepted_silently(param):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        parse_bulk_data(_GRID + [param])


@pytest.mark.parametrize("param, reason", [
    ("PARAM, POST, -1", "post-processor output files"),
    ("PARAM, PRTMAXIM, YES", "printout of maximum loads"),
    ("PARAM, GRDPNT, 0", "grid point weight generator"),
    ("PARAM, AUTOSPC, YES", "automatic constraint of singular DOFs"),
    ("PARAM, MAXRATIO, 1.+8", "singularity threshold"),
    ("PARAM, BAILOUT, -1", "continue past a near-singular matrix"),
])
def test_listed_output_param_is_ignored_with_its_reason(param, reason):
    name = param.split(",")[1].strip()
    with pytest.warns(UserWarning, match=rf"BDF card 'PARAM,{name}' ignored \({reason}"):
        parse_bulk_data(_GRID + [param])


def test_any_other_param_keeps_the_unknown_warning():
    with pytest.warns(UserWarning, match="Unknown BDF card 'PARAM,NEWSEQ' — skipped"):
        parse_bulk_data(_GRID + ["PARAM, NEWSEQ, -1"])


def test_case_control_param_follows_the_same_rules():
    """PARAM is also a case-control command (QRG p.570); #80 routes it here."""
    with pytest.raises(ValueError, match="PARAM,INREL,-1 is not supported"):
        parse_case_control(["SOL 101", "PARAM,INREL,-1", "SUBCASE 1"])
