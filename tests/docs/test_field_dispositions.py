"""The "Vendor fields" tables in ``02_card_reference.md`` state what the parser does (#95, D2).

CLAUDE.md rule 7: each field of a vendor card is read, refused if non-blank, or documented
as ignored with the reason.  ``CARDS`` below is that statement for every vendor-named card,
with one or more probes per field.  Two things are gated:

* **the parser does what the table says** — each probe changes one field of a valid card
  and the deck must then parse to a different model (read), be refused, or parse to the
  same model (ignored / not checked);
* **the card reference prints this table** — ``render`` gives the block that must appear,
  word for word, in the card's section.  To change a table, change ``CARDS`` and run
  ``python tests/docs/test_field_dispositions.py --write``.

The unread-line refusal (#63) and the pyNastran cross-parse (#83) cover whole lines and
field values; this covers a field inside a line that is read.
"""
from __future__ import annotations

import copy
import re
import sys
import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf

REPO = Path(__file__).resolve().parents[2]
CARD_REFERENCE = REPO / "docs/10_standard/02_card_reference.md"

#: A model every probe card can sit in: a five-grid beam, spare grids, one CORD2R parallel
#: to basic, and a two-by-two aero panel with its lists.
CONTEXT = """GRID,1,,0.,0.,0.
GRID,2,,1.,0.,0.
GRID,3,,2.,0.,0.
GRID,4,,3.,0.,0.
GRID,5,,4.,0.,0.
GRID,21,,4.,1.,0.
GRID,22,,4.,2.,0.
GRID,23,,4.,3.,0.
GRID,24,,4.,4.,0.
GRID,25,,5.,1.,0.
GRID,26,,5.,2.,0.
CORD2R,7,,1.,0.,0.,1.,0.,1.
+,2.,0.,0.
MAT1,1,1.e7,,0.3
MAT1,3,2.e7,,0.3
PBAR,1,1,1.,1.,1.,1.
PBAR,2,1,2.,2.,2.,2.
CBAR,2,1,2,3,0.,1.,0.
CBAR,3,1,3,4,0.,1.,0.
PROD,3,1,1.,1.
PROD,4,1,2.,2.
PBUSH,62,K,1.,1.,1.,1.,1.,1.
PBUSH,63,K,2.,2.,2.,2.,2.,2.
SPC1,1,123456,1
FORCE,14,5,0,1.,0.,0.,1.
FORCE,17,5,0,1.,0.,0.,1.
AEROS,0,0,1.,4.,4.,0,0
PAERO1,1
PAERO1,4
AEFACT,9,0.,.5,1.
CAERO1,100,1,0,2,2,,,0
+,0.,0.,0.,1.,0.,3.,0.,1.
SET1,5,1,2,3,4
SET1,6,2,3,4,5
AELIST,7,100,101
AELIST,8,102,103
AESTAT,501,ANGLEA
AESTAT,503,URDD3""".splitlines()

READ, REFUSED, SAME = "read", "refused", "same"

#: Issue for data in a field the vendor layout leaves blank (found writing these tables).
BLANK_FIELD_ISSUE = "#109"


def e(row: int, col: int, value: str, *more: tuple[int, int, str]) -> list:
    """A probe that sets field ``col + 1`` of line ``row + 1`` (and any ``more``)."""
    return [(row, col, value), *more]


def line(*fields: str) -> tuple:
    """A probe that adds a continuation line."""
    return ("+",) + tuple(fields)


def blank(fields: str) -> str:
    return (f"Data in {fields}, blank in the vendor layout, is not refused "
            f"({BLANK_FIELD_ISSUE})")


# card -> (citation, context cards to drop, base lines, lines after the card,
#          [(row of the table, cell text, probes, outcome every probe must give)])
R, X, I, U = "Read", "Refused", "Ignored", "Not checked"
OUTCOME = {R: READ, X: REFUSED, I: SAME, U: SAME}

CARDS: dict[str, tuple] = {
    "CORD2R": ("MSC QRG p.1469", [], [["CORD2R", "8", "", "0.", "0.", "0.", "0.", "0.", "1."],
                                    ["+", "1.", "0.", "0."]], [], [
        (R, "CID, RID, A1–A3, B1–B3, C1–C3",
         [e(0, 1, "11"), e(0, 2, "7"), e(0, 3, ".5"), e(0, 4, ".5"), e(0, 5, ".5"),
          e(0, 6, ".5"), e(0, 7, ".5"), e(0, 8, "2."), e(1, 1, "2."), e(1, 2, ".5"),
          e(1, 3, ".5")]),
        (U, blank("fields 5–9 of line 2"), [e(1, 4, "1.")]),
    ]),
    "GRID": ("MSC QRG p.1944", [], [["GRID", "20", "", "9.", "0.", "0.", "", "", ""]], [], [
        (R, "ID, CP, X1–X3, CD (prints results in that frame; see CD ≠ 0 above), PS",
         [e(0, 1, "30"), e(0, 2, "7"), e(0, 3, "8."), e(0, 4, "1."), e(0, 5, "1."),
          e(0, 6, "7"), e(0, 7, "123")]),
        (X, "SEID (non-zero: no superelements); a second line",
         [e(0, 8, "3"), line("1.")]),
    ]),
    "CBAR": ("MSC QRG p.1360", [], [["CBAR", "1", "1", "1", "2", "0.", "1.", "0.", ""], ["+"]],
             [], [
        (R, "EID, PID, GA, GB, X1–X3, OFFT (one of the eight legal words; the offset "
            "letters have no effect), PA, PB",
         [e(0, 1, "91"), e(0, 2, "2"), e(0, 3, "3"), e(0, 4, "3"), e(0, 5, ".5"),
          e(0, 6, "2."), e(0, 7, "1."), e(0, 8, "BGG"), e(1, 1, "5"), e(1, 2, "5")]),
        (X, "G0 (an integer in field 6); W1A–W3B (non-zero: offsets are not supported); "
            "a third line",
         [e(0, 5, "20"), e(1, 3, ".1"), e(1, 4, ".1"), e(1, 5, ".1"), e(1, 6, ".1"),
          e(1, 7, ".1"), e(1, 8, ".1"), line("1.")]),
    ]),
    "CROD": ("MSC QRG p.1522", [], [["CROD", "30", "3", "4", "5"]], [], [
        (R, "EID, PID, G1, G2", [e(0, 1, "31"), e(0, 2, "4"), e(0, 3, "3"), e(0, 4, "3")]),
        (U, blank("fields 6–9"), [e(0, 5, "1.")]),
    ]),
    "PROD": ("MSC QRG p.2622", [], [["PROD", "5", "1", "1.", "1.", "", ""]], [], [
        (R, "PID, MID, A, J, C, NSM",
         [e(0, 1, "6"), e(0, 2, "3"), e(0, 3, "2."), e(0, 4, "2."), e(0, 5, ".5"),
          e(0, 6, ".5")]),
        (U, blank("fields 8–9"), [e(0, 7, "1.")]),
    ]),
    "CONROD": ("MSC QRG p.1452", [], [["CONROD", "40", "4", "5", "1", "1.", "1.", "", ""]],
               [], [
        (R, "EID, G1, G2, MID, A, J, C, NSM",
         [e(0, 1, "41"), e(0, 2, "3"), e(0, 3, "3"), e(0, 4, "3"), e(0, 5, "2."),
          e(0, 6, "2."), e(0, 7, ".5"), e(0, 8, ".5")]),
    ]),
    "PLOTEL": ("MSC QRG p.2594", [], [["PLOTEL", "50", "1", "5"]], [], [
        (R, "EID, G1, G2", [e(0, 1, "51"), e(0, 2, "2"), e(0, 3, "4")]),
        (U, blank("fields 5–9"), [e(0, 4, "3")]),
    ]),
    "PBAR": ("MSC QRG p.2431", [], [["PBAR", "9", "1", "1.", "1.", "1.", "1.", "", ""],
                                  ["+"], ["+"]], [], [
        (R, "PID, MID, A, I1, I2, J, NSM, C1–F2",
         [e(0, 1, "10"), e(0, 2, "3"), e(0, 3, "2."), e(0, 4, "2."), e(0, 5, "2."),
          e(0, 6, "2."), e(0, 7, ".5"), e(1, 1, ".1"), e(1, 2, ".1"), e(1, 3, ".1"),
          e(1, 4, ".1"), e(1, 5, ".1"), e(1, 6, ".1"), e(1, 7, ".1"), e(1, 8, ".1")]),
        (X, "K1, K2 (non-blank: no shear flexibility); I12 (non-zero: uncoupled bending "
            "planes); a fourth line",
         [e(2, 1, ".8"), e(2, 2, ".8"), e(2, 3, ".1"), line("1.")]),
        (U, blank("field 9 of line 1"), [e(0, 8, "1.")]),
    ]),
    "PBUSH": ("MSC QRG p.2493", [], [["PBUSH", "60", "K", "1.", "1.", "1.", "1.", "1.", "1."]],
              [], [
        (R, "PID, the `K` line (K1–K6)", [e(0, 1, "61"), e(0, 3, "2."), e(0, 8, "2.")]),
        (X, "the `B`, `GE`, `M` and `T` lines, unless every value is blank or zero "
            "(damping, mass and thermal data are not used)",
         [line("", "B", "1."), line("", "GE", ".1"), line("", "M", "1."),
          line("", "T", "1.e-5", "20.", "1")]),
        (I, "the `RCV` line (stress recovery coefficients: output only); a `B`, `GE`, `M` "
            "or `T` line of zeros",
         [line("", "RCV", "1.", "1.", "1.", "1."), line("", "B", "0.")]),
    ]),
    "CBUSH": ("MSC QRG p.1378–1379", [], [["CBUSH", "70", "62", "4", "5", "0.", "1.", "0.", ""],
                                         ["+"]], [], [
        (R, "EID, PID, GA, GB, X1–X3, CID, S",
         [e(0, 1, "71"), e(0, 2, "63"), e(0, 3, "3"), e(0, 4, "3"), e(0, 5, ".5"),
          e(0, 6, "2."), e(0, 7, "1."), e(0, 8, "7"), e(1, 1, ".25")]),
        (X, "GO (an integer in field 6); OCID other than blank or −1 (the S1–S3 offset is "
            "not supported)",
         [e(0, 5, "20"), e(1, 2, "7")]),
        (I, "OCID = −1; S1–S3 (MSC reads them only \"if OCID > 0\", p.1379, and such an "
            "OCID is refused)",
         [e(1, 2, "-1"), e(1, 3, ".1"), e(1, 4, ".1"), e(1, 5, ".1")]),
        (U, blank("fields 7–9 of line 2"), [e(1, 6, "1"), e(1, 8, "1")]),
    ]),
    "RBE2": ("MSC QRG p.2699", [], [["RBE2", "80", "5", "123456", "21", "22"]], [], [
        (R, "EID, GN, CM, GMi",
         [e(0, 1, "81"), e(0, 2, "4"), e(0, 3, "123"), e(0, 4, "23")]),
        (X, "ALPHA, TREF (a real after the grid list stops with a Python `int()` message, "
            "#89)",
         [e(0, 6, "1.e-5"), e(0, 6, "1.e-5", (0, 7, "20."))]),
    ]),
    "RBAR": ("MSC QRG p.2691–2692", [], [["RBAR", "82", "5", "23", "123456", "", "", "", ""],
                                        ["+"]], [], [
        (R, "EID, GA, GB", [e(0, 1, "83"), e(0, 2, "4"), e(0, 3, "24")]),
        (X, "CNA other than 123456; CNB non-blank; CMA non-blank; CMB other than blank, 0 "
            "or 123456 (only the all-six-dependent bar of remark 4 is built); TREF (field 2 "
            "of line 2: an unread line)",
         [e(0, 4, "123"), e(0, 5, "456"), e(0, 6, "456"), e(0, 7, "123"), e(1, 1, "20.")]),
        (I, "CMB = 123456 (the default set); ALPHA (no thermal loads)",
         [e(0, 7, "123456"), e(0, 8, "1.e-5")]),
    ]),
    "RBE3": ("MSC QRG p.2704", [], [["RBE3", "84", "", "25", "123456", "1.", "123456", "3", "4"]],
             [], [
        (R, "EID, REFGRID, REFC, WTi, Ci, Gi,j",
         [e(0, 1, "85"), e(0, 3, "26"), e(0, 4, "123"), e(0, 5, "2."), e(0, 6, "123"),
          e(0, 7, "2")]),
        (X, "field 3 (blank in MSC's layout); the `UM` section",
         [e(0, 2, "5"), line("UM", "3", "1")]),
        (I, "the `ALPHA` section (ALPHA, TREF), with a warning: no thermal loads",
         [line("ALPHA", "1.e-5", "20.")]),
    ]),
    "MAT1": ("MSC QRG p.2020", [], [["MAT1", "2", "1.e7", "4.e6", "0.3", "1.", "", "", ""]],
             [], [
        (R, "MID, E, G, NU, RHO",
         [e(0, 1, "4"), e(0, 2, "2.e7"), e(0, 3, "5.e6"), e(0, 4, ".25"), e(0, 5, "2.")]),
        (X, "the second line (ST, SC, SS, MCSID): an unread line",
         [line("1.", "1.", "1.", "7")]),
        (I, "A, TREF (no thermal loads); GE (no supported solution uses structural damping)",
         [e(0, 6, "1.e-5"), e(0, 7, "20."), e(0, 8, ".02")]),
    ]),
    "CONM2": ("MSC QRG p.1449", [], [["CONM2", "90", "5", "0", "1.", "0.", "0.", "0.", ""],
                                    ["+", "0.", "0.", "0.", "0.", "0.", "0."]], [], [
        (R, "EID, G, CID (0 or a CORD2R), M, X1–X3, I11–I33",
         [e(0, 1, "91"), e(0, 2, "4"), e(0, 3, "7"), e(0, 4, "2."), e(0, 5, ".1"),
          e(0, 6, ".1"), e(0, 7, ".1"), e(1, 1, "1."), e(1, 2, ".1"), e(1, 3, "1."),
          e(1, 4, ".1"), e(1, 5, ".1"), e(1, 6, "1.")]),
        (X, "CID = −1 (X1–X3 as the C.G. in basic; refused with a misleading message, "
            "#89); field 9 of line 1 (blank in MSC's layout)",
         [e(0, 3, "-1"), e(0, 8, "1.")]),
        (U, blank("fields 8–9 of line 2"), [e(1, 7, "1.")]),
    ]),
    "SPC": ("MSC QRG p.2833", [], [["SPC", "2", "1", "123", "0.", "2", "3", "0."]], [], [
        (R, "SID, G1, C1, G2, C2",
         [e(0, 1, "3"), e(0, 2, "3"), e(0, 3, "12"), e(0, 5, "4"), e(0, 6, "1")]),
        (X, "D1, D2 (non-zero: no enforced displacement)", [e(0, 4, ".1"), e(0, 7, ".1")]),
        (U, blank("field 9"), [e(0, 8, "1")]),
    ]),
    "SPC1": ("MSC QRG p.2835", ["SPC1"], [["SPC1", "1", "123456", "1"]], [], [
        (R, "SID, C, Gi", [e(0, 1, "3"), e(0, 2, "123"), e(0, 3, "2")]),
        (X, "`THRU` (stops with a Python `int()` message, #89)", [e(0, 4, "THRU", (0, 5, "3"))]),
    ]),
    "FORCE": ("MSC QRG p.1868", [], [["FORCE", "10", "5", "0", "1.", "0.", "0.", "1.", ""]],
              [], [
        (R, "SID, G, CID, F, N1–N3",
         [e(0, 1, "11"), e(0, 2, "4"), e(0, 3, "7"), e(0, 4, "2."), e(0, 5, "1."),
          e(0, 6, "1."), e(0, 7, "2.")]),
        (U, blank("field 9"), [e(0, 8, "1.")]),
    ]),
    "MOMENT": ("MSC QRG p.2294", [], [["MOMENT", "10", "5", "0", "1.", "0.", "0.", "1.", ""]],
               [], [
        (R, "SID, G, CID, M, N1–N3",
         [e(0, 1, "11"), e(0, 2, "4"), e(0, 3, "7"), e(0, 4, "2."), e(0, 5, "1."),
          e(0, 6, "1."), e(0, 7, "2.")]),
        (U, blank("field 9"), [e(0, 8, "1.")]),
    ]),
    "LOAD": ("MSC QRG p.2008", [], [["LOAD", "12", "1.", "1.", "14"]], [], [
        (R, "SID, S, Si, Li (a FORCE, MOMENT or GRAV set; a LOAD set is refused, #89)",
         [e(0, 1, "13"), e(0, 2, "2."), e(0, 3, "2."), e(0, 4, "17")]),
    ]),
    "GRAV": ("MSC QRG p.1941", [], [["GRAV", "15", "0", "9.81", "0.", "0.", "-1.", ""]], [], [
        (R, "SID, A, N1–N3",
         [e(0, 1, "16"), e(0, 3, "1."), e(0, 4, "1."), e(0, 5, "1."), e(0, 6, "-2.")]),
        (X, "CID (non-zero: gravity is given in basic)", [e(0, 2, "7")]),
        (I, "MB (it says where a superelement run finds CID; sbeam has no superelements)",
         [e(0, 7, "-1")]),
        (U, blank("field 9"), [e(0, 8, "1")]),
    ]),
    "EIGRL": ("MSC QRG p.1801–1802", [], [["EIGRL", "20", "", "", "3", "", "", "", ""]], [], [
        (R, "SID, ND, NORM (field 9: `MASS` or `MAX`)",
         [e(0, 1, "21"), e(0, 4, "4"), e(0, 8, "MAX")]),
        (X, "V1, V2 (the lowest ND roots are returned; no frequency range); the option "
            "line (`NORM=MAX` …): an unread line",
         [e(0, 2, ".1"), e(0, 3, "100."), line("NORM=MAX")]),
        (I, "MSGLVL, MAXSET, SHFSCL (they steer MSC's Lanczos solver, not which roots are "
            "found)",
         [e(0, 5, "1"), e(0, 6, "5"), e(0, 7, "10.")]),
    ]),
    "MASSSET": ("MSC QRG p.2018", [], [["MASSSET", "300", "1.", "1.", "0", "1.", "101"]],
                ["BEGIN MASSID=101", "CONM2,6001,5,0,1."], [
        (R, "ID, S0, Si, IDi",
         [e(0, 1, "301"), e(0, 2, "2."), e(0, 3, "2."), e(0, 5, "2.")]),
    ]),
    "AEROS": ("MSC QRG p.1151", ["AEROS"], [["AEROS", "0", "0", "1.", "4.", "4.", "0", "0", ""]],
              [], [
        (R, "ACSID (0 or a CORD2R parallel to basic), RCSID, REFC, REFB, REFS, SYMXZ, "
            "SYMXY (both read here; a non-zero value is refused when the aero model is "
            "built)",
         [e(0, 1, "7"), e(0, 2, "7"), e(0, 3, "2."), e(0, 4, "5."), e(0, 5, "5."),
          e(0, 6, "1"), e(0, 7, "1")]),
        (X, "field 9 (blank in MSC's layout; sbeam's MACH until v0.4.1)", [e(0, 8, ".5")]),
    ]),
    "PAERO1": ("MSC QRG p.2413", [], [["PAERO1", "2"]], [], [
        (R, "PID", [e(0, 1, "3")]),
        (I, "B1–B6 (IDs of associated CAERO2 bodies; sbeam has no CAERO2, and a deck "
            "holding one is refused)",
         [e(0, 2, "500"), e(0, 7, "500")]),
        (U, blank("field 9"), [e(0, 8, "1")]),
    ]),
    "AEFACT": ("MSC QRG p.1141", [], [["AEFACT", "8", "0.", ".5", "1."]], [], [
        (R, "SID, Di", [e(0, 1, "10"), e(0, 2, ".1")]),
    ]),
    "CAERO1": ("MSC QRG p.1343", [], [["CAERO1", "200", "1", "0", "2", "2", "", "", "0"],
                                     ["+", "0.", "-3.", "0.", "1.", "0.", "-.5", "0.", "1."]],
               [], [
        (R, "EID, PID, CP, NSPAN, NCHORD, LSPAN, LCHORD, IGID, X1, Y1, Z1, X12, X4, Y4, "
            "Z4, X43",
         [e(0, 1, "300"), e(0, 2, "4"), e(0, 3, "7"), e(0, 4, "3"), e(0, 5, "3"),
          e(0, 4, "", (0, 6, "9")), e(0, 5, "", (0, 7, "9")),
          e(1, 1, ".1"), e(1, 2, "-2.9"), e(1, 3, ".1"), e(1, 4, "2."), e(1, 5, ".1"),
          e(1, 6, "-.6"), e(1, 7, ".1"), e(1, 8, "2.")]),
        (X, "LSPAN with NSPAN, LCHORD with NCHORD (MSC uses the list only when the count "
            "is zero or blank, #89); an IGID that differs from another CAERO1's (one AIC "
            "over every panel)",
         [e(0, 6, "9"), e(0, 7, "9"), e(0, 8, "1")]),
    ]),
    "SET1": ("MSC QRG p.2813", [], [["SET1", "4", "1", "2", "3"]], [], [
        (R, "SID, IDi", [e(0, 1, "3"), e(0, 2, "5")]),
        (X, "`THRU` (stops with a Python `int()` message, #89)", [e(0, 3, "THRU", (0, 4, "4"))]),
    ]),
    "SPLINE2": ("MSC QRG p.2849", [], [["SPLINE2", "1", "100", "100", "103", "5", "0.", "1.", "0"],
                                      ["+", "", "", "", ""]], [], [
        (R, "EID, CAERO, ID1, ID2, SETG, DZ (≥ 0), DTOR (> 0), CID, DTHX, DTHY",
         [e(0, 1, "2"), e(0, 3, "101"), e(0, 4, "102"), e(0, 5, "6"), e(0, 6, ".1"),
          e(0, 7, "2."), e(0, 8, "7"), e(1, 1, "-1."), e(1, 2, "-1.")]),
        (X, "USAGE other than `BOTH` or blank (`FORCE`, `DISP`: every spline is used for "
            "both transforms); field 4 of line 2 (blank in MSC's layout)",
         [e(1, 4, "FORCE"), e(1, 4, "DISP"), e(1, 3, "BOTH")]),
        (I, "USAGE = `BOTH` (the default)", [e(1, 4, "BOTH")]),
        (U, blank("fields 6–9 of line 2"), [e(1, 5, "1"), e(1, 8, "1")]),
    ]),
    "AELIST": ("MSC QRG p.1145", [], [["AELIST", "9", "100", "101"]], [], [
        (R, "SID, Ei, `THRU`",
         [e(0, 1, "10"), e(0, 2, "102"), e(0, 3, "THRU", (0, 4, "103"))]),
    ]),
    "AESTAT": ("MSC QRG p.1153", [], [["AESTAT", "502", "PITCH"]], [], [
        (R, "ID, LABEL (one of MSC's standard labels)", [e(0, 1, "504"), e(0, 2, "SIDES")]),
        (X, "any other LABEL (MSC needs AELINK or DMI data for it, p.1154 remark 3)",
         [e(0, 2, "THRUST")]),
        (U, blank("fields 4–9"), [e(0, 3, "1")]),
    ]),
    "AESURF": ("MSC QRG p.1155", [], [["AESURF", "601", "ELEV", "0", "7", "", "", "", ""],
                                     ["+"]], [], [
        (R, "ID, LABEL, CID1, ALID1, CID2, ALID2 (the last two together), EFF",
         [e(0, 1, "602"), e(0, 2, "FLAP"), e(0, 3, "7"), e(0, 4, "8"),
          e(0, 5, "7", (0, 6, "8")), e(0, 7, ".5")]),
        (X, "LDW = `NOLDW`; the second line (CREFC, CREFS, PLLIM, PULIM, HMLLIM, HMULIM, "
            "TQLLIM, TQULIM): limits and reference values are not used (#44)",
         [e(0, 8, "NOLDW"), e(1, 1, "2."), e(1, 2, "2."), e(1, 3, "-.5"), e(1, 4, ".5"),
          e(1, 5, "-1."), e(1, 6, "1."), e(1, 7, "1"), e(1, 8, "1")]),
        (I, "LDW = `LDW` (the default)", [e(0, 8, "LDW")]),
    ]),
    "TRIM": ("MSC QRG p.2992", [], [["TRIM", "1", "0.3", "100.", "ANGLEA", "0.1", "", "", ""],
                                   ["+"]], [], [
        (R, "SID, MACH, Q, LABELi, UXi",
         [e(0, 1, "2"), e(0, 2, ".5"), e(0, 3, "200."), e(0, 4, "URDD3"), e(0, 5, ".2"),
          e(0, 6, "URDD3", (0, 7, "0.")), e(1, 1, "URDD3", (1, 2, "0."))]),
        (X, "AEQR other than blank or 1.0 (the rigid and scaled-feedback trims, #88)",
         [e(0, 8, "0."), e(0, 8, ".5")]),
        (I, "AEQR = 1.0 (the default: elastic trim)", [e(0, 8, "1.")]),
    ]),
    "SUPORT": ("MSC QRG p.2870", [], [["SUPORT", "1", "123456"]], [], [
        (R, "IDi, Ci", [e(0, 1, "2"), e(0, 2, "35"), e(0, 3, "2", (0, 4, "123"))]),
    ]),
    "DIVERG": ("MSC QRG p.1603", [], [["DIVERG", "70", "2", ".5"]], [], [
        (R, "SID, NROOT, Mi", [e(0, 1, "71"), e(0, 2, "3"), e(0, 3, ".6"), e(0, 4, ".7")]),
    ]),
    "AECOMP": ("MSC QRG p.1138", [], [["AECOMP", "WING", "AELIST", "7"]], [], [
        (R, "NAME, LISTTYPE (`AELIST` or `SET1`), LISTIDi",
         [e(0, 1, "W2"), e(0, 2, "SET1", (0, 3, "5")), e(0, 3, "8"), e(0, 4, "8")]),
        (X, "LISTTYPE = `CAERO` or `CMPID` (#89)", [e(0, 2, "CAERO"), e(0, 2, "CMPID")]),
    ]),
    "MONPNT1": ("MSC QRG p.2303–2304", [], [["AECOMP", "WING", "AELIST", "7"],
                                           ["MONPNT1", "WROOT", "root load"],
                                           ["+", "123456", "WING", "0", "0.", "0.", "0.", ""]],
                [], [
        (R, "NAME, LABEL, AXES, COMP, CP, X, Y, Z",
         [e(1, 1, "W2"), e(1, 2, "other"), e(2, 1, "35"), e(2, 3, "7"), e(2, 4, "1."),
          e(2, 5, "1."), e(2, 6, "1.")]),
        (X, "CD other than blank or CP (output is in CP, MSC's default)", [e(2, 7, "7")]),
        (I, "CD = CP", [e(2, 7, "0")]),
        (U, blank("field 9 of line 2"), [e(2, 8, "1")]),
    ]),
    "TABLED1": ("MSC QRG p.2896", [], [["TABLED1", "30", "", "", "", "", "", "", ""],
                                      ["+", "0.", "0.", "1.", "1.", "ENDT"]], [], [
        (R, "TID, xi, yi", [e(0, 1, "31"), e(1, 1, "-1."), e(1, 2, "5.")]),
        (X, "XAXIS, YAXIS = `LOG` (linear interpolation only)",
         [e(0, 2, "LOG"), e(0, 3, "LOG")]),
        (I, "XAXIS, YAXIS = `LINEAR` (the default); `ENDT` (a table without it is "
            "accepted)",
         [e(0, 2, "LINEAR"), e(0, 3, "LINEAR"), e(1, 5, "")]),
    ]),
}

#: Vendor-named cards whose section already carries a per-field table of its own.
OWN_TABLE = {"DMIJ", "DMIK", "TRIMVAR"}
#: Vendor-named cards refused whole; their sections say so.
REFUSED_WHOLE = {"SPLINE1", "MONPNT3"}
#: sbeam-only cards and case-control words in the "at a glance" list: no vendor layout.
SBEAM_ONLY = {"MASSCASE", "W2GJ", "WKK", "AECORR", "CPINJ", "PSTRIP", "STRIPK", "LOADINJ",
              "BODYATT", "TRIMINEQ", "TRIMWGT", "MONSECT", "GUSTLF", "MANVR", "MANTRIM",
              "MANCMD", "MANTIME", "MANPRNT"}


# ---------------------------------------------------------------------------
# probing
# ---------------------------------------------------------------------------

def _pad(rows: list[list[str]]) -> list[list[str]]:
    return [list(r) + [""] * (9 - len(r)) for r in rows]


def _parse(card: str, rows: list[list[str]], tmp: Path) -> str:
    _cite, drop, _base, tail, _table = CARDS[card]
    context = [ln for ln in CONTEXT if not any(ln.startswith(d + ",") for d in drop)]
    body = [",".join(r).rstrip(",") for r in rows]
    deck = tmp / "probe.bdf"
    deck.write_text("\n".join(["SOL 101", "SUBCASE 1", "SPC = 1", "BEGIN BULK",
                               *context, *body, *tail, "ENDDATA"]) + "\n")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return repr(parse_bdf(deck)[1])


def _apply(base: list[list[str]], probe) -> list[list[str]]:
    rows = _pad(copy.deepcopy(base))
    if isinstance(probe, tuple):                      # an added continuation line
        return rows + _pad([["+", *probe[1:]]])
    for row, col, value in probe:
        rows[row][col] = value
    return rows


def outcome(card: str, probe, tmp: Path) -> str:
    base = CARDS[card][2]
    reference = _parse(card, _pad(copy.deepcopy(base)), tmp)
    try:
        model = _parse(card, _apply(base, probe), tmp)
    except (ValueError, IndexError, NotImplementedError):
        return REFUSED
    return SAME if model == reference else READ


def _probes() -> list:
    return [pytest.param(card, row, probe, id=f"{card}-{row.split()[0]}-{k}")
            for card, spec in CARDS.items()
            for row, _text, probes in spec[4]
            for k, probe in enumerate(probes)]


@pytest.mark.parametrize("card, row, probe", _probes())
def test_parser_does_what_the_table_says(card, row, probe, tmp_path):
    assert outcome(card, probe, tmp_path) == OUTCOME[row], (
        f"{card}: probe {probe} is listed under '{row}' in the Vendor fields table")


# ---------------------------------------------------------------------------
# the document
# ---------------------------------------------------------------------------

BEGIN = "<!-- vendor-fields:{card} -->"
END = "<!-- /vendor-fields -->"


def render(card: str) -> str:
    cite, _drop, _base, _tail, table = CARDS[card]
    cells: dict[str, list[str]] = {R: [], X: [], I: [], U: []}
    for row, text, _probes in table:
        cells[row].append(text)
    out = [BEGIN.format(card=card),
           f"**Vendor fields** ({cite}; gate `tests/docs/test_field_dispositions.py`):",
           "",
           "| Disposition | Fields |",
           "|---|---|"]
    for row in (R, X, I, U):
        if cells[row] or row in (R, X, I):
            out.append(f"| {row} | {'; '.join(cells[row]) or '—'} |")
    out.append(END)
    return "\n".join(out)


def _section(text: str, card: str) -> tuple[int, int]:
    """Character span of the card's ``### CARD`` section."""
    m = re.search(rf"^### {card}\b.*$", text, re.M)
    assert m, f"no '### {card}' section in the card reference"
    nxt = re.search(r"^#{2,3} ", text[m.end():], re.M)
    return m.start(), m.end() + (nxt.start() if nxt else len(text) - m.end())


@pytest.mark.parametrize("card", sorted(CARDS))
def test_card_reference_prints_the_table(card):
    text = CARD_REFERENCE.read_text(encoding="utf-8")
    a, b = _section(text, card)
    assert render(card) in text[a:b], (
        f"the Vendor fields table of {card} in 02_card_reference.md is not the one CARDS "
        "gives; run `python tests/docs/test_field_dispositions.py --write`")


def test_every_vendor_card_at_a_glance_has_a_table():
    """Each bulk card in "Supported cards at a glance" is accounted for."""
    text = CARD_REFERENCE.read_text(encoding="utf-8")
    glance = text[text.index("## Supported cards at a glance"):text.index("## File Structure")]
    listed: set[str] = set()
    for item in re.findall(r"^- \*\*(.+?):\*\*(.*?)(?=^- \*\*|\Z)", glance, re.M | re.S):
        if item[0].startswith("Case control"):
            continue
        listed |= set(re.findall(r"\b[A-Z][A-Z0-9]+\b", re.sub(r"\(.*?\)", "", item[1])))
    known = set(CARDS) | OWN_TABLE | REFUSED_WHOLE | SBEAM_ONLY
    assert listed - known == set(), f"cards with no Vendor fields table: {listed - known}"
    assert (set(CARDS) | OWN_TABLE) - listed <= {"MASSSET"}, "table for a card not listed"


def _write() -> None:
    text = CARD_REFERENCE.read_text(encoding="utf-8")
    for card in CARDS:
        a, b = _section(text, card)
        section = text[a:b]
        block = render(card)
        old = re.search(re.escape(BEGIN.format(card=card)) + r".*?" + re.escape(END),
                        section, re.S)
        if old:
            section = section[:old.start()] + block + section[old.end():]
        else:
            body = section.rstrip()
            rule = body.endswith("\n---")
            if rule:
                body = body[:-3].rstrip()
            section = body + "\n\n" + block + ("\n\n---" if rule else "") + "\n\n"
        text = text[:a] + section + text[b:]
    CARD_REFERENCE.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if "--write" in sys.argv:
        _write()
    else:                                   # print what each probe does
        import tempfile
        for name, spec in CARDS.items():
            for row_, _text, probes_ in spec[4]:
                for p in probes_:
                    got = outcome(name, p, Path(tempfile.mkdtemp()))
                    flag = "" if got == OUTCOME[row_] else "   <-- expected " + OUTCOME[row_]
                    print(f"{name:8s} {row_:12s} {str(p)[:60]:60s} {got}{flag}")
