from dataclasses import dataclass


@dataclass
class Mat1:
    mid: int
    E: float    # Young's modulus
    G: float    # Shear modulus
    nu: float   # Poisson's ratio
    rho: float  # Mass density
