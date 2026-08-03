"""Result data structures for sbeam FEA solver."""

from dataclasses import dataclass, field
from typing import Any, Optional, Union

import numpy as np

from sbeam.types import FloatArray, LuFactor, SparseMatrix


@dataclass
class BarForce:
    eid: int
    # End forces and moments in element LOCAL coordinates
    axial: float = 0.0    # Fx at end B (positive = tension)
    shear1: float = 0.0   # Vy at end B (positive = in local y)
    shear2: float = 0.0   # Vz at end B (positive = in local z)
    torque: float = 0.0   # Mx (torsion)
    bm1_a: float = 0.0    # My at end A (bending in xz plane)
    bm2_a: float = 0.0    # Mz at end A (bending in xy plane)
    bm1_b: float = 0.0    # My at end B
    bm2_b: float = 0.0    # Mz at end B


@dataclass
class BarStress:
    eid: int
    axial: float = 0.0
    sa: float = 0.0   # Bending stress at recovery point C (end A)
    sb: float = 0.0   # Bending stress at recovery point C (end B)
    # Additional recovery points
    sa_d: float = 0.0  # At recovery point D, end A
    sb_d: float = 0.0  # At recovery point D, end B
    sa_e: float = 0.0  # At recovery point E, end A
    sb_e: float = 0.0  # At recovery point E, end B
    sa_f: float = 0.0  # At recovery point F, end A
    sb_f: float = 0.0  # At recovery point F, end B


@dataclass
class MonitorLoad:
    """Integrated section load at a monitor point (MONPNT1 / MONPNT3).

    Forces/moments are reported in the monitor's ``cp`` coordinate frame, summed
    over the monitor's AECOMP collection and scaled by the symmetry ``parity``
    factor (2.0 for a half-model with AEROS SYMXZ≠0, else 1.0).
    """
    name: str
    label: str
    mtype: str                      # 'MONPNT1' or 'MONPNT3'
    axes: int
    cid: int                        # cp coordinate frame the loads are reported in
    ref: FloatArray                 # (3,) reference point in basic CID 0
    totals: FloatArray              # (6,) Fx,Fy,Fz,Mx,My,Mz in cp frame
    aero: Optional[FloatArray] = None      # (6,) aero contribution in cp frame
    inertia: Optional[FloatArray] = None   # (6,) inertia contribution (MONPNT3; zero for plain trim)
    reaction: Optional[FloatArray] = None  # (6,) SPC/SUPORT reaction contribution (MONPNT3)
    parity: float = 1.0             # symmetry doubling factor applied to all components
    whole_airplane: bool = False    # True when parity≠1 (annotate output to avoid double-up)
    source_ids: list[int] = field(default_factory=list)   # AELIST or SET1 SIDs


@dataclass
class SectionCutStation:
    """One cut plane of a MONSECT section-cut table.

    Loads are the resultant of everything on the cut's ``side``, taken about
    ``ref`` and reported in the cut CID frame as a raw ``[Fx, Fy, Fz, Mx, My, Mz]``
    6-vector; ``SectionCutResult.comp_map`` reorders those into the labelled
    ``[N, V*, V*, Mt, M*, M*]`` stress components.  No symmetry parity is ever
    applied (unlike ``MonitorLoad``): a cut on a half model is already the
    physical per-side load.
    """
    station: float                  # station coordinate along the cut axis, cid frame
    ref:     FloatArray             # (3,) reference point in basic CID 0 (cut-plane/EA intercept)
    totals:  FloatArray             # (6,) aero + inertia + reaction, cid frame
    aero:    FloatArray             # (6,) aero contribution
    inertia: FloatArray             # (6,) inertia contribution (zero for an AELIST cut / plain trim)
    reaction: FloatArray            # (6,) SPC/SUPORT reaction contribution (zero for an AELIST cut)
    n_members: int = 0              # grids (SET1) or boxes (AELIST) on the integrated side
    # (6,) d/ds of the labelled components vs the previous station — the running
    # load in the per-unit-span sense.  None at the first station.
    d_ds: Optional[FloatArray] = None
    # Step 68 transient contributions, cid frame; None on a static trim (where
    # the structure has no elastic acceleration, so there is no such column to
    # report — as opposed to a zero one).  ``totals`` includes them when present.
    elastic_inertia: Optional[FloatArray] = None   # (6,) M·ü_e — the elastic d'Alembert load
    damping: Optional[FloatArray] = None           # (6,) modal-damping force (ζ ≠ 0 only)


@dataclass
class SectionCutResult:
    """Per-station running-load table for one MONSECT card (Monitor Phase 2)."""
    name:  str
    label: str
    comp:  str                      # AECOMP name
    listtype: str                   # 'SET1' (aero+inertia+reaction) or 'AELIST' (aero only)
    cid:   int                      # frame the components are reported in
    axis:  int                      # station axis within cid (1/2/3)
    side:  str                      # 'POS' or 'NEG'
    stations: list[SectionCutStation] = field(default_factory=list)
    # comp_map[i] is the index into the raw cid-frame 6-vector for labelled
    # component i of [N, Vy, Vz, Mt, My, Mz] — see section_cuts.component_map.
    comp_map: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
    half_model: bool = False        # AEROS SYMXZ≠0: the table is per side, never doubled
    normal: Optional[FloatArray] = None   # (3,) cut normal in basic, when overridden


@dataclass
class SectionCutEnvelopeEntry:
    """Max/min of one labelled component at one station over a maneuver.

    ``max_sample``/``min_sample`` are 1-based, matching the f06 SAMPLE column and
    the MLDPRNT numbering (DEF-M5).  They are the **driving** samples and are
    generally not the run's critical sample — see
    :mod:`sbeam.results.section_envelope`.
    """
    station: float
    comp: int                       # 0..5, index into the labelled component order
    max_value: float
    max_sample: int
    max_time: float
    min_value: float
    min_sample: int
    min_time: float

    @property
    def absmax(self) -> float:
        """The larger magnitude of the two extremes (the sizing number)."""
        return max(abs(self.max_value), abs(self.min_value))


@dataclass
class SectionCutEnvelope:
    """Per-station max/min envelope of one MONSECT cut over a maneuver (Step 68)."""
    name:  str
    label: str
    comp:  str
    listtype: str
    cid:   int
    axis:  int
    side:  str
    comp_map: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
    half_model: bool = False
    n_samples: int = 0              # samples the envelope was reduced over
    entries: list[SectionCutEnvelopeEntry] = field(default_factory=list)


@dataclass
class Sol101Result:
    displacements: FloatArray         # Full displacement vector (n_dofs,)
    reactions: dict[int, FloatArray] = field(default_factory=dict)   # {gid: (6,)} SPC reactions
    bar_forces: dict[int, BarForce] = field(default_factory=dict)     # {eid: BarForce}
    bar_stresses: dict[int, BarStress] = field(default_factory=dict)   # {eid: BarStress}
    # Note: cbush_forces are in global coordinates (unlike bar_forces which are local)
    cbush_forces: dict[int, FloatArray] = field(default_factory=dict)  # forces at GB (GA if grounded)


@dataclass
class Sol103Result:
    frequencies_hz: FloatArray      # shape (n_modes,) — natural frequencies in Hz
    mode_shapes: FloatArray         # shape (n_dofs, n_modes) — full global DOF mode shapes
    eigenvalues: FloatArray         # shape (n_modes,) — raw eigenvalues ω² [rad²/s²]
    generalized_masses: FloatArray  # shape (n_modes,) — phi_i^T M_free phi_i per mode
    # A-set eigendata retained for downstream consumers (Step 59: GAF export,
    # Step 61 modal basis). Populated by run_sol103; default None so older
    # constructors stay valid.
    phi_free: Optional[FloatArray] = None   # (n_a, n_modes) a-set mode shapes
    free_dofs: Optional[list[int]] = None   # a-set indices into the g-set
    K_free: Optional[Union[FloatArray, SparseMatrix]] = None   # (n_a, n_a) a-set stiffness
    M_free: Optional[Union[FloatArray, SparseMatrix]] = None   # (n_a, n_a) a-set mass


@dataclass
class Sol144Result:
    displacements: FloatArray           # (n_dofs,) full g-set; SPC DOFs zeroed
    bar_forces: dict[int, BarForce]                    # {eid: BarForce}
    bar_stresses: dict[int, BarStress]                  # {eid: BarStress}
    q_aa: FloatArray                    # (n_a, n_a) dense aero stiffness on a-set
    q: float                            # dynamic pressure used in this solve
    free_dofs: list[int]                     # a-set indices into g-set (length n_a)
    k_aa_lu: LuFactor                      # (lu, piv) from lu_factor(K_aa); reusable by Step 52
    modal_coords: Optional[FloatArray] = None   # (n_modes,) ξ; None when ROM not used
    phi_free: Optional[FloatArray] = None       # (n_a, n_modes); None when ROM not used
    k_hh: Optional[FloatArray] = None           # (n_modes, n_modes) modal structural stiffness
    q_hh: Optional[FloatArray] = None           # (n_modes, n_modes) modal GAF matrix


@dataclass
class Sol144TrimResult:
    """Result of a SOL 144 static aeroelastic trim subcase."""
    subcase_id: int
    trim_sid: int
    q: float                             # dynamic pressure
    mach: float
    trim_vars: dict[str, float]          # all labels (free + prescribed)
    displacements: FloatArray            # (n_dofs,) full g-set; SPC/SUPORT DOFs zeroed
    bar_forces: dict[int, BarForce]                     # {eid: BarForce}
    bar_stresses: dict[int, BarStress]                   # {eid: BarStress}
    q_aa: FloatArray                     # (n_a, n_a) aerodynamic stiffness on a-set
    free_dofs: list[int]                      # a-set indices into g-set (length n_a)
    rigid_derivs: dict[str, dict[str, float]]                   # {label: {'CZ','CMY','CMX','CMZ','CX','CY'}}
    restrained_derivs: dict[str, dict[str, float]]              # {label: {'CZ','CMY','CMX','CMZ'}}
    unrestrained_derivs: Optional[dict[str, dict[str, float]]] = None   # {label: {'CZ','CMY','CMX','CMZ'}} mean-axis (inertia-relief) column — AE8b; aero labels only
    unrestrained_intercepts: Optional[dict[str, float]] = None  # {'CZ0','CMY0'} unrestrained w_g-baseline intercepts
    box_gamma: Optional[FloatArray] = None   # (n_box,) circulation strengths at trim
    total_cl: float = 0.0                # body-axis CZ = Fz / (q * sref) (balances weight at trim)
    total_cm: float = 0.0               # total CMy / (q * sref * cref) about x_ref
    total_cx: float = 0.0                # body-axis CX = Fx / (q * sref) (streamwise, ≈0)
    total_cl_wind: float = 0.0           # wind-axis lift = CZ·cosα − CX·sinα at trim α (genuine CL)
    total_cy: float = 0.0                # body-axis CY = Fy / (q * sref) (side force, ≈0 symmetric)
    total_cmx: float = 0.0               # total roll CMx / (q * sref * bref) about the RCSID origin
    total_cmz: float = 0.0               # total yaw CMz / (q * sref * bref) about the RCSID origin
    # --- Step 56 outputs (f06 blocks, AEROF/APRES, flight-load export) ---
    box_cp: Optional[FloatArray] = None       # (n_box,) ΔCp per box at trim (normal-projected force/q / area)
    box_forces: Optional[FloatArray] = None   # (n_box, 3) physical aero force per box = q * (skj@gamma)
    grid_loads: Optional[FloatArray] = None   # (n_dofs,) g-set aero flight-load vector = g_disp^T (q * f_box)
    # --- Step 53 outputs (balanced maneuver loads & inertia relief) ---
    inertial_loads: Optional[FloatArray] = None  # (n_dofs,) g-set inertial load = M_ax @ a_all (final trim URDD); feeds MONPNT3 inertia column
    net_loads: Optional[FloatArray] = None       # (n_dofs,) g-set net maneuver load = grid_loads + inertial_loads (the stress deliverable)
    maneuver_closure: Optional[FloatArray] = None  # (6,) body-frame resultant (Fx,Fy,Fz,Mx,My,Mz) of net_loads about the moment ref; ≈0 for a balanced free-aircraft maneuver (V-C5/KC9)
    q_div: Optional[float] = None             # critical divergence dynamic pressure (restrained l-set); None if none
    hinge_moments: Optional[dict[str, dict[str, float]]] = None      # {AESURF label: {'total': HM/q at trim, <trim_label>: dHM/dδ}} about cid1 hinge axis
    trim_mode: str = "determined"             # "determined" or "over-determined" (Step 52)
    monitor_loads: Optional[dict[str, MonitorLoad]] = None      # {name: MonitorLoad} integrated section loads (MON1–MON3)
    section_loads: Optional[dict[str, SectionCutResult]] = None  # {name: SectionCutResult} MONSECT running loads
    chordcp_echo: Optional[dict[str, Any]] = None       # Step 54 injected-operating-point echo: {'alpha_ref', 'data_machs', 'surfaces': {eid: {'FZ_Q','MY_Q','FZ_Q_VLM'}}}
    load_injection_echo: Optional[list[dict[str, Any]]] = None  # Step 64 SPLINE0/un-splined load injection: [{'source','master_grid','n_boxes','force','moment'}]; None/[] = no injection
    # --- Step 60 (MASSSET payload / mass case) ---
    massset_sid: Optional[int] = None         # MASSSET SID selected by the subcase; None = baseline
    massset_label: str = "BASELINE"           # mass-case name for output headers
    massset_mass: float = 0.0                 # total case mass (GPWG) for this configuration
    massset_cg: Optional[tuple[float, float, float]] = None   # CG of the case mass


@dataclass
class DivergRoot:
    """One divergence root (Step 55)."""
    q_div: float                          # divergence dynamic pressure (positive real root)
    v_div: Optional[float] = None         # divergence speed = sqrt(2*q_div/rho); None when no RHOREF
    mode_shape: Optional[FloatArray] = None  # (n_dofs,) g-set divergence eigenvector (max-abs normalised)


@dataclass
class DivergMachResult:
    """Divergence sweep results at a single Mach number (Step 55)."""
    mach: float
    roots: list["DivergRoot"]              # sorted by ascending q_div


@dataclass
class Sol144DivergResult:
    """Result of a SOL 144 DIVERG-card divergence sweep (Step 55).

    Divergence depends only on K_aa and Q_aa (the w_g/Q_ax trim RHS does not
    enter the eigenvalue), so this is solved independently of any TRIM card.
    """
    subcase_id: int
    diverg_sid: int
    nroots: int
    rhoref: float                         # reference density for V_div (0.0 ⇒ V_div omitted)
    mach_results: list["DivergMachResult"]


@dataclass
class ManeuverStep:
    """One output sample of a Phase G0 transient maneuver run."""
    t: float                              # sample time
    trim_vars: dict[str, float]           # commanded/held δ(t) at this time
    displacements: FloatArray             # (n_dofs,) g-set; SPC/SUPORT DOFs zeroed
    bar_forces: dict[int, BarForce]                      # {eid: BarForce}
    grid_loads: FloatArray                # (n_dofs,) g-set aero flight load at this instant
    inertial_loads: FloatArray            # (n_dofs,) g-set inertial load = M_ax · a_urdd(t)
    net_loads: FloatArray                 # (n_dofs,) net (aero + inertial) load — stress deliverable
    closure: FloatArray                   # (6,) body-frame resultant (Fx..Mz) of net_loads about the ref
    Fz_aero: float = 0.0                  # instantaneous aero Fz (force/q · q) = lift
    My_aero: float = 0.0                  # instantaneous aero pitching moment about x_ref
    # Modal amplitudes: (n_e,) restrained elastic ξ under the Step 62 solver;
    # (n_h,) full free-flight perturbation Δξ under the Step 63 solver.
    modal_coords: Optional[FloatArray] = None
    # Step 63 free-flight rigid states (n_r,), basic frame about suport_pos,
    # perturbations about the IC trim; None under the prescribed-rigid solvers.
    xi_r: Optional[FloatArray] = None            # rigid displacements Δξ_r
    xi_r_dot: Optional[FloatArray] = None        # rigid rates Δξ̇_r
    xi_r_ddot: Optional[FloatArray] = None       # rigid accelerations Δξ̈_r
    # Load-factor ratio URDD3_basic(t)/URDD3_basic(t0) (D3); None when not
    # free-flight or when the IC has no vertical acceleration to normalize by.
    nz_rel: Optional[float] = None
    # Step 68 — the elastic d'Alembert load −M·ü_e and the damping force −M·w,
    # g-set.  Deliberately NOT folded into net_loads: that vector feeds the
    # exported FORCE/MOMENT cards, the closure diagnostic and the DEF-M5
    # critical-sample metric, and moving all three at once is a separate
    # decision (see designs/monsect_transient_section_cuts.md §9 O1).
    elastic_inertial_loads: Optional[FloatArray] = None
    damping_loads: Optional[FloatArray] = None
    # {name: SectionCutResult} MONSECT running loads at this sample.
    section_loads: Optional[dict[str, "SectionCutResult"]] = None


def peak_grid_force(step: "ManeuverStep") -> float:
    """Severity metric for one maneuver sample: peak per-grid net force.

    The maximum over grids of the net (aero + inertial) translational force
    magnitude ``‖F‖`` at that grid.

    This is the single metric that selects the critical sample, fills the f06
    and MLDPRNT columns, and labels both (DEF-M5).  It is deliberately *not*:

    * ``‖closure[:3]‖`` — the resultant about the reference point, i.e. the
      aero/inertia balance residual.  On a converged balanced maneuver that is
      ~0, so selecting on it picks the sample with the most numerical noise.
    * ``max|net_loads|`` over all six DOFs — that mixes forces and moments,
      which have different units, so the winner depends on the unit system.
    """
    n = step.net_loads.size // 6
    if n == 0:
        return 0.0
    f = step.net_loads[:6 * n].reshape(n, 6)[:, :3]
    return float(np.linalg.norm(f, axis=1).max())


@dataclass
class ManeuverResult:
    """Result of a Phase G0 (DLM-free quasi-steady) transient maneuver subcase."""
    subcase_id: int
    mloads_sid: int
    trim_sid: int                         # initial-condition TRIM sid (via MLDTRIM)
    q: float                              # dynamic pressure
    mach: float
    labels: list[str]                          # all trim-variable labels (column order)
    times: FloatArray                     # (n_out,) output sample times
    steps: list["ManeuverStep"]            # one per output sample
    crit_index: int                       # index into steps of the peak_grid_force sample
    mldprnt_items: list[str] = field(default_factory=list)  # requested ASCII-print keywords
    massset_sid: Optional[int] = None     # MASSSET mass case (None = baseline)
    n_modes_used: Optional[int] = None    # retained elastic modes (Step 62 solver; None = direct l-set)
    # Step 62 basis summary for the f06 (n_r, n_e, n_available, freqs_hz,
    # orthogonality_residual, n_massless); None for the direct l-set solver.
    basis_info: Optional[dict] = None
    # Step 68 — {name: SectionCutEnvelope} per-station max/min over the run's
    # samples.  None when the deck has no MONSECT cards.
    section_envelope: Optional[dict[str, "SectionCutEnvelope"]] = None
