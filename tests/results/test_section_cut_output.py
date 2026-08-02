"""MONSECT outputs — f06 SECTION CUT RUNNING LOADS block + section_loads CSV."""
import csv
import types

import numpy as np

from sbeam.results.f06_writer import _section_cut_block
from sbeam.results.load_export import write_section_loads_csv
from sbeam.results.results import SectionCutResult, SectionCutStation
from sbeam.results.section_cuts import component_map


def _sample_cut(half_model=False):
    cmap = component_map(2)
    # Raw cid-frame [Fx, Fy, Fz, Mx, My, Mz] per station.
    raw = [
        np.array([0.0, 0.0, 8000.0, 60000.0, -1200.0, 0.0]),
        np.array([0.0, 0.0, 5000.0, 30000.0, -600.0, 0.0]),
    ]
    stations = []
    prev = None
    for s, v in zip((1.0, 3.0), raw):
        d = None if prev is None else (np.array([v[i] for i in cmap])
                                       - np.array([prev[i] for i in cmap])) / 2.0
        stations.append(SectionCutStation(
            station=s, ref=np.array([2.0, s, 0.5]), totals=v, aero=v,
            inertia=np.zeros(6), reaction=np.zeros(6), n_members=4, d_ds=d,
        ))
        prev = v
    return {"SECRW": SectionCutResult(
        name="SECRW", label="RIGHT WING", comp="RWING", listtype="SET1",
        cid=7, axis=2, side="POS", stations=stations, comp_map=cmap,
        half_model=half_model,
    )}


def test_f06_block_renders_with_explicit_component_legend():
    lines = []
    _section_cut_block(lines, _sample_cut())
    text = "\n".join(lines)
    assert "S E C T I O N   C U T   R U N N I N G   L O A D S" in text
    assert "MONSECT SECRW" in text
    assert "COMP RWING (SET1)" in text
    assert "AERO + INERTIA + REACTION" in text
    # The legend must be printed, not assumed: only N and Mt are role names.
    assert "N=Fy" in text and "Mt=My" in text and "Vz=Fz" in text and "Mx=Mx" in text
    # Station rows carry the labelled values.
    assert "8.000000E+03" in text and "6.000000E+04" in text


def test_f06_block_flags_half_model_but_never_whole_airplane():
    """A section cut is never parity-scaled, so it must not borrow MON4's tag."""
    lines = []
    _section_cut_block(lines, _sample_cut(half_model=True))
    text = "\n".join(lines)
    assert "HALF-MODEL (LOADS PER SIDE)" in text
    assert "WHOLE-AIRPLANE" not in text


def test_f06_block_marks_an_aero_only_cut():
    cuts = _sample_cut()
    cuts["SECRW"].listtype = "AELIST"
    lines = []
    _section_cut_block(lines, cuts)
    assert "AERO ONLY" in "\n".join(lines)


def test_csv_carries_labelled_and_raw_components(tmp_path):
    results = {7: types.SimpleNamespace(
        section_loads=_sample_cut(), massset_sid=20, massset_label="CRUISE")}
    path = tmp_path / "out.section_loads.csv"
    write_section_loads_csv(str(path), results)

    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    r0, r1 = rows

    assert r0["case"] == "7" and r0["massset"] == "20" and r0["mass_case"] == "CRUISE"
    assert r0["name"] == "SECRW" and r0["listtype"] == "SET1" and r0["axis"] == "2"
    assert float(r0["station"]) == 1.0
    # The mapping is named in the row itself, so no consumer has to infer it.
    assert (r0["comp_1"], r0["comp_4"], r0["comp_3"]) == ("N", "Mt", "Vz")
    assert float(r0["c3"]) == 8000.0            # Vz = Fz
    assert float(r0["c5"]) == 60000.0           # Mx = Mx (bending)
    assert float(r0["c4"]) == -1200.0           # Mt = My (torque)
    # Raw cid components are written alongside.
    assert float(r0["Fz"]) == 8000.0 and float(r0["Mx"]) == 60000.0
    # Contribution split.
    assert float(r0["c3_aero"]) == 8000.0
    assert float(r0["c3_inertia"]) == 0.0

    # Running-load derivative: blank at the first station, filled after.
    assert r0["dc3_ds"] == ""
    assert float(r1["dc3_ds"]) == (5000.0 - 8000.0) / 2.0


def test_csv_skips_subcases_without_section_cuts(tmp_path):
    results = {
        1: types.SimpleNamespace(section_loads=None),
        2: types.SimpleNamespace(section_loads=_sample_cut()),
    }
    path = tmp_path / "out.csv"
    write_section_loads_csv(str(path), results)
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    assert {r["case"] for r in rows} == {"2"}
