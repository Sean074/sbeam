"""NASTRAN-style .f06 output writer for SOL 101 and SOL 103 results."""

from datetime import datetime

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import Sol101Result, Sol103Result
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.coord_transform import build_transform


def _fmt(val: float) -> str:
    """Format a float in NASTRAN 13.6E style."""
    return f"{val:13.6E}"


def write_f06_sol101(
    filepath: str,
    case_control,
    bulk: BulkData,
    result: Sol101Result,
    subcase_id: int = 1,
) -> None:
    """Write NASTRAN-style .f06 file for SOL 101 results."""
    grid_index = build_grid_index(bulk)
    gids_sorted = sorted(bulk.grids.keys())

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = getattr(case_control, "title", "") or "sbeam SOL 101"

    lines = []

    # ---- Header ----
    lines.append(f"1                                                                           {'sbeam':>20}")
    lines.append("                                          SOL 101 STATIC ANALYSIS")
    lines.append(f"                                          {title}")
    lines.append(f"                                          DATE: {now}")
    lines.append("")

    lines.append(f"                           SUBCASE {subcase_id}")
    lines.append("")

    # ---- DISPLACEMENT section ----
    lines.append("                                         D I S P L A C E M E N T   V E C T O R")
    lines.append("")
    lines.append("      POINT ID.   TYPE          T1             T2             T3             R1             R2             R3")

    for gid in gids_sorted:
        i = grid_index[gid]
        base = 6 * i
        t = result.displacements[base:base+3]
        r = result.displacements[base+3:base+6]
        cd = bulk.grids[gid].cd
        if cd != 0 and cd in bulk.cord2rs:
            R = build_transform(cd, bulk.cord2rs)
            t = R.T @ t
            r = R.T @ r
        lines.append(
            f"{gid:>14}     G  {_fmt(t[0])}{_fmt(t[1])}{_fmt(t[2])}{_fmt(r[0])}{_fmt(r[1])}{_fmt(r[2])}"
        )

    lines.append("")

    # ---- SPCFORCE section ----
    lines.append("                                    F O R C E S   O F   S I N G L E - P O I N T   C O N S T R A I N T")
    lines.append("")
    lines.append("      POINT ID.   TYPE          T1             T2             T3             R1             R2             R3")

    for gid in gids_sorted:
        if gid in result.reactions:
            r = result.reactions[gid]
            lines.append(
                f"{gid:>14}     G  {_fmt(r[0])}{_fmt(r[1])}{_fmt(r[2])}{_fmt(r[3])}{_fmt(r[4])}{_fmt(r[5])}"
            )

    lines.append("")

    # ---- BAR FORCES section ----
    lines.append("                                  F O R C E S   I N   B A R   E L E M E N T S         ( C B A R )")
    lines.append("")
    lines.append(
        "      ELEMENT ID.    AXIAL FORCE    SHEAR-1        SHEAR-2        TORQUE         BENDING-1 A    BENDING-2 A    BENDING-1 B    BENDING-2 B"
    )

    for eid in sorted(bulk.cbars.keys()):
        if eid in result.bar_forces:
            bf = result.bar_forces[eid]
            lines.append(
                f"{eid:>14}"
                f"  {_fmt(bf.axial)}{_fmt(bf.shear1)}{_fmt(bf.shear2)}{_fmt(bf.torque)}"
                f"{_fmt(bf.bm1_a)}{_fmt(bf.bm2_a)}{_fmt(bf.bm1_b)}{_fmt(bf.bm2_b)}"
            )

    lines.append("")

    # ---- BAR STRESSES section ----
    lines.append("                                 S T R E S S E S   I N   B A R   E L E M E N T S        ( C B A R )")
    lines.append("")
    lines.append(
        "      ELEMENT ID.    AXIAL          SA(END-A)      SB(END-B)"
    )

    for eid in sorted(bulk.cbars.keys()):
        if eid in result.bar_stresses:
            bs = result.bar_stresses[eid]
            lines.append(
                f"{eid:>14}  {_fmt(bs.axial)}{_fmt(bs.sa)}{_fmt(bs.sb)}"
            )

    lines.append("")
    lines.append("                                       * * * END OF JOB * * *")
    lines.append("")

    with open(filepath, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def write_f06_sol103(
    filepath: str,
    case_control,
    bulk: BulkData,
    result: Sol103Result,
    subcase_id: int = 1,
) -> None:
    """Write NASTRAN-style .f06 file for SOL 103 normal modes results."""
    grid_index = build_grid_index(bulk)
    gids_sorted = sorted(bulk.grids.keys())

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = getattr(case_control, "title", "") or "sbeam SOL 103"

    lines = []

    # Header
    lines.append(f"1                                                                           {'sbeam':>20}")
    lines.append("                                          SOL 103 NORMAL MODES")
    lines.append(f"                                          {title}")
    lines.append(f"                                          DATE: {now}")
    lines.append("")
    lines.append(f"                           SUBCASE {subcase_id}")
    lines.append("")

    # Real Eigenvalue Table
    lines.append("                                          R E A L   E I G E N V A L U E S")
    lines.append("")
    lines.append(
        "   MODE NO.      EIGENVALUE            RADIANS             CYCLES             GENERALIZED MASS"
    )

    for i, (freq, lam) in enumerate(zip(result.frequencies_hz, result.eigenvalues), start=1):
        omega = 2.0 * 3.141592653589793 * freq
        lines.append(
            f"{i:>10}  {_fmt(lam)}  {_fmt(omega)}  {_fmt(freq)}  {_fmt(1.0)}"
        )

    lines.append("")

    # Mode shape tables
    for mode_idx in range(result.mode_shapes.shape[1]):
        freq = result.frequencies_hz[mode_idx]
        lines.append(
            f"                          E I G E N V E C T O R   NO. {mode_idx + 1}     FREQ = {freq:.6E} Hz"
        )
        lines.append("")
        lines.append(
            "      POINT ID.   TYPE          T1             T2             T3             R1             R2             R3"
        )
        phi = result.mode_shapes[:, mode_idx]
        for gid in gids_sorted:
            i = grid_index[gid]
            base = 6 * i
            t = phi[base:base+3]
            r = phi[base+3:base+6]
            cd = bulk.grids[gid].cd
            if cd != 0 and cd in bulk.cord2rs:
                R = build_transform(cd, bulk.cord2rs)
                t = R.T @ t
                r = R.T @ r
            lines.append(
                f"{gid:>14}     G  "
                f"{_fmt(t[0])}{_fmt(t[1])}{_fmt(t[2])}"
                f"{_fmt(r[0])}{_fmt(r[1])}{_fmt(r[2])}"
            )
        lines.append("")

    lines.append("                                       * * * END OF JOB * * *")
    lines.append("")

    with open(filepath, "w") as fh:
        fh.write("\n".join(lines) + "\n")
