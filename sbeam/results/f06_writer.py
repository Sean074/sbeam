"""NASTRAN-style .f06 output writer for SOL 101 and SOL 103 results."""

import math
from datetime import datetime

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import (
    Sol101Result, Sol103Result, Sol144TrimResult, Sol144DivergResult,
)
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


def _monitor_block(lines: list, monitor_loads: dict) -> None:
    """Append a MONITOR POINT INTEGRATED LOADS block (MON4).

    One header row of metadata per monitor (LABEL, TYPE, AXES, CID, reference
    point) followed by the six integrated force/moment components in the
    monitor's cp frame.  Annotated *WHOLE-AIRPLANE* when a symmetry parity factor
    has been applied so downstream consumers do not double-count.
    """
    lines.append("                          M O N I T O R   P O I N T   I N T E G R A T E D   L O A D S")
    lines.append("")
    for name in sorted(monitor_loads.keys()):
        ml = monitor_loads[name]
        tag = "   *WHOLE-AIRPLANE*" if ml.whole_airplane else ""
        lines.append(
            f"      MONITOR {name:<8}  LABEL: {ml.label:<24}  {ml.mtype}"
            f"   AXES = {ml.axes}   CID = {ml.cid}{tag}"
        )
        lines.append(
            f"        REF POINT (BASIC):  X ={_fmt(ml.ref[0])}  Y ={_fmt(ml.ref[1])}"
            f"  Z ={_fmt(ml.ref[2])}"
        )
        lines.append("              FX             FY             FZ             MX             MY             MZ")
        lines.append("        " + "".join(_fmt(v) for v in ml.totals))
        lines.append("")
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
    lines.append(f"      TRIM SOLUTION: {result.trim_mode.upper()}")
    lines.append("")
    lines.append("      LABEL           TYPE             VALUE")
    for label in sorted(result.trim_vars.keys()):
        kind = "PRESCRIBED" if label.upper() in prescribed else "FREE"
        lines.append(f"      {label:<12}    {kind:<12}  {_fmt(result.trim_vars[label])}")
    lines.append("")

    # ---- INJECTED OPERATING POINT (CHORDCP, Step 54) ----
    if result.chordcp_echo:
        echo = result.chordcp_echo
        a_rad = echo['alpha_ref']
        lines.append("                          I N J E C T E D   O P E R A T I N G   P O I N T   (CHORDCP)")
        lines.append("")
        mach_str = (", ".join(f"{m:.4f}" for m in echo['data_machs'])
                    if echo['data_machs'] else "NOT STATED")
        lines.append(
            f"      ALPHREF = {a_rad:.6f} RAD ({math.degrees(a_rad):.4f} DEG)"
            f"     DATA MACH = {mach_str}"
        )
        lines.append("")
        lines.append("      CAERO1          FZ/Q INJECTED    MY/Q INJECTED   FZ/Q VLM FLAT-PLATE")
        tot_fz = tot_my = tot_vlm = 0.0
        for eid in sorted(echo['surfaces']):
            s = echo['surfaces'][eid]
            tot_fz  += s['FZ_Q']
            tot_my  += s['MY_Q']
            tot_vlm += s['FZ_Q_VLM']
            lines.append(
                f"      {eid:<12}  {_fmt(s['FZ_Q'])}  {_fmt(s['MY_Q'])}  {_fmt(s['FZ_Q_VLM'])}"
            )
        lines.append(
            f"      {'TOTAL':<12}  {_fmt(tot_fz)}  {_fmt(tot_my)}  {_fmt(tot_vlm)}"
        )
        lines.append("")

    # ---- STABILITY & CONTROL DERIVATIVES (rigid + restrained + unrestrained) ----
    unrest = result.unrestrained_derivs or {}
    lines.append("                              S T A B I L I T Y   D E R I V A T I V E S")
    lines.append("")
    lines.append("                          --------------- RIGID ---------------    ----- ELASTIC RESTRAINED -----    ---- ELASTIC UNRESTRAINED ----")
    lines.append("      LABEL              CZ            CMY            CX            CY            CZ            CMY            CZ            CMY")
    for label in sorted(result.trim_vars.keys()):
        rg = result.rigid_derivs.get(label, {})
        el = result.restrained_derivs.get(label, {})
        un = unrest.get(label)
        # URDD acceleration columns have no unrestrained entry (they are the
        # mean-axis ü_r unknowns); print N/A there.
        un_cz = _fmt(un['CZ']) if un else "          N/A"
        un_cm = _fmt(un['CMY']) if un else "          N/A"
        lines.append(
            f"      {label:<12}  "
            f"{_fmt(rg.get('CZ', 0.0))}{_fmt(rg.get('CMY', 0.0))}"
            f"{_fmt(rg.get('CX', 0.0))}{_fmt(rg.get('CY', 0.0))}"
            f"{_fmt(el.get('CZ', 0.0))}{_fmt(el.get('CMY', 0.0))}"
            f"{un_cz}{un_cm}"
        )
    lines.append("")
    if result.unrestrained_intercepts:
        ic = result.unrestrained_intercepts
        lines.append(
            f"      UNRESTRAINED INTERCEPTS (W2GJ BASELINE):   "
            f"CZ0 ={_fmt(ic.get('CZ0', 0.0))}    CMY0 ={_fmt(ic.get('CMY0', 0.0))}"
        )
        lines.append("")

    # ---- LATERAL / DIRECTIONAL DERIVATIVES (roll/yaw moments, Step 52) ----
    # CMX = rolling-moment coeff (C_lp from ROLL, C_lβ from SIDES); CMZ = yawing-
    # moment coeff (C_nr from YAW).  Both about the AERO reference, /(S_ref·b_ref).
    lines.append("                    L A T E R A L / D I R E C T I O N A L   D E R I V A T I V E S")
    lines.append("")
    lines.append("                          ------- RIGID -------    -- ELASTIC RESTRAINED --")
    lines.append("      LABEL              CMX           CMZ            CMX           CMZ")
    for label in sorted(result.trim_vars.keys()):
        rg = result.rigid_derivs.get(label, {})
        el = result.restrained_derivs.get(label, {})
        lines.append(
            f"      {label:<12}  "
            f"{_fmt(rg.get('CMX', 0.0))}{_fmt(rg.get('CMZ', 0.0))}"
            f"{_fmt(el.get('CMX', 0.0))}{_fmt(el.get('CMZ', 0.0))}"
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
    # CZ is the body-axis vertical-force coefficient (balances weight at trim);
    # CL is the genuine wind-axis lift (⊥ to U∞) = CZ·cosα − CX·sinα at trim α.
    lines.append(
        f"      TOTAL CZ (BODY) = {_fmt(result.total_cl)}        "
        f"TOTAL CL (WIND) = {_fmt(result.total_cl_wind)}"
    )
    lines.append(
        f"      TOTAL CX (BODY) = {_fmt(result.total_cx)}        "
        f"TOTAL CY (BODY) = {_fmt(getattr(result, 'total_cy', 0.0))}"
    )
    lines.append(
        f"      TOTAL CMX (ROLL) = {_fmt(getattr(result, 'total_cmx', 0.0))}       "
        f"TOTAL CMY = {_fmt(result.total_cm)}       "
        f"TOTAL CMZ (YAW) = {_fmt(getattr(result, 'total_cmz', 0.0))}"
    )
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

    # ---- MONITOR POINT INTEGRATED LOADS (MON4) ----
    if result.monitor_loads:
        _monitor_block(lines, result.monitor_loads)

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


def _build_f06_sol144_diverg_text(
    case_control,
    bulk: BulkData,
    result: Sol144DivergResult,
    subcase_id: int = 1,
) -> str:
    """Return a SOL 144 DIVERG-card divergence sweep .f06 block (Step 55).

    One AERODYNAMIC DIVERGENCE table per Mach (root no., Q-DIV, V-DIV) followed by
    the max-abs-normalised divergence mode shape for each root.
    """
    grid_index = build_grid_index(bulk)
    gids_sorted = sorted(bulk.grids.keys())

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = getattr(case_control, "title", "") or "sbeam SOL 144"

    lines = []
    lines.append(f"1    {title}")
    lines.append(f"     SOL 144 AEROELASTIC DIVERGENCE   SUBCASE {subcase_id}   {now}")
    lines.append("")

    has_v = result.rhoref > 0.0
    for mr in result.mach_results:
        lines.append(
            "                                  A E R O D Y N A M I C   D I V E R G E N C E"
        )
        lines.append(f"      MACH = {_fmt(mr.mach)}        REF DENSITY (RHOREF) = {_fmt(result.rhoref)}")
        lines.append("")
        if not mr.roots:
            lines.append("      NO DIVERGENCE FOUND (NO POSITIVE REAL ROOT)")
            lines.append("")
            continue
        header = "      ROOT NO.        Q-DIV"
        if has_v:
            header += "          V-DIV"
        lines.append(header)
        for i, root in enumerate(mr.roots, start=1):
            row = f"{i:>14}  {_fmt(root.q_div)}"
            if has_v:
                row += f"{_fmt(root.v_div)}"
            lines.append(row)
        lines.append("")

        # Divergence mode shape(s) — max-abs normalised g-set eigenvector.
        for i, root in enumerate(mr.roots, start=1):
            if root.mode_shape is None:
                continue
            lines.append(
                f"                        D I V E R G E N C E   M O D E   S H A P E   "
                f"( ROOT {i}, Q-DIV = {_fmt(root.q_div)} )"
            )
            lines.append("")
            lines.append(
                "      POINT ID.   TYPE          T1             T2             T3             R1             R2             R3"
            )
            for gid in gids_sorted:
                base = 6 * grid_index[gid]
                t = root.mode_shape[base:base+3]
                r = root.mode_shape[base+3:base+6]
                t, r = _transform_to_cd(t, r, gid, bulk)
                lines.append(
                    f"{gid:>14}     G  {_fmt(t[0])}{_fmt(t[1])}{_fmt(t[2])}{_fmt(r[0])}{_fmt(r[1])}{_fmt(r[2])}"
                )
            lines.append("")

    return "\n".join(lines) + "\n"


def _build_f06_sol144_maneuver_text(
    case_control,
    bulk: BulkData,
    result,
    subcase_id: int = 1,
) -> str:
    """Return a SOL 144 transient maneuver loads .f06 block (Phase G0, AC5).

    Blocks: run summary (MLOADS/MLDTRIM sids, q, Mach, sample count, critical
    sample), a per-output-time MANEUVER TIME HISTORY table (trim variables,
    aero Fz/My, peak |net| grid force), and the critical-sample detail — net
    load closure resultant plus the shared DISPLACEMENT / BAR FORCE blocks.
    The full per-sample field output stays in the MLDPRNT ASCII export.
    """
    grid_index = build_grid_index(bulk)
    gids_sorted = sorted(bulk.grids.keys())

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = getattr(case_control, "title", "") or "sbeam SOL 144"

    lines = []
    lines.append(f"1    {title}")
    lines.append(
        f"     SOL 144 TRANSIENT MANEUVER LOADS (QUASI-STEADY)   "
        f"SUBCASE {subcase_id}   {now}"
    )
    lines.append("")
    lines.append(
        f"                           SUBCASE {subcase_id}     MLOADS = {result.mloads_sid}"
        f"     TRIM = {result.trim_sid}     MACH = {result.mach:.4f}"
        f"     Q = {_fmt(result.q).strip()}"
    )
    lines.append("")

    if not result.steps:
        lines.append("      NO OUTPUT SAMPLES")
        lines.append("")
        lines.append("                                       * * * END OF JOB * * *")
        lines.append("")
        return "\n".join(lines) + "\n"

    crit = result.steps[result.crit_index]
    lines.append(
        f"      OUTPUT SAMPLES = {len(result.steps)}        CRITICAL SAMPLE = "
        f"{result.crit_index + 1} (T = {_fmt(crit.t).strip()}, PEAK |NET FORCE|)"
    )
    lines.append("")

    # ---- MANEUVER TIME HISTORY ----
    labels = [l for l in result.labels if l in result.steps[0].trim_vars]
    lines.append("                              M A N E U V E R   T I M E   H I S T O R Y")
    lines.append("")
    header = "      SAMPLE           T"
    for label in labels:
        header += f"  {label:>13}"
    header += "        FZ-AERO        MY-AERO     MAX |NET F|"
    lines.append(header)
    for i, step in enumerate(result.steps):
        net_f = np.abs(step.net_loads).max() if step.net_loads is not None else 0.0
        row = f"{i + 1:>12}{_fmt(step.t)}"
        for label in labels:
            row += _fmt(step.trim_vars.get(label, 0.0))
        row += f"{_fmt(step.Fz_aero)}{_fmt(step.My_aero)}{_fmt(net_f)}"
        crit_mark = "  <-- CRITICAL" if i == result.crit_index else ""
        lines.append(row + crit_mark)
    lines.append("")

    # ---- Critical-sample detail ----
    lines.append(
        f"                    C R I T I C A L   S A M P L E   D E T A I L   "
        f"( SAMPLE {result.crit_index + 1}, T = {_fmt(crit.t).strip()} )"
    )
    lines.append("")
    c = crit.closure
    lines.append("      NET (AERO + INERTIAL) LOAD CLOSURE RESULTANT ABOUT THE MOMENT REFERENCE")
    lines.append(
        f"      FX ={_fmt(c[0])}   FY ={_fmt(c[1])}   FZ ={_fmt(c[2])}"
        f"   MX ={_fmt(c[3])}   MY ={_fmt(c[4])}   MZ ={_fmt(c[5])}"
    )
    lines.append("")

    _displacement_block(lines, crit.displacements, bulk, grid_index, gids_sorted)
    _bar_forces_block(lines, bulk, crit.bar_forces)

    lines.append("                                       * * * END OF JOB * * *")
    lines.append("")

    return "\n".join(lines) + "\n"


# Public aliases (R22): callers that need the assembled f06 *text* (main.py CLI,
# viewer) should import these, not the underscore-prefixed names — a rename of the
# private builders would otherwise silently break those cross-module imports.
build_f06_sol101_text = _build_f06_sol101_text
build_f06_sol103_text = _build_f06_sol103_text
build_f06_sol144_text = _build_f06_sol144_text
build_f06_sol144_diverg_text = _build_f06_sol144_diverg_text
build_f06_sol144_maneuver_text = _build_f06_sol144_maneuver_text
