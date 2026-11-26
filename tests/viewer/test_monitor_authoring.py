"""Monitors authored and drawn in the viewer: AECOMP, MONPNT1, MONSECT (#116)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
import pytest
from streamlit.testing.v1 import AppTest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Monpnt3, Monsect
from sbeam.model.card_writers import write_monpnt1, write_monsect
from sbeam.parser.bdf_reader import parse_bdf
from sbeam_tools.viewer.monitor_view import add_monitor_traces, cut_line, monitor_geometry
from tests.samples import sample_path
from tests.viewer.journey_helpers import _open, _submit, differences

HA144A = sample_path("ha144a_fullspan_sbeam.bdf")
MONITOR_CARDS = ("AECOMP", "MONPNT1", "MONSECT")


def _sbeam_app():
    from sbeam_tools.viewer.app import main
    main()


def _without_monitors(path: Path) -> str:
    """The deck with every AECOMP, MONPNT1 and MONSECT card (and its continuations) removed."""
    out: list[str] = []
    dropping = False
    for line in path.read_text().splitlines():
        if line.startswith("$"):
            out.append(line)
            continue
        continuation = line.startswith(("+", " ", "*")) or not line.strip()
        if not continuation:
            dropping = line.replace(",", " ").split()[0].upper() in MONITOR_CARDS
        if not dropping:
            out.append(line)
    return "\n".join(out) + "\n"


def _open_path(path: Path) -> AppTest:
    at = AppTest.from_function(_sbeam_app, default_timeout=300)
    at.run()
    at.text_input(key="deck_path_input").set_value(str(path))
    at.button(key="open_deck").click()
    at.run()
    assert at.session_state["_parse_error"] is None, at.session_state["_parse_error"]
    return at


def _apply(at: AppTest, family: str) -> None:
    _submit(at, f"auth_form_{family}")
    assert not at.exception and not at.error, (family, [e.value for e in at.error])


def _author_aecomp(at: AppTest, card: Any) -> None:
    at.text_input(key="auth_aecomp_name").set_value(card.name)
    at.selectbox(key="auth_aecomp_type").set_value(card.listtype)
    at.multiselect(key=f"auth_aecomp_{card.listtype.lower()}").set_value(list(card.list_ids))
    other = "set1" if card.listtype == "AELIST" else "aelist"
    at.multiselect(key=f"auth_aecomp_{other}").set_value([])
    _apply(at, "aecomp")


def _author_monpnt(at: AppTest, family: str, card: Any) -> None:
    at.text_input(key=f"auth_{family}_name").set_value(card.name)
    at.text_input(key=f"auth_{family}_label").set_value(card.label)
    at.text_input(key=f"auth_{family}_axes").set_value(str(card.axes))
    at.selectbox(key=f"auth_{family}_comp").set_value(card.comp)
    at.selectbox(key=f"auth_{family}_cp").set_value(card.cp)
    for axis in "xyz":
        at.number_input(key=f"auth_{family}_{axis}").set_value(getattr(card, axis))
    _apply(at, family)


def _author_monsect(at: AppTest, card: Monsect) -> None:
    at.text_input(key="auth_monsect_name").set_value(card.name)
    at.text_input(key="auth_monsect_label").set_value(card.label)
    at.selectbox(key="auth_monsect_comp").set_value(card.comp)
    at.selectbox(key="auth_monsect_cid").set_value(card.cid)
    at.selectbox(key="auth_monsect_axis").set_value(card.axis)
    at.selectbox(key="auth_monsect_side").set_value(card.side)
    at.text_input(key="auth_monsect_stations").set_value(
        ", ".join(repr(v) for v in card.stations))
    _apply(at, "monsect")


def _run(at: AppTest) -> dict:
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    return at.session_state["sol144_result"]


# --- authoring -------------------------------------------------------------------------

def test_monitors_authored_from_nothing_reproduce_the_deck(tmp_path):
    """Every monitor card of HA144A is removed and typed back through the forms.  The
    export has the deck's cards and the run has its monitor loads, which other gates
    hold to MSC's printed HA144A values."""
    deck = tmp_path / "ha144a_without_monitors.bdf"
    deck.write_text(_without_monitors(HA144A))
    cc_orig, orig = parse_bdf(HA144A)
    _, stripped = parse_bdf(deck)
    assert not (stripped.aecomps or stripped.monpnt1s or stripped.monpnt3s or stripped.monsects)
    assert len(orig.aecomps) == 5 and len(orig.monpnt1s) + len(orig.monpnt3s) == 4
    assert len(orig.monsects) == 1

    at = _open_path(deck)
    for card in orig.aecomps.values():
        _author_aecomp(at, card)
    for card in orig.monpnt1s.values():
        _author_monpnt(at, "monpnt1", card)
    for card in orig.monpnt3s.values():
        _author_monpnt(at, "monpnt3", card)
    for card in orig.monsects.values():
        _author_monsect(at, card)

    bulk = at.session_state["bulk_data"]
    for store in ("aecomps", "monpnt1s", "monpnt3s", "monsects"):
        assert differences(getattr(orig, store), getattr(bulk, store), store) == []
    assert at.session_state["authored_cards"] == {
        "aecomp": set(orig.aecomps), "monpnt1": set(orig.monpnt1s),
        "monpnt3": set(orig.monpnt3s), "monsect": set(orig.monsects)}

    # the export parses to the same cards
    at.checkbox(key="cc_show_editor").check()
    at.run()
    text = [c.value for c in at.code if "BEGIN BULK" in c.value][-1]
    _, exported = parse_bdf(deck.with_name("exported.bdf"), text=text)
    for store in ("aecomps", "monpnt1s", "monpnt3s", "monsects"):
        assert differences(getattr(orig, store), getattr(exported, store), store) == []

    # and the run gives the original deck's monitor and section loads
    authored = _run(at)
    original = _run(_open("ha144a/ha144a_fullspan_sbeam.bdf"))
    for sc_id, result in original.items():
        assert sorted(authored[sc_id].monitor_loads) == sorted(result.monitor_loads)
        for name, load in result.monitor_loads.items():
            np.testing.assert_allclose(authored[sc_id].monitor_loads[name].totals,
                                       load.totals, rtol=1e-12, atol=1e-9)
        assert differences(result.section_loads, authored[sc_id].section_loads, "cuts") == []
        assert result.section_loads, "the deck has a MONSECT, so there are section loads"
    wing = original[1].monitor_loads["MWINGEA"].totals
    assert abs(wing[2]) > 1.0, "the comparison is of loads, not of zeros"


def test_a_structural_and_an_aerodynamic_monitor_go_to_their_own_stores():
    """One card, two kinds: the SET1 form's card is a structural monitor (``monpnt3s``)."""
    at = _open("ha144a/ha144a_fullspan_sbeam.bdf")
    at.text_input(key="auth_monpnt3_name").set_value("NEWSTR")
    _apply(at, "monpnt3")
    at.text_input(key="auth_monpnt1_name").set_value("NEWAER")
    _apply(at, "monpnt1")
    bulk = at.session_state["bulk_data"]
    assert "NEWSTR" in bulk.monpnt3s and "NEWSTR" not in bulk.monpnt1s
    assert "NEWAER" in bulk.monpnt1s and "NEWAER" not in bulk.monpnt3s
    assert bulk.aecomps[bulk.monpnt3s["NEWSTR"].comp].listtype == "SET1"
    assert bulk.aecomps[bulk.monpnt1s["NEWAER"].comp].listtype == "AELIST"
    # both are written as MONPNT1, in MSC's two-line layout
    for card in (bulk.monpnt3s["NEWSTR"], bulk.monpnt1s["NEWAER"]):
        first, second = write_monpnt1(card)
        assert first.startswith("MONPNT1 ") and second.startswith("+, 123456, ")


def test_the_parsers_monitor_rules_reach_the_forms():
    at = _open("ha144a/ha144a_fullspan_sbeam.bdf")
    before = at.session_state["bulk_data"]
    # a monitor name is unique across MONPNT1 and MONSECT
    at.text_input(key="auth_monsect_name").set_value("MWINGEA")
    at.text_input(key="auth_monsect_stations").set_value("1.0 2.0")
    _submit(at, "auth_form_monsect")
    assert any("would not parse" in e.value and "MWINGEA" in e.value for e in at.error)
    # stations must increase
    at.text_input(key="auth_monsect_name").set_value("SECNEW")
    at.text_input(key="auth_monsect_stations").set_value("2.0 1.0")
    _submit(at, "auth_form_monsect")
    assert any("increasing" in e.value for e in at.error)
    assert at.session_state["bulk_data"] is before


def test_save_as_new_gives_a_monitor_a_free_name():
    at = _open("ha144a/ha144a_fullspan_sbeam.bdf")
    at.selectbox(key="auth_sel_monsect").set_value("SECRW")
    at.run()
    next(b for b in at.button if b.label == "Save as new SID"
         and b.form_id == "auth_form_monsect").click()
    at.run()
    assert not at.error, [e.value for e in at.error]
    bulk = at.session_state["bulk_data"]
    assert sorted(bulk.monsects) == ["SEC1", "SECRW"]
    assert bulk.monsects["SEC1"].stations == bulk.monsects["SECRW"].stations


def test_writers_layout():
    cut = Monsect(name="S1", label="RIGHT WING", comp="RW", cid=7, axis=2, side="NEG",
                  tol=None, stations=[float(i) for i in range(10)], normal=(0.2, 1.0, 0.0))
    assert write_monsect(cut) == [
        "MONSECT, S1, RIGHT WING, RW, 7, 2, NEG, ",
        "+, 0.0, 1.000000, 2.000000, 3.000000, 4.000000, 5.000000, 6.000000, 7.000000",
        "+, 8.000000, 9.000000",
        "+, NORMAL, 0.200000, 1.000000, 0.0",
    ]
    long_label = "Wing Integrated Load to Butline 155"
    mon = Monpnt3(name="WING155", label=long_label, axes=34, comp="WING", cp=0,
                  x=0.0, y=155.0, z=15.0)
    first, second = write_monpnt1(mon)
    assert first == f"MONPNT1 WING155 {long_label}" and first[16:] == long_label
    assert second == "+, 34, WING, 0, 0.0, 155.0000, 15.00000"
    with pytest.raises(ValueError, match="8 characters"):
        write_monpnt1(Monpnt3(name="TOOLONGNAME", label="", axes=3, comp="W", cp=0,
                              x=0.0, y=0.0, z=0.0))


# --- drawing ---------------------------------------------------------------------------

def _hand_frame(card: Any) -> tuple[np.ndarray, np.ndarray]:
    """A CORD2R's origin and axes from its three points, by the card's definition:
    A is the origin, B is on the z-axis, C is in the x-z plane."""
    assert card.rid == 0
    a, b, c = (np.array(p, dtype=float) for p in (card.a, card.b, card.c))
    z = (b - a) / np.linalg.norm(b - a)
    y = np.cross(z, c - a)
    y /= np.linalg.norm(y)
    return a, np.column_stack([np.cross(y, z), y, z])


@pytest.fixture(scope="module")
def flagship():
    _, bulk = parse_bdf(sample_path("cessna210_flagship_trim.bdf"))
    return bulk, build_aero_model(bulk, grid_index=build_grid_index(bulk))


def test_cut_reference_points_are_on_the_cards_axis(flagship):
    """SECRW's stations run along axis 2 of CORD2R 991, the swept wing frame: each
    reference point is the origin plus the station along that axis, in basic axes."""
    bulk, aero = flagship
    cut = bulk.monsects["SECRW"]
    origin, axes = _hand_frame(bulk.cord2rs[cut.cid])
    assert abs(axes[0, 1]) > 1e-3, "the frame is swept, so the test is not of an identity"
    geometry = monitor_geometry(bulk, aero)["SECRW"]
    expected = np.array([origin + s * axes[:, cut.axis - 1] for s in cut.stations])
    np.testing.assert_allclose(geometry.refs, expected, atol=1e-12)
    np.testing.assert_allclose(geometry.normal, axes[:, cut.axis - 1], atol=1e-12)
    # members beyond each cut can only fall as the cut moves outboard, and end at none
    assert geometry.on_side == sorted(geometry.on_side, reverse=True)
    assert geometry.on_side[-1] == 0


def test_a_monitor_reference_point_in_a_local_frame_is_drawn_in_basic(flagship):
    bulk, aero = flagship
    origin, axes = _hand_frame(bulk.cord2rs[991])
    comp = next(n for n, c in bulk.aecomps.items() if c.listtype == "SET1")
    bulk.monpnt3s["LOCAL"] = Monpnt3(name="LOCAL", label="", axes=123456, comp=comp,
                                     cp=991, x=0.25, y=1.5, z=-0.1)
    try:
        geometry = monitor_geometry(bulk, aero)["LOCAL"]
    finally:
        del bulk.monpnt3s["LOCAL"]
    np.testing.assert_allclose(geometry.refs[0], origin + axes @ [0.25, 1.5, -0.1], atol=1e-12)
    assert not np.allclose(geometry.refs[0], [0.25, 1.5, -0.1])


def test_cut_line_lies_in_the_cut_plane():
    ref, normal = np.array([1.0, 2.0, 3.0]), np.array([0.3, 1.0, 0.1])
    a, b = cut_line(ref, normal, 0.5)
    assert (a - ref) @ normal == pytest.approx(0.0, abs=1e-12)
    assert (b - ref) @ normal == pytest.approx(0.0, abs=1e-12)
    assert np.linalg.norm(b - a) == pytest.approx(1.0)
    np.testing.assert_allclose((a + b) / 2, ref)
    vertical = cut_line(ref, np.array([0.0, 0.0, 1.0]), 0.5)       # a horizontal plane
    assert vertical[0][2] == vertical[1][2] == 3.0


def test_traces_carry_the_geometry(flagship):
    bulk, aero = flagship
    geometry = monitor_geometry(bulk, aero)
    fig = go.Figure()
    add_monitor_traces(fig, geometry, "SECRW", model_span=10.0)
    refs, members, cuts = fig.data
    all_refs = np.vstack([g.refs for g in geometry.values()])
    np.testing.assert_allclose(np.column_stack([refs.x, refs.y, refs.z]), all_refs)
    assert "SECRW @ 0.3" in refs.text and "MWROOT" in refs.text
    np.testing.assert_allclose(np.column_stack([members.x, members.y, members.z]),
                               geometry["SECRW"].members)
    assert len(cuts.x) == 3 * len(geometry["SECRW"].stations)      # two ends and a gap each
    # without a highlight only the reference points are drawn
    plain = go.Figure()
    add_monitor_traces(plain, geometry, None, model_span=10.0)
    assert len(plain.data) == 1


def test_the_monitors_tab_draws_them():
    at = _open("cessna210_flagship/cessna210_flagship_trim.bdf")
    at.checkbox(key="auth_mon_draw").check()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    at.selectbox(key="auth_mon_highlight").set_value("SECRWA")
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    table = next(d.value for d in at.dataframe if "Ref X" in map(str, d.value.columns))
    cut = at.session_state["bulk_data"].monsects["SECRWA"]
    assert list(table["Station"]) == cut.stations
    assert "Boxes summed" in table.columns and table["Boxes summed"].iloc[-1] == 0
    assert any("MONPNT3" in c.value and "#86" in c.value for c in at.caption)
