from dataclasses import dataclass


@dataclass
class Aeros:
    acsid: int    # aerodynamic coordinate system (0 = basic)
    rcsid: int    # reference coordinate system for rigid body motion (0 = basic)
    cref:  float  # reference chord length
    bref:  float  # reference span
    sref:  float  # reference area
    symxz: int    # +1 = symmetric about XZ plane, -1 = antisymmetric, 0 = none
    symxy: int    # +1 = symmetric about XY plane, -1 = antisymmetric, 0 = none
