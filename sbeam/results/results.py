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
    rigid_derivs: dict                   # {label: {'CZ','CMY','CX','CY'}}
    restrained_derivs: dict              # {label: {'CZ','CMY'}}
    box_gamma: Optional[np.ndarray] = None   # (n_box,) circulation strengths at trim
    total_cl: float = 0.0                # total CL = Fz / (q * sref)
    total_cm: float = 0.0               # total CMy / (q * sref * cref) about x_ref
