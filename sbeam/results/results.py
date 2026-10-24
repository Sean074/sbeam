"""Result data structures for sbeam FEA solver."""

from dataclasses import dataclass, field
from typing import Any, Optional, Union

import numpy as np

from sbeam.types import FloatArray, LuFactor, SparseMatrix


@dataclass
class BarForce:
    """CBAR end forces in the NASTRAN/MSC ``FORCES IN BAR ELEMENTS`` layout (DEF-M18, #21).

    All values are internal resultants on the positive (+x) face of the section
    in the element local frame (``bar_internal_resultants``; ``09_conventions.md``
    §9). Plane 1 is the element x–y plane (bending about local z, PBAR ``I1``);
    plane 2 is the x–z plane (bending about local y, PBAR ``I2``). The plane
    moments carry the NASTRAN sign: ``M1 = +Mz⁺`` and ``M2 = −My⁺``, so both are
    positive when they put the +y / +z fibres in compression and the bending
    stress is ``σ = −M1·y/I1 − M2·z/I2`` (NASTRAN-95 ``sbar2.f``). On a
    cantilever with tip loads +Py, +Pz: ``M1(x) = Py(L−x)``, ``M2(x) = Pz(L−x)``.
    """
    eid: int
    m1_a: float = 0.0    # BEND-MOMENT END-A PLANE 1  (= +Mz on the +x face at end A)
    m2_a: float = 0.0    # BEND-MOMENT END-A PLANE 2  (= −My on the +x face at end A)
    m1_b: float = 0.0    # BEND-MOMENT END-B PLANE 1  (= +Mz on the +x face at end B)
    m2_b: float = 0.0    # BEND-MOMENT END-B PLANE 2  (= −My on the +x face at end B)
    v1: float = 0.0      # SHEAR PLANE 1  (Vy, along local +y; constant without element loads)
    v2: float = 0.0      # SHEAR PLANE 2  (Vz, along local +z)
    axial: float = 0.0   # AXIAL FORCE    (tension positive)
    torque: float = 0.0  # TORQUE         (right-handed about local +x)


@dataclass
class BarStress:
    """CBAR stresses in the NASTRAN/MSC ``STRESSES IN BAR ELEMENTS`` layout (DEF-M18, #21).

    ``sa1``–``sa4`` / ``sb1``–``sb4`` are the **bending-only** fibre stresses at
    PBAR recovery points C, D, E, F at ends A and B,
    ``σ_b = −M1·y/I1 − M2·z/I2`` on the :class:`BarForce` plane moments. A point
    left at (0, 0) carries zero bending stress, as in NASTRAN. ``axial`` is
    ``P/A``; ``sa_max``/``sa_min`` (and ``sb_*``) are ``axial`` plus the
    max/min over the four bending values, i.e. the extreme **total** stress at
    that end. Tension is positive. Margins of safety are not computed (no
    allowables are parsed).
    """
    eid: int
    sa1: float = 0.0
    sa2: float = 0.0
    sa3: float = 0.0
    sa4: float = 0.0
    sb1: float = 0.0
    sb2: float = 0.0
    sb3: float = 0.0
    sb4: float = 0.0
    axial: float = 0.0
    sa_max: float = 0.0
    sa_min: float = 0.0
    sb_max: float = 0.0
    sb_min: float = 0.0


@dataclass
class RodForce:
    """CROD / CONROD forces in the NASTRAN ``FORCES IN ROD ELEMENTS`` layout (#38).

    +x-face internal resultants in the element frame, from the same
    ``bar_internal_resultants`` helper as the CBAR table (``09_conventions.md``
    §8/§9): ``axial = P`` tension positive, ``torque = T`` right-handed about the
    GA→GB axis. A rod carries nothing else.
    """
    eid: int
    axial: float = 0.0
    torque: float = 0.0


@dataclass
class RodStress:
    """CROD / CONROD stresses in the NASTRAN ``STRESSES IN ROD ELEMENTS`` layout (#38).

    ``axial = P/A`` (tension positive); ``torsional = T·C/J`` with the PROD /
    CONROD torsional stress coefficient ``C`` (0 when ``J = 0`` or ``C = 0``, as
    NASTRAN-95 ``srod1.f`` sets ``C/J = 0`` for ``J = 0``). Margins of safety are
    not computed (no allowables are parsed).
    """
    eid: int
    axial: float = 0.0
    torsional: float = 0.0


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
    # Transient (MLOADS) contributions, cp frame (#2); None on a static trim,
    # where the structure has no elastic acceleration — as opposed to zero.
    # ``totals`` includes them when present; ``inertia`` stays the RIGID
    # inertia, exactly as on ``SectionCutStation``.
    elastic_inertia: Optional[FloatArray] = None   # (6,) −M·ü_e, the elastic d'Alembert load
    damping: Optional[FloatArray] = None           # (6,) −M·w, the damping force (ζ/α ≠ 0 only)


@dataclass
class MonitorEnvelopeEntry:
    """Max/min of one component of one monitor over a maneuver (#2).

    ``max_sample``/``min_sample`` are 1-based, matching the f06 SAMPLE column
    and the MLDPRNT numbering (DEF-M5).  They are the **driving** samples and
    are generally not the run's critical sample.
    """
    comp: int                       # 0..5, index into [Fx, Fy, Fz, Mx, My, Mz] (cp frame)
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
class MonitorEnvelope:
    """Per-component max/min envelope of one monitor point over a maneuver (#2)."""
    name:  str
    label: str
    mtype: str
    axes:  int
    cid:   int
    whole_airplane: bool = False
    n_samples: int = 0              # samples the envelope was reduced over
    entries: list[MonitorEnvelopeEntry] = field(default_factory=list)


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
    rod_forces: dict[int, RodForce] = field(default_factory=dict)      # {eid: RodForce} CROD + CONROD (#38)
    rod_stresses: dict[int, RodStress] = field(default_factory=dict)   # {eid: RodStress}


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
    rod_forces: dict[int, RodForce] = field(default_factory=dict)      # {eid: RodForce} (#38)
    rod_stresses: dict[int, RodStress] = field(default_factory=dict)   # {eid: RodStress}


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
    gust_echo: Optional[dict[str, Any]] = None          # Issue #1 GUSTLF provenance: {'sid','trimid','n','g','urdd3','sense','ude','veas','kg','mu','a','asrc','alt'} — recorded by sbeam_tools/cases/gust.py, echoed only (sbeam does not compute the gust)
    load_injection_echo: Optional[list[dict[str, Any]]] = None  # Step 64 SPLINE0/un-splined load injection: [{'source','master_grid','n_boxes','force','moment'}]; None/[] = no injection
    # --- Step 67a (quasi-steady yaw-rate wing term) ---
    yaw_rate_iters: int = 0                   # fixed-point iterations spent on the loading-scaled yaw-rate force column; 0 = term not active (no YAW label, or zero yaw rate)
    # --- Step 60 (MASSSET payload / mass case) ---
    massset_sid: Optional[int] = None         # MASSSET SID selected by the subcase; None = baseline
    massset_label: str = "BASELINE"           # mass-case name for output headers
    massset_mass: float = 0.0                 # total case mass (GPWG) for this configuration
    massset_cg: Optional[tuple[float, float, float]] = None   # CG of the case mass
    rod_forces: dict[int, RodForce] = field(default_factory=dict)      # {eid: RodForce} CROD + CONROD (#38)
    rod_stresses: dict[int, RodStress] = field(default_factory=dict)   # {eid: RodStress}


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
    inertial_loads: FloatArray            # (n_dofs,) g-set RIGID inertial load = M_ax · a_urdd(t)
    # (n_dofs,) the FULL applied load at this sample — aero + rigid inertia +
    # elastic inertia + damping (#3).  The stress deliverable: applied
    # statically to the same model it reproduces this sample's internal loads.
    net_loads: FloatArray
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
    # g-set.  Both are INCLUDED in net_loads (#3); they are carried separately
    # as well because the section cuts report them as their own columns.
    elastic_inertial_loads: Optional[FloatArray] = None
    damping_loads: Optional[FloatArray] = None
    # {name: SectionCutResult} MONSECT running loads at this sample.
    section_loads: Optional[dict[str, "SectionCutResult"]] = None
    # {name: MonitorLoad} MONPNT1/MONPNT3 integrated loads at this sample (#2).
    monitor_loads: Optional[dict[str, "MonitorLoad"]] = None
    rod_forces: dict[int, RodForce] = field(default_factory=dict)   # {eid: RodForce} (#38)


def peak_grid_force(step: "ManeuverStep") -> float:
    """Severity metric for one maneuver sample: peak per-grid net force.

    The maximum over grids of the net applied translational force magnitude
    ``‖F‖`` at that grid (aero + rigid inertia + elastic inertia + damping on a
    transient sample, #3).

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
    basis_info: Optional[dict[str, Any]] = None
    # Step 68 — {name: SectionCutEnvelope} per-station max/min over the run's
    # samples.  None when the deck has no MONSECT cards.
    section_envelope: Optional[dict[str, "SectionCutEnvelope"]] = None
    # #2 — {name: MonitorEnvelope} per-component max/min over the run's
    # samples.  None when the deck has no MONPNT1/MONPNT3 cards.
    monitor_envelope: Optional[dict[str, "MonitorEnvelope"]] = None
