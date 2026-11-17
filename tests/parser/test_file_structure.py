"""The input file is read as NASTRAN reads it: INCLUDE, BEGIN BULK and ENDDATA (#81).

An INCLUDE inserts its file where it stands and may nest; ENDDATA ends the bulk data;
BEGIN BULK opens the one bulk data section sbeam reads.  QRG pages are PDF pages of the
MSC Nastran 2024.1 Quick Reference Guide.
"""
import pytest

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data, parse_bulk_file

_CC = "SOL 101\nSUBCASE 1\n  LOAD = 10\n  SPC = 1\n"
_MODEL = ("GRID,1,,0.,0.,0.\nGRID,2,,1.,0.,0.\nMAT1,1,2.e11,,.3\n"
          "PBAR,1,1,.01,1.e-6,1.e-6,1.e-6\nCBAR,1,1,1,2,0.,1.,0.\nSPC1,1,123456,1\n")
_FORCE = "FORCE,10,2,,1000.,0.,0.,1.\n"


def _deck(tmp_path, text, **files):
    for name, body in files.items():
        path = tmp_path / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    deck = tmp_path / "run.bdf"
    deck.write_text(text)
    return deck


class TestEnddata:
    def test_card_after_enddata_is_refused(self, tmp_path):
        """Audit C7: a second FORCE after ENDDATA was applied (6000 N, NASTRAN 1000 N)."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\n" + _MODEL + _FORCE + "ENDDATA\n"
                     + "FORCE,10,2,,5000.,0.,0.,1.\n")
        with pytest.raises(ValueError, match="Bulk data after ENDDATA: 'FORCE,10,2,,5000."):
            parse_bdf(deck)

    def test_comments_and_blanks_after_enddata_are_harmless(self, tmp_path):
        deck = _deck(tmp_path, _CC + "BEGIN BULK\n" + _MODEL + _FORCE + "ENDDATA\n\n$ end\n")
        assert parse_bdf(deck)[1].forces[10][0].f == 1000.0

    def test_enddata_is_optional(self, tmp_path):
        """QRG p.1808 remark 1."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\n" + _MODEL + _FORCE)
        assert 10 in parse_bdf(deck)[1].forces

    def test_enddata_in_an_included_file_ahead_of_more_bulk_is_refused(self, tmp_path):
        """The repo's flagship bulk ended in ENDDATA and drivers read an overlay after it."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'model.dat'\n" + _FORCE + "ENDDATA\n",
                     **{"model.dat": _MODEL + "ENDDATA\n"})
        with pytest.raises(ValueError, match=r"ENDDATA in .*model\.dat, this line in .*run\.bdf"):
            parse_bdf(deck)

    def test_parse_bulk_data_stops_at_enddata(self):
        with pytest.raises(ValueError, match="Bulk data after ENDDATA"):
            parse_bulk_data(["GRID,1,,0.,0.,0.", "ENDDATA", "GRID,2,,1.,0.,0."])


class TestInclude:
    def test_bulk_include_below_begin_bulk(self, tmp_path):
        """QRG p.1984 example: BEGIN BULK / INCLUDE 'MYBULK.DATA' / ENDDATA."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'model.dat'\n" + _FORCE + "ENDDATA\n",
                     **{"model.dat": _MODEL})
        cc, bulk = parse_bdf(deck)
        assert sorted(bulk.grids) == [1, 2] and cc.includes == ["model.dat"]

    def test_bulk_included_above_begin_bulk_is_refused(self, tmp_path):
        """Audit C8: INCLUDE inserts its file where it stands (QRG p.465), so this bulk
        is case control to NASTRAN; sbeam used to read it as bulk data."""
        deck = _deck(tmp_path, _CC + "INCLUDE 'model.dat'\nBEGIN BULK\n" + _FORCE + "ENDDATA\n",
                     **{"model.dat": _MODEL})
        with pytest.raises(ValueError, match=r"model\.dat holds bulk data \(GRID\) but is "
                                             "INCLUDEd above BEGIN BULK"):
            parse_bdf(deck)

    def test_case_control_include_above_begin_bulk(self, tmp_path):
        """QRG p.465: INCLUDE may appear anywhere, so case control may come from a file."""
        deck = _deck(tmp_path, "SOL 101\nINCLUDE 'cases.inc'\nBEGIN BULK\n" + _MODEL + _FORCE,
                     **{"cases.inc": "SUBCASE 1\n  LOAD = 10\n  SPC = 1\n"})
        cc, _ = parse_bdf(deck)
        assert cc.subcases[0].load_sid == 10 and cc.includes == []

    def test_nested_include_is_relative_to_the_including_file(self, tmp_path):
        """QRG p.1984 remark 1: INCLUDEs nest; sbeam resolves a name against its own file."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'sub/model.dat'\n",
                     **{"sub__model.dat": _MODEL + "INCLUDE 'loads.dat'\n",
                        "sub__loads.dat": _FORCE})
        cc, bulk = parse_bdf(deck)
        assert 10 in bulk.forces
        assert cc.includes == ["sub/model.dat"]   # the main deck's INCLUDEs only

    def test_include_splits_a_card_from_its_continuation(self, tmp_path):
        """Textual insertion: the included line continues the card before the INCLUDE."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\n" + _MODEL + _FORCE
                     + "LOAD,20,1.,1.,10\nINCLUDE 'more.dat'\n",
                     **{"more.dat": "+,2.,10\n"})
        assert parse_bdf(deck)[1].loads[20].components == [(1.0, 10), (2.0, 10)]

    @pytest.mark.parametrize("statement", [
        "INCLUDE 'model.dat'", 'INCLUDE "model.dat"', "INCLUDE model.dat",
        "include 'model.dat'  $ shared model",
    ], ids=["single", "double", "unquoted", "lower-comment"])
    def test_filename_forms(self, tmp_path, statement):
        deck = _deck(tmp_path, _CC + f"BEGIN BULK\n{statement}\n" + _FORCE,
                     **{"model.dat": _MODEL})
        assert parse_bdf(deck)[0].includes == ["model.dat"]

    def test_filename_split_across_lines(self, tmp_path):
        """QRG p.1984 remark 2: INCLUDE '/dir123 / /dir456 / /dir789/filename.dat'."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'a\n      /b\n   /model.dat'\n" + _FORCE,
                     **{"a__b__model.dat": _MODEL})
        assert parse_bdf(deck)[0].includes == ["a/b/model.dat"]

    def test_unclosed_quote_is_refused(self, tmp_path):
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'model.dat\n" + _FORCE)
        with pytest.raises(ValueError, match="has no closing quote"):
            parse_bdf(deck)

    def test_nesting_deeper_than_ten_is_refused(self, tmp_path):
        """QRG p.1984 remark 1: 'The nested depth level must not be greater than 10.'"""
        files = {f"f{k}.dat": f"INCLUDE 'f{k + 1}.dat'\n" for k in range(1, 11)}
        files["f11.dat"] = _MODEL
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'f1.dat'\n" + _FORCE, **files)
        with pytest.raises(ValueError, match="nest more than 10 deep"):
            parse_bdf(deck)
        files["f10.dat"] = _MODEL                     # ten deep is allowed
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'f1.dat'\n" + _FORCE, **files)
        assert 10 in parse_bdf(deck)[1].forces

    def test_self_include_is_refused(self, tmp_path):
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'loop.dat'\n",
                     **{"loop.dat": "INCLUDE 'loop.dat'\n"})
        with pytest.raises(ValueError, match="includes itself"):
            parse_bdf(deck)

    def test_missing_file_names_the_including_file(self, tmp_path):
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'model.dat'\n",
                     **{"model.dat": "INCLUDE 'gone.dat'\n"})
        with pytest.raises(FileNotFoundError, match=r"'gone\.dat' \(INCLUDEd by .*model\.dat"):
            parse_bdf(deck)

    def test_parse_bulk_file_expands_includes(self, tmp_path):
        """The viewer loads a driver deck's geometry: its INCLUDEd bulk used to be lost."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\nINCLUDE 'model.dat'\n" + _FORCE + "ENDDATA\n",
                     **{"model.dat": _MODEL})
        assert sorted(parse_bulk_file(deck).grids) == [1, 2]


class TestBeginBulk:
    @pytest.mark.parametrize("begin", [
        "BEGIN SUPER=1", "BEGIN BULK SUPER=1", "BEGIN BULK TRMC=101", "BEGIN AUXMODEL=22",
    ])
    def test_partitioned_section_is_refused(self, tmp_path, begin):
        """QRG p.286–287: these open a separate Bulk Data Section, which sbeam merged."""
        deck = _deck(tmp_path, _CC + "BEGIN BULK\n" + _MODEL + f"{begin}\n" + _FORCE)
        with pytest.raises(ValueError, match="partitioned Bulk Data Sections"):
            parse_bdf(deck)

    def test_partitioned_section_as_the_opening_begin_is_refused(self, tmp_path):
        deck = _deck(tmp_path, _CC + "BEGIN BULK TRMC=101\n" + _MODEL + _FORCE)
        with pytest.raises(ValueError, match="partitioned Bulk Data Sections"):
            parse_bdf(deck)

    def test_spacing_and_case_of_begin_bulk(self, tmp_path):
        deck = _deck(tmp_path, _CC + "begin   bulk  $ model\n" + _MODEL + _FORCE)
        assert 10 in parse_bdf(deck)[1].forces
