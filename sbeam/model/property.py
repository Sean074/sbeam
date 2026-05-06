from dataclasses import dataclass


@dataclass
class Pbar:
    pid: int
    mid: int
    A: float   # Cross-sectional area
    I1: float  # Area moment of inertia about local 1-axis
    I2: float  # Area moment of inertia about local 2-axis
    J: float   # Torsional constant
    nsm: float = 0.0  # Non-structural mass per unit length
    # Stress recovery point coordinates (y, z in cross-section plane)
    c1: float = 0.0
    c2: float = 0.0
    d1: float = 0.0
    d2: float = 0.0
    e1: float = 0.0
    e2: float = 0.0
    f1: float = 0.0
    f2: float = 0.0


@dataclass
class Pbush:
    pid: int
    k1: float = 0.0  # Translational stiffness along local x
    k2: float = 0.0  # Translational stiffness along local y
    k3: float = 0.0  # Translational stiffness along local z
    k4: float = 0.0  # Rotational stiffness about local x (torsional)
    k5: float = 0.0  # Rotational stiffness about local y
    k6: float = 0.0  # Rotational stiffness about local z
