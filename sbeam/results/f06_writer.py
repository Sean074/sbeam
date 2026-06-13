"""NASTRAN-style .f06 output writer for SOL 101 and SOL 103 results."""

from datetime import datetime

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import Sol101Result, Sol103Result, Sol144TrimResult
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.coord_transform import build_transform


def _fmt(val: float) -> str:
    """Format a float in NASTRAN 13.6E style."""
    return f"{val:13.6E}"


def _transform_to_cd(t: np.ndarray, r: np.ndarray, gid: int, bulk: BulkData):
    """Rotate translation/rotation vectors into the grid's output (CD) coordinate frame."""
    cd = bulk.grids[gid].cd
    if cd != 0 and cd in bulk.cord2rs:
        R = build_transform(cd, bulk.cord2rs)
        t = R.T @ t
        r = R.T @ r
    return t, r


def _collect_grav_loads(bulk: BulkData, load_sid: int) -> list:
    """Return list of Grav objects referenced by load_sid (direct or via LOAD card)."""
    gravs = []
    if load_sid in bulk.gravs:
        gravs.append(bulk.gravs[load_sid])
    elif load_sid in bulk.loads:
        for _, sid_i in bulk.loads[load_sid].components:
            if sid_i in bulk.gravs:
                gravs.append(bulk.gravs[sid_i])
    return gravs


_STRESS_PTS = [
    ("C", "sa",   "sb",   "c1", "c2"),
    ("D", "sa_d", "sb_d", "d1", "d2"),
    ("E", "sa_e", "sb_e", "e1", "e2"),
    ("F", "sa_f", "sb_f", "f1", "f2"),
]


def _displacement_block(lines: list, displacements, bulk: BulkData, grid_index: dict, gids_sorted: list) -> None:
    """Append a NASTRAN DISPLACEMENT VECTOR block (shared by SOL 101 / 144)."""
    lines.append("                                         D I S P L A C E M E N T   V E C T O R")
    lines.append("")
    lines.append("      POINT ID.   TYPE          T1             T2             T3             R1             R2             R3")
    for gid in gids_sorted:
        i = grid_index[gid]
        base = 6 * i
        t = displacements[base:base+3]
        r = displacements[base+3:base+6]
        t, r = _transform_to_cd(t, r, gid, bulk)
        lines.append(
            f"{gid:>14}     G  {_fmt(t[0])}{_fmt(t[1])}{_fmt(t[2])}{_fmt(r[0])}{_fmt(r[1])}{_fmt(r[2])}"
        )
    lines.append("")


def _bar_forces_block(lines: list, bulk: BulkData, bar_forces: dict) -> None:
    """Append a NASTRAN FORCES IN BAR ELEMENTS (CBAR) block (shared by SOL 101 / 144)."""
    lines.append("                                  F O R C E S   I N   B A R   E L E M E N T S         ( C B A R )")
    lines.append("")
    lines.append(
        "      ELEMENT ID.    AXIAL FORCE    SHEAR-1        SHEAR-2        TORQUE         BENDING-1 A    BENDING-2 A    BENDING-1 B    BENDING-2 B"
    )
    for eid in sorted(bulk.cbars.keys()):
        if eid in bar_forces:
            bf = bar_forces[eid]
            lines.append(
                f"{eid:>14}"
                f"  {_fmt(bf.axial)}{_fmt(bf.shear1)}{_fmt(bf.shear2)}{_fmt(bf.torque)}"
                f"{_fmt(bf.bm1_a)}{_fmt(bf.bm2_a)}{_fmt(bf.bm1_b)}{_fmt(bf.bm2_b)}"
            )
    lines.append("")


def _bar_stresses_block(lines: list, bulk: BulkData, bar_stresses: dict) -> None:
    """Append a NASTRAN STRESSES IN BAR ELEMENTS (CBAR) block (shared by SOL 101 / 144)."""
    lines.append("                                 S T R E S S E S   I N   B A R   E L E M E N T S        ( C B A R )")
    lines.append("")
    lines.append(
        "      ELEMENT ID.    AXIAL          PT      SA(END-A)      SB(END-B)"
    )
    for eid in sorted(bulk.cbars.keys()):
        if eid not in bar_stresses:
            continue
        bs = bar_stresses[eid]
        pbar = bulk.pbars[bulk.cbars[eid].pid]
        first = True
        for pt, sa_attr, sb_attr, y_attr, z_attr in _STRESS_PTS:
            if getattr(pbar, y_attr) == 0.0 and getattr(pbar, z_attr) == 0.0:
                continue
            sa = getattr(bs, sa_attr)
            sb = getattr(bs, sb_attr)
            if first:
                lines.append(
                    f"{eid:>14}  {_fmt(bs.axial)}    {pt}  {_fmt(sa)}{_fmt(sb)}"
                )
                first = False
            else:
                lines.append(
                    f"{'':>14}  {'':13}    {pt}  {_fmt(sa)}{_fmt(sb)}"
                )
    lines.append("")


def _build_f06_sol101_text(
    case_control,
    bulk: BulkData,
    result: Sol101Result,
    subcase_id: int = 1,
) -> str:
    """Return a complete SOL 101 .f06 block as a string."""
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

    # ---- GRAV applied loads echo (when oload requested and GRAV present) ----
    _subcase_obj = None
    if hasattr(case_control, "subcases"):
        for sc in case_control.subcases:
            if sc.subcase_id == subcase_id:
                _subcase_obj = sc
                break
    if _subcase_obj is not None and _subcase_obj.oload and _subcase_obj.load_sid is not None:
        grav_loads = _collect_grav_loads(bulk, _subcase_obj.load_sid)
        if grav_loads:
            lines.append("                               A P P L I E D   G R A V I T Y   L O A D S")
            lines.append("")
            lines.append("      SID        CID              G              N1             N2             N3")
            for grav in grav_loads:
                lines.append(
                    f"{grav.sid:>10}{grav.cid:>10}"
                    f"  {_fmt(grav.g)}{_fmt(grav.n1)}{_fmt(grav.n2)}{_fmt(grav.n3)}"
                )
            lines.append("")

    # ---- DISPLACEMENT section ----
    _displacement_block(lines, result.displacements, bulk, grid_index, gids_sorted)

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
    _bar_forces_block(lines, bulk, result.bar_forces)

    # ---- BAR STRESSES section ----
    _bar_stresses_block(lines, bulk, result.bar_stresses)

    # ---- CBUSH FORCES section ----
    if result.cbush_forces:
        lines.append("                                F O R C E S   I N   C B U S H   E L E M E N T S        ( C B U S H )")
        lines.append("")
        lines.append(
            "      ELEMENT ID.       F1             F2             F3             M1             M2             M3"
        )
        for eid in sorted(bulk.cbushs.keys()):
            if eid in result.cbush_forces:
                f = result.cbush_forces[eid]
                lines.append(
                    f"{eid:>14}"
                    f"  {_fmt(f[0])}{_fmt(f[1])}{_fmt(f[2])}{_fmt(f[3])}{_fmt(f[4])}{_fmt(f[5])}"
                )
        lines.append("")

    lines.append("                                       * * * END OF JOB * * *")
    lines.append("")

    return "\n".join(lines) + "\n"


def _build_f06_sol103_text(
    case_control,
    bulk: BulkData,
    result: Sol103Result,
    subcase_id: int = 1,
) -> str:
    """Return a complete SOL 103 .f06 block as a string."""
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

    for i, (freq, lam, gm) in enumerate(
        zip(result.frequencies_hz, result.eigenvalues, result.generalized_masses), start=1
    ):
        omega = 2.0 * 3.141592653589793 * freq
        lines.append(
            f"{i:>10}  {_fmt(lam)}  {_fmt(omega)}  {_fmt(freq)}  {_fmt(gm)}"
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
            t, r = _transform_to_cd(t, r, gid, bulk)
            lines.append(
                f"{gid:>14}     G  "
                f"{_fmt(t[0])}{_fmt(t[1])}{_fmt(t[2])}"
                f"{_fmt(r[0])}{_fmt(r[1])}{_fmt(r[2])}"
            )
        lines.append("")

    lines.append("                                       * * * END OF JOB * * *")
    lines.append("")

    return "\n".join(lines) + "\n"


def _build_f06_sol144_text(
    case_control,
    bulk: BulkData,
    result: Sol144TrimResult,
    subcase_id: int = 1,
) -> str:
    """Return a complete SOL 144 static aeroelastic trim .f06 block as a string.

    Blocks: TRIM VARIABLES, STABILITY DERIVATIVES (rigid + elastic-restrained),
    AERODYNAMIC TOTALS (CL/CMY), AERODYNAMIC DIVERGENCE, the shared DISPLACEMENT
    / BAR FORCE / BAR STRESS blocks, and — when the subcase requests AEROF/APRES —
    an AERODYNAMIC BOX PRESSURES AND FORCES block.
    """
    grid_index = build_grid_index(bulk)
    gids_sorted = sorted(bulk.grids.keys())

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = getattr(case_control, "title", "") or "sbeam SOL 144"

    # Locate the matching subcase to read AEROF/APRES output requests.
    subcase_obj = None
    if hasattr(case_control, "subcases"):
        for sc in case_control.subcases:
            if sc.subcase_id == subcase_id:
                subcase_obj = sc
                break
    want_aero = bool(subcase_obj and (subcase_obj.aerof or subcase_obj.apres))

    # Prescribed vs free labels (prescribed values are fixed on the TRIM card).
    prescribed = set()
    trim_card = bulk.trims.get(result.trim_sid)
    if trim_card is not None:
        prescribed = {k.upper() for k in trim_card.vars.keys()}

    lines = []

    # ---- Header ----
    lines.append(f"1                                                                           {'sbeam':>20}")
    lines.append("                                  SOL 144 STATIC AEROELASTIC RESPONSE")
    lines.append(f"                                          {title}")
    lines.append(f"                                          DATE: {now}")
    lines.append("")
    lines.append(
        f"                           SUBCASE {subcase_id}     TRIM = {result.trim_sid}"
        f"     MACH = {result.mach:.4f}     Q = {_fmt(result.q).strip()}"
    )
    lines.append("")

    # ---- TRIM VARIABLES ----
    lines.append("                                          T R I M   V A R I A B L E S")
    lines.append("")
    lines.append("      LABEL           TYPE             VALUE")
    for label in sorted(result.trim_vars.keys()):
        kind = "PRESCRIBED" if label.upper() in prescribed else "FREE"
        lines.append(f"      {label:<12}    {kind:<12}  {_fmt(result.trim_vars[label])}")
    lines.append("")

    # ---- STABILITY & CONTROL DERIVATIVES (rigid + elastic restrained) ----
    lines.append("                              S T A B I L I T Y   D E R I V A T I V E S")
    lines.append("")
    lines.append("                          --------------- RIGID ---------------    ----- ELASTIC RESTRAINED -----")
    lines.append("      LABEL              CZ            CMY            CX            CY            CZ            CMY")
    for label in sorted(result.trim_vars.keys()):
        rg = result.rigid_derivs.get(label, {})
        el = result.restrained_derivs.get(label, {})
        lines.append(
            f"      {label:<12}  "
            f"{_fmt(rg.get('CZ', 0.0))}{_fmt(rg.get('CMY', 0.0))}"
            f"{_fmt(rg.get('CX', 0.0))}{_fmt(rg.get('CY', 0.0))}"
            f"{_fmt(el.get('CZ', 0.0))}{_fmt(el.get('CMY', 0.0))}"
        )
    lines.append("")

    # ---- HINGE-MOMENT DERIVATIVES (about each AESURF cid1 hinge axis) ----
    if result.hinge_moments:
        lines.append("                          H I N G E   M O M E N T   D E R I V A T I V E S")
        lines.append("")
        lines.append("      (moment about each control's cid1 hinge axis, at the trim dynamic pressure)")
        lines.append("")
        for surf in sorted(result.hinge_moments):
            entry = result.hinge_moments[surf]
            lines.append(f"      SURFACE: {surf}")
            lines.append("        TRIM VARIABLE      d(HM)/d(VAR)")
            for label in sorted(k for k in entry if k != "total"):
                lines.append(f"        {label:<14}{_fmt(result.q * entry[label])}")
            lines.append(f"        {'TOTAL (TRIM)':<14}{_fmt(result.q * entry['total'])}")
            lines.append("")

    # ---- AERODYNAMIC TOTALS ----
    lines.append("                                     A E R O D Y N A M I C   T O T A L S")
    lines.append("")
    lines.append(f"      TOTAL CL = {_fmt(result.total_cl)}        TOTAL CMY = {_fmt(result.total_cm)}")
    lines.append("")

    # ---- AERODYNAMIC DIVERGENCE ----
    lines.append("                                  A E R O D Y N A M I C   D I V E R G E N C E")
    lines.append("")
    if result.q_div is None:
        lines.append("      NO DIVERGENCE FOUND (Q-DIV -> INFINITY)")
    else:
        ratio = result.q / result.q_div if result.q_div else 0.0
        lines.append(
            f"      CRITICAL DIVERGENCE DYNAMIC PRESSURE  Q-DIV = {_fmt(result.q_div)}"
            f"        Q / Q-DIV = {_fmt(ratio)}"
        )
    lines.append("")

    # ---- Shared structural-response blocks ----
    _displacement_block(lines, result.displacements, bulk, grid_index, gids_sorted)
    _bar_forces_block(lines, bulk, result.bar_forces)
    _bar_stresses_block(lines, bulk, result.bar_stresses)

    # ---- AERODYNAMIC BOX PRESSURES AND FORCES (AEROF / APRES) ----
    # BOX ID is the global 1-based box index (= AeroModel box k + 1).
    if want_aero and result.box_forces is not None and result.box_cp is not None:
        lines.append("                      A E R O D Y N A M I C   B O X   P R E S S U R E S   A N D   F O R C E S")
        lines.append("")
        lines.append("      BOX ID         DELTA-CP          FX             FY             FZ")
        for k in range(len(result.box_forces)):
            cp = result.box_cp[k]
            fx, fy, fz = result.box_forces[k]
            lines.append(
                f"{k + 1:>12}  {_fmt(cp)}  {_fmt(fx)}{_fmt(fy)}{_fmt(fz)}"
            )
        lines.append("")

    lines.append("                                       * * * END OF JOB * * *")
    lines.append("")

    return "\n".join(lines) + "\n"


def write_f06_sol101(
    filepath: str,
    case_control,
    bulk: BulkData,
    result: Sol101Result,
    subcase_id: int = 1,
) -> None:
    """Write NASTRAN-style .f06 file for SOL 101 results."""
    with open(filepath, "w") as fh:
        fh.write(_build_f06_sol101_text(case_control, bulk, result, subcase_id))


def write_f06_sol103(
    filepath: str,
    case_control,
    bulk: BulkData,
    result: Sol103Result,
    subcase_id: int = 1,
) -> None:
    """Write NASTRAN-style .f06 file for SOL 103 normal modes results."""
    with open(filepath, "w") as fh:
        fh.write(_build_f06_sol103_text(case_control, bulk, result, subcase_id))


def write_f06_sol144(
    filepath: str,
    case_control,
    bulk: BulkData,
    result: Sol144TrimResult,
    subcase_id: int = 1,
) -> None:
    """Write NASTRAN-style .f06 file for a SOL 144 static aeroelastic trim subcase."""
    with open(filepath, "w") as fh:
        fh.write(_build_f06_sol144_text(case_control, bulk, result, subcase_id))


# Public aliases (R22): callers that need the assembled f06 *text* (main.py CLI,
# viewer) should import these, not the underscore-prefixed names — a rename of the
# private builders would otherwise silently break those cross-module imports.
build_f06_sol101_text = _build_f06_sol101_text
build_f06_sol103_text = _build_f06_sol103_text
build_f06_sol144_text = _build_f06_sol144_text
