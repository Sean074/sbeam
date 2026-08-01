"""Phase G0 transient maneuver-loads output — ASCII time histories + critical
critical-step FORCE/MOMENT export.

``MLDPRNT`` requests an ASCII time-history dump of the maneuver states and
recovered loads.  In addition, the single critical sample is exported as
NASTRAN ``FORCE``/``MOMENT`` cards — the same loads-team deliverable as the
Step 53 balanced-maneuver export, reusing ``emit_force_moment_cards`` so the
card form is identical.

The critical sample is the peak ``results.peak_grid_force`` sample, and sample
numbering here is 1-based to match the f06 ``SAMPLE`` column: the selector, the
printed column, the label and the exported card set are all the same metric on
the same numbering (DEF-M5).
"""

from typing import Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import ManeuverResult, peak_grid_force
from sbeam.assembly.load_vector import build_grid_index
from sbeam.results.load_export import emit_force_moment_cards


def build_maneuver_time_history_text(result: ManeuverResult) -> str:
    """Return an ASCII time-history table for an MLDPRNT request.

    Columns: time, each trim-variable command δ(t), instantaneous aero lift Fz
    and pitch moment My, the net force/moment closure norms (the aero/inertia
    balance residual — a solution-quality diagnostic), and ``PEAK_GRID_F``, the
    severity metric that selects the critical sample.  The ``MLDPRNT`` item
    keywords are reserved for column selection in a later increment; increment 1
    prints the full set.
    """
    labels = result.labels
    header_cols = (
        ["TIME"] + [l[:12] for l in labels]
        + ["FZ_AERO", "MY_AERO", "CLOSURE_F", "CLOSURE_M", "PEAK_GRID_F"]
    )
    lines = [
        f"$ Phase G0 transient maneuver loads — subcase {result.subcase_id}, "
        f"MLOADS {result.mloads_sid}",
        # 1-based, matching the f06 SAMPLE column (DEF-M5).
        f"$ IC TRIM={result.trim_sid}  Q={result.q:g}  MACH={result.mach:g}  "
        f"critical sample={result.crit_index + 1} of {len(result.steps)} "
        f"(t={result.times[result.crit_index]:g}, peak |net grid force|)",
        "  ".join(f"{c:>13s}" for c in header_cols),
    ]
    for s in result.steps:
        row = [f"{s.t:13.5e}"]
        row += [f"{s.trim_vars.get(l, 0.0):13.5e}" for l in labels]
        cl_f = float(np.linalg.norm(s.closure[:3]))
        cl_m = float(np.linalg.norm(s.closure[3:]))
        row += [f"{s.Fz_aero:13.5e}", f"{s.My_aero:13.5e}",
                f"{cl_f:13.5e}", f"{cl_m:13.5e}", f"{peak_grid_force(s):13.5e}"]
        lines.append("  ".join(row))
    return "\n".join(lines) + "\n"


def build_maneuver_critical_load_cards_text(
    bulk: BulkData, result: ManeuverResult, sid: Optional[int] = None
) -> str:
    """FORCE/MOMENT cards for the critical (peak per-grid net force) sample.

    Emits the net (aero + inertial) grid load at ``result.steps[crit_index]`` —
    the worst-case balanced maneuver load for stress sizing.
    """
    if not result.steps:
        raise ValueError("build_maneuver_critical_load_cards_text: no maneuver samples")
    sid = sid if sid is not None else result.subcase_id
    grid_index = build_grid_index(bulk)
    step = result.steps[result.crit_index]
    lines = [
        f"$ Phase G0 critical maneuver loads (aero + inertial) — subcase "
        f"{result.subcase_id}, SID {sid}",
        f"$ MLOADS={result.mloads_sid}  IC TRIM={result.trim_sid}  Q={result.q:g}  "
        f"MACH={result.mach:g}  t={step.t:g}",
        f"$ Net (aero + inertial) load at the peak |net grid force| sample "
        f"({result.crit_index + 1} of {len(result.steps)}).",
    ]
    lines += emit_force_moment_cards(step.net_loads, bulk, grid_index, sid)
    return "\n".join(lines) + "\n"


def write_maneuver_outputs(
    stem: str, bulk: BulkData, results: dict[int, ManeuverResult]
) -> tuple[str, str]:
    """Write the ASCII time histories and critical-step load cards.

    Args:
        stem:    Output path stem (no extension); writes ``<stem>.mldprnt.txt``
                 and ``<stem>.maneuver_qs_loads.bdf``.
        bulk:    Parsed BulkData.
        results: {subcase_id: ManeuverResult}.

    Returns:
        (mldprnt_path, loads_path) of the two files written.
    """
    mldprnt_path = f"{stem}.mldprnt.txt"
    loads_path = f"{stem}.maneuver_qs_loads.bdf"
    th_blocks = [build_maneuver_time_history_text(r) for r in results.values()]
    ld_blocks = [
        build_maneuver_critical_load_cards_text(bulk, r, sid=sc_id)
        for sc_id, r in results.items()
    ]
    with open(mldprnt_path, "w") as fh:
        fh.write("\n".join(th_blocks))
    with open(loads_path, "w") as fh:
        fh.write("\n".join(ld_blocks))
    return mldprnt_path, loads_path
