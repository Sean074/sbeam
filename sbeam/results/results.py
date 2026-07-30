"""Result data structures for sbeam FEA solver."""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


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
    ref: np.ndarray                 # (3,) reference point in basic CID 0
    totals: np.ndarray              # (6,) Fx,Fy,Fz,Mx,My,Mz in cp frame
    aero: np.ndarray = None         # (6,) aero contribution in cp frame
    inertia: np.ndarray = None      # (6,) inertia contribution (MONPNT3; zero for plain trim)
    reaction: np.ndarray = None     # (6,) SPC/SUPORT reaction contribution (MONPNT3)
    parity: float = 1.0             # symmetry doubling factor applied to all components
    whole_airplane: bool = False    # True when parity≠1 (annotate output to avoid double-up)
    source_ids: list = field(default_factory=list)   # AELIST or SET1 SIDs


@dataclass
class Sol101Result:
    displacements: np.ndarray         # Full displacement vector (n_dofs,)
    reactions: dict = field(default_factory=dict)      # {gid: np.ndarray(6,)} SPC reaction forces
    bar_forces: dict = field(default_factory=dict)     # {eid: BarForce}
    bar_stresses: dict = field(default_factory=dict)   # {eid: BarStress}
    # Note: cbush_forces are in global coordinates (unlike bar_forces which are local)
    cbush_forces: dict = field(default_factory=dict)   # {eid: np.ndarray(6,)} forces at GB (or GA for grounded)


@dataclass
class Sol103Result:
    frequencies_hz: np.ndarray      # shape (n_modes,) — natural frequencies in Hz
    mode_shapes: np.ndarray         # shape (n_dofs, n_modes) — full global DOF mode shapes
    eigenvalues: np.ndarray         # shape (n_modes,) — raw eigenvalues ω² [rad²/s²]
    generalized_masses: np.ndarray  # shape (n_modes,) — phi_i^T M_free phi_i per mode
    # A-set eigendata retained for downstream consumers (Step 59: GAF export,
    # Step 61 modal basis). Populated by run_sol103; default None so older
    # constructors stay valid.
    phi_free: Optional[np.ndarray] = None   # (n_a, n_modes) a-set mode shapes
    free_dofs: Optional[list] = None        # a-set indices into the g-set
    K_free: Optional[object] = None         # (n_a, n_a) a-set stiffness (dense or sparse CSR)
    M_free: Optional[object] = None         # (n_a, n_a) a-set mass (dense or sparse CSR)


@dataclass
class Sol144Result:
    displacements: np.ndarray           # (n_dofs,) full g-set; SPC DOFs zeroed
    bar_forces: dict                    # {eid: BarForce}
    bar_stresses: dict                  # {eid: BarStress}
    q_aa: np.ndarray                    # (n_a, n_a) dense aero stiffness on a-set
    q: float                            # dynamic pressure used in this solve
    free_dofs: list                     # a-set indices into g-set (length n_a)
    k_aa_lu: tuple                      # (lu, piv) from lu_factor(K_aa); reusable by Step 52
    modal_coords: Optional[np.ndarray] = None   # (n_modes,) ξ; None when ROM not used
    phi_free: Optional[np.ndarray] = None       # (n_a, n_modes); None when ROM not used
    k_hh: Optional[np.ndarray] = None           # (n_modes, n_modes) modal structural stiffness
    q_hh: Optional[np.ndarray] = None           # (n_modes, n_modes) modal GAF matrix


@dataclass
class Sol144TrimResult:
    """Result of a SOL 144 static aeroelastic trim subcase."""
    subcase_id: int
    trim_sid: int
    q: float                             # dynamic pressure
    mach: float
    trim_vars: dict                      # {label: value} — all labels (free + prescribed)
    displacements: np.ndarray            # (n_dofs,) full g-set; SPC/SUPORT DOFs zeroed
    bar_forces: dict                     # {eid: BarForce}
    bar_stresses: dict                   # {eid: BarStress}
    q_aa: np.ndarray                     # (n_a, n_a) aerodynamic stiffness on a-set
    free_dofs: list                      # a-set indices into g-set (length n_a)
    k_aa_lu: tuple                       # (lu, piv) for reuse by derivative solver
    rigid_derivs: dict                   # {label: {'CZ','CMY','CMX','CMZ','CX','CY'}}
    restrained_derivs: dict              # {label: {'CZ','CMY','CMX','CMZ'}}
    unrestrained_derivs: Optional[dict] = None   # {label: {'CZ','CMY','CMX','CMZ'}} mean-axis (inertia-relief) column — AE8b; aero labels only
    unrestrained_intercepts: Optional[dict] = None  # {'CZ0','CMY0'} unrestrained w_g-baseline intercepts
    box_gamma: Optional[np.ndarray] = None   # (n_box,) circulation strengths at trim
    total_cl: float = 0.0                # body-axis CZ = Fz / (q * sref) (balances weight at trim)
    total_cm: float = 0.0               # total CMy / (q * sref * cref) about x_ref
    total_cx: float = 0.0                # body-axis CX = Fx / (q * sref) (streamwise, ≈0)
    total_cl_wind: float = 0.0           # wind-axis lift = CZ·cosα − CX·sinα at trim α (genuine CL)
    total_cy: float = 0.0                # body-axis CY = Fy / (q * sref) (side force, ≈0 symmetric)
    total_cmx: float = 0.0               # total roll CMx / (q * sref * bref) about the RCSID origin
    total_cmz: float = 0.0               # total yaw CMz / (q * sref * bref) about the RCSID origin
    # --- Step 56 outputs (f06 blocks, AEROF/APRES, flight-load export) ---
    box_cp: Optional[np.ndarray] = None       # (n_box,) ΔCp per box at trim (normal-projected force/q / area)
    box_forces: Optional[np.ndarray] = None   # (n_box, 3) physical aero force per box = q * (skj@gamma)
    grid_loads: Optional[np.ndarray] = None   # (n_dofs,) g-set aero flight-load vector = g_disp^T (q * f_box)
    # --- Step 53 outputs (balanced maneuver loads & inertia relief) ---
    inertial_loads: Optional[np.ndarray] = None  # (n_dofs,) g-set inertial load = M_ax @ a_all (final trim URDD); feeds MONPNT3 inertia column
    net_loads: Optional[np.ndarray] = None       # (n_dofs,) g-set net maneuver load = grid_loads + inertial_loads (the stress deliverable)
    maneuver_closure: Optional[np.ndarray] = None  # (6,) body-frame resultant (Fx,Fy,Fz,Mx,My,Mz) of net_loads about the moment ref; ≈0 for a balanced free-aircraft maneuver (V-C5/KC9)
    q_div: Optional[float] = None             # critical divergence dynamic pressure (restrained l-set); None if none
    hinge_moments: Optional[dict] = None      # {AESURF label: {'total': HM/q at trim, <trim_label>: dHM/dδ}} about cid1 hinge axis
    trim_mode: str = "determined"             # "determined" or "over-determined" (Step 52)
    monitor_loads: Optional[dict] = None      # {name: MonitorLoad} integrated section loads (MON1–MON3)
    chordcp_echo: Optional[dict] = None       # Step 54 injected-operating-point echo: {'alpha_ref', 'data_machs', 'surfaces': {eid: {'FZ_Q','MY_Q','FZ_Q_VLM'}}}
    # --- Step 60 (MASSSET payload / mass case) ---
    massset_sid: Optional[int] = None         # MASSSET SID selected by the subcase; None = baseline
    massset_label: str = "BASELINE"           # mass-case name for output headers
    massset_mass: float = 0.0                 # total case mass (GPWG) for this configuration
    massset_cg: Optional[tuple] = None        # (cg_x, cg_y, cg_z) of the case mass


@dataclass
class DivergRoot:
    """One divergence root (Step 55)."""
    q_div: float                          # divergence dynamic pressure (positive real root)
    v_div: Optional[float] = None         # divergence speed = sqrt(2*q_div/rho); None when no RHOREF
    mode_shape: Optional[np.ndarray] = None  # (n_dofs,) g-set divergence eigenvector (max-abs normalised)


@dataclass
class DivergMachResult:
    """Divergence sweep results at a single Mach number (Step 55)."""
    mach: float
    roots: list                           # list[DivergRoot] sorted by ascending q_div


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
    mach_results: list                    # list[DivergMachResult]


@dataclass
class ManeuverStep:
    """One output sample of a Phase G0 transient maneuver run."""
    t: float                              # sample time
    trim_vars: dict                       # {label: value} — commanded/held δ(t) at this time
    displacements: np.ndarray             # (n_dofs,) g-set; SPC/SUPORT DOFs zeroed
    bar_forces: dict                      # {eid: BarForce}
    grid_loads: np.ndarray                # (n_dofs,) g-set aero flight load at this instant
    inertial_loads: np.ndarray            # (n_dofs,) g-set inertial load = M_ax · a_urdd(t)
    net_loads: np.ndarray                 # (n_dofs,) net (aero + inertial) load — stress deliverable
    closure: np.ndarray                   # (6,) body-frame resultant (Fx..Mz) of net_loads about the ref
    Fz_aero: float = 0.0                  # instantaneous aero Fz (force/q · q) = lift
    My_aero: float = 0.0                  # instantaneous aero pitching moment about x_ref


@dataclass
class ManeuverResult:
    """Result of a Phase G0 (DLM-free quasi-steady) transient maneuver subcase."""
    subcase_id: int
    mloads_sid: int
    trim_sid: int                         # initial-condition TRIM sid (via MLDTRIM)
    q: float                              # dynamic pressure
    mach: float
    labels: list                          # all trim-variable labels (column order)
    times: np.ndarray                     # (n_out,) output sample times
    steps: list                           # list[ManeuverStep], one per output sample
    crit_index: int                       # index into steps of the peak |net force| sample
    mldprnt_items: list = field(default_factory=list)  # requested ASCII-print quantity keywords
