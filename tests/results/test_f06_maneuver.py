"""AC5 — f06 maneuver block (build_f06_sol144_maneuver_text).

The Phase G0 transient maneuver f06 block: run summary, MANEUVER TIME HISTORY
table with the critical-sample marker, and the critical-sample detail (closure
resultant + shared displacement/bar-force blocks). Shared by the CLI and the
viewer f06 export.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.results.results import ManeuverResult, ManeuverStep
from sbeam.results.f06_writer import build_f06_sol144_maneuver_text


def _two_grid_bulk() -> BulkData:
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
    return bulk


def _step(t: float, elev: float, net_peak: float) -> ManeuverStep:
    n = 12
    net = np.zeros(n)
    net[2] = net_peak
    return ManeuverStep(
        t=t,
        trim_vars={"ANGLEA": 0.1, "ELEV": elev},
        displacements=np.zeros(n),
        bar_forces={},
        grid_loads=np.zeros(n),
        inertial_loads=np.zeros(n),
        net_loads=net,
        closure=np.array([0.0, 0.0, net_peak, 0.0, 2.0 * net_peak, 0.0]),
        Fz_aero=net_peak,
        My_aero=-4.0 * net_peak,
    )


def _result(steps: list) -> ManeuverResult:
    crit = int(np.argmax([np.abs(s.net_loads).max() for s in steps])) if steps else 0
    return ManeuverResult(
        subcase_id=2, mloads_sid=5, trim_sid=7, q=40.0, mach=0.9,
        labels=["ANGLEA", "ELEV"],
        times=np.array([s.t for s in steps]),
        steps=steps, crit_index=crit,
    )


def test_maneuver_block_content():
    bulk = _two_grid_bulk()
    steps = [_step(0.0, 0.5, 100.0), _step(0.1, 0.6, 300.0), _step(0.2, 0.6, 200.0)]
    text = build_f06_sol144_maneuver_text(
        SimpleNamespace(title="AC5 test"), bulk, _result(steps), subcase_id=2)

    assert "SOL 144 TRANSIENT MANEUVER LOADS" in text
    assert "MLOADS = 5" in text and "TRIM = 7" in text
    assert "M A N E U V E R   T I M E   H I S T O R Y" in text
    assert "ELEV" in text and "ANGLEA" in text
    assert "OUTPUT SAMPLES = 3" in text
    # Peak |net| is sample 2 (1-based), marked in its row only.
    crit_rows = [ln for ln in text.splitlines() if "<-- CRITICAL" in ln]
    assert len(crit_rows) == 1 and crit_rows[0].lstrip().startswith("2")
    assert "CRITICAL SAMPLE = 2" in text
    assert "C R I T I C A L   S A M P L E   D E T A I L" in text
    assert "LOAD CLOSURE RESULTANT" in text
    # Shared structural blocks at the critical sample.
    assert "D I S P L A C E M E N T   V E C T O R" in text or "DISPLACEMENT" in text.upper()
    assert "F O R C E S   I N   B A R   E L E M E N T S" in text


def test_maneuver_block_empty_steps():
    text = build_f06_sol144_maneuver_text(
        SimpleNamespace(title=""), _two_grid_bulk(), _result([]), subcase_id=1)
    assert "NO OUTPUT SAMPLES" in text
    assert "END OF JOB" in text
