"""Export trimmed SOL 144 grid loads as NASTRAN FORCE/MOMENT bulk-data cards.

For a determined (plain) trim the exported set is the g-set aerodynamic flight
load ``G_disp^T·(q·P_k)`` recovered by ``run_sol144_trim`` (``result.grid_loads``);
by spline force/moment conservation it sums to the total trimmed lift/moment.
The cards are emitted in comma free-field form with a unit scale factor so the
direction components carry the physical load:

    FORCE,  SID, GID, 0, 1.0, Fx, Fy, Fz
    MOMENT, SID, GID, 0, 1.0, Mx, My, Mz

Maneuver-balanced (aero + inertial) net loads (Step 53) are emitted by
``build_maneuver_load_cards_text`` from ``result.net_loads`` — the same card
form, but the set sums to the trimmed lift minus the inertia-relief reaction
(i.e. the constraint reaction for the balanced maneuver).
"""

from typing import Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import Sol144TrimResult
from sbeam.assembly.load_vector import build_grid_index

# Loads below this magnitude are treated as zero and not emitted.
_TOL = 1e-9


def _fmt(val: float) -> str:
    """Format a load component in NASTRAN 6-digit scientific style."""
    return f"{val:.6E}"


def _emit_force_moment_cards(loads_g: np.ndarray, bulk: BulkData, grid_index: dict, sid: int) -> list:
    """Return FORCE/MOMENT card lines for a g-set load vector (one per grid)."""
    lines = []
    for gid in sorted(bulk.grids.keys()):
        base = 6 * grid_index[gid]
        f = loads_g[base:base + 3]
        m = loads_g[base + 3:base + 6]
        if np.any(np.abs(f) > _TOL):
            lines.append(
                f"FORCE, {sid}, {gid}, 0, 1.0, {_fmt(f[0])}, {_fmt(f[1])}, {_fmt(f[2])}"
            )
        if np.any(np.abs(m) > _TOL):
            lines.append(
                f"MOMENT, {sid}, {gid}, 0, 1.0, {_fmt(m[0])}, {_fmt(m[1])}, {_fmt(m[2])}"
            )
    return lines


def build_aero_load_cards_text(
    bulk: BulkData,
    result: Sol144TrimResult,
    sid: Optional[int] = None,
) -> str:
    """Return FORCE/MOMENT bulk-data card text for one trimmed subcase.

    Args:
        bulk:   Parsed BulkData (for the grid ordering / grid_index).
        result: Sol144TrimResult with ``grid_loads`` populated.
        sid:    Load set ID to stamp on the cards; defaults to the subcase id.

    Returns:
        Comma free-field NASTRAN card text (with a leading comment block).

    Raises:
        ValueError if result.grid_loads is None.
    """
    if result.grid_loads is None:
        raise ValueError(
            "build_aero_load_cards_text: result.grid_loads is None — "
            "the trim result carries no exportable flight loads."
        )

    sid = sid if sid is not None else result.subcase_id
    grid_index = build_grid_index(bulk)

    lines = [
        f"$ SOL 144 trimmed aerodynamic flight loads — subcase {result.subcase_id}, SID {sid}",
        f"$ TRIM={result.trim_sid}  Q={result.q:g}  MACH={result.mach:g}  CL={result.total_cl:.6f}",
        "$ FORCE/MOMENT set sums to the total trimmed lift/moment (plain trim).",
    ]
    lines += _emit_force_moment_cards(result.grid_loads, bulk, grid_index, sid)
    return "\n".join(lines) + "\n"


def build_maneuver_load_cards_text(
    bulk: BulkData,
    result: Sol144TrimResult,
    sid: Optional[int] = None,
) -> str:
    """Return FORCE/MOMENT card text for one trimmed subcase's net maneuver load.

    Emits ``result.net_loads`` (aero + inertia-relief, Step 53) — the stress
    deliverable for a balanced maneuver.  Card form is identical to the aero-only
    export; only the load content differs.

    Raises:
        ValueError if result.net_loads is None.
    """
    if result.net_loads is None:
        raise ValueError(
            "build_maneuver_load_cards_text: result.net_loads is None — "
            "the trim result carries no maneuver-balanced loads."
        )

    sid = sid if sid is not None else result.subcase_id
    grid_index = build_grid_index(bulk)

    lines = [
        f"$ SOL 144 balanced maneuver loads (aero + inertia relief) — subcase {result.subcase_id}, SID {sid}",
        f"$ TRIM={result.trim_sid}  Q={result.q:g}  MACH={result.mach:g}  CL={result.total_cl:.6f}",
        "$ FORCE/MOMENT set is the net (aero + inertial) maneuver load for stress (Step 53).",
    ]
    lines += _emit_force_moment_cards(result.net_loads, bulk, grid_index, sid)
    return "\n".join(lines) + "\n"


def write_aero_load_cards(filepath: str, bulk: BulkData, results: dict) -> None:
    """Write FORCE/MOMENT cards for all trimmed subcases to one bulk-data file.

    Args:
        filepath: Output path (a ``*.bdf``-style bulk-data fragment).
        bulk:     Parsed BulkData.
        results:  {subcase_id: Sol144TrimResult}.  One card block per subcase,
                  each stamped with SID = subcase_id.
    """
    blocks = [
        build_aero_load_cards_text(bulk, result, sid=sc_id)
        for sc_id, result in results.items()
    ]
    with open(filepath, "w") as fh:
        fh.write("\n".join(blocks))


def write_maneuver_load_cards(filepath: str, bulk: BulkData, results: dict) -> None:
    """Write net maneuver-balanced FORCE/MOMENT cards for all subcases (Step 53).

    Args:
        filepath: Output path (a ``*.maneuver_loads.bdf`` bulk-data fragment).
        bulk:     Parsed BulkData.
        results:  {subcase_id: Sol144TrimResult}.  One block per subcase, SID =
                  subcase_id.
    """
    blocks = [
        build_maneuver_load_cards_text(bulk, result, sid=sc_id)
        for sc_id, result in results.items()
    ]
    with open(filepath, "w") as fh:
        fh.write("\n".join(blocks))
