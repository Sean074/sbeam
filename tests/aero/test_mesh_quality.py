"""A7/A8 — pre-solve VLM mesh-quality warnings in build_aero_model.

A7: warn when a VLM CAERO1 has fewer than 4 chordwise boxes (NASA SP-405
    steady-VLM guidance; lift converges at NCHORD=1, chordwise loading and
    moment do not).
A8: warn when any box aspect ratio (spanwise/streamwise edge) falls outside
    [0.5, 2.0] — high-AR boxes degrade the VLM induced-downwash kernel.

Decoupled strip body panels (PID → PSTRIP) carry no horseshoe vortex, so
neither warning applies to them.
"""

import warnings

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.aero.aero_model import build_aero_model


def _bulk(caero_lines: str, prop: str = "PAERO1, 10\n"):
    text = (
        "AEROS, 0, 0, 1.0, 8.0, 8.0, 0, 0, 0.0\n"
        + prop
        + caero_lines
    )
    return parse_bulk_data(text.splitlines())


def _square_wing(nspan: int, nchord: int, pid: int = 10) -> str:
    """Full-span 8×1 rectangular CAERO1 (span 8, chord 1) in the XY plane."""
    return (
        f"CAERO1, 100, {pid}, 0, {nspan}, {nchord}, 0, 0, 1\n"
        "+, 0.0, -4.0, 0.0, 1.0, 0.0, 4.0, 0.0, 1.0\n"
    )


class TestLowNchordWarning:
    def test_nchord_below_4_warns(self):
        bulk = _bulk(_square_wing(nspan=16, nchord=2))
        with pytest.warns(UserWarning, match=r"CAERO1 100: only 2 chordwise"):
            build_aero_model(bulk)

    def test_nchord_4_is_silent(self):
        bulk = _bulk(_square_wing(nspan=32, nchord=4))
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            build_aero_model(bulk)
        assert [w for w in rec if "chordwise boxes" in str(w.message)] == []

    def test_strip_panel_is_exempt(self):
        """PSTRIP body strips have no VLM kernel — NCHORD=1 must not warn."""
        bulk = _bulk(_square_wing(nspan=8, nchord=1, pid=20), prop="PSTRIP, 20\n")
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            build_aero_model(bulk)
        assert [w for w in rec if "chordwise boxes" in str(w.message)] == []


class TestBoxAspectRatioWarning:
    def test_sliver_boxes_warn(self):
        # span 8 / 1 spanwise box = 8; chord 1 / 4 chordwise boxes = 0.25 → AR 32
        bulk = _bulk(_square_wing(nspan=1, nchord=4))
        with pytest.warns(UserWarning, match=r"CAERO1 100: 4 of 4 boxes.*aspect"):
            build_aero_model(bulk)

    def test_square_boxes_are_silent(self):
        # span 8 / 16 = 0.5; chord 1 / 4 = 0.25 → AR 2.0 (band edge, inclusive)
        bulk = _bulk(_square_wing(nspan=16, nchord=4))
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            build_aero_model(bulk)
        assert [w for w in rec if "aspect" in str(w.message)] == []

    def test_strip_panel_is_exempt(self):
        """PSTRIP slender body strips are exempt from the AR band."""
        bulk = _bulk(_square_wing(nspan=1, nchord=1, pid=20), prop="PSTRIP, 20\n")
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            build_aero_model(bulk)
        assert [w for w in rec if "aspect" in str(w.message)] == []
