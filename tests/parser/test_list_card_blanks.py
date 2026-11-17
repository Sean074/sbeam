"""List cards apply their own QRG blank-field rule; a blank is never skipped (#73 sweep).

DIVERG stops at a blank (QRG 2024.1 p.1603 remark 4; ``test_step55_diverg.py``); AEFACT
and AELIST forbid an embedded blank (p.1141 remark 2, p.1145 remark 3).  sbeam used to
skip the blank and read on.  Trailing blanks are not embedded and stay harmless.
"""
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data


@pytest.mark.parametrize("lines, match", [
    (["AEFACT,97,.3,,1.0"], r"AEFACT 97: embedded blank fields are not allowed.*\['1\.0'\]"),
    (["AEFACT,97,.1,.2,.3,.4,.5,.6,,+A", "+A,.8"], "AEFACT 97: embedded blank"),
    (["AELIST,75,1001,,1003"], r"AELIST 75: intervening blank fields are not allowed"),
    (["AELIST,75,1001,THRU,,1075"], "AELIST 75: intervening blank"),
], ids=["aefact", "aefact-before-continuation", "aelist", "aelist-thru"])
def test_embedded_blank_is_refused(lines, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(lines)


def test_qrg_examples_and_trailing_blanks_read():
    bulk = parse_bulk_data([
        "AEFACT,97,.3,.7,1.0,,",                            # QRG p.1141 example + blanks
        "AELIST,75,1001,THRU,1075,1101,THRU,1109,1201",     # QRG p.1145 example
        "+,1202",
    ])
    assert bulk.aefacts[97].data == pytest.approx([0.3, 0.7, 1.0])
    els = bulk.aelists[75].elements
    assert (len(els), els[0], els[-1]) == (75 + 9 + 2, 1001, 1202)
