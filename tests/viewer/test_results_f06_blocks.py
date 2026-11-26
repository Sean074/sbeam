"""The results page shows the f06 blocks that change how its numbers are read (#118).

Each test runs a sample deck in the viewer and compares what the page shows with the
line the f06 prints for the same result, read out of the f06 text.  The viewer computes
none of these numbers: it shows result fields and the solver package's functions.
"""
from __future__ import annotations

import re
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from sbeam.results.f06_writer import build_f06_sol144_text, coefficient_frame
from tests.viewer.journey_helpers import _assert_clean, _open

_NUM = r"[-+]?\d\.\d+E[-+]\d+"


def _run(name: str) -> AppTest:
    at = _open(name)
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run()
    _assert_clean(at, "run")
    return at


def _f06(at: AppTest, subcase: int) -> str:
    return build_f06_sol144_text(
        at.session_state["case_control"], at.session_state["bulk_data"],
        at.session_state["sol144_result"][subcase], subcase)


def _table(at: AppTest, *columns: str) -> pd.DataFrame:
    """The one table on the page that has all of ``columns``."""
    found = [d.value for d in at.dataframe if set(columns) <= set(map(str, d.value.columns))]
    assert len(found) == 1, (columns, len(found))
    return found[0]


def _no_table(at: AppTest, *columns: str) -> bool:
    return not any(set(columns) <= set(map(str, d.value.columns)) for d in at.dataframe)


def _f06_numbers(text: str, after: str, skip_lines: int) -> list[float]:
    lines = text.splitlines()
    i = next(k for k, line in enumerate(lines) if after in line)
    return [float(v) for v in re.findall(_NUM, lines[i + skip_lines])]


# --- coefficient frame ---------------------------------------------------------------

def test_the_frame_of_the_coefficients_is_stated_with_mscs_transformation():
    """HA144A's reference frame has z down, so MSC's CZ and sbeam's have opposite signs."""
    at = _run("ha144a/ha144a_fullspan_sbeam.bdf")
    bulk = at.session_state["bulk_data"]
    rcsid, t_mat, offset = coefficient_frame(bulk)
    assert rcsid != 0 and t_mat[2, 2] == pytest.approx(-1.0)

    shown = _table(at, "X bas", "Y bas", "Z bas", "offset")
    assert np.allclose(shown[["X bas", "Y bas", "Z bas"]].to_numpy(float), t_mat)
    assert np.allclose(shown["offset"].to_numpy(float), offset)
    assert any("basic axes" in c.value and f"RCSID = {rcsid}" in c.value for c in at.caption)

    # the f06 prints the same matrix, to four decimals
    text = _f06(at, 1)
    rows = [line for line in text.splitlines() if re.search(r"\{ [XYZ] \}", line)][:3]
    printed = np.array([[float(v) for v in re.findall(r"-?\d+\.\d{4}", row)[:3]] for row in rows])
    assert np.allclose(printed, t_mat, atol=5e-5)


def test_the_frame_is_the_identity_without_a_reference_frame():
    at = _run("validation/val_dihedral_trim.bdf")
    shown = _table(at, "X bas", "Y bas", "Z bas", "offset")
    assert np.allclose(shown[["X bas", "Y bas", "Z bas"]].to_numpy(float), np.eye(3))
    assert any("RCSID = 0" in c.value for c in at.caption)


# --- injected aero loads (LOADINJ) -----------------------------------------------------

def test_injected_aero_loads_match_the_f06():
    at = _run("ha144a/ha144a_body_trim.bdf")
    result = at.session_state["sol144_result"][1]
    assert result.load_injection_echo
    shown = _table(at, "Source", "Master grid", "Boxes", "FZ", "MY")
    assert len(shown) == len(result.load_injection_echo)

    text = _f06(at, 1)
    lines = text.splitlines()
    start = next(k for k, line in enumerate(lines) if "I N J E C T E D   A E R O   L O A D S" in line)
    printed = [[float(v) for v in re.findall(_NUM, line)] for line in lines[start + 3:start + 3 + len(shown)]]
    six = shown[["FX", "FY", "FZ", "MX", "MY", "MZ"]].to_numpy(float)
    assert np.allclose(six, np.array(printed), rtol=1e-6, atol=1e-9)
    assert list(shown["Master grid"]) == [inj["master_grid"] for inj in result.load_injection_echo]
    # invariant: a symmetric airplane at zero sideslip puts no net side force on the body
    assert abs(six[:, 1].sum()) < 1e-6 * np.abs(six[:, 2]).max()


def test_a_deck_without_injection_shows_no_injection_block():
    at = _run("validation/val_dihedral_trim.bdf")
    assert _no_table(at, "Source", "Master grid")
    assert not any("Injected" in m.value for m in at.markdown)
    assert not any("Applied structural load" in m.value for m in at.markdown)


# --- applied structural load (#6) ------------------------------------------------------

def test_applied_load_resultant_matches_the_f06():
    at = _run("validation/val_thrust_trim.bdf")
    sel = at.selectbox(key="sol144_sc_sel")
    sel.set_value(2)
    at.run()
    result = at.session_state["sol144_result"][2]
    assert result.applied_loads is not None and result.load_sid == 710
    assert any("Applied structural load" in m.value and "LOAD = 710" in m.value
               for m in at.markdown)
    shown = _table(at, "FX", "FY", "FZ", "MX", "MY", "MZ").iloc[0].to_numpy(float)
    printed = _f06_numbers(_f06(at, 2), "A P P L I E D   S T R U C T U R A L   L O A D", 4)
    assert np.allclose(shown, printed, rtol=1e-6, atol=1e-9)
    # invariant: thrust is along the body axis, so it has no side or vertical component
    assert shown[0] != 0.0 and shown[1] == 0.0 and shown[2] == 0.0


def test_a_subcase_without_a_load_shows_no_applied_block():
    at = _run("validation/val_thrust_trim.bdf")
    assert at.session_state["sol144_result"][1].applied_loads is None
    assert at.selectbox(key="sol144_sc_sel").value == 1
    assert not any("Applied structural load" in m.value for m in at.markdown)


# --- injected operating point (CPINJ) --------------------------------------------------

def _cpinj_block():
    """No sample deck uses CPINJ (#119), so the block is drawn from an echo by hand."""
    from types import SimpleNamespace        # the app function runs as its own script

    from sbeam_tools.viewer.results_view import _render_injected_operating_point
    echo = {"alpha_ref": 0.05, "data_machs": [0.3],
            "surfaces": {100: {"FZ_Q": 2.0, "MY_Q": -0.5, "FZ_Q_VLM": 1.9},
                         200: {"FZ_Q": 0.4, "MY_Q": -0.3, "FZ_Q_VLM": 0.5}}}
    _render_injected_operating_point(SimpleNamespace(chordcp_echo=echo))  # type: ignore[arg-type]


def test_injected_operating_point_block():
    at = AppTest.from_function(_cpinj_block)
    at.run()
    assert not at.exception
    shown = _table(at, "CAERO1", "FZ/q injected", "MY/q injected", "FZ/q VLM flat-plate")
    assert list(shown["CAERO1"]) == ["100", "200", "TOTAL"]
    assert shown["FZ/q injected"].tolist() == pytest.approx([2.0, 0.4, 2.4])
    assert shown["MY/q injected"].tolist() == pytest.approx([-0.5, -0.3, -0.8])
    assert shown["FZ/q VLM flat-plate"].tolist() == pytest.approx([1.9, 0.5, 2.4])
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Data Mach"] == "0.3000"
    assert float(metrics["ALPHREF (deg)"]) == pytest.approx(np.degrees(0.05), rel=1e-4)
