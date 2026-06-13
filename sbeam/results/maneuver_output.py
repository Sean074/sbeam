"""Phase G0 transient maneuver-loads output — ASCII time histories + critical
critical-step FORCE/MOMENT export.

``MLDPRNT`` requests an ASCII time-history dump of the maneuver states and
recovered loads.  In addition, the single critical sample (peak net resultant
force) is exported as NASTRAN ``FORCE``/``MOMENT`` cards — the same loads-team
deliverable as the Step 53 balanced-maneuver export, reusing
``_emit_force_moment_cards`` so the card form is identical.
"""

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import ManeuverResult
from sbeam.assembly.load_vector import build_grid_index
from sbeam.results.load_export import _emit_force_moment_cards


def build_maneuver_time_history_text(result: ManeuverResult) -> str:
    """Return an ASCII time-history table for an MLDPRNT request.

    Columns: time, each trim-variable command δ(t), instantaneous aero lift Fz
    and pitch moment My, the net force/moment closure norms, and the peak net
    grid-load magnitude.  The ``MLDPRNT`` item keywords are reserved for column
    selection in a later increment; increment 1 prints the full set.
    """
    labels = result.labels
    header_cols = (
        ["TIME"] + [l[:12] for l in labels]
        + ["FZ_AERO", "MY_AERO", "CLOSURE_F", "CLOSURE_M", "MAX_NET"]
    )
    lines = [
        f"$ Phase G0 transient maneuver loads — subcase {result.subcase_id}, "
        f"MLOADS {result.mloads_sid}",
        f"$ IC TRIM={result.trim_sid}  Q={result.q:g}  MACH={result.mach:g}  "
        f"critical sample index={result.crit_index} (t={result.times[result.crit_index]:g})",
        "  ".join(f"{c:>13s}" for c in header_cols),
    ]
    for s in result.steps:
        row = [f"{s.t:13.5e}"]
        row += [f"{s.trim_vars.get(l, 0.0):13.5e}" for l in labels]
        cl_f = float(np.linalg.norm(s.closure[:3]))
        cl_m = float(np.linalg.norm(s.closure[3:]))
        max_net = float(np.max(np.abs(s.net_loads))) if s.net_loads.size else 0.0
        row += [f"{s.Fz_aero:13.5e}", f"{s.My_aero:13.5e}",
                f"{cl_f:13.5e}", f"{cl_m:13.5e}", f"{max_net:13.5e}"]
        lines.append("  ".join(row))
    return "\n".join(lines) + "\n"


def build_maneuver_critical_load_cards_text(
    bulk: BulkData, result: ManeuverResult, sid: int = None
) -> str:
    """FORCE/MOMENT cards for the critical (peak net force) maneuver sample.

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
        "$ Net (aero + inertial) load at the peak |net force| sample.",
    ]
    lines += _emit_force_moment_cards(step.net_loads, bulk, grid_index, sid)
    return "\n".join(lines) + "\n"


def write_maneuver_outputs(stem: str, bulk: BulkData, results: dict) -> tuple:
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
