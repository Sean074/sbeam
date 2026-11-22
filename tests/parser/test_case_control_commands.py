"""Every case-control line is read, ignored for a stated reason, or refused (#80).

Before #80 the parser dropped any line it did not know, so a PARAM, a symmetry
command or a SUBCOM above BEGIN BULK changed nothing and said nothing.  MSC rules
cited here are from the Quick Reference Guide 2024.1 (PDF page numbers).
"""
import glob
import os
import warnings

import pytest

from sbeam.parser.case_control import parse_case_control

REPO = os.path.join(os.path.dirname(__file__), "..", "..")


def _parse(*lines):
    return parse_case_control(["SOL 101", *lines])


class TestUnknownCommands:

    def test_misspelt_selector_is_refused(self):
        with pytest.raises(ValueError, match="Unknown case control command.*FROCE"):
            _parse("SUBCASE 1", "FROCE = 10")

    def test_unsupported_msc_command_is_refused(self):
        with pytest.raises(ValueError, match="Unknown case control command.*MPC"):
            _parse("SUBCASE 1", "MPC = 5")

    def test_line_that_is_not_a_command_is_refused(self):
        with pytest.raises(ValueError, match="Unknown case control command"):
            _parse("SUBCASE 1", "+, 1, 2, 3")

    def test_selector_with_a_non_integer_set_id_is_refused(self):
        with pytest.raises(ValueError, match="LOAD.*set ID must be an integer"):
            _parse("LOAD = TEN")

    def test_bulk_only_file_still_reports_the_missing_sol(self):
        with pytest.raises(ValueError, match="no SOL statement"):
            parse_case_control(["GRID, 1, , 0.0, 0.0, 0.0", "+, 1, 2"])


class TestRefusedCommands:

    @pytest.mark.parametrize("line", ["AESYMXZ = SYMMETRIC", "AESYMXY = ANTISYMMETRIC"])
    def test_case_control_symmetry_is_refused(self, line):
        # QRG p.252 remark 1: the command, when present, decides the symmetry.
        with pytest.raises(ValueError, match="AESYMX[YZ].*AEROS"):
            _parse(line)

    @pytest.mark.parametrize("line", [
        "SUBCOM 3", "SYMCOM 3", "SYM 3", "REPCASE 3", "SUBSEQ = 1.0, 1.0",
        "SYMSEQ = 1.0, 1.0"])
    def test_other_subcase_delimiters_are_refused(self, line):
        # QRG p.210.  Dropped, a SUBCOM's lines overwrote the previous SUBCASE.
        with pytest.raises(ValueError, match=line.split()[0]):
            _parse("SUBCASE 1", "LOAD = 10", line, "LOAD = 20")

    @pytest.mark.parametrize("line", ["COMPILE SEDRCVR", "ALTER 21", "ENDALTER"])
    def test_dmap_is_refused(self, line):
        with pytest.raises(ValueError, match="DMAP"):
            _parse(line)

    def test_msc_gust_is_not_read_as_gustlf(self):
        with pytest.raises(ValueError, match="GUST is the SOL 146"):
            _parse("GUST = 4")

    def test_output_request_with_describers_is_refused(self):
        with pytest.raises(ValueError, match="describers"):
            _parse("DISPLACEMENT(PRINT,PUNCH) = ALL")


class TestParam:
    """PARAM is a case-control command too (QRG p.570); the bulk rules apply."""

    def test_aunits_is_refused_as_in_bulk(self):
        with pytest.raises(ValueError, match="AUNITS"):
            _parse("PARAM,AUNITS,0.1")

    def test_wtmass_is_refused_as_in_bulk(self):
        with pytest.raises(ValueError, match="WTMASS"):
            _parse("PARAM, WTMASS, 0.00259")

    def test_unread_param_warns_as_in_bulk(self):
        with pytest.warns(UserWarning, match="PARAM,POST"):
            _parse("PARAM,POST,-1")

    def test_wtmass_of_one_is_accepted(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _parse("PARAM,WTMASS,1.0")


class TestSolNames:

    @pytest.mark.parametrize("name, number", [
        ("SESTATIC", 101), ("SEMODES", 103), ("AESTAT", 144), ("aestat", 144)])
    def test_msc_solution_name(self, name, number):
        # QRG p.186-187, Table 2.
        assert parse_case_control([f"SOL {name}"]).sol == number

    @pytest.mark.parametrize("value", ["SEBUCKL", "105"])
    def test_unsupported_solution_is_refused(self, value):
        with pytest.raises(ValueError, match=f"SOL {value} not supported"):
            parse_case_control([f"SOL {value}"])


class TestAbbreviations:
    """First four characters, if unique (QRG p.209)."""

    def test_abbreviated_requests_and_selectors(self):
        sc = _parse("SUBCASE 1", "DISP = ALL", "SPCF = ALL", "METH = 20",
                    "APRES = ALL", "SUBT = ignored").subcases[0]
        assert (sc.displacement, sc.spcforce, sc.apres) == (True, True, True)
        assert sc.method_sid == 20

    @pytest.mark.parametrize("line, attribute", [
        ("SPCFORCES = ALL", "spcforce"), ("SPCFORCE = ALL", "spcforce"),
        ("ELFORCE = ALL", "force"), ("ELSTRESS = ALL", "stress"),
        ("APRESSURE = ALL", "apres")])
    def test_msc_full_names_and_equivalents(self, line, attribute):
        # QRG p.634 (SPCFORCES), p.413 (ELFORCE), p.646 (ELSTRESS), p.263.
        assert getattr(_parse(line).subcases[0], attribute) is True

    def test_three_characters_are_not_an_abbreviation(self):
        with pytest.raises(ValueError, match="Unknown case control command"):
            _parse("DIS = ALL")

    def test_ambiguous_abbreviation_is_refused(self):
        with pytest.raises(ValueError, match="ambiguous.*SUBCASE, SUBCOM"):
            _parse("SUBC 1")

    def test_exact_name_wins_over_a_longer_command(self):
        # TRIM is also the start of TRIMOBJ and TRIMF.
        assert _parse("TRIM = 7").subcases[0].trim_sid == 7


class TestIgnoredCommands:

    def test_headings_and_executive_statements_are_silent(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            cc = parse_case_control([
                "ID MSC, HA144A", "TIME 5", "DIAG 8", "SOL 144", "CEND",
                "TITLE = T", "SUBTITLE = S", "LABEL = L", "ECHO = BOTH",
                "LINE = 60", "MAXLINES = 100000", "MONITOR = ALL",
                "ASSIGN USERFILE='X.CSV' STATUS=UNKNOWN UNIT=52",
                "SUBCASE 1", "TRIM = 1"])
        assert cc.title == "T"
        assert cc.subcases[0].trim_sid == 1

    @pytest.mark.parametrize("line", ["GPFORCE = ALL", "GPFO = ALL", "TRIMF = ALL"])
    def test_unwritten_output_request_warns(self, line):
        with pytest.warns(UserWarning, match="sbeam does not write"):
            _parse(line)


class TestContinuation:
    """A line ending in a comma continues on the next one (QRG p.209)."""

    def test_continued_ignored_command_takes_its_second_line(self):
        cc = _parse("ECHO = SORT,", "PUNCH", "LOAD = 10")
        assert cc.subcases[0].load_sid == 10

    def test_heading_ending_in_a_comma_is_not_continued(self):
        cc = _parse("TITLE = WING,", "LOAD = 10")
        assert cc.title == "WING,"
        assert cc.subcases[0].load_sid == 10


def _repo_decks():
    decks = []
    for pattern in ("sample/**/*.bdf", "tests/**/*.bdf", "examples/**/*.bdf"):
        for path in sorted(glob.glob(os.path.join(REPO, pattern), recursive=True)):
            with open(path, errors="replace") as fh:
                lines = fh.read().splitlines()
            head = []
            for line in lines:
                if line.split("$")[0].strip().upper().startswith("BEGIN"):
                    break
                head.append(line)
            else:
                continue          # no BEGIN BULK: a bulk-data file
            decks.append(pytest.param(head, id=os.path.relpath(path, REPO)))
    return decks


@pytest.mark.parametrize("head", _repo_decks())
def test_every_repo_deck_uses_known_commands(head):
    """Invariant: no shipped deck holds a line the parser would refuse."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parse_case_control(head)
