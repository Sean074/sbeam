"""Result data structures for sbeam FEA solver."""

from dataclasses import dataclass, field
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
    reactions: dict = field(default_factory=dict)    # {gid: np.ndarray(6,)} SPC reaction forces
    bar_forces: dict = field(default_factory=dict)   # {eid: BarForce}
    bar_stresses: dict = field(default_factory=dict) # {eid: BarStress}


@dataclass
class Sol103Result:
    frequencies_hz: np.ndarray  # shape (n_modes,) — natural frequencies in Hz
    mode_shapes: np.ndarray     # shape (n_dofs, n_modes) — full global DOF mode shapes
    eigenvalues: np.ndarray     # shape (n_modes,) — raw eigenvalues ω² [rad²/s²]
