"""V-TSEC6 — section-cut envelope over a transient maneuver (Step 68).

The envelope is checked against a brute-force reduction over the same per-sample
tables, so a failure is the reduction itself and nothing upstream.  The property
that carries the most weight is that the **driving sample is per station and
component** — if the envelope silently reported the run's critical sample
everywhere it would look plausible and be wrong exactly where it matters.
"""
import csv
import types

import numpy as np
import pytest

from sbeam.results.f06_writer import _section_envelope_block
from sbeam.results.load_export import (
    build_maneuver_section_envelope_csv_text,
    write_maneuver_section_envelope_csv,
)
from sbeam.results.results import SectionCutResult, SectionCutStation
from sbeam.results.section_cuts import component_map, labelled
from sbeam.results.section_envelope import build_section_envelope

CMAP = component_map(2)


def _cut(values):
    """One cut whose stations carry the given raw cid-frame 6-vectors."""
    stations = [
        SectionCutStation(
            station=float(j), ref=np.array([0.0, float(j), 0.0]),
            totals=np.asarray(v, dtype=float), aero=np.asarray(v, dtype=float),
            inertia=np.zeros(6), reaction=np.zeros(6), n_members=2,
            elastic_inertia=np.zeros(6), damping=np.zeros(6),
        )
        for j, v in enumerate(values)
    ]
    return {"SECRW": SectionCutResult(
        name="SECRW", label="RIGHT WING", comp="RWING", listtype="SET1",
        cid=7, axis=2, side="POS", stations=stations, comp_map=CMAP,
    )}


def _result(per_sample_values, crit_index=0):
    """A ManeuverResult stand-in: per_sample_values[i][j] = station j at sample i."""
    steps = [types.SimpleNamespace(t=0.1 * i, section_loads=_cut(v))
             for i, v in enumerate(per_sample_values)]
    r = types.SimpleNamespace(
        subcase_id=3, mloads_sid=9, massset_sid=None,
        crit_index=crit_index, steps=steps, section_envelope=None,
        times=np.array([s.t for s in steps]))
    r.section_envelope = build_section_envelope(r)
    return r


# Station 0 peaks at sample 2; station 1 peaks at sample 0 — deliberately
# different, so a per-station driving sample is distinguishable from a global one.
_VALUES = [
    [[0, 0, 100.0, 0, 900.0, 0], [0, 0, 80.0, 0, 400.0, 0]],
    [[0, 0, 150.0, 0, 500.0, 0], [0, 0, 20.0, 0, 100.0, 0]],
    [[0, 0, 300.0, 0, 200.0, 0], [0, 0, -50.0, 0, 50.0, 0]],
]


def test_envelope_matches_a_brute_force_reduction():
    r = _result(_VALUES)
    env = r.section_envelope["SECRW"]

    # Brute force: stack the labelled tables and reduce with numpy directly.
    stacked = np.array([
        [labelled(st.totals, CMAP) for st in s.section_loads["SECRW"].stations]
        for s in r.steps
    ])
    for e in env.entries:
        j = int(e.station)
        assert e.max_value == pytest.approx(stacked[:, j, e.comp].max())
        assert e.min_value == pytest.approx(stacked[:, j, e.comp].min())
        assert e.max_sample == int(stacked[:, j, e.comp].argmax()) + 1
        assert e.min_sample == int(stacked[:, j, e.comp].argmin()) + 1
        assert e.absmax == pytest.approx(
            max(abs(e.max_value), abs(e.min_value)))


def test_driving_sample_is_per_station_and_not_the_critical_sample():
    """The whole reason the envelope exists rather than the critical sample."""
    r = _result(_VALUES, crit_index=0)
    env = r.section_envelope["SECRW"]
    vz = 2                                    # labelled index of Vz

    s0 = next(e for e in env.entries if e.station == 0.0 and e.comp == vz)
    s1 = next(e for e in env.entries if e.station == 1.0 and e.comp == vz)
    assert s0.max_sample == 3                 # station 0 peaks at the last sample
    assert s1.max_sample == 1                 # station 1 peaks at the first
    assert s0.max_sample != s1.max_sample
    # And neither is forced to agree with the run's critical sample.
    assert s0.max_sample != r.crit_index + 1


def test_envelope_times_track_the_driving_samples():
    r = _result(_VALUES)
    env = r.section_envelope["SECRW"]
    for e in env.entries:
        assert e.max_time == pytest.approx(r.steps[e.max_sample - 1].t)
        assert e.min_time == pytest.approx(r.steps[e.min_sample - 1].t)


def test_ties_resolve_to_the_earliest_sample():
    """Documented tie-break: reproducible run to run."""
    flat = [[[0, 0, 42.0, 0, 0, 0]]] * 4
    env = _result(flat).section_envelope["SECRW"]
    e = next(x for x in env.entries if x.comp == 2)
    assert e.max_sample == 1 and e.min_sample == 1


def test_no_cuts_gives_no_envelope():
    steps = [types.SimpleNamespace(t=0.0, section_loads=None)]
    r = types.SimpleNamespace(steps=steps, crit_index=0)
    assert build_section_envelope(r) is None


def test_n_samples_is_recorded():
    r = _result(_VALUES)
    assert r.section_envelope["SECRW"].n_samples == 3


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #

def test_f06_envelope_block_names_the_critical_sample_distinctly():
    """The block must say the driving sample need not be the critical one."""
    r = _result(_VALUES, crit_index=1)
    lines = []
    _section_envelope_block(lines, r.section_envelope, r.crit_index + 1)
    text = "\n".join(lines)
    assert "S E C T I O N   C U T   E N V E L O P E" in text
    assert "NEED NOT BE THE" in text
    assert "CRITICAL SAMPLE (2)" in text
    assert "SAMPLES = 3" in text
    # Legend printed, as in the running-loads block.
    assert "N=Fy" in text and "Vz=Fz" in text


def test_envelope_csv_rows(tmp_path):
    r = _result(_VALUES, crit_index=1)
    path = tmp_path / "out.maneuver_section_envelope.csv"
    write_maneuver_section_envelope_csv(str(path), {3: r})
    with open(path) as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 2 * 6                 # 2 stations x 6 components
    r0 = rows[0]
    assert r0["case"] == "3" and r0["mloads"] == "9"
    assert r0["critical_sample"] == "2" and r0["n_samples"] == "3"
    # comp_index is 1-based and comp_name is the labelled name.
    assert r0["comp_index"] == "1" and r0["comp_name"] == "N"

    vz = next(x for x in rows
              if float(x["station"]) == 0.0 and x["comp_name"] == "Vz")
    assert float(vz["max"]) == 300.0 and vz["max_sample"] == "3"
    assert float(vz["absmax"]) == 300.0


def test_envelope_csv_text_matches_the_file(tmp_path):
    r = _result(_VALUES)
    path = tmp_path / "out.csv"
    write_maneuver_section_envelope_csv(str(path), {3: r})
    with open(path, newline="") as fh:
        assert fh.read() == build_maneuver_section_envelope_csv_text({3: r})
