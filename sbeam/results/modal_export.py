"""Reduced modal model export: MHH, KHH, PHIA, PHIX as OP4 + Universal file (#100).

A SOL 103 subcase with ``MODEXP(OP4,UF) = n`` writes, next to the deck:

* ``<stem>.op4`` — MSC OUTPUT4 ASCII, real double: ``MHH`` and ``KHH`` (n_modes²,
  symmetric), ``PHIA`` (the a-set modes, MSC's meaning) and ``PHIX`` (the modes at the
  grids of SET n, six rows per grid in SET order, T1 T2 T3 R1 R2 R3, basic axes).  The
  layout follows MSC's ASCII OUTPUT4 as Flaps reads it (``flaps_env/work/demo/ha145b.op4``):
  a ``NCOL NROW FORM TYPE NAME FORMAT`` header, ``ICOL IROW NW`` column records from the
  first to the last non-zero row, and an ``NCOL+1`` terminator record.
* ``<stem>_dofmap.csv`` — the grid and component of every PHIA and PHIX row.
* ``<stem>.uf`` — Universal file datasets 15 (grids), 82 (element traces) and 55 (one
  real normal mode per dataset, six DOF per node).  Dataset 55's records for a normal mode
  are written as the Flaps-written ``fma.nodal.uf`` lays out its complex modes; no UF
  specification is in the library, so the layout is *unverified* beyond that file and a
  Flaps import (the manual G5 gate).

MHH and KHH are formed as ΦᵀMΦ and ΦᵀKΦ on the a-set, never assumed to be I and
diag(ω²).  Units are the deck's own (no conversion).  A free-free model (no SPC, six
zero-frequency modes) has its rigid-body modes replaced by geometric rigid vectors about
the C.G., mass-orthonormalised (Löwdin): the eigensolver returns an arbitrary mixture of
them, and a consumer such as sgear wants heave, pitch and roll as such.
"""
import csv
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.reduction import AsetReduction, reduce_to_aset
from sbeam.assembly.rigid_body import build_rigid_vectors_g
from sbeam.gpwg import reduce_rigid_body_mass, rigid_body_mass_matrix
from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.results.results import Sol103Result
from sbeam.types import FloatArray

_COMPONENTS = ("T1", "T2", "T3", "R1", "R2", "R3")
#: A mode is rigid when its eigenvalue is below this fraction of the largest one
_RIGID_TOL = 1.0e-8


@dataclass
class ModalModel:
    """The matrices one MODEXP request writes, with the meaning of their rows."""
    mhh: FloatArray
    khh: FloatArray
    phia: FloatArray
    phix: FloatArray
    frequencies_hz: FloatArray
    a_rows: list[tuple[int, str]]     # (grid, component) of each PHIA row
    x_rows: list[tuple[int, str]]     # (grid, component) of each PHIX row
    phi_g: FloatArray                 # g-set modes (for the Universal file)
    rigid_replaced: bool


def interface_grids(cc: CaseControl, subcase: SubcaseControl, bulk: BulkData) -> list[int]:
    """The grids of the subcase's MODEXP SET, in SET order (QRG p.625).

    A SET under the SUBCASE is that subcase's; otherwise the one above every SUBCASE.
    An ID that is not a grid is skipped with a warning (MSC ignores it, p.625); ``ALL``
    is every grid in ID order.
    """
    n = subcase.modexp_set
    if n is None:
        raise ValueError(f"Subcase {subcase.subcase_id}: no MODEXP request")
    if n in subcase.sets:
        members = subcase.sets[n]
    elif n in cc.sets:
        members = cc.sets[n]
    else:
        raise ValueError(f"Subcase {subcase.subcase_id}: MODEXP = {n} names no SET {n} in "
                         "case control")
    if members is None:
        return sorted(bulk.grids)
    grids = [g for g in members if g in bulk.grids]
    skipped = [g for g in members if g not in bulk.grids]
    if skipped:
        warnings.warn(f"MODEXP SET {n}: {len(skipped)} ID(s) are not grids and are skipped "
                      f"({skipped[:5]}…), as MSC ignores them (QRG p.625)", UserWarning)
    if not grids:
        raise ValueError(f"MODEXP SET {n}: no member is a grid of the model")
    return grids


def _expand(red: AsetReduction, phi_a: FloatArray, n_dofs: int) -> FloatArray:
    """a-set vectors to the g-set, as ``run_sol103`` expands its modes."""
    if red.dep_dofs:
        phi_red = np.zeros((red.n_red, phi_a.shape[1]))
        phi_red[red.free_local, :] = phi_a
        return np.asarray(red.T @ phi_red)
    full = np.zeros((n_dofs, phi_a.shape[1]))
    full[red.free_dofs, :] = phi_a
    return full


def build_modal_model(cc: CaseControl, bulk: BulkData, subcase: SubcaseControl,
                      result: Sol103Result) -> ModalModel:
    """The MHH / KHH / PHIA / PHIX of one SOL 103 subcase (#100)."""
    if result.phi_free is None or result.K_free is None or result.M_free is None \
            or result.free_dofs is None:
        raise ValueError("MODEXP needs the a-set matrices run_sol103 retains")
    eigrl = bulk.eigrls.get(subcase.method_sid) if subcase.method_sid is not None else None
    if eigrl is not None and (eigrl.norm or "MASS").upper() != "MASS":
        raise ValueError(f"MODEXP: EIGRL {eigrl.sid} NORM = {eigrl.norm}; the modal model is "
                         "exported mass-normalised only — set NORM = MASS (#100)")
    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)
    red = reduce_to_aset(bulk, grid_index, subcase.spc_sid)
    phi_a = np.array(result.phi_free, dtype=float)
    phi_g = np.array(result.mode_shapes, dtype=float)
    k_a = result.K_free
    m_a = result.M_free

    lam = np.einsum("ij,ij->j", phi_a, np.asarray(k_a @ phi_a))
    rigid = np.flatnonzero(lam < _RIGID_TOL * max(float(np.max(lam)), 1.0e-300))
    replaced = False
    if subcase.spc_sid is None and len(rigid) == 6:
        cg = _centre_of_gravity(bulk)
        r_g = build_rigid_vectors_g(bulk, grid_index, [1, 2, 3, 4, 5, 6], cg)
        # The a-set rows are a row selection of the g-set (rigid vectors are displacements);
        # expanding them back must regenerate every dependent DOF, as build_rigid_modes
        # asserts for the maneuver basis
        r_a = r_g[red.free_dofs, :]
        if not np.allclose(_expand(red, r_a, n_dofs), r_g, atol=1e-9 * max(1.0, np.abs(r_g).max())):
            raise ValueError("MODEXP: a rigid element is not rigid-body exact; the geometric "
                             "rigid modes cannot be exported")
        m_r = r_a.T @ np.asarray(m_a @ r_a)
        w, v = np.linalg.eigh(0.5 * (m_r + m_r.T))
        c = v @ np.diag(w ** -0.5) @ v.T          # Löwdin: (RᵀMR)^(-1/2)
        phi_a[:, rigid] = r_a @ c
        phi_g[:, rigid] = r_g @ c
        replaced = True
    elif len(rigid):
        warnings.warn(f"MODEXP: {len(rigid)} zero-frequency mode(s) are exported as the "
                      "eigensolver returned them; geometric rigid vectors replace them only "
                      "for a free-free model (no SPC, six rigid modes)", UserWarning)

    mhh = phi_a.T @ np.asarray(m_a @ phi_a)
    khh = phi_a.T @ np.asarray(k_a @ phi_a)
    gids_by_index = {i: gid for gid, i in grid_index.items()}
    a_rows = [(gids_by_index[d // 6], _COMPONENTS[d % 6]) for d in result.free_dofs]
    grids = interface_grids(cc, subcase, bulk)
    x_idx = [6 * grid_index[g] + c for g in grids for c in range(6)]
    x_rows = [(g, comp) for g in grids for comp in _COMPONENTS]
    return ModalModel(mhh=mhh, khh=khh, phia=phi_a, phix=phi_g[x_idx, :],
                      frequencies_hz=np.asarray(result.frequencies_hz), a_rows=a_rows,
                      x_rows=x_rows, phi_g=phi_g, rigid_replaced=replaced)


def _centre_of_gravity(bulk: BulkData) -> FloatArray:
    """C.G. in basic axes from MO about the basic origin (the GPWG reduction, #90)."""
    t = reduce_rigid_body_mass(rigid_body_mass_matrix(bulk, 0), 0)
    return np.array([t.cg[2][0], t.cg[2][1], t.cg[0][2]])


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------

def write_op4(path: str, matrices: Sequence[tuple[str, FloatArray, int]]) -> None:
    """MSC OUTPUT4 ASCII, real double precision (TYPE 2), format 1P,3E23.16.

    ``matrices`` is ``(name, array, form)``: FORM 1 square, 2 rectangular, 6 symmetric.
    """
    lines: list[str] = []
    for name, a, form in matrices:
        a = np.asarray(a, dtype=float)
        nrow, ncol = a.shape
        lines.append(f"{ncol:8d}{nrow:8d}{form:8d}{2:8d}{name:<8s}1P,3E23.16")
        for j in range(ncol):
            nz = np.flatnonzero(a[:, j])
            if not len(nz):
                continue
            first, last = int(nz[0]), int(nz[-1])
            values = a[first:last + 1, j]
            lines.append(f"{j + 1:8d}{first + 1:8d}{len(values):8d}")
            for k in range(0, len(values), 3):
                lines.append("".join(f"{v:23.16E}" for v in values[k:k + 3]))
        lines.append(f"{ncol + 1:8d}{1:8d}{1:8d}")
        lines.append(f"{1.0:23.16E}")
    Path(path).write_text("\n".join(lines) + "\n")


def write_dofmap(path: str, model: ModalModel) -> None:
    """Grid and component of every PHIA and PHIX row; units and normalisation in the header."""
    with open(path, "w", newline="") as fh:
        fh.write("# sbeam reduced modal model (#100). Mass-normalised modes (MHH = I); "
                 "KHH = PhiT K Phi.\n# Units: the deck's own consistent units. "
                 "Rows in basic axes; components T1 T2 T3 R1 R2 R3.\n"
                 f"# Rigid-body modes replaced by geometric vectors about the C.G.: "
                 f"{'yes' if model.rigid_replaced else 'no'}\n")
        w = csv.writer(fh)
        w.writerow(["matrix", "row", "grid", "component"])
        for name, rows in (("PHIA", model.a_rows), ("PHIX", model.x_rows)):
            for k, (gid, comp) in enumerate(rows, start=1):
                w.writerow([name, k, gid, comp])


def _element_traces(bulk: BulkData) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for coll in (bulk.cbars, bulk.crods, bulk.conrods, bulk.plotels, bulk.cbushs):
        for e in coll.values():
            ga, gb = getattr(e, "ga", None), getattr(e, "gb", None)
            if ga is not None and gb is not None and ga in bulk.grids and gb in bulk.grids:
                pairs.append((ga, gb))
    return pairs


def write_universal(path: str, bulk: BulkData, model: ModalModel,
                    title: str = "sbeam") -> None:
    """Universal file: datasets 15 (grids), 82 (traces), 55 (real modes, 6 DOF)."""
    grid_index = build_grid_index(bulk)
    lines = ["    -1", "    15"]
    for gid in sorted(bulk.grids):
        g = bulk.grids[gid]
        lines.append(f"{gid:10d}{0:10d}{0:10d}{1:10d}{g.x:13.5e}{g.y:13.5e}{g.z:13.5e}")
    lines.append("    -1")
    trace: list[int] = []
    for ga, gb in _element_traces(bulk):
        trace += [ga, gb, 0]
    if trace:
        lines += ["    -1", "    82", f"{1:10d}{len(trace):10d}{1:10d}", title[:80]]
        for k in range(0, len(trace), 8):
            lines.append("".join(f"{n:10d}" for n in trace[k:k + 8]))
        lines.append("    -1")
    for m in range(model.phi_g.shape[1]):
        lines += ["    -1", "    55"] + [title[:80]] * 5
        # model 1 structural, analysis 2 normal mode, data 3 = 6 DOF, specific 8
        # displacement, data type 2 real single, NDV 6
        lines.append("".join(f"{v:10d}" for v in (1, 2, 3, 8, 2, 6)))
        lines.append("".join(f"{v:10d}" for v in (2, 4, 1, m + 1)))
        lines.append("".join(f"{v:13.5e}" for v in (
            float(model.frequencies_hz[m]), float(model.mhh[m, m]), 0.0, 0.0)))
        for gid in sorted(bulk.grids):
            i = grid_index[gid]
            lines.append(f"{gid:10d}")
            lines.append("".join(f"{v:13.5e}" for v in model.phi_g[6 * i:6 * i + 6, m]))
        lines.append("    -1")
    Path(path).write_text("\n".join(lines) + "\n")


def export_modal_model(stem: str, cc: CaseControl, bulk: BulkData,
                       subcase: SubcaseControl, result: Sol103Result,
                       formats: Optional[Sequence[str]] = None) -> list[str]:
    """Write the files one MODEXP request asks for; returns their paths."""
    model = build_modal_model(cc, bulk, subcase, result)
    formats = formats or subcase.modexp_formats or ("OP4", "UF")
    written: list[str] = []
    if "OP4" in formats:
        n_m, n_a, n_x = model.mhh.shape[0], model.phia.shape[0], model.phix.shape[0]
        write_op4(f"{stem}.op4", [
            ("MHH", model.mhh, 6), ("KHH", model.khh, 6),
            ("PHIA", model.phia, 1 if n_a == n_m else 2),
            ("PHIX", model.phix, 1 if n_x == n_m else 2)])
        write_dofmap(f"{stem}_dofmap.csv", model)
        written += [f"{stem}.op4", f"{stem}_dofmap.csv"]
    if "UF" in formats:
        write_universal(f"{stem}.uf", bulk, model, title=cc.title or "sbeam")
        written.append(f"{stem}.uf")
    return written
