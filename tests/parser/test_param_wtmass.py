import warnings

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

# A weight-unit deck: PARAM,WTMASS scales the mass matrix in Nastran, which sbeam does not do
_WEIGHT_DECK = """\
PARAM, WTMASS, 0.002588
GRID, 1, , 0.0, 0.0, 0.0
CONM2, 1, 1, , 5.0
""".splitlines()


def test_param_wtmass_refused_unless_one():
    # WTMASS other than 1.0 is refused, naming the card and the rule
    with pytest.raises(ValueError, match="WTMASS"):
        parse_bulk_data(_WEIGHT_DECK)

    # WTMASS = 1.0 is a no-op and parses silently
    no_op = [line.replace("0.002588", "1.0") for line in _WEIGHT_DECK]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bulk = parse_bulk_data(no_op)
    assert 1 in bulk.conm2s
    assert not any("PARAM" in str(w.message) for w in caught)


def test_other_params_still_warn():
    # Only WTMASS is understood; any other PARAM is skipped with the unknown-card warning
    with pytest.warns(UserWarning, match="PARAM,AUNITS"):
        parse_bulk_data(["PARAM, AUNITS, 0.1", "GRID, 1, , 0.0, 0.0, 0.0"])
