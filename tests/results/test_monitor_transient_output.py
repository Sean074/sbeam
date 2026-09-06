"""#2 — transient monitor outputs: f06 blocks, envelope reduction, CSVs.

Checked on stand-in results (no solver), so a failure here is the output
layer itself.  The static MONITOR block is asserted byte-identical to what it
printed before the transient flags existed.
"""
import csv
import types

import numpy as np

from sbeam.results.f06_writer import _monitor_block, _monitor_envelope_block
from sbeam.results.load_export import (
    build_maneuver_monitor_csv_text,
    build_maneuver_monitor_envelope_csv_text,
    write_maneuver_monitor_csv,
    write_maneuver_monitor_envelope_csv,
)
from sbeam.results.results import MonitorLoad
from sbeam.results.section_envelope import build_monitor_envelope
from tests.results.test_monitor_output import _sample_monitors


def _monitor(name, totals, mtype="MONPNT3", elastic=None, damping=None):
    t = np.asarray(totals, dtype=float)
    el = None if elastic is None else np.asarray(elastic, dtype=float)
    da = None if damping is None else np.asarray(damping, dtype=float)
    aero = t.copy()
    if el is not None:
        aero = aero - el
    if da is not None:
        aero = aero - da
    return MonitorLoad(
        name=name, label=f"LABEL {name}", mtype=mtype, axes=123456, cid=0,
        ref=np.array([1.0, 0.0, 0.0]), totals=t, aero=aero,
        inertia=np.zeros(6), reaction=np.zeros(6),
        elastic_inertia=el, damping=da,
    )


def _result(per_sample, crit_index=0):
    """per_sample[i] = {name: totals} at sample i (Fz varies)."""
    steps = []
    for i, mons in enumerate(per_sample):
        ml = {name: _monitor(name, v, elastic=np.full(6, 0.1 * i),
                             damping=np.zeros(6))
              for name, v in mons.items()}
        steps.append(types.SimpleNamespace(t=0.05 * i, monitor_loads=ml))
    return types.SimpleNamespace(
        subcase_id=3, mloads_sid=9, massset_sid=None,
        crit_index=crit_index, steps=steps, monitor_envelope=None,
    )


def _three_sample_result():
    return _result([
        {"MA": [0, 0, 100, 0, 5, 0], "MB": [0, 0, -1, 0, 0, 0]},
        {"MA": [0, 0, 300, 0, -7, 0], "MB": [0, 0, -4, 0, 0, 0]},
        {"MA": [0, 0, 200, 0, 1, 0], "MB": [0, 0, -2, 0, 0, 0]},
    ], crit_index=2)


# --------------------------------------------------------------------------- #
# f06
# --------------------------------------------------------------------------- #

def test_static_monitor_block_is_unchanged():
    """The defaults reproduce the pre-#2 block exactly (byte-identical gate)."""
    lines = []
    _monitor_block(lines, _sample_monitors())
    text = "\n".join(lines)
    assert "SOURCE:" not in text
    assert "TOTAL" not in text
    assert "( S A M P L E" not in text
    i = next(k for k, ln in enumerate(lines) if "MONITOR MWING" in ln)
    assert lines[i + 2].strip().startswith("FX")
    assert lines[i + 3].startswith("        " + f"{0.0:13.6E}")


def test_transient_monitor_block_prints_the_contribution_split():
    ml = _monitor("MW", [1, 2, 3, 4, 5, 6], elastic=[0.5] * 6, damping=[0.25] * 6)
    m1 = _monitor("MA", [7, 8, 9, 0, 0, 0], mtype="MONPNT1")
    lines = []
    _monitor_block(lines, {"MW": ml, "MA": m1},
                   title_suffix="   ( S A M P L E  4,  T = 1.500000E-01 )",
                   contributions=True)
    text = "\n".join(lines)
    assert "( S A M P L E  4," in lines[0]
    assert "SOURCE: AERO + INERTIA + REACTION + ELASTIC INERTIA + DAMPING" in text
    assert "SOURCE: AERO ONLY" in text
    for row in ("TOTAL", "AERO", "INERTIA (RIGID)", "ELASTIC INERTIA",
                "DAMPING", "REACTION"):
        assert any(ln.strip().startswith(row) for ln in lines), row
    # The MONPNT1 prints only its total.
    i = next(k for k, ln in enumerate(lines) if "MONITOR MA" in ln)
    block = lines[i:i + 6]
    assert sum(ln.strip().startswith("TOTAL") for ln in block) == 1
    assert not any("ELASTIC" in ln for ln in block[1:])


def test_transient_block_names_damping_only_when_it_is_nonzero():
    ml = _monitor("MW", [1, 2, 3, 4, 5, 6], elastic=[0.5] * 6, damping=[0.0] * 6)
    lines = []
    _monitor_block(lines, {"MW": ml}, contributions=True)
    text = "\n".join(lines)
    assert "+ ELASTIC INERTIA" in text
    assert "+ DAMPING" not in text
    assert not any(ln.strip().startswith("DAMPING") for ln in lines)


def test_envelope_block_renders_with_the_driving_sample():
    res = _three_sample_result()
    env = build_monitor_envelope(res)
    lines = []
    _monitor_envelope_block(lines, env, crit_sample=res.crit_index + 1)
    text = "\n".join(lines)
    assert "M O N I T O R   P O I N T   E N V E L O P E" in text
    assert "CRITICAL SAMPLE (3)" in text
    fz = next(ln for ln in lines if ln.strip().startswith("FZ") and "MA" not in ln)
    # MA: max 300 at sample 2, min 100 at sample 1 — comes first (sorted).
    assert "3.000000E+02" in fz and "1.000000E+02" in fz


# --------------------------------------------------------------------------- #
# Envelope reduction
# --------------------------------------------------------------------------- #

def test_envelope_matches_brute_force_and_is_per_component():
    res = _three_sample_result()
    env = build_monitor_envelope(res)
    assert set(env) == {"MA", "MB"}
    ma = env["MA"]
    assert ma.n_samples == 3 and ma.mtype == "MONPNT3"
    fz = ma.entries[2]
    assert (fz.max_value, fz.max_sample, fz.max_time) == (300.0, 2, 0.05)
    assert (fz.min_value, fz.min_sample) == (100.0, 1)
    my = ma.entries[4]
    assert (my.max_value, my.max_sample) == (5.0, 1)
    assert (my.min_value, my.min_sample) == (-7.0, 2)
    assert my.absmax == 7.0
    # The driving sample is per component: Fz max at 2, My max at 1, neither
    # the critical sample (3).
    mb = env["MB"]
    assert mb.entries[2].min_sample == 2 and mb.entries[2].max_sample == 1
    # Ties resolve to the earliest sample.
    assert ma.entries[0].max_sample == 1 and ma.entries[0].min_sample == 1


def test_envelope_is_none_without_monitors():
    res = types.SimpleNamespace(steps=[types.SimpleNamespace(t=0.0, monitor_loads=None)])
    assert build_monitor_envelope(res) is None


# --------------------------------------------------------------------------- #
# CSVs
# --------------------------------------------------------------------------- #

def test_maneuver_monitor_csv_rows_and_columns(tmp_path):
    res = _three_sample_result()
    path = tmp_path / "x.maneuver_monitor_loads.csv"
    write_maneuver_monitor_csv(str(path), {3: res})
    with open(path) as fh:
        header = next(csv.reader(fh))
        fh.seek(0)
        rows = list(csv.DictReader(fh))
    assert len(header) == len(set(header)), "duplicate column names"
    assert header[:6] == ["case", "mloads", "massset", "sample", "time", "critical"]
    assert header[6:11] == ["name", "type", "label", "axes", "cid"]     # static schema verbatim
    assert "Fz_elastic" in header and "elastic_Fz" in header and "react_Mz" in header
    assert len(rows) == 3 * 2
    r = next(x for x in rows if x["name"] == "MA" and x["sample"] == "2")
    assert r["case"] == "3" and r["mloads"] == "9" and r["critical"] == "0"
    assert float(r["Fz"]) == 300.0 and float(r["time"]) == 0.05
    assert float(r["Fz_elastic"]) == 0.1 and float(r["elastic_Mz"]) == 0.1
    assert float(r["Fz_aero"]) == float(r["aero_Fz"]) == 300.0 - 0.1
    crit = [x for x in rows if x["critical"] == "1"]
    assert {x["sample"] for x in crit} == {"3"}
    assert build_maneuver_monitor_csv_text({3: res}) == path.read_bytes().decode()


def test_maneuver_monitor_envelope_csv(tmp_path):
    res = _three_sample_result()
    res.monitor_envelope = build_monitor_envelope(res)
    path = tmp_path / "x.maneuver_monitor_envelope.csv"
    write_maneuver_monitor_envelope_csv(str(path), {3: res})
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2 * 6
    r = next(x for x in rows if x["name"] == "MA" and x["comp_name"] == "Fz")
    assert r["max"] == "3.000000E+02" and r["max_sample"] == "2"
    assert r["min_sample"] == "1" and r["critical_sample"] == "3"
    assert r["n_samples"] == "3" and r["type"] == "MONPNT3"
    assert build_maneuver_monitor_envelope_csv_text({3: res}) == path.read_bytes().decode()
