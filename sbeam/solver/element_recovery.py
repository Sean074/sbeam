"""Element force / stress recovery through the line-element registry (#38).

One loop serves SOL 101, SOL 144 (trim and static) and MLOADS; before #38 each
solver carried its own copy of the CBAR loop. CBAR recovery is unchanged and
still lives in ``sol101.py`` (``recover_bar_forces``, ``recover_bar_stresses``);
this module adds the rod and the aggregate.
"""

from dataclasses import dataclass, field

from sbeam.assembly.elements import LineElement, iter_line_elements, line_element, rod_section
from sbeam.model.bulk_data import BulkData
from sbeam.model.element import Cbar
from sbeam.results.results import BarForce, BarStress, RodForce, RodStress
from sbeam.types import FloatArray


def local_end_forces(
    le: LineElement, displacements: FloatArray, grid_index: dict[int, int],
) -> FloatArray:
    """Element-frame nodal 12-vector ``f_local = K_local · T · u`` for any line element."""
    ia = grid_index[le.ga]
    ib = grid_index[le.gb]
    dofs = [6 * ia + d for d in range(6)] + [6 * ib + d for d in range(6)]
    u_local = le.T @ displacements[dofs]
    return le.K_local @ u_local


def rod_force_from_local(eid: int, f_local: FloatArray) -> RodForce:
    """Rod +x-face resultants from the nodal vector, via the §8 sign helper."""
    from sbeam.solver.sol101 import bar_internal_resultants  # single sign source (#37)
    r = bar_internal_resultants(f_local)
    return RodForce(eid=eid, axial=r.p, torque=r.t)


def rod_stress_from_force(eid: int, rf: RodForce, A: float, J: float, c: float) -> RodStress:
    """``σ = P/A``, ``τ = T·C/J`` (NASTRAN-95 ``srod1.f``/``srod2.f``; ``C/J = 0`` at ``J = 0``)."""
    axial = rf.axial / A if A > 0.0 else 0.0
    torsional = rf.torque * c / J if J > 0.0 else 0.0
    return RodStress(eid=eid, axial=axial, torsional=torsional)


@dataclass
class ElementResults:
    """Per-type element recovery dicts, keyed by EID."""
    bar_forces: dict[int, BarForce] = field(default_factory=dict)
    bar_stresses: dict[int, BarStress] = field(default_factory=dict)
    rod_forces: dict[int, RodForce] = field(default_factory=dict)
    rod_stresses: dict[int, RodStress] = field(default_factory=dict)


def recover_line_elements(
    bulk: BulkData, displacements: FloatArray, grid_index: dict[int, int],
    stresses: bool = True,
) -> ElementResults:
    """Recover forces (and stresses) for every registered line element.

    ``stresses=False`` is the MLOADS per-sample path, which keeps forces only.
    """
    from sbeam.solver.sol101 import recover_bar_forces, recover_bar_stresses

    out = ElementResults()
    for elem in iter_line_elements(bulk):
        if isinstance(elem, Cbar):
            out.bar_forces[elem.eid] = recover_bar_forces(
                elem, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)
            if stresses:
                out.bar_stresses[elem.eid] = recover_bar_stresses(
                    elem, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)
            continue
        le = line_element(elem, bulk)
        rf = rod_force_from_local(elem.eid, local_end_forces(le, displacements, grid_index))
        out.rod_forces[elem.eid] = rf
        if stresses:
            sec = rod_section(elem, bulk)
            out.rod_stresses[elem.eid] = rod_stress_from_force(elem.eid, rf, sec.A, sec.J, sec.c)
    return out
