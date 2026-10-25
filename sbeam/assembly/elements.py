"""Line-element registry — the per-element interface for CBAR and CROD/CONROD (#38).

Assembly, GPWG and force recovery used to iterate ``bulk.cbars`` directly. This
module is the single place that knows how each two-node line element builds its
released local stiffness, its transform, its mass and its section data
(``docs/30_future/designs/rod_element_crod.md`` D1–D4):

- :func:`iter_line_elements` yields every CBAR, CROD and CONROD (in that order,
  each in deck order), so a loop written against it picks up every type.
- :func:`line_element` returns the :class:`LineElement` record (geometry +
  condensed local stiffness + transform) used by stiffness assembly and by
  ``K·T·u`` force recovery.
- :func:`line_element_mass_global` / :func:`line_element_mass_per_length` are
  the mass side, kept separate so recovery (called per MLOADS time step) never
  builds a mass matrix.

The CBAR entry wraps ``released_local_stiffness``, ``transform_matrix`` and
``element_mass_global`` exactly as the pre-#38 loops did, so a deck without rods
assembles bit-identically. Only CBAR and the rod are registered (CLAUDE.md
rule 5); CBUSH keeps its own path.
"""

from dataclasses import dataclass
from typing import Callable, Iterator, Union

import numpy as np
from scipy.linalg import block_diag

from sbeam.assembly.mass_matrix import element_mass_global
from sbeam.assembly.stiffness import released_local_stiffness, transform_matrix
from sbeam.model.bulk_data import BulkData
from sbeam.model.element import Cbar, Conrod, Crod
from sbeam.model.grid import Grid
from sbeam.model.material import Mat1
from sbeam.model.property import Pbar
from sbeam.types import FloatArray

#: The element cards the registry knows.
LineElementCard = Union[Cbar, Crod, Conrod]

#: Local 12-DOF indices a rod leaves at exactly zero stiffness (all shear and
#: bending rows: Ty, Tz, Ry, Rz at both ends).
ROD_ZERO_DOFS = (1, 2, 4, 5, 7, 8, 10, 11)


# --------------------------------------------------------------------------- #
# Section data
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RodSection:
    """Rod section data, whether it came from a PROD or inline on a CONROD (D4)."""
    mid: int
    A: float
    J: float
    c: float      # torsional stress coefficient: tau = T * c / J
    nsm: float    # non-structural mass per unit length


def rod_section(elem: Union[Crod, Conrod], bulk: BulkData) -> RodSection:
    """The only place that distinguishes CROD (+PROD) from CONROD."""
    if isinstance(elem, Conrod):
        return RodSection(mid=elem.mid, A=elem.A, J=elem.J, c=elem.c, nsm=elem.nsm)
    prod = bulk.prods[elem.pid]
    return RodSection(mid=prod.mid, A=prod.A, J=prod.J, c=prod.c, nsm=prod.nsm)


# --------------------------------------------------------------------------- #
# The record
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LineElement:
    """Geometry, condensed local stiffness and transform of one two-node element.

    ``K_local`` is the 12×12 local stiffness with any releases already condensed
    (zero rows/columns at released or absent DOFs); ``T`` maps global to local
    (``u_local = T @ u_global``). Local DOF order per node ``[Tx, Ty, Tz, Rx, Ry,
    Rz]``, node A first.
    """
    eid: int
    kind: str          # "CBAR", "CROD" or "CONROD"
    ga: int
    gb: int
    L: float
    K_local: FloatArray
    T: FloatArray

    def global_stiffness(self) -> FloatArray:
        """12×12 element stiffness in the basic frame: ``Tᵀ K_local T``."""
        return self.T.T @ self.K_local @ self.T


def _length(ga: Grid, gb: Grid) -> float:
    ga_pos = np.array([ga.x, ga.y, ga.z])
    gb_pos = np.array([gb.x, gb.y, gb.z])
    return float(np.linalg.norm(gb_pos - ga_pos))


# --------------------------------------------------------------------------- #
# CBAR entry — exactly the pre-#38 element_stiffness_global arithmetic
# --------------------------------------------------------------------------- #

def cbar_line_element(
    cbar: Cbar, grids: dict[int, Grid], pbars: dict[int, Pbar], mat1s: dict[int, Mat1],
) -> LineElement:
    """CBAR record on the explicit dict signature the solver recovery wrapper keeps."""
    pbar = pbars[cbar.pid]
    mat1 = mat1s[pbar.mid]
    L = _length(grids[cbar.ga], grids[cbar.gb])
    K_local, _ = released_local_stiffness(pbar, mat1, L, cbar.pa, cbar.pb)
    T = transform_matrix(cbar, grids)
    return LineElement(eid=cbar.eid, kind="CBAR", ga=cbar.ga, gb=cbar.gb,
                       L=L, K_local=K_local, T=T)


def _cbar_entry(cbar: Cbar, bulk: BulkData) -> LineElement:
    return cbar_line_element(cbar, bulk.grids, bulk.pbars, bulk.mat1s)


# --------------------------------------------------------------------------- #
# Rod entry (D2, D3)
# --------------------------------------------------------------------------- #

def rod_frame(eid: int, kind: str, ga: Grid, gb: Grid) -> FloatArray:
    """3×3 rotation (rows = local axes in the basic frame) for a rod.

    ``e_x = (GB − GA)/L`` as for CBAR (``09_conventions.md`` §9). A rod has no
    orientation vector, so ``e_y`` is a deterministic unit vector normal to
    ``e_x`` built from the basic axis least aligned with it, and
    ``e_z = e_x × e_y``. The rod stiffness and mass are non-zero only on the
    axial / torsional DOFs and on isotropic translation blocks, so the global
    matrices do not depend on this choice (design gate G5b).
    """
    dx = np.array([gb.x - ga.x, gb.y - ga.y, gb.z - ga.z], dtype=float)
    L = float(np.linalg.norm(dx))
    if L < 1e-12:
        raise ValueError(f"{kind} {eid}: nodes GA={ga.gid} and GB={gb.gid} are coincident")
    e_x = dx / L
    v = np.zeros(3)
    v[int(np.argmin(np.abs(e_x)))] = 1.0
    v_perp = v - np.dot(v, e_x) * e_x
    e_y = v_perp / np.linalg.norm(v_perp)
    e_z = np.cross(e_x, e_y)
    return np.array([e_x, e_y, e_z])


def rod_local_stiffness(E: float, G: float, A: float, J: float, L: float) -> FloatArray:
    """12×12 rod stiffness in local axes: ``EA/L`` on (0, 6), ``GJ/L`` on (3, 9).

    NASTRAN-95 ``krod.f`` (``DSCL = A·E/L``, ``DSCR = J·G/L`` on ``n nᵀ``) written
    in the element frame. Every other row and column is exactly zero.
    """
    K = np.zeros((12, 12))
    a = E * A / L
    K[0, 0] = a;  K[6, 6] = a
    K[0, 6] = -a; K[6, 0] = -a
    t = G * J / L
    K[3, 3] = t;  K[9, 9] = t
    K[3, 9] = -t; K[9, 3] = -t
    return K


def rod_local_mass(m_lin: float, L: float) -> FloatArray:
    """12×12 consistent translational rod mass, no rotary or torsional inertia (D3).

    ``m·L/6·[2 1; 1 2]`` on each translation pair (0,6), (1,7), (2,8) with
    ``m = ρA + NSM`` — the 3D-truss consistent mass (MSC ``COUPMASS`` for CROD).
    The rotational rows are zero, as in MSC and NASTRAN-95: a rod has no
    ``I1``/``I2`` for the CBAR ``ρ(I1+I2)`` term and ``J`` is a stiffness
    constant, not a mass moment. Rigid-body mass is ``m·L`` exactly.
    """
    M = np.zeros((12, 12))
    c = m_lin * L / 6.0
    for i in (0, 1, 2):
        M[i, i] = 2 * c;       M[i + 6, i + 6] = 2 * c
        M[i, i + 6] = c;       M[i + 6, i] = c
    return M


def _rod_entry(elem: Union[Crod, Conrod], bulk: BulkData) -> LineElement:
    kind = "CONROD" if isinstance(elem, Conrod) else "CROD"
    sec = rod_section(elem, bulk)
    mat1 = bulk.mat1s[sec.mid]
    ga, gb = bulk.grids[elem.ga], bulk.grids[elem.gb]
    R = rod_frame(elem.eid, kind, ga, gb)
    L = _length(ga, gb)
    K_local = rod_local_stiffness(mat1.E, mat1.G, sec.A, sec.J, L)
    return LineElement(eid=elem.eid, kind=kind, ga=elem.ga, gb=elem.gb,
                       L=L, K_local=K_local, T=block_diag(R, R, R, R))


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_BUILDERS: dict[type, Callable[..., LineElement]] = {
    Cbar: _cbar_entry,
    Crod: _rod_entry,
    Conrod: _rod_entry,
}


def line_element(elem: LineElementCard, bulk: BulkData) -> LineElement:
    """Build the :class:`LineElement` record for any registered element card."""
    try:
        builder = _BUILDERS[type(elem)]
    except KeyError:
        raise TypeError(f"{type(elem).__name__} is not a registered line element") from None
    return builder(elem, bulk)


def iter_line_elements(bulk: BulkData) -> Iterator[LineElementCard]:
    """Every registered line element: CBARs, then CRODs, then CONRODs, in deck order.

    The CBAR pass runs first and in insertion order so that the COO scatter of
    a rodless deck sums in the same order as before #38 (bit-identity).
    """
    yield from bulk.cbars.values()
    yield from bulk.crods.values()
    yield from bulk.conrods.values()


def line_element_mass_per_length(elem: LineElementCard, bulk: BulkData) -> float:
    """``ρA + NSM`` for the element, the GPWG line-mass density."""
    if isinstance(elem, Cbar):
        pbar = bulk.pbars[elem.pid]
        mat1 = bulk.mat1s[pbar.mid]
        return mat1.rho * pbar.A + pbar.nsm
    sec = rod_section(elem, bulk)
    mat1 = bulk.mat1s[sec.mid]
    return mat1.rho * sec.A + sec.nsm


def line_element_mass_global(elem: LineElementCard, bulk: BulkData) -> FloatArray:
    """12×12 element mass in the basic frame (CBAR consistent + congruently
    condensed; rod consistent translational, D3)."""
    if isinstance(elem, Cbar):
        return element_mass_global(elem, bulk.grids, bulk.pbars, bulk.mat1s)
    le = line_element(elem, bulk)
    M_local = rod_local_mass(line_element_mass_per_length(elem, bulk), le.L)
    return le.T.T @ M_local @ le.T
