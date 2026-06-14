"""MON4 — f06 MONITOR POINT INTEGRATED LOADS block + CSV export."""
import csv
import types

import numpy as np

from sbeam.results.results import MonitorLoad
from sbeam.results.f06_writer import _monitor_block
from sbeam.results.load_export import write_monitor_csv


def _sample_monitors():
    return {
        "MWING": MonitorLoad(
            name="MWING", label="FULL WING", mtype="MONPNT3", axes=123456, cid=0,
            ref=np.array([1.5, 0.0, 0.0]),
            totals=np.array([0.0, 0.0, 8000.0, 60000.0, -1200.0, 0.0]),
            aero=np.array([0.0, 0.0, 8000.0, 60000.0, -1200.0, 0.0]),
            inertia=np.zeros(6), reaction=np.zeros(6),
            parity=1.0, whole_airplane=False, source_ids=[300],
        ),
        "MWAERO": MonitorLoad(
            name="MWAERO", label="WING AERO", mtype="MONPNT1", axes=123456, cid=0,
            ref=np.zeros(3),
            totals=np.array([0.0, 0.0, 16000.0, 0.0, 0.0, 0.0]),
            aero=np.array([0.0, 0.0, 16000.0, 0.0, 0.0, 0.0]),
            inertia=np.zeros(6), reaction=np.zeros(6),
            parity=2.0, whole_airplane=True, source_ids=[200],
        ),
    }


def test_f06_monitor_block_renders():
    lines = []
    _monitor_block(lines, _sample_monitors())
    text = "\n".join(lines)
    assert "M O N I T O R   P O I N T   I N T E G R A T E D   L O A D S" in text
    assert "MONITOR MWING" in text
    assert "MONPNT3" in text
    # Parity annotation only on the whole-airplane (half-model) monitor.
    assert "*WHOLE-AIRPLANE*" in text
    mwing_idx = next(i for i, ln in enumerate(lines) if "MONITOR MWING" in ln)
    assert "*WHOLE-AIRPLANE*" not in lines[mwing_idx]
    # The Fz total appears in the values row.
    assert "8.000000E+03" in text


def test_csv_matches_monitor_values(tmp_path):
    results = {7: types.SimpleNamespace(monitor_loads=_sample_monitors())}
    path = tmp_path / "out.monitor_loads.csv"
    write_monitor_csv(str(path), results)

    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}

    mwing = by_name["MWING"]
    assert mwing["case"] == "7"
    assert mwing["type"] == "MONPNT3"
    assert float(mwing["Fz"]) == 8000.0
    assert float(mwing["My"]) == -1200.0
    assert float(mwing["Fz_aero"]) == 8000.0
    assert float(mwing["Fz_inertia"]) == 0.0
    assert int(mwing["whole_airplane"]) == 0

    mwaero = by_name["MWAERO"]
    assert mwaero["type"] == "MONPNT1"
    assert float(mwaero["Fz"]) == 16000.0
    assert float(mwaero["parity"]) == 2.0
    assert int(mwaero["whole_airplane"]) == 1


def test_csv_skips_subcases_without_monitors(tmp_path):
    results = {
        1: types.SimpleNamespace(monitor_loads=None),
        2: types.SimpleNamespace(monitor_loads=_sample_monitors()),
    }
    path = tmp_path / "out.csv"
    write_monitor_csv(str(path), results)
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    assert {r["case"] for r in rows} == {"2"}
