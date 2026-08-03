"""SOL 144 static aeroelastic trim solver (Step 52+).

Solves the trimmed static aeroelastic problem — free trim variables
(ANGLEA/PITCH/URDD*/AESURF deltas) balanced through the SUPORT Schur
partition — plus stability derivatives, divergence, flight/maneuver loads
and monitor outputs.

Matrix chain (theory docs/20_theory/01_aeroelastics_theory.md Eq. 2, 22a):
    Q_aa  = G_disp^T  S_kj  (A_jj*)^-1  D_jk  G_slope       (n_g, n_g)
    f_g   = G_disp^T  S_kj  (A_jj*)^-1  w_g                  (n_g,)

Public API:
    run_sol144_trim(bulk, subcase, aero, aero_cache)
    run_sol144_diverg(bulk, subcase, aero, aero_cache)
    AeroCache

The Step-50 no-trim reference path (``run_aeroelastic_static``) lives in
``sol144_static.py`` and is re-exported here.
"""

import warnings
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness, get_spc_dofs
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.reduction import reduce_to_aset, expand_to_g
from sbeam.assembly.coord_transform import get_transform
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.aero.aero_model import AeroModel
from sbeam.aero.coupling import build_qaa, build_fg
from sbeam.aero.integration import build_djx, build_djk
from sbeam.results.results import Sol144TrimResult
from sbeam.results.monitor_points import compute_monitor_loads
from sbeam.results.section_cuts import compute_section_cuts
from sbeam.solver.sol101 import recover_bar_forces, recover_bar_stresses, recover_reactions
from sbeam.types import FloatArray, LuFactor
from sbeam.model.aero import require_aeros

# Facade re-exports (P13/DEF-R1/R3) — the split modules; every name stays
# importable from its historic home here.  Import order follows the dependency
# layering (util has no sol144-internal imports; derivs/diverg import util).
from sbeam.solver.sol144_util import (  # noqa: F401
    AeroCache, urdd_rcsid_to_basic, urdd_basic_to_rcsid, load_resultant,
    build_inertial_cols, get_suport_local, pitch_moment, aero_moment_resultant,
    URDD_DOF,
)
from sbeam.solver.sol144_trim_solve import (  # noqa: F401
    build_trim_schur, recover_u_a,
    solve_trim_determined, solve_trim_overdetermined,
)
from sbeam.solver.sol144_derivs import (  # noqa: F401
    compute_rigid_derivs, compute_hinge_moments,
    compute_restrained_derivs, compute_unrestrained_derivs,
)
from sbeam.solver.sol144_diverg import (  # noqa: F401
    run_sol144_diverg, divergence_dynamic_pressure, divergence_roots,
)
from sbeam.solver.sol144_static import (  # noqa: F401
    run_aeroelastic_static, build_qaa_aset, solve_direct,
    solve_rom, mode_acceleration_recovery,
)

# Backwards-compatible aliases for the historic underscore-private names.  The
# helpers became the split modules' public API (P13 lint pass), but tests and
# studies still import the old names from here (e.g. test_step50_qaa,
# test_modal_basis, test_ae11_hinge, test_step55_diverg) — keep both bound.
_URDD_DOF = URDD_DOF
_build_trim_schur = build_trim_schur
_recover_u_a = recover_u_a
_solve_trim_determined = solve_trim_determined
_solve_trim_overdetermined = solve_trim_overdetermined
_compute_hinge_moments = compute_hinge_moments
_compute_restrained_derivs = compute_restrained_derivs
_compute_unrestrained_derivs = compute_unrestrained_derivs
_divergence_dynamic_pressure = divergence_dynamic_pressure
_divergence_roots = divergence_roots
_build_qaa_aset = build_qaa_aset
_solve_direct = solve_direct
_solve_rom = solve_rom
_mode_acceleration_recovery = mode_acceleration_recovery

#: The facade surface: everything importable from this module by design —
#: the trim entry point, the split modules' public API, and the historic
#: underscore aliases still pinned by tests.
__all__ = [
    "run_sol144_trim",
    # sol144_util
    "AeroCache", "urdd_rcsid_to_basic", "urdd_basic_to_rcsid", "load_resultant",
    "build_inertial_cols", "get_suport_local", "pitch_moment",
    "aero_moment_resultant", "URDD_DOF",
    # sol144_trim_solve
    "build_trim_schur", "recover_u_a",
    "solve_trim_determined", "solve_trim_overdetermined",
    # sol144_derivs
    "compute_rigid_derivs", "compute_hinge_moments",
    "compute_restrained_derivs", "compute_unrestrained_derivs",
    # sol144_diverg
    "run_sol144_diverg", "divergence_dynamic_pressure", "divergence_roots",
    # sol144_static
    "run_aeroelastic_static", "build_qaa_aset", "solve_direct",
    "solve_rom", "mode_acceleration_recovery",
    # historic underscore aliases (test-pinned)
    "_URDD_DOF", "_build_trim_schur", "_recover_u_a",
    "_solve_trim_determined", "_solve_trim_overdetermined",
    "_compute_hinge_moments", "_compute_restrained_derivs",
    "_compute_unrestrained_derivs", "_divergence_dynamic_pressure",
    "_divergence_roots", "_build_qaa_aset", "_solve_direct",
    "_solve_rom", "_mode_acceleration_recovery",
]


# ---------------------------------------------------------------------------
# Step 52 — SOL 144 Trim Solver
# ---------------------------------------------------------------------------

def _build_injection_echo(
    aero: AeroModel,
    box_forces: FloatArray,
    ref_point: FloatArray,
    grid_index: dict[int, int],
    free_dofs: list[int],
) -> list[dict[str, Any]]:
    """Summarise the Step 64 load injections for the f06 (and warn on dead ends).

    For each group of structurally-uncoupled boxes (SPLINE0 body panels,
    un-splined boxes) report the master grid, the box count and the physical
    6-component resultant about ``ref_point`` that the injection puts into the
    trim balance and the load export.

    Warns when the master grid's translations are all constrained: the injected
    load is then removed by the a-set reduction and reappears as an SPC
    reaction rather than trimming the aircraft.

    Returns [] when no injection is active, so decks without body panels get a
    byte-identical f06.
    """
    echo: list[dict[str, Any]] = []
    free = set(free_dofs)
    for inj in aero.load_injections:
        idx = inj.boxes
        forces = box_forces[idx]
        sub_boxes = [aero.boxes[k] for k in idx]
        f_tot = forces.sum(axis=0)
        m_tot = aero_moment_resultant(forces, sub_boxes, ref_point)
        col = 6 * grid_index[inj.master_grid]
        if not any((col + d) in free for d in range(3)):
            warnings.warn(
                f"{inj.source}: master GRID {inj.master_grid} has all three "
                "translations constrained — the injected aerodynamic load "
                f"(F={f_tot}) is carried by the constraint, not by the trim.",
                UserWarning,
            )
        echo.append({
            'source':      inj.source,
            'master_grid': inj.master_grid,
            'n_boxes':     len(idx),
            'force':       f_tot,
            'moment':      m_tot,
        })
    return echo




# KC7: the injected CHORDCP mean flow is only valid as a perturbation base near
# its reference AOA — the trim warns when the trimmed AOA strays further than
# this from it (~2 degrees).
_CHORDCP_ALPHA_TOL = 0.035  # rad


@dataclass
class _TrimState:
    """Mutable dataflow context threaded through the run_sol144_trim stages.

    Each ``_stage_*`` helper reads the fields written by the stages before it
    and writes its own outputs back; ``run_sol144_trim`` owns the calling
    order.  Fields appear in the order the stages produce them.
    """

    # Inputs
    bulk: BulkData
    subcase: SubcaseControl
    aero: AeroModel
    aero_cache: Optional[AeroCache]

    # Stage-produced fields are declared ``field(init=False)`` with no default:
    # they do not exist until their stage writes them, so a premature read
    # fails loudly (AttributeError) instead of silently passing None around,
    # and the declared types stay non-Optional.  ``Optional[...]`` below marks
    # only the fields for which None is a genuine runtime value.

    # _stage_validate_inputs
    trim_sid: int = field(init=False)
    trim_card: Any = field(init=False)
    q_dyn: float = field(init=False)

    # _stage_resolve_massset_and_mach
    massset_sid: Optional[int] = field(init=False)
    mass_case_label: str = field(init=False)
    mass_case_gpwg: Any = field(init=False)
    grid_index: dict[int, int] = field(init=False)
    spc_sid: Optional[int] = field(init=False)
    mach: float = field(init=False)

    # _stage_build_labels
    all_labels: list[str] = field(init=False)
    chordcp_alpha_ref: Optional[float] = field(init=False)
    prescribed_dict: dict[str, float] = field(init=False)
    free_labels: list[str] = field(init=False)

    # _stage_resolve_ref_geometry
    aeros: Any = field(init=False)
    x_ref: float = field(init=False)
    R_rcsid: FloatArray = field(init=False)
    suport_pos: FloatArray = field(init=False)

    # _stage_echo_chordcp
    chordcp_echo: Optional[dict[str, Any]] = field(init=False)

    # _stage_build_downwash_and_reduce
    D_jx: FloatArray = field(init=False)
    red: Any = field(init=False)
    T: Any = field(init=False)
    free_local: list[int] = field(init=False)
    free_dofs: list[int] = field(init=False)
    red_dofs: Any = field(init=False)
    Q_ax_a: FloatArray = field(init=False)
    K_gg: Any = field(init=False)
    K_aa: FloatArray = field(init=False)
    Q_aa: FloatArray = field(init=False)
    f_aero_g: FloatArray = field(init=False)
    label_to_col: dict[str, int] = field(init=False)
    pres_values_basic: FloatArray = field(init=False)
    M_gg: Any = field(init=False)
    M_ax_g: FloatArray = field(init=False)
    f_rhs_a: FloatArray = field(init=False)
    M_ax_a: FloatArray = field(init=False)
    suport_local: list[int] = field(init=False)
    over_determined: bool = field(init=False)
    n_free: int = field(init=False)
    n_suport: int = field(init=False)
    free_label_cols: list[int] = field(init=False)

    # _stage_solve_trim
    u_a: FloatArray = field(init=False)
    delta_free_arr: FloatArray = field(init=False)
    K_ll_lu: LuFactor = field(init=False)
    l_idx: list[int] = field(init=False)
    r_idx: list[int] = field(init=False)
    trim_mode: str = field(init=False)
    trim_vars: dict[str, float] = field(init=False)
    delta_all: FloatArray = field(init=False)

    # _stage_recover_displacements
    displacements: FloatArray = field(init=False)
    bar_forces: dict[int, Any] = field(init=False)
    bar_stresses: dict[int, Any] = field(init=False)

    # _stage_compute_derivs
    rigid_derivs: dict[str, dict[str, float]] = field(init=False)
    rest_derivs: dict[str, dict[str, float]] = field(init=False)
    unrest_derivs: Any = field(init=False)
    unrest_intercepts: Any = field(init=False)

    # _stage_compute_totals
    gamma: FloatArray = field(init=False)
    f_box_vec: FloatArray = field(init=False)
    total_cl: float = field(init=False)
    total_cm: float = field(init=False)
    total_cx: float = field(init=False)
    total_cl_wind: float = field(init=False)
    total_cy: float = field(init=False)
    total_cmx: float = field(init=False)
    total_cmz: float = field(init=False)
    hinge_moments: Any = field(init=False)

    # _stage_flight_and_net_loads
    box_forces: FloatArray = field(init=False)
    box_cp: FloatArray = field(init=False)
    grid_loads: FloatArray = field(init=False)
    load_injection_echo: list[dict[str, Any]] = field(init=False)
    inertial_loads: FloatArray = field(init=False)
    net_loads: FloatArray = field(init=False)
    maneuver_closure: FloatArray = field(init=False)
    q_div: Optional[float] = field(init=False)

    # _stage_monitor_outputs
    monitor_loads: Any = field(init=False)
    section_loads: Any = field(init=False)


def _stage_validate_inputs(st: _TrimState) -> None:
    """SUPORT/TRIM presence + DEF-M4 LOAD refusal; picks up the TRIM card."""
    bulk, subcase = st.bulk, st.subcase

    if not bulk.supports:
        raise ValueError("run_sol144_trim: no SUPORT card found in model")

    trim_sid = subcase.trim_sid
    if trim_sid is None or trim_sid not in bulk.trims:
        raise ValueError(f"run_sol144_trim: TRIM SID {trim_sid} not found")

    # DEF-M4 — the trim RHS is aero + inertia only; it has no f_struct term, so a
    # LOAD request here would be read, discarded and never mentioned.  Refuse it
    # rather than silently solving a different problem than the deck asked for.
    if subcase.load_sid is not None:
        raise ValueError(
            f"run_sol144_trim: subcase {subcase.subcase_id} requests both "
            f"TRIM={trim_sid} and LOAD={subcase.load_sid}, but SOL 144 trim "
            "applies aerodynamic and inertial loads only — the LOAD would be "
            "silently ignored.  Remove the LOAD request, or use the restrained "
            "static path (run_aeroelastic_static), which does combine a LOAD "
            "set with the aero load."
        )

    trim_card = bulk.trims[trim_sid]
    q_dyn  = trim_card.q

    st.trim_sid, st.trim_card, st.q_dyn = trim_sid, trim_card, q_dyn


def _stage_resolve_massset_and_mach(st: _TrimState) -> None:
    """MASSSET mass case (Step 60) + flight-Mach / AeroCache resolution (AE9)."""
    bulk, subcase, aero, aero_cache = st.bulk, st.subcase, st.aero, st.aero_cache
    trim_card = st.trim_card

    # ------------------------------------------------------------------ #
    # Mass case (Step 60) — MASSSET payload configuration for this subcase
    # ------------------------------------------------------------------ #
    # Every mass-derived operator below (M_ax, M_aa, GPWG) is built for this
    # case; nothing else changes.  The AIC, splines and the whole AeroCache are
    # geometry/Mach-only and are reused across mass cases untouched — a MASSSET
    # sweep must never invalidate the aero cache.
    from sbeam.gpwg import compute_gpwg
    from sbeam.model.mass_overlay import resolve_mass_case
    massset_sid = subcase.massset_sid
    mass_case_label = resolve_mass_case(bulk, massset_sid).label
    mass_case_gpwg = compute_gpwg(bulk, massset_sid)

    grid_index = build_grid_index(bulk)
    spc_sid = subcase.spc_sid

    # ------------------------------------------------------------------ #
    # Resolve the flight Mach for this subcase (AE9)
    # ------------------------------------------------------------------ #
    # The AIC is Mach-dependent (Prandtl–Glauert β scaling), so the flight Mach
    # comes from the TRIM card.  AEROS.mach is the fallback when the TRIM field is
    # unset (0.0); a genuine disagreement is warned about.  A supersonic Mach is
    # rejected by build_aero_model / AeroCache (steady subsonic VLM only).
    aeros_mach = require_aeros(bulk).mach if bulk.aeros else 0.0
    mach = trim_card.mach if trim_card.mach else aeros_mach
    if trim_card.mach and aeros_mach and abs(trim_card.mach - aeros_mach) > 1e-9:
        warnings.warn(
            f"run_sol144_trim: TRIM Mach {trim_card.mach} disagrees with AEROS "
            f"Mach {aeros_mach}; using the TRIM Mach {trim_card.mach} for the AIC.",
            UserWarning,
        )

    if aero_cache is None:
        aero_cache = AeroCache(bulk, grid_index, seed=aero)
    aero = aero_cache.get(mach)

    st.massset_sid, st.mass_case_label, st.mass_case_gpwg = (
        massset_sid, mass_case_label, mass_case_gpwg)
    st.grid_index, st.spc_sid = grid_index, spc_sid
    st.mach, st.aero, st.aero_cache = mach, aero, aero_cache


def _stage_build_labels(st: _TrimState) -> None:
    """AESTAT+AESURF label assembly, CHORDCP validation (KC7), free/prescribed split."""
    bulk, aero, mach, trim_card = st.bulk, st.aero, st.mach, st.trim_card

    # ------------------------------------------------------------------ #
    # All labels (AESTAT + AESURF), sorted consistently
    # ------------------------------------------------------------------ #
    all_labels = sorted(
        [a.label for a in bulk.aestats.values()]
        + [s.label for s in bulk.aesurfs.values()]
    )

    # ------------------------------------------------------------------ #
    # CHORDCP injection validation (Step 54, KC7)
    # ------------------------------------------------------------------ #
    chordcp_alpha_ref = aero.chordcp_alpha_ref
    if chordcp_alpha_ref is not None:
        if abs(chordcp_alpha_ref) > 0.0 and "ANGLEA" not in all_labels:
            raise ValueError(
                "CHORDCP injection with a nonzero ALPHREF requires an ANGLEA "
                "AESTAT label (the injected operating point is re-referenced "
                "through the angle-of-attack normalwash column)."
            )
        card_machs = sorted({c.mach for c in bulk.chordcps.values() if c.mach})
        if card_machs and any(abs(m - mach) > 1e-9 for m in card_machs):
            warnings.warn(
                f"run_sol144_trim: CHORDCP data Mach {card_machs} disagrees with "
                f"the flight Mach {mach}; the injected pressures were measured at "
                "a different operating point (KC7).",
                UserWarning,
            )

    # Separate free (to solve for) vs prescribed (given in TRIM card)
    prescribed_dict = {k.upper(): v for k, v in trim_card.vars.items()}
    free_labels   = [l for l in all_labels if l not in prescribed_dict]

    st.all_labels, st.chordcp_alpha_ref = all_labels, chordcp_alpha_ref
    st.prescribed_dict, st.free_labels = prescribed_dict, free_labels


def _stage_resolve_ref_geometry(st: _TrimState) -> None:
    """Moment reference point + RCSID rotation matrix for the URDD transform."""
    bulk = st.bulk

    # ------------------------------------------------------------------ #
    # Reference geometry + RCSID rotation matrix for URDD transform
    # ------------------------------------------------------------------ #
    aeros = require_aeros(bulk)
    if aeros.rcsid:
        x_ref_pt, R_rcsid = get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref    = float(x_ref_pt[0])
        suport_pos = x_ref_pt          # RCSID origin = moment reference
    else:
        x_ref    = 0.0
        R_rcsid  = np.eye(3)
        suport_pos = np.zeros(3)

    st.aeros, st.x_ref, st.R_rcsid, st.suport_pos = aeros, x_ref, R_rcsid, suport_pos


def _stage_echo_chordcp(st: _TrimState) -> None:
    """CHORDCP injected-operating-point echo (Step 54, KC7 visibility)."""
    bulk, aero = st.bulk, st.aero
    chordcp_alpha_ref, x_ref = st.chordcp_alpha_ref, st.x_ref

    # ------------------------------------------------------------------ #
    # CHORDCP injected-operating-point echo (Step 54) — per-surface integrals
    # of the supplied Cp, plus the VLM flat-plate lift at the same ALPHREF as
    # a plausibility reference for the f06 block (KC7 visibility).
    # ------------------------------------------------------------------ #
    chordcp_echo = None
    if chordcp_alpha_ref is not None:
        n_z_all = np.array([b.normal[2] for b in aero.boxes])
        cp_flat = aero.ajj_inv_corr @ (-n_z_all * chordcp_alpha_ref)
        surfaces: dict[int, dict[str, float]] = {}
        for card in sorted(bulk.chordcps.values(), key=lambda c: c.caero_eid):
            idxs = np.array([j for j, b in enumerate(aero.boxes)
                             if b.caero_eid == card.caero_eid])
            cp   = np.asarray(card.data, dtype=float)
            area = np.array([aero.boxes[j].area for j in idxs])
            nz   = n_z_all[idxs]
            xfp  = np.array([aero.boxes[j].force_point[0] for j in idxs])
            surfaces[card.caero_eid] = {
                'FZ_Q':     float((cp * area * nz).sum()),
                'MY_Q':     float(-(cp * area * nz * (xfp - x_ref)).sum()),
                'FZ_Q_VLM': float((cp_flat[idxs] * area * nz).sum()),
            }
        chordcp_echo = {
            'alpha_ref':  chordcp_alpha_ref,
            'data_machs': sorted({c.mach for c in bulk.chordcps.values() if c.mach}),
            'surfaces':   surfaces,
        }

    st.chordcp_echo = chordcp_echo


def _stage_build_downwash_and_reduce(st: _TrimState) -> None:
    """D_jx/Q_ax on the g-set, a-set reduction, RHS assembly, SUPORT indexing."""
    bulk, aero = st.bulk, st.aero
    grid_index, spc_sid, q_dyn = st.grid_index, st.spc_sid, st.q_dyn
    all_labels, prescribed_dict, free_labels = (
        st.all_labels, st.prescribed_dict, st.free_labels)
    aeros, R_rcsid, suport_pos = st.aeros, st.R_rcsid, st.suport_pos
    massset_sid = st.massset_sid

    # ------------------------------------------------------------------ #
    # Build D_jx and Q_ax on the g-set
    # ------------------------------------------------------------------ #
    # Full-span model: aero and inertia are both whole-airplane, so there is no
    # symmetry force-doubling factor (the AE1 Step D `sym=2` double-count that
    # halved the trim solution is gone with half-span support).
    D_jx = build_djx(aero.boxes, all_labels, bulk,
                     id_to_k=aero.require_box_id_to_k())   # (n_box, n_labels)
    Q_ax_g = aero.require_g_load().T @ aero.skj @ aero.ajj_inv_corr @ D_jx  # (n_g, n_labels)

    # ------------------------------------------------------------------ #
    # A-set partition (SPC + RBE3 reduction)
    # ------------------------------------------------------------------ #
    red = reduce_to_aset(bulk, grid_index, spc_sid)
    T, free_local, free_dofs = red.T, red.free_local, red.free_dofs
    red_dofs = red.red_dofs

    # Reduce Q_ax and structural stiffness to a-set
    Q_ax_a = red.reduce_rect(Q_ax_g)               # (n_a, n_labels)

    K_gg = assemble_global_stiffness(bulk)
    K_aa = red.reduce_matrix(K_gg, dense=True)     # (n_a, n_a)

    # Also compute Q_aa for storage in result
    Q_gg = build_qaa(aero, aero.require_g_load(), aero.require_g_slope())
    Q_aa = red.reduce_matrix(Q_gg)

    # ------------------------------------------------------------------ #
    # Build combined RHS: q*f_g (baseline aero) + inertial load
    # ------------------------------------------------------------------ #
    f_aero_g = q_dyn * build_fg(aero, aero.require_g_load())   # (n_g,) baseline aero (whole-airplane)

    # Aerodynamic contribution of prescribed trim variables (URDD cols = 0)
    label_to_col = {l: i for i, l in enumerate(all_labels)}
    pres_values = np.array([prescribed_dict.get(l, 0.0) for l in all_labels])
    pres_aero_g = q_dyn * Q_ax_g @ pres_values       # (n_g,)

    # Transform prescribed URDD values from RCSID frame to basic frame (AE5).
    # pres_values_basic is used only for the inertial path; prescribed_dict
    # is preserved in RCSID-frame form so trim_vars output matches the input card.
    pres_values_basic = urdd_rcsid_to_basic(
        pres_values, label_to_col, R_rcsid, bool(aeros.rcsid)
    )

    # Mass matrix for this mass case.  Assembled once here and reused by both
    # M_ax (below) and the unrestrained-derivative block further down — one mass
    # model for the whole subcase, by construction (Q4 / DEF-M3).
    M_gg = assemble_global_mass(bulk, massset_sid)

    # Inertial sensitivity matrix (basic frame); prescribed inertial RHS (AE7).
    # M_ax_g[:, col] = dF/dURDD_col = -M_gg @ phi_r; zero for non-URDD labels.
    M_ax_g = build_inertial_cols(
        bulk, all_labels, grid_index, suport_pos, massset_sid, M_gg=M_gg)
    pres_inertial_g = M_ax_g @ pres_values_basic     # (n_g,) — free URDD entry = 0

    f_rhs_g = f_aero_g + pres_aero_g + pres_inertial_g  # (n_g,)

    # Reduce f_rhs to a-set
    f_rhs_a = red.reduce_vector(f_rhs_g)   # (n_a,)

    # Reduce M_ax to a-set (same RBE3+SPC path as Q_ax)
    M_ax_a = red.reduce_rect(M_ax_g)       # (n_a, n_labels)

    # ------------------------------------------------------------------ #
    # SUPORT DOF indices in a-set
    # ------------------------------------------------------------------ #
    suport_local = get_suport_local(bulk, free_dofs, grid_index)
    n_suport = len(suport_local)
    n_free   = len(free_labels)

    over_determined = n_free > n_suport
    if n_free < n_suport:
        raise ValueError(
            f"Under-determined trim (n_free={n_free} < n_suport={n_suport}): "
            "more SUPORT DOFs than free variables."
        )
    if n_free == 0:
        raise ValueError("run_sol144_trim: no free trim variables — all labels prescribed.")

    # ------------------------------------------------------------------ #
    # Map free labels to column indices in Q_ax_a
    # ------------------------------------------------------------------ #
    free_label_cols = [label_to_col[l] for l in free_labels]

    st.D_jx, st.red = D_jx, red
    st.T, st.free_local, st.free_dofs, st.red_dofs = T, free_local, free_dofs, red_dofs
    st.Q_ax_a, st.K_gg, st.K_aa, st.Q_aa = Q_ax_a, K_gg, K_aa, Q_aa
    st.f_aero_g, st.label_to_col = f_aero_g, label_to_col
    st.pres_values_basic, st.M_gg, st.M_ax_g = pres_values_basic, M_gg, M_ax_g
    st.f_rhs_a, st.M_ax_a = f_rhs_a, M_ax_a
    st.suport_local, st.over_determined = suport_local, over_determined
    st.n_free, st.n_suport, st.free_label_cols = n_free, n_suport, free_label_cols


def _stage_solve_trim(st: _TrimState) -> None:
    """Schur trim solve (determined / over-determined), trim-variable assembly."""
    bulk, subcase = st.bulk, st.subcase
    K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a = (
        st.K_aa, st.Q_aa, st.Q_ax_a, st.M_ax_a, st.f_rhs_a)
    q_dyn, suport_local, free_label_cols = st.q_dyn, st.suport_local, st.free_label_cols
    all_labels, free_labels, prescribed_dict = (
        st.all_labels, st.free_labels, st.prescribed_dict)
    label_to_col, aeros, R_rcsid = st.label_to_col, st.aeros, st.R_rcsid
    pres_values_basic, chordcp_alpha_ref = st.pres_values_basic, st.chordcp_alpha_ref
    over_determined, n_free, n_suport = st.over_determined, st.n_free, st.n_suport

    # ------------------------------------------------------------------ #
    # Schur-complement trim solve (determined or over-determined)
    # ------------------------------------------------------------------ #
    if over_determined:
        # Resolve the TRIMOBJ/TRIMCON/TRIMVAR sets referenced by this subcase.
        trimobj = bulk.trimobjs.get(subcase.trimobj_sid) if subcase.trimobj_sid else None
        if trimobj is None and bulk.trimobjs:
            # Fall back to a single defined TRIMOBJ when the subcase did not name one.
            trimobj = next(iter(bulk.trimobjs.values())) if len(bulk.trimobjs) == 1 else None
        if trimobj is None:
            raise ValueError(
                f"Over-determined trim (n_free={n_free} > n_suport={n_suport}) "
                "requires a TRIMOBJ card to specify the weighted objective."
            )
        trimcons = []
        for cons in bulk.trimcons.values():
            trimcons.extend(cons)
        u_a, delta_free_arr, K_ll_lu, l_idx, r_idx = solve_trim_overdetermined(
            K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q_dyn, suport_local,
            free_labels, free_label_cols, trimobj, trimcons, bulk.trimvars,
        )
    else:
        u_a, delta_free_arr, K_ll_lu, l_idx, r_idx = solve_trim_determined(
            K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q_dyn, suport_local, free_label_cols
        )
    trim_mode = "over-determined" if over_determined else "determined"

    # ------------------------------------------------------------------ #
    # Assemble full trim variable dict
    # ------------------------------------------------------------------ #
    trim_vars: dict[str, float] = dict(prescribed_dict)
    for i, lbl in enumerate(free_labels):
        trim_vars[lbl] = float(delta_free_arr[i])

    # FREE URDD variables are solved in the BASIC frame — their sensitivity
    # column in the Schur system is the basic-frame M_ax — while URDD *labels*
    # are RCSID-frame values.  Rebuild the label values from the full basic
    # triple (prescribed entries from pres_values_basic, free entries from the
    # solve) so trim_vars is uniformly RCSID; without this a free URDD on an
    # RCSID deck is reported in the wrong frame and the downstream
    # rcsid-to-basic rotation corrupts the inertial loads and closure
    # (latent since Step 52 — every earlier deck prescribed its URDDs;
    # exposed by the Step 63 settled-state gate).
    free_urdd = [l for l in free_labels if l in URDD_DOF]
    if free_urdd and bool(aeros.rcsid):
        urdd_full_basic = pres_values_basic.copy()
        for i, lbl in enumerate(free_labels):
            if lbl in URDD_DOF:
                urdd_full_basic[label_to_col[lbl]] = float(delta_free_arr[i])
        urdd_full_rcsid = urdd_basic_to_rcsid(
            urdd_full_basic, label_to_col, R_rcsid, True)
        for lbl in free_urdd:
            trim_vars[lbl] = float(urdd_full_rcsid[label_to_col[lbl]])

    # Full delta_all vector (ordered by all_labels)
    delta_all = np.array([trim_vars.get(l, 0.0) for l in all_labels])

    # KC7: the injected mean flow is only valid as a perturbation base near its
    # reference AOA — warn when the trimmed AOA strays outside ~2 degrees of it
    # (_CHORDCP_ALPHA_TOL, module constant).
    if chordcp_alpha_ref is not None and "ANGLEA" in trim_vars:
        alpha_err = abs(trim_vars["ANGLEA"] - chordcp_alpha_ref)
        if alpha_err > _CHORDCP_ALPHA_TOL:
            warnings.warn(
                f"run_sol144_trim: trimmed ANGLEA {trim_vars['ANGLEA']:.4f} rad is "
                f"{alpha_err:.4f} rad from the CHORDCP reference AOA "
                f"{chordcp_alpha_ref:.4f} rad (> {_CHORDCP_ALPHA_TOL} rad ≈ 2°); "
                "the trim perturbs about the injected operating point and its "
                "validity degrades with distance (KC7).",
                UserWarning,
            )

    st.u_a, st.delta_free_arr = u_a, delta_free_arr
    st.K_ll_lu, st.l_idx, st.r_idx = K_ll_lu, l_idx, r_idx
    st.trim_mode, st.trim_vars, st.delta_all = trim_mode, trim_vars, delta_all


def _stage_recover_displacements(st: _TrimState) -> None:
    """a→g expansion through the RBAR/RBE3 T matrix + CBAR force/stress recovery."""
    bulk = st.bulk
    u_a, T, free_local, red_dofs, grid_index = (
        st.u_a, st.T, st.free_local, st.red_dofs, st.grid_index)

    # ------------------------------------------------------------------ #
    # Expand a-set displacement to full g-set via RBAR/RBE3 T matrix.
    # AE1 Step B1: RBAR slave DOFs must move with their masters before any
    # downstream `g_slope @ u` or `_compute_aero_forces` call; a bare index
    # scatter leaves them at zero and corrupts the structural normalwash.
    # ------------------------------------------------------------------ #
    displacements = expand_to_g(u_a, T, free_local, len(red_dofs))

    # ------------------------------------------------------------------ #
    # CBAR force / stress recovery
    # ------------------------------------------------------------------ #
    bar_forces   = {}
    bar_stresses = {}
    for cbar in bulk.cbars.values():
        bar_forces[cbar.eid]   = recover_bar_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)
        bar_stresses[cbar.eid] = recover_bar_stresses(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)

    st.displacements = displacements
    st.bar_forces, st.bar_stresses = bar_forces, bar_stresses


def _stage_compute_derivs(st: _TrimState) -> None:
    """Rigid, elastic-restrained and unrestrained (AE8b) stability derivatives."""
    bulk, aero, q_dyn = st.bulk, st.aero, st.q_dyn
    D_jx, all_labels, x_ref, suport_pos = st.D_jx, st.all_labels, st.x_ref, st.suport_pos
    K_ll_lu, l_idx, r_idx, Q_ax_a, M_ax_a = (
        st.K_ll_lu, st.l_idx, st.r_idx, st.Q_ax_a, st.M_ax_a)
    T, free_local, red_dofs, free_dofs, grid_index = (
        st.T, st.free_local, st.red_dofs, st.free_dofs, st.grid_index)
    K_aa, Q_aa, red, M_gg, f_aero_g = st.K_aa, st.Q_aa, st.red, st.M_gg, st.f_aero_g

    # ------------------------------------------------------------------ #
    # Rigid derivatives (no structural deformation)
    # ------------------------------------------------------------------ #
    rigid_derivs = compute_rigid_derivs(aero, D_jx, all_labels, bulk, x_ref, suport_pos)

    # ------------------------------------------------------------------ #
    # Elastic restrained derivatives (finite difference, u_r = 0)
    # ------------------------------------------------------------------ #
    rest_derivs = compute_restrained_derivs(
        K_ll_lu, l_idx, Q_ax_a, M_ax_a, all_labels,
        aero, D_jx,
        T, free_local, len(red_dofs),
        bulk, x_ref, q_dyn, suport_pos,
    )

    # ------------------------------------------------------------------ #
    # Unrestrained (mean-axis / inertia-relief) derivatives — AE8b
    # (MSC Aeroelastic Analysis UG Eqs. 2-111 … 2-134)
    # ------------------------------------------------------------------ #
    M_aa = red.reduce_matrix(M_gg, dense=True)   # M_gg assembled with M_ax above
    f_aero_a = red.reduce_vector(f_aero_g)
    unrest_derivs, unrest_intercepts = compute_unrestrained_derivs(
        K_aa, M_aa, Q_aa, Q_ax_a, f_aero_a, all_labels,
        l_idx, r_idx, free_dofs, grid_index, bulk, q_dyn, suport_pos,
    )

    st.rigid_derivs, st.rest_derivs = rigid_derivs, rest_derivs
    st.unrest_derivs, st.unrest_intercepts = unrest_derivs, unrest_intercepts


def _stage_compute_totals(st: _TrimState) -> None:
    """Aerodynamic totals at trim (body/wind axes) + hinge moments."""
    bulk, aero = st.bulk, st.aero
    displacements, D_jx, delta_all, all_labels = (
        st.displacements, st.D_jx, st.delta_all, st.all_labels)
    aeros, x_ref, suport_pos = st.aeros, st.x_ref, st.suport_pos

    # ------------------------------------------------------------------ #
    # Total CL and CM at trim
    # ------------------------------------------------------------------ #
    djk = build_djk(aero.boxes)
    w_struct = djk @ (aero.require_g_slope() @ displacements)
    w_total  = w_struct + D_jx @ delta_all + aero.wg
    gamma    = aero.ajj_inv_corr @ w_total
    f_box_vec = aero.skj @ gamma
    Fz_total = float(f_box_vec[2::3].sum())
    Fx_total = float(f_box_vec[0::3].sum())
    # nose-up-positive (single-source helper, AE1 Step E); whole-airplane (full-span)
    My_total = float(pitch_moment(f_box_vec, aero.boxes, x_ref))
    sref = aeros.sref
    cref = aeros.cref
    # Fz_total and My_total are force/q (skj @ Cp); divide by area only, not q.
    # total_cl/total_cx are BODY-axis (CZ along global-z, CX along streamwise-x);
    # total_cl balances weight at trim and matches NASTRAN's body-axis convention.
    total_cl = Fz_total / sref if sref > 0 else 0.0
    total_cx = Fx_total / sref if sref > 0 else 0.0
    total_cm = My_total / (sref * cref) if sref * cref > 0 else 0.0
    # Wind-axis lift (genuine CL, ⊥ to U∞): rotate the body resultant through
    # the trimmed angle of attack.  CL_wind = CZ·cosα − CX·sinα; equals CZ only
    # at α ≈ 0 (see docs/20_theory/01_aeroelastics_theory.md §5.4).
    alpha_trim = (
        float(delta_all[all_labels.index("ANGLEA")])
        if "ANGLEA" in all_labels else 0.0
    )
    total_cl_wind = float(
        total_cl * np.cos(alpha_trim) - total_cx * np.sin(alpha_trim)
    )
    # Lateral/directional totals — side force plus the full 3-component moment
    # resultant about the RCSID origin, matching the CMX/CMZ derivative-column
    # convention (Step 52).  ≈0 for a symmetric model at a symmetric trim.
    bref = aeros.bref
    Fy_total = float(f_box_vec[1::3].sum())
    Mx_total, _, Mz_total = aero_moment_resultant(
        f_box_vec.reshape(-1, 3), aero.boxes, suport_pos
    )
    total_cy = Fy_total / sref if sref > 0 else 0.0
    total_cmx = float(Mx_total) / (sref * bref) if sref * bref > 0 else 0.0
    total_cmz = float(Mz_total) / (sref * bref) if sref * bref > 0 else 0.0

    # ------------------------------------------------------------------ #
    # Hinge-moment derivatives + trimmed hinge moment per AESURF control
    # ------------------------------------------------------------------ #
    hinge_moments = compute_hinge_moments(aero, D_jx, all_labels, bulk, f_box_vec)

    st.gamma, st.f_box_vec = gamma, f_box_vec
    st.total_cl, st.total_cm, st.total_cx = total_cl, total_cm, total_cx
    st.total_cl_wind, st.total_cy = total_cl_wind, total_cy
    st.total_cmx, st.total_cmz = total_cmx, total_cmz
    st.hinge_moments = hinge_moments


def _stage_flight_and_net_loads(st: _TrimState) -> None:
    """Per-box forces (Step 56), injection echo (Step 64), balanced maneuver
    loads + closure (Step 53), critical divergence q."""
    bulk, aero, q_dyn = st.bulk, st.aero, st.q_dyn
    f_box_vec, delta_all, label_to_col = st.f_box_vec, st.delta_all, st.label_to_col
    aeros, R_rcsid, suport_pos = st.aeros, st.R_rcsid, st.suport_pos
    grid_index, spc_sid, red = st.grid_index, st.spc_sid, st.red
    M_ax_g, K_aa, Q_aa, l_idx = st.M_ax_g, st.K_aa, st.Q_aa, st.l_idx

    # ------------------------------------------------------------------ #
    # Step 56 — per-box pressures/forces, g-set flight loads, divergence q
    # ------------------------------------------------------------------ #
    # f_box_vec is in force/q units; the physical box force is q * f_box_vec.
    # ΔCp is the normal-projected force per unit area in force/q units (so the
    # box's z-normal flat-plate limit reduces to f_box_vec[3j+2] / area).
    n_box = len(aero.boxes)
    box_forces = np.empty((n_box, 3))
    box_cp = np.empty(n_box)
    for j, b in enumerate(aero.boxes):
        f_j = f_box_vec[3 * j:3 * j + 3]
        box_forces[j] = q_dyn * f_j
        box_cp[j] = float(np.dot(f_j, b.normal) / b.area) if b.area > 0 else 0.0

    # g-set aero flight-load vector for FORCE/MOMENT export (plain trim:
    # G_load^T · q · P_k).  Preserves net force/moment through the spline.
    grid_loads = aero.require_g_load().T @ (q_dyn * f_box_vec)

    # Step 64 / DEF-M1 — echo what the load injection contributed.  Boxes with
    # no structural coupling (SPLINE0 body panels, un-splined boxes) enter the
    # trim balance and the load export as a rigid load at their master grid;
    # report each group's 6-component resultant about the moment reference so a
    # mis-placed master grid is visible.  Empty on decks with none, so their f06
    # is byte-identical.
    load_injection_echo = _build_injection_echo(
        aero, box_forces, suport_pos, grid_index, red.free_dofs
    )

    # ------------------------------------------------------------------ #
    # Step 53 — balanced maneuver loads & inertia relief.
    # The inertial g-set load is M_ax · a using the FINAL trim accelerations
    # (prescribed AND solved-free URDD), not just the prescribed ones — the
    # free URDD already entered the displacement solve via the M_ax_a column.
    # Net (aero + inertial) grid loads are the deliverable for stress and the
    # non-zero inertia column consumed by MONPNT3 (MON3).  For a 1g determined
    # trim with URDD≈0 these reduce to the aero-only / zero case.
    # ------------------------------------------------------------------ #
    delta_all_basic = urdd_rcsid_to_basic(
        delta_all, label_to_col, R_rcsid, bool(aeros.rcsid)
    )
    inertial_loads = M_ax_g @ delta_all_basic     # (n_g,)
    net_loads = grid_loads + inertial_loads       # (n_g,)

    # Force/moment closure (V-C5 / KC9): body-frame resultant of the net
    # (aero + inertial) load about the moment reference.  For a true free
    # aircraft (SUPORT, no SPC) this must balance to ≈ 0 — a non-zero residual
    # flags a gravity double-count or a lumped-vs-consistent mass mismatch.  For
    # an SPC'd (e.g. half-span) model the residual legitimately equals the
    # constraint reaction, so the hard warning fires only in the free case; the
    # residual is always stored for the per-case acceptance test.
    maneuver_closure = load_resultant(net_loads, bulk, grid_index, suport_pos)
    spc_dofs_closure = get_spc_dofs(bulk, spc_sid, grid_index) if spc_sid else []
    if len(spc_dofs_closure) == 0:
        aero_res = load_resultant(grid_loads, bulk, grid_index, suport_pos)
        f_scale = max(np.linalg.norm(aero_res[:3]), 1.0)
        m_scale = max(np.linalg.norm(aero_res[3:]), 1.0)
        if (np.linalg.norm(maneuver_closure[:3]) > 1e-6 * f_scale or
                np.linalg.norm(maneuver_closure[3:]) > 1e-6 * m_scale):
            warnings.warn(
                f"SOL 144 maneuver closure: free-aircraft net (aero+inertial) "
                f"resultant is non-zero (F={maneuver_closure[:3]}, "
                f"M={maneuver_closure[3:]}) — check inertia relief / load factor "
                f"(KC9).",
                UserWarning,
            )

    # Critical divergence dynamic pressure on the restrained l-set.
    K_ll_div = K_aa[np.ix_(l_idx, l_idx)]
    Q_ll_div = Q_aa[np.ix_(l_idx, l_idx)]
    q_div = divergence_dynamic_pressure(K_ll_div, Q_ll_div)

    st.box_forces, st.box_cp, st.grid_loads = box_forces, box_cp, grid_loads
    st.load_injection_echo = load_injection_echo
    st.inertial_loads, st.net_loads = inertial_loads, net_loads
    st.maneuver_closure, st.q_div = maneuver_closure, q_div


def _stage_monitor_outputs(st: _TrimState) -> None:
    """MON2/MON3 monitor points + MONSECT section cuts (Monitor Phase 2)."""
    bulk, aero, grid_index, spc_sid = st.bulk, st.aero, st.grid_index, st.spc_sid
    displacements, K_gg = st.displacements, st.K_gg
    box_forces, grid_loads, inertial_loads, net_loads = (
        st.box_forces, st.grid_loads, st.inertial_loads, st.net_loads)
    massset_sid = st.massset_sid

    # ------------------------------------------------------------------ #
    # MON2/MON3 — monitor-point integrated section loads.
    # The reaction column needs the SPC/SUPORT reaction that balances the net
    # (aero + inertial) load; recovered the same way as SOL 101 (R = K·u − f).
    # ------------------------------------------------------------------ #
    monitor_loads = None
    section_loads = None
    # A SET1-backed MONSECT needs the reaction column for exactly the same
    # reason MONPNT3 does — a cut that spans a constrained grid carries its
    # reaction across the plane.
    needs_reactions = bool(bulk.monpnt3s) or any(
        bulk.aecomps[c.comp].listtype == "SET1" for c in bulk.monsects.values()
    )
    if bulk.monpnt1s or bulk.monpnt3s or bulk.monsects:
        reactions = {}
        if needs_reactions:
            constrained = list(get_spc_dofs(bulk, spc_sid, grid_index)) if spc_sid else []
            for sup in bulk.supports:
                if sup.gid in grid_index:
                    base = grid_index[sup.gid] * 6
                    constrained += [base + (int(ch) - 1) for ch in sup.dofs]
            if constrained:
                reactions = recover_reactions(
                    bulk, displacements, constrained, K_gg, grid_index, net_loads
                )
        if bulk.monpnt1s or bulk.monpnt3s:
            monitor_loads = compute_monitor_loads(
                bulk, aero, box_forces, grid_loads, inertial_loads, grid_index,
                reactions, massset_sid
            )
        # MONSECT — the same integrand swept over cut planes (Monitor Phase 2).
        if bulk.monsects:
            section_loads = compute_section_cuts(
                bulk, aero, box_forces, grid_loads, inertial_loads, grid_index,
                reactions
            )

    st.monitor_loads, st.section_loads = monitor_loads, section_loads


def _pack_trim_result(st: _TrimState) -> Sol144TrimResult:
    """Assemble the Sol144TrimResult from the completed stage state."""
    mass_case_gpwg = st.mass_case_gpwg
    return Sol144TrimResult(
        subcase_id=st.subcase.subcase_id,
        trim_sid=st.trim_sid,
        q=st.q_dyn,
        mach=st.mach,
        trim_vars=st.trim_vars,
        displacements=st.displacements,
        bar_forces=st.bar_forces,
        bar_stresses=st.bar_stresses,
        q_aa=st.Q_aa,
        free_dofs=st.free_dofs,
        rigid_derivs=st.rigid_derivs,
        restrained_derivs=st.rest_derivs,
        unrestrained_derivs=st.unrest_derivs,
        unrestrained_intercepts=st.unrest_intercepts,
        box_gamma=st.gamma,
        total_cl=st.total_cl,
        total_cm=st.total_cm,
        total_cx=st.total_cx,
        total_cl_wind=st.total_cl_wind,
        total_cy=st.total_cy,
        total_cmx=st.total_cmx,
        total_cmz=st.total_cmz,
        box_cp=st.box_cp,
        box_forces=st.box_forces,
        grid_loads=st.grid_loads,
        inertial_loads=st.inertial_loads,
        net_loads=st.net_loads,
        maneuver_closure=st.maneuver_closure,
        q_div=st.q_div,
        hinge_moments=st.hinge_moments,
        trim_mode=st.trim_mode,
        monitor_loads=st.monitor_loads,
        section_loads=st.section_loads,
        chordcp_echo=st.chordcp_echo,
        load_injection_echo=st.load_injection_echo,
        massset_sid=st.massset_sid,
        massset_label=st.mass_case_label,
        massset_mass=mass_case_gpwg.total_mass,
        massset_cg=(mass_case_gpwg.cg_x, mass_case_gpwg.cg_y, mass_case_gpwg.cg_z),
    )


def run_sol144_trim(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
    aero_cache: Optional["AeroCache"] = None,
) -> Sol144TrimResult:
    """SOL 144 static aeroelastic trim solve (Step 52).

    Solves the coupled structural/aerodynamic trim problem using the Schur
    complement method.  Handles both the determined case
    (n_free == n_suport) and the over-determined (redundant-control) case —
    the latter via null-space reduction with a weighted-L2 objective from
    the TRIMOBJ/TRIMCON/TRIMVAR cards.

    Args:
        bulk:       Parsed BulkData — must include SUPORT and TRIM cards.
        subcase:    SubcaseControl — uses spc_sid and trim_sid.
        aero:       AeroModel with g_slope, g_disp, ajj_inv_corr, skj, wg
                    populated.  Used directly when its Mach matches the TRIM
                    Mach; otherwise it seeds the AeroCache and the AIC is rebuilt
                    at the TRIM Mach (AE9).
        aero_cache: Optional AeroCache shared across subcases so multi-Mach runs
                    build each AIC once.  When None, a local cache seeded with
                    ``aero`` is created.

    Returns:
        Sol144TrimResult with trim variables, displacements, stability derivatives.

    Raises:
        ValueError  if no SUPORT card, TRIM card, a LOAD request the trim
                    cannot honour, or the trim is over-determined without a
                    TRIMOBJ objective.
    """
    st = _TrimState(bulk=bulk, subcase=subcase, aero=aero, aero_cache=aero_cache)
    _stage_validate_inputs(st)
    _stage_resolve_massset_and_mach(st)
    _stage_build_labels(st)
    _stage_resolve_ref_geometry(st)
    _stage_echo_chordcp(st)
    _stage_build_downwash_and_reduce(st)
    _stage_solve_trim(st)
    _stage_recover_displacements(st)
    _stage_compute_derivs(st)
    _stage_compute_totals(st)
    _stage_flight_and_net_loads(st)
    _stage_monitor_outputs(st)
    return _pack_trim_result(st)
