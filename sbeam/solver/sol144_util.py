"""SOL 144 shared utilities (P13/DEF-R1 split from sol144.py).

AeroCache (Mach-keyed AeroModel memoization, AE9), URDD reference-frame
rotations, g-set load resultants, the inertial sensitivity matrix M_ax
(Q4/DEF-M3), SUPORT a-set indexing, and the box-force moment resultants
(AE1 Step E convention).  Pure helpers — no trim solve, no derivative logic.
All names remain importable from ``sbeam.solver.sol144`` (facade).
"""

import warnings
from typing import Any, Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.aero.aero_model import AeroModel, build_aero_model
from sbeam.aero.panel import AeroBox
from sbeam.types import FloatArray


class AeroCache:
    """Mach-keyed cache of AeroModels for multi-Mach SOL 144 (AE9).

    The VLM AIC depends on Mach (Prandtl–Glauert / Göthert β scaling), so each
    TRIM subcase at a distinct Mach needs its own AeroModel.  Building the AIC is
    the expensive step, so models are memoized by Mach (rounded to 6 dp) and the
    build-once fixture pattern still holds across subcases at the same Mach.

    The cache is seeded with a prebuilt AeroModel so existing callers that pass a
    model built at ``AEROS.mach`` incur no rebuild when ``TRIM.mach`` matches.
    """

    _MACH_DP = 6

    def __init__(self, bulk: BulkData, grid_index: dict[int, int], seed: Optional[AeroModel] = None):
        self.bulk = bulk
        self.grid_index = grid_index
        self._cache: dict[float, AeroModel] = {}
        if seed is not None:
            self._cache[round(float(seed.mach), self._MACH_DP)] = seed

    def get(self, mach: float) -> AeroModel:
        """Return the AeroModel for ``mach``, building and memoizing on a miss."""
        key = round(float(mach), self._MACH_DP)
        model = self._cache.get(key)
        if model is None:
            model = build_aero_model(self.bulk, grid_index=self.grid_index, mach=mach)
            self._cache[key] = model
        return model



def urdd_rcsid_to_basic(
    vec: FloatArray, label_to_col: dict[str, int], R_rcsid: FloatArray, has_rcsid: bool
) -> FloatArray:
    """Rotate the URDD translational/rotational triples of a label-ordered trim
    vector from the RCSID frame into the basic CID 0 frame (AE5).

    ``vec`` is ordered by ``all_labels``; ``label_to_col`` maps each label to its
    index.  Non-URDD entries (aero labels) pass through unchanged.  Absent URDD
    components are treated as zero in the rotation, then only the present ones are
    written back.  Returns a copy; the input is not mutated.
    """
    out = vec.copy()
    if not has_rcsid:
        return out
    for triple_lbls in (['URDD1', 'URDD2', 'URDD3'], ['URDD4', 'URDD5', 'URDD6']):
        present = {l: label_to_col[l] for l in triple_lbls if l in label_to_col}
        if not present:
            continue
        triple = np.array([
            out[label_to_col[l]] if l in label_to_col else 0.0 for l in triple_lbls
        ])
        triple_basic = R_rcsid @ triple
        for i, lbl in enumerate(triple_lbls):
            if lbl in present:
                out[present[lbl]] = triple_basic[i]
    return out


def urdd_basic_to_rcsid(
    vec: FloatArray, label_to_col: dict[str, int], R_rcsid: FloatArray, has_rcsid: bool
) -> FloatArray:
    """Inverse of ``urdd_rcsid_to_basic``: rotate the URDD triples of a
    label-ordered vector from the basic CID 0 frame into the RCSID frame.

    Same conventions: non-URDD entries pass through, absent URDD components are
    treated as zero in the rotation, only present ones are written back, and a
    copy is returned.  Used by the Step 63 free-flight recovery to express the
    basic-frame ``ξ̈_r`` accelerations as URDD label values.

    If the rotation puts non-negligible content onto an absent URDD component
    (no AESTAT label to carry it), a ``UserWarning`` names the component — the
    dropped content would silently vanish from the label bookkeeping.
    """
    out = vec.copy()
    if not has_rcsid:
        return out
    R_inv = R_rcsid.T
    for triple_lbls in (['URDD1', 'URDD2', 'URDD3'], ['URDD4', 'URDD5', 'URDD6']):
        present = {l: label_to_col[l] for l in triple_lbls if l in label_to_col}
        if not present:
            continue
        triple = np.array([
            out[label_to_col[l]] if l in label_to_col else 0.0 for l in triple_lbls
        ])
        triple_rcsid = R_inv @ triple
        scale = max(1.0, float(np.abs(triple_rcsid).max()))
        for i, lbl in enumerate(triple_lbls):
            if lbl in present:
                out[present[lbl]] = triple_rcsid[i]
            elif abs(triple_rcsid[i]) > 1e-10 * scale:
                warnings.warn(
                    f"urdd_basic_to_rcsid: the RCSID rotation places "
                    f"{triple_rcsid[i]:.4g} on {lbl}, which has no AESTAT "
                    "label — that acceleration component is dropped from the "
                    "URDD bookkeeping.",
                    UserWarning,
                )
    return out


def load_resultant(
    loads_g: FloatArray, bulk: BulkData, grid_index: dict[int, int], ref_pos: FloatArray
) -> FloatArray:
    """Body-frame 6-component resultant (Fx,Fy,Fz, Mx,My,Mz) of a g-set load
    vector about ``ref_pos``, summed over all grids.

    Moments are taken about the (undeformed) grid positions in the basic CID 0
    frame — the small-deflection convention used throughout the trim path.
    """
    F = np.zeros(3)
    M = np.zeros(3)
    for gid, gi in grid_index.items():
        f = loads_g[gi * 6: gi * 6 + 3]
        m = loads_g[gi * 6 + 3: gi * 6 + 6]
        g = bulk.grids[gid]
        r = np.array([g.x, g.y, g.z]) - ref_pos
        F += f
        M += m + np.cross(r, f)
    return np.concatenate([F, M])


#: URDD label -> rigid DOF component (1-6).  URDD1-3 are translational
#: accelerations along basic x/y/z; URDD4-6 are angular accelerations about
#: basic x/y/z, referred to ``suport_pos``.
_URDD_DOF = {f"URDD{d}": d for d in range(1, 7)}


def build_inertial_cols(
    bulk: BulkData,
    all_labels: list[str],
    grid_index: dict[int, int],
    suport_pos: FloatArray,
    massset_sid: Optional[int] = None,
    M_gg: Optional[Any] = None,
) -> FloatArray:
    """Inertial sensitivity matrix M_ax on the full g-set — basic frame.

    Returns (n_g, n_labels) where column k is dF/dURDD_k (force per unit
    acceleration for URDD labels; zero for aerodynamic labels).  All values
    are expressed in the basic CID 0 frame; RCSID-frame URDD values must be
    transformed to basic before multiplying.

    Definition — one mass model (Q4 / DEF-M3)
    -----------------------------------------
    A unit URDD_k is, by definition, a unit rigid-body acceleration of the whole
    airframe about ``suport_pos``.  The d'Alembert load it induces is therefore

        M_ax[:, k] = -M_gg @ phi_r_g[:, dof(k)]

    with ``phi_r_g`` the geometric rigid-body vectors from
    ``assembly.rigid_body.build_rigid_vectors_g`` and ``M_gg`` the *same*
    consistent mass matrix the elastic equations use.  This is not an
    approximation of the inertia model — it *is* the inertia model, so
    ``M_ax = -M_aa Phi_r`` holds column for column on the a-set as an identity
    (``red.reduce_rect`` is ``T^T .`` and ``T Phi_r_a = Phi_r_g``).

    Before this was unified, M_ax was a hand-rolled *lumped* model that read
    ``conm2.m`` and the diagonal ``i11/i22/i33`` in the basic frame only.  It
    silently dropped CONM2 offset transport, products of inertia, CONM2 CID
    rotation and PBAR ``nsm``, and mixed lumped CBAR half-masses with the
    consistent ``M_aa`` — all of which ``assemble_global_mass`` handles and all
    of which now come along for free.

    Args:
        bulk:        parsed model.
        all_labels:  trim labels, in column order.
        grid_index:  {gid: i} — must be the g-set ordering ``M_gg`` was built on.
        suport_pos:  rigid-acceleration reference point, basic coordinates.
        massset_sid: MASSSET mass case (Step 60); ignored when ``M_gg`` is given.
        M_gg:        pre-assembled global mass matrix for this mass case.  Pass
                     it when the caller already has one — it is the single most
                     expensive object here.  When ``None`` it is assembled from
                     ``bulk``/``massset_sid``.

    Raises:
        ValueError: if a supplied ``M_gg`` does not match the g-set size.
    """
    from sbeam.assembly.rigid_body import build_rigid_vectors_g

    n_g = 6 * len(grid_index)
    M = np.zeros((n_g, len(all_labels)))

    # {rigid DOF -> column} for the URDD labels actually present.
    urdd_cols: dict[int, int] = {}
    for col, label in enumerate(all_labels):
        dof = _URDD_DOF.get(label.upper())
        if dof is not None:
            urdd_cols[dof] = col
    if not urdd_cols:
        return M            # aerodynamic labels only — M_ax is identically zero

    if M_gg is None:
        M_gg = assemble_global_mass(bulk, massset_sid)
    elif M_gg.shape != (n_g, n_g):
        raise ValueError(
            f"build_inertial_cols: supplied M_gg is {M_gg.shape[0]}x"
            f"{M_gg.shape[1]} but the g-set has {n_g} DOFs — the mass matrix "
            "and grid_index must come from the same model."
        )

    dofs = sorted(urdd_cols)
    phi_r_g = build_rigid_vectors_g(bulk, grid_index, dofs, suport_pos)
    cols = -np.asarray(M_gg @ phi_r_g)          # (n_g, n_dofs)

    for k, dof in enumerate(dofs):
        M[:, urdd_cols[dof]] = cols[:, k]
    return M


def get_suport_local(
    bulk: BulkData, free_dofs: list[int], grid_index: dict[int, int]
) -> list[int]:
    """Return local a-set indices corresponding to SUPORT DOFs.

    Uses bulk.supports (list[Suport]).  DOF string "35" means Tz (3) and Ry (5).
    """
    g_to_local = {g_dof: loc for loc, g_dof in enumerate(free_dofs)}
    suport_local = []
    for sup in bulk.supports:
        if sup.gid not in grid_index:
            continue
        base = grid_index[sup.gid] * 6
        for ch in sup.dofs:
            g_dof = base + (int(ch) - 1)
            if g_dof in g_to_local:
                suport_local.append(g_to_local[g_dof])
    return suport_local




def pitch_moment(f_box_vec: FloatArray, boxes: list[AeroBox], x_ref: float) -> float:
    """Nose-up-positive aerodynamic pitching moment about ``x_ref`` (AE1 Step E).

    Single source for the moment-arm convention `My = −ΣFz·(x_force − x_ref)`
    used throughout the trim chain.  The sign is nose-up positive, matching
    `solve_rigid_cl.CM` (`vlm.py`) and NASTRAN's Cm convention.  Each box load
    acts at its ¼-chord bound-vortex midpoint `box.force_point` (AE6), not the
    ¾-chord collocation point.

    Args:
        f_box_vec: (3·n_box,) per-box force vector [Fx0, Fy0, Fz0, Fx1, …] in
                   force/q units (skj @ Cp).
        boxes:     AeroBox list (provides force_point[0] moment arms).
        x_ref:     moment reference x-coordinate in basic CID 0 (RCSID origin).

    Returns:
        Pitching moment about x_ref (force/q · length units).  Full-span model,
        so this is already the whole-airplane moment (no symmetry factor).
    """
    return -sum(
        f_box_vec[3 * j + 2] * (boxes[j].force_point[0] - x_ref)
        for j in range(len(boxes))
    )


def aero_moment_resultant(
    box_forces: FloatArray, boxes: list[AeroBox], ref_point: FloatArray
) -> FloatArray:
    """Full 3-component aerodynamic moment about ``ref_point`` (Step 58).

    ``M = Σ_j (r_j − ref) × F_j`` with ``r_j = box.force_point`` (¼-chord
    bound-vortex midpoint) and ``F_j`` the per-box force.  Returns ``[Mx, My, Mz]``
    — roll, pitch, yaw — in the same frame as ``box_forces``.

    Unlike ``pitch_moment`` (the single-source nose-up-positive *pitch* arm used
    inside the trim), this is the complete resultant needed once lifting surfaces
    leave the xy-plane: a canted panel carries a side force ``Fy`` that contributes
    roll/yaw, and the moment arm has a non-zero ``z`` component.  Used by the
    V-C-DIH dihedral gate to assert residual ``Fy``/roll/yaw ≈ 0 over a symmetric
    build, and reusable by future monitor-point load integration.

    Args:
        box_forces: per-box force, shape ``(n_box, 3)`` ``[Fx, Fy, Fz]`` (any
                    consistent force units).
        boxes:      AeroBox list (provides ``force_point``).
        ref_point:  (3,) moment reference in the same CID frame as the forces.

    Returns:
        (3,) ndarray ``[Mx, My, Mz]``.
    """
    ref = np.asarray(ref_point, dtype=float)
    m = np.zeros(3)
    for j, box in enumerate(boxes):
        m += np.cross(box.force_point - ref, box_forces[j])
    return m


