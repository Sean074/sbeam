"""Export trimmed SOL 144 grid loads as NASTRAN FORCE/MOMENT bulk-data cards.

For a determined (plain) trim the exported set is the g-set aerodynamic flight
load ``G_disp^T·(q·P_k)`` recovered by ``run_sol144_trim`` (``result.grid_loads``);
by spline force/moment conservation it sums to the total trimmed lift/moment.
The cards are emitted in comma free-field form with a unit scale factor so the
direction components carry the physical load:

    FORCE,  SID, GID, 0, 1.0, Fx, Fy, Fz
    MOMENT, SID, GID, 0, 1.0, Mx, My, Mz

Maneuver-balanced (aero + inertial) net loads are a separate item (Step 53).
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
    gl = result.grid_loads

    lines = [
        f"$ SOL 144 trimmed aerodynamic flight loads — subcase {result.subcase_id}, SID {sid}",
        f"$ TRIM={result.trim_sid}  Q={result.q:g}  MACH={result.mach:g}  CL={result.total_cl:.6f}",
        "$ FORCE/MOMENT set sums to the total trimmed lift/moment (plain trim).",
    ]
    for gid in sorted(bulk.grids.keys()):
        base = 6 * grid_index[gid]
        f = gl[base:base + 3]
        m = gl[base + 3:base + 6]
        if np.any(np.abs(f) > _TOL):
            lines.append(
                f"FORCE, {sid}, {gid}, 0, 1.0, {_fmt(f[0])}, {_fmt(f[1])}, {_fmt(f[2])}"
            )
        if np.any(np.abs(m) > _TOL):
            lines.append(
                f"MOMENT, {sid}, {gid}, 0, 1.0, {_fmt(m[0])}, {_fmt(m[1])}, {_fmt(m[2])}"
            )
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
