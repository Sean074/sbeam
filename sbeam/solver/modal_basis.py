"""Free-free maneuver modal basis and the one-time h-set operator set (Step 61).

This is the basis layer of the ZAERO-style transient maneuver architecture
(Phase G0 Steps 61-63).  It builds, once per job, everything that depends only on
geometry, the baseline mass case and Mach:

    Phi = [Phi_r | Phi_e]        (n_a, n_h)   free-free basis
    M_hh, K_hh, M_rr                          structural h-set operators
    Q_hh, Q_hx/Q_hc, B_hh, f_h0               aerodynamic h-set operators

Nothing here integrates in time — the modal transient solver that consumes these
objects lands with Step 62, and the free rigid partition with Step 63.

Why geometric rigid vectors (Phi_r) rather than eigensolver zero modes
---------------------------------------------------------------------
A free-free ``eigh`` returns the zero-frequency subspace in an arbitrary linear
combination, which changes with the mass case and the LAPACK build.  Geometric
rigid-body vectors about the SUPORT reference point are deterministic and give:

  * an exact algebraic map between the rigid modal coordinates and the trim
    labels (unit plunge: ``xi_ddot = URDD3``; unit pitch: ``xi_ddot = URDD5``,
    ``xi_dot * c_ref / 2V = PITCH``, ``xi = ANGLEA``);
  * ``M_rr = Phi_r^T M_aa Phi_r`` equal to the GPWG rigid mass about that point;
  * the column-for-column identity ``M_ax = -M_aa Phi_r`` against
    ``sol144.build_inertial_cols`` (same reference point, ``suport_pos``).
    Since Q4/DEF-M3 that identity is *definitional*, not incidental:
    ``build_inertial_cols`` forms its columns as ``-M_gg Phi_r_g`` from the same
    geometric primitive (``assembly.rigid_body.build_rigid_vectors_g``) and the
    same consistent mass matrix.

This is the same mathematical object as ``designs/rbmref_card.md``'s
``B_target``; ``build_rigid_modes`` here is its single owner.

Mean axis
---------
The elastic modes are explicitly mass-orthogonalized against ``Phi_r``
(``phi_e <- phi_e - Phi_r M_rr^-1 Phi_r^T M_aa phi_e``, re-M-normalized), so
``Phi_e^T M_aa Phi_r = 0`` by construction.  That *is* the mean-axis condition
(ZAERO Ch. 12 Eqs 12.9-12.16), the same physics as
``sol144._compute_unrestrained_derivs``.

Massless DOFs
-------------
The basis eigensolve runs on the **statically condensed** a-set: DOFs with no
mass at all (the rotational DOFs of a CONM2-only model) are eliminated by exact
Guyan condensation before ``solve_modes`` is called — see ``_condense_massless``
for why the alternative (regularise and filter) silently corrupts the basis.

Sign / scaling conventions
--------------------------
All aerodynamic h-set operators are **dynamic-pressure free** (like ``Q_aa`` in
``aero/coupling.py``): the solver forms ``q * Q_hh`` etc.  The modal EOM they
serve (Step 62/63) is::

    M_hh d2xi + [C_hh - q B_hh] dxi + [K_hh - q Q_hh] xi = q Q_hc d_c(t)

Public API:
    build_rigid_modes(...)          -> Phi_r (the single rigid-basis builder)
    build_maneuver_basis(...)       -> ManeuverBasis
    truncate_basis(...)             -> ManeuverBasis (per-subcase NMODES slice)
    build_hset_gafs(...)            -> HsetGafs
    assemble_aset_operators(...)    -> AsetOperators (shared with maneuver_qs)
"""

import warnings
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.model.load import Eigrl
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.reduction import reduce_to_aset, AsetReduction
from sbeam.assembly.rigid_body import build_rigid_vectors_g
from sbeam.aero.aero_model import AeroModel
from sbeam.aero.coupling import build_qaa, build_fg, build_gaf
from sbeam.aero.integration import build_djx, build_dj_rigidrate, rigid_rate_scales
from sbeam.solver.sol103 import solve_modes
from sbeam.solver.sol144_util import build_inertial_cols, get_suport_local
from sbeam.types import FloatArray, IntArray, SparseMatrix
from sbeam.model.aero import require_aeros


# Relative generalized-mass floor below which a mode is discarded.  After the
# mean-axis projection a rigid-body eigenvector collapses to ~0, which is how the
# zero-frequency subspace leaves the elastic basis.
_MASS_FLOOR = 1e-8

# A DOF is treated as massless (and statically condensed out before the
# eigensolve) when its M_aa diagonal and row are this small relative to the
# largest mass diagonal.
_MASSLESS_TOL = 1e-12

# Frequency below which a discarded mode is reported as a rigid-body zero mode
# rather than a massless-DOF artefact, as a fraction of the lowest retained
# elastic frequency.  Diagnostics only — it never decides what is kept.
_ZERO_FREQ_FRAC = 1e-3

# Tolerance on the rigid-vector round trip through the RBE3/RBAR transformation.
_RIGID_ROUNDTRIP_TOL = 1e-8

#: Rigid DOF (1-6) -> the trim labels its modal coordinate maps onto.  ``accel``
#: is exact and unconditional (xi_ddot IS the URDD value, by construction of the
#: unit rigid vectors).  ``rate``/``disp`` name the steady labels the rigid
#: velocity / displacement feed; their scale factors live with the geometry in
#: ``aero.integration.build_dj_rigidrate`` so there is one owner of the
#: nondimensionalization.  Lateral attitude (roll/yaw angle) has no steady label
#: entry: Steps 62-63 are symmetric-maneuver scope and the lateral
#: attitude-to-sideslip sign convention is deliberately not encoded here.
_RIGID_LABELS = {
    1: ("URDD1", None,     None),
    2: ("URDD2", "SIDES",  None),
    3: ("URDD3", "ANGLEA", None),
    4: ("URDD4", "ROLL",   None),
    5: ("URDD5", "PITCH",  "ANGLEA"),
    6: ("URDD6", "YAW",    None),
}


@dataclass
class ManeuverBasis:
    """Free-free basis Phi = [Phi_r | Phi_e] and its structural h-set operators."""
    phi: FloatArray                  # (n_a, n_h)
    n_r: int
    n_e: int
    rigid_dofs: list[int]                 # rigid DOF components (1-6), one per Phi_r column
    # col -> {"dof", "accel", "rate", "disp"}; values are label strings or None
    rigid_label_map: dict[int, dict[str, Any]]
    suport_pos: FloatArray
    elastic_freqs_hz: FloatArray     # (n_e,)
    M_hh: FloatArray                 # (n_h, n_h) — block diagonal at baseline
    K_hh: FloatArray
    M_rr: FloatArray                 # (n_r, n_r) — GPWG rigid mass about suport_pos
    orthogonality_residual: float    # max |Phi^T M_aa Phi - blockdiag|
    n_filtered: int = 0              # modes dropped by the generalized-mass filter
    filtered_freqs_hz: FloatArray = field(default_factory=lambda: np.zeros(0))
    n_available_elastic: int = 0     # elastic modes before NMODES truncation
    n_massless: int = 0              # a-set DOFs statically condensed before the solve

    @property
    def n_h(self) -> int:
        return self.phi.shape[1]


@dataclass
class HsetGafs:
    """One-time aerodynamic h-set operators (geometry + Mach only, q-free)."""
    Q_hh: FloatArray                 # (n_h, n_h)   modal GAF
    Q_hx: FloatArray                 # (n_h, n_lab) all trim-label columns
    Q_hc: FloatArray                 # (n_h, n_ctl) AESURF subset view of Q_hx
    ctrl_labels: list[str]
    all_labels: list[str]
    B_hh: FloatArray                 # (n_h, n_h)   rigid-rate columns only (Level 1)
    f_h0: FloatArray                 # (n_h,)       baseline (camber/twist) aero
    C_hh: FloatArray                 # (n_h, n_h)   diag(2 zeta omega) on the elastic block
    zeta: float
    v_inf: float


@dataclass
class AsetOperators:
    """A-set matrices shared by the legacy and modal maneuver paths.

    Exactly the quantities ``maneuver_qs.assemble_operators`` built inline
    before Step 61; both solvers now go through this single assembly so their
    a-set indices and matrices are identical by construction.
    """
    grid_index: dict[int, int]
    red: AsetReduction
    all_labels: list[str]
    label_to_col: dict[str, int]
    K_aa: FloatArray
    M_aa: FloatArray
    Q_aa: FloatArray
    # g-set stiffness and mass, retained rather than discarded (Step 68): the
    # transient elastic-inertia load must be formed as M_gg·ü_g, since mapping a
    # reduced a-set force back to the g-set through Tᵀ is not well defined across
    # an RBE3.  K_gg is what ``recover_reactions`` needs for the reaction column.
    K_gg: SparseMatrix
    M_gg: SparseMatrix
    Q_ax_a: FloatArray               # (n_a, n_lab) q-free aero sensitivity
    M_ax_a: FloatArray
    M_ax_g: FloatArray
    f_aero_g_unit: FloatArray        # (n_g,) q-free baseline aero load
    D_jx: FloatArray
    suport_local: list[int]
    rigid_dofs: list[int]                 # SUPORT DOF components (1-6), ascending
    suport_pos: FloatArray
    x_ref: float
    R_rcsid: FloatArray
    has_rcsid: bool


# ---------------------------------------------------------------------------
# Shared a-set assembly
# ---------------------------------------------------------------------------

def assemble_aset_operators(
    bulk: BulkData, subcase: SubcaseControl, aero: AeroModel,
) -> AsetOperators:
    """Assemble the a-set operators the maneuver solvers share.

    Mirrors ``run_sol144_trim``'s assembly (Q_ax, K_aa, Q_aa, M_aa, M_ax,
    baseline aero, RCSID transform) on the Step 59 ``reduce_to_aset`` path.  All
    aerodynamic quantities are dynamic-pressure free; the caller applies q.
    """
    from sbeam.assembly.coord_transform import get_transform

    grid_index = build_grid_index(bulk)

    all_labels = sorted(
        [a.label for a in bulk.aestats.values()]
        + [s.label for s in bulk.aesurfs.values()]
    )
    label_to_col = {l: i for i, l in enumerate(all_labels)}

    aeros = require_aeros(bulk)
    if aeros.rcsid:
        x_ref_pt, R_rcsid = get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref = float(x_ref_pt[0])
        suport_pos = x_ref_pt
        has_rcsid = True
    else:
        x_ref = 0.0
        R_rcsid = np.eye(3)
        suport_pos = np.zeros(3)
        has_rcsid = False

    D_jx = build_djx(aero.boxes, all_labels, bulk,
                     id_to_k=aero.require_box_id_to_k())          # (n_box, n_lab)
    Q_ax_g = aero.require_g_load().T @ aero.skj @ aero.ajj_inv_corr @ D_jx    # (n_g, n_lab)

    red = reduce_to_aset(bulk, grid_index, subcase.spc_sid)

    Q_ax_a = red.reduce_rect(Q_ax_g)

    K_gg = assemble_global_stiffness(bulk)
    K_aa = red.reduce_matrix(K_gg, dense=True)

    Q_gg = build_qaa(aero, aero.require_g_load(), aero.require_g_slope())
    Q_aa = red.reduce_matrix(Q_gg)

    massset_sid = subcase.massset_sid            # Step 60 mass case (None = baseline)
    M_gg = assemble_global_mass(bulk, massset_sid)
    M_aa = red.reduce_matrix(M_gg, dense=True)

    f_aero_g_unit = build_fg(aero, aero.require_g_load())                     # (n_g,) q-free
    # Same M_gg as M_aa above — M_ax IS -M_gg Phi_r, so the a-set identity
    # M_ax_a = -M_aa Phi_r holds exactly rather than in a limit (Q4 / DEF-M3).
    M_ax_g = build_inertial_cols(
        bulk, all_labels, grid_index, suport_pos, massset_sid, M_gg=M_gg)
    M_ax_a = red.reduce_rect(M_ax_g)

    suport_local = get_suport_local(bulk, red.free_dofs, grid_index)
    rigid_dofs = sorted({int(ch) for sup in bulk.supports for ch in sup.dofs})

    return AsetOperators(
        grid_index=grid_index, red=red,
        all_labels=all_labels, label_to_col=label_to_col,
        K_aa=K_aa, M_aa=M_aa, Q_aa=Q_aa, Q_ax_a=Q_ax_a, K_gg=K_gg, M_gg=M_gg,
        M_ax_a=M_ax_a, M_ax_g=M_ax_g, f_aero_g_unit=f_aero_g_unit,
        D_jx=D_jx, suport_local=suport_local, rigid_dofs=rigid_dofs,
        suport_pos=suport_pos, x_ref=x_ref, R_rcsid=R_rcsid, has_rcsid=has_rcsid,
    )


# ---------------------------------------------------------------------------
# Rigid-body basis
# ---------------------------------------------------------------------------

def build_rigid_modes(
    bulk: BulkData,
    grid_index: dict[int, int],
    red: AsetReduction,
    rigid_dofs: list[int],
    ref_pos: FloatArray,
) -> FloatArray:
    """Geometric rigid-body vectors about ``ref_pos``, restricted to the a-set.

    THE single a-set rigid-basis builder (Step 61 owns it;
    ``designs/rbmref_card.md`` reuses it rather than deriving its own
    ``B_target``).  The g-set geometry itself comes from
    ``assembly.rigid_body.build_rigid_vectors_g``, which
    ``sol144.build_inertial_cols`` also uses so that ``M_ax`` and ``Phi_r``
    cannot describe different rigid motions.

    Column k corresponds to ``rigid_dofs[k]``:

      * translation (DOF 1-3): unit displacement along the axis on every grid's
        translational DOF;
      * rotation (DOF 4-6) about the unit axis ``a``: ``a x r_i`` on the
        translational DOFs and ``a`` on the rotational DOFs, with
        ``r_i = grid_pos_i - ref_pos``.

    Restriction to the a-set is a **row selection** on the independent DOFs, not
    the force-type ``T^T .`` reduction: rigid vectors are displacements, and the
    RBE3/RBAR transformation regenerates the dependent DOFs from them.  That is
    asserted here — a rigid element which is not rigid-body exact would otherwise
    corrupt the basis silently.

    Args:
        bulk:       parsed model (grid positions, in basic CID 0).
        grid_index: {gid: i}.
        red:        a-set reduction from ``reduce_to_aset``.
        rigid_dofs: rigid DOF components 1-6 (typically the SUPORT DOFs).
        ref_pos:    reference point in basic coordinates (``suport_pos``).

    Returns:
        (n_a, n_r) rigid-body basis on the a-set.
    """
    phi_r_g = build_rigid_vectors_g(bulk, grid_index, rigid_dofs, ref_pos)
    phi_r_a = phi_r_g[red.free_dofs, :]

    # Round trip: the a-set vector re-expanded through T must reproduce the
    # geometric rigid vector (rigid-body exactness of the RBE3/RBAR set).
    for col in range(phi_r_a.shape[1]):
        back = red.expand_to_g(phi_r_a[:, col])
        scale = max(1.0, float(np.abs(phi_r_g[:, col]).max()))
        err = float(np.abs(back - phi_r_g[:, col]).max()) / scale
        if err > _RIGID_ROUNDTRIP_TOL:
            raise ValueError(
                f"build_rigid_modes: rigid-body vector for DOF "
                f"{rigid_dofs[col]} is not reproduced through the RBE3/RBAR "
                f"transformation (max relative error {err:.3e}).  Either a "
                "rigid element is not rigid-body exact, or an SPC constrains a "
                "DOF the SUPORT frees."
            )
    return phi_r_a


# ---------------------------------------------------------------------------
# Full basis
# ---------------------------------------------------------------------------

def _condense_massless(
    K_aa: FloatArray, M_aa: FloatArray
) -> tuple[FloatArray, IntArray]:
    """Static (Guyan) condensation of the massless a-set DOFs.

    CONM2-only models (no CBAR ``rho``, no rotary inertia) leave rotational DOFs
    with no mass at all.  Feeding those straight to the generalised eigensolver
    is the Phase G0 risk-1 trap: ``solve_modes`` must Tikhonov-regularise the
    singular mass matrix, and the resulting eigenvectors carry ``O(1/sqrt(eps))``
    amplitudes on the massless DOFs.  Those amplitudes are M-orthogonal only
    against the *regularised* mass, so the mean-axis projection against the true
    ``M_aa`` leaves the retained modes badly non-orthogonal (observed: 0.99 on
    the HA144A deck) — a generalized-mass filter cannot see it, because the
    contaminated modes still have unit generalized mass.

    Condensing the massless DOFs out first removes the problem at the source and
    is **exact**, not an approximation: with no mass on those DOFs their
    equations are purely static, ``u_o = -K_oo^-1 K_om u_m``, at every frequency.
    The returned transformation also contains the rigid-body vectors exactly
    (they are strain-free, so ``K u_r = 0`` implies the same static relation),
    which is what keeps ``Phi_e^T M_aa Phi_r = 0`` clean.

    Returns:
        (T_cond, m_dofs) — ``T_cond`` is (n_a, n_m) mapping the retained
        mass-carrying DOFs to the full a-set; identity when nothing is massless.
    """
    n_a = K_aa.shape[0]
    diag = np.diag(M_aa)
    max_diag = float(np.abs(diag).max()) if n_a else 0.0
    if max_diag <= 0.0:
        raise ValueError(
            "build_maneuver_basis: the a-set mass matrix is entirely zero — the "
            "model has no mass."
        )
    tol = _MASSLESS_TOL * max_diag
    row_norm = np.abs(M_aa).max(axis=1)
    massless = (np.abs(diag) <= tol) & (row_norm <= tol)

    m_dofs = np.where(~massless)[0]
    o_dofs = np.where(massless)[0]
    if o_dofs.size == 0:
        return np.eye(n_a), m_dofs

    K_oo = K_aa[np.ix_(o_dofs, o_dofs)]
    K_om = K_aa[np.ix_(o_dofs, m_dofs)]
    try:
        G = -np.linalg.solve(K_oo, K_om)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "build_maneuver_basis: the massless a-set DOFs form a singular "
            "stiffness partition (a mechanism with no mass) — cannot condense "
            f"them out.  Add mass or constrain the free DOFs.  ({exc})"
        ) from exc

    T_cond = np.zeros((n_a, m_dofs.size))
    T_cond[m_dofs, :] = np.eye(m_dofs.size)
    T_cond[o_dofs, :] = G
    return T_cond, m_dofs

def build_maneuver_basis(
    bulk: BulkData,
    ops: AsetOperators,
    eigrl: Optional[Eigrl] = None,
    nmodes: int = 0,
) -> ManeuverBasis:
    """Build the free-free basis Phi = [Phi_r | Phi_e] from the baseline mass case.

    ``solve_modes`` is called **exactly once** here (the basis-consistency rule of
    ``designs/matrix_gaf_export.md`` 4.3); the resulting object is what the GAF
    and mass-case loops consume, so nothing downstream can reach the eigensolver
    and drift the basis.

    Args:
        bulk:   parsed model.
        ops:    a-set operators from ``assemble_aset_operators``.
        eigrl:  EIGRL for the basis eigensolve; ``None`` ⇒ all modes, MASS norm.
        nmodes: retained ELASTIC mode count (0 ⇒ all).  Rigid modes are always
                all retained.

    Returns:
        ManeuverBasis.
    """
    if not ops.rigid_dofs:
        raise ValueError(
            "build_maneuver_basis: no SUPORT DOFs found — the free-free maneuver "
            "basis needs a SUPORT card to define the rigid-body reference DOFs."
        )
    K_aa, M_aa = ops.K_aa, ops.M_aa

    phi_r = build_rigid_modes(
        bulk, ops.grid_index, ops.red, ops.rigid_dofs, ops.suport_pos)
    n_r = phi_r.shape[1]
    M_rr = phi_r.T @ M_aa @ phi_r
    if np.linalg.matrix_rank(M_rr) < n_r:
        raise ValueError(
            "build_maneuver_basis: the rigid mass matrix M_rr about the SUPORT "
            "point is singular — the model has no mass in a supported direction."
        )
    M_rr_inv = np.linalg.inv(M_rr)

    if eigrl is None:
        eigrl = Eigrl(sid=0, nd=None, norm="MASS")
    T_cond, _m_dofs = _condense_massless(K_aa, M_aa)
    K_red = T_cond.T @ K_aa @ T_cond
    M_red = T_cond.T @ M_aa @ T_cond
    K_red = 0.5 * (K_red + K_red.T)
    M_red = 0.5 * (M_red + M_red.T)
    freqs, modes_red = solve_modes(K_red, M_red, eigrl, force_dense=True)
    modes = T_cond @ modes_red

    # Mean-axis projection (twice — the standard re-orthogonalization), then the
    # generalized-mass filter that drops the rigid-body zero modes, which
    # collapse to ~0 once their rigid content is removed.
    kept_cols, kept_freqs = [], []
    dropped_freqs = []
    for j in range(modes.shape[1]):
        v = modes[:, j].copy()
        for _ in range(2):
            v -= phi_r @ (M_rr_inv @ (phi_r.T @ (M_aa @ v)))
        m_gen = float(v @ (M_aa @ v))
        if m_gen <= _MASS_FLOOR:
            dropped_freqs.append(freqs[j])
            continue
        kept_cols.append(v / np.sqrt(m_gen))
        kept_freqs.append(freqs[j])

    if not kept_cols:
        raise ValueError(
            "build_maneuver_basis: no elastic modes survived the mean-axis "
            "projection — the model appears to be entirely rigid-body."
        )
    n_available = len(kept_cols)
    if nmodes:
        if nmodes > n_available:
            warnings.warn(
                f"build_maneuver_basis: MLOADS NMODES={nmodes} exceeds the "
                f"{n_available} elastic modes available from the basis solve; "
                "retaining all of them.",
                UserWarning, stacklevel=2,
            )
        kept_cols = kept_cols[:nmodes]
        kept_freqs = kept_freqs[:nmodes]

    dropped = np.array(dropped_freqs)
    if dropped.size:
        f_low = kept_freqs[0]
        n_unexpected = int((dropped >= _ZERO_FREQ_FRAC * f_low).sum())
        if n_unexpected:
            # The mass filter is meant to remove the rigid-body zero modes only.
            # Anything else it catches is a mode with essentially no mass — a
            # modelling problem the user should see.
            warnings.warn(
                f"build_maneuver_basis: dropped {n_unexpected} non-zero-frequency "
                "mode(s) with negligible generalized mass; check the mass "
                "modelling.  Mode-acceleration recovery covers the omitted "
                "flexibility.",
                UserWarning, stacklevel=2,
            )

    phi_e = np.column_stack(kept_cols) if kept_cols else np.zeros((M_aa.shape[0], 0))
    phi = np.hstack([phi_r, phi_e])

    M_hh = phi.T @ M_aa @ phi
    K_hh = phi.T @ K_aa @ phi

    # Orthogonality residual: coupling between the rigid and elastic partitions
    # (the mean-axis condition) plus the elastic block's departure from I.
    n_e = phi_e.shape[1]
    scale = max(1.0, float(np.abs(np.diag(M_rr)).max()))
    resid = float(np.abs(M_hh[:n_r, n_r:]).max()) / scale if n_e else 0.0
    if n_e:
        resid = max(resid, float(np.abs(M_hh[n_r:, n_r:] - np.eye(n_e)).max()))

    rigid_label_map = {}
    for col, dof in enumerate(ops.rigid_dofs):
        accel, rate, disp = _RIGID_LABELS[dof]
        rigid_label_map[col] = {
            "dof": dof, "accel": accel, "rate": rate, "disp": disp}

    return ManeuverBasis(
        phi=phi, n_r=n_r, n_e=n_e,
        rigid_dofs=list(ops.rigid_dofs), rigid_label_map=rigid_label_map,
        suport_pos=ops.suport_pos,
        elastic_freqs_hz=np.array(kept_freqs),
        M_hh=M_hh, K_hh=K_hh, M_rr=M_rr,
        orthogonality_residual=resid,
        n_filtered=int(dropped.size), filtered_freqs_hz=dropped,
        n_available_elastic=n_available,
        n_massless=int(K_aa.shape[0] - T_cond.shape[1]),
    )


def truncate_basis(basis: ManeuverBasis, nmodes: int) -> ManeuverBasis:
    """Return a copy of ``basis`` retaining the first ``nmodes`` elastic modes.

    Rigid modes are always all retained.  ``nmodes`` <= 0 returns the basis
    unchanged.  This is how a per-subcase MLOADS NMODES is applied to the shared
    (untruncated) job-level basis: a column slice, never a re-solve — the basis
    object stays the single eigensolve of ``build_maneuver_basis`` (risk item 9).
    """
    if nmodes <= 0 or nmodes >= basis.n_e:
        if nmodes > basis.n_e:
            warnings.warn(
                f"truncate_basis: MLOADS NMODES={nmodes} exceeds the "
                f"{basis.n_e} elastic modes available from the basis solve; "
                "retaining all of them.",
                UserWarning, stacklevel=2,
            )
        return basis
    n_r = basis.n_r
    n_h = n_r + nmodes
    return ManeuverBasis(
        phi=basis.phi[:, :n_h], n_r=n_r, n_e=nmodes,
        rigid_dofs=list(basis.rigid_dofs),
        rigid_label_map=dict(basis.rigid_label_map),
        suport_pos=basis.suport_pos,
        elastic_freqs_hz=basis.elastic_freqs_hz[:nmodes],
        M_hh=basis.M_hh[:n_h, :n_h], K_hh=basis.K_hh[:n_h, :n_h],
        M_rr=basis.M_rr,
        orthogonality_residual=basis.orthogonality_residual,
        n_filtered=basis.n_filtered, filtered_freqs_hz=basis.filtered_freqs_hz,
        n_available_elastic=basis.n_available_elastic,
        n_massless=basis.n_massless,
    )


def rigid_state_label_increments(
    basis: ManeuverBasis,
    bulk: BulkData,
    v_inf: float,
    dxi_r: FloatArray,
    dvxi_r: FloatArray,
) -> dict[str, float]:
    """Trim-label increments equivalent to the rigid disp/rate states (Step 63).

    Maps the free-flight rigid modal displacements ``dxi_r`` and rates
    ``dvxi_r`` (perturbations about trim, basic frame about ``suport_pos``)
    onto the steady trim labels via ``rigid_label_map`` and the
    ``rigid_rate_scales`` nondimensionalization, so that feeding the returned
    increments through the steady ``D_jx`` label columns reproduces exactly the
    attitude (``Q_hh`` rigid columns) and rate (``B_hh``) aerodynamics of the
    coupled EOM — the free-flight recovery consistency identity.

    Increments are ADDITIVE and may stack on one label: the DOF-5 attitude
    (disp -> ANGLEA) and the DOF-3 plunge rate (rate -> ANGLEA, the −ḣ/V term
    of ``α = θ − ḣ/V``) both feed ANGLEA.  URDD (acceleration) labels are NOT
    handled here — ``ξ̈_r`` maps to them unscaled and frame-rotated by the
    caller (see ``sol144.urdd_basic_to_rcsid``).
    """
    scales = rigid_rate_scales(bulk, v_inf)
    out: dict[str, float] = {}
    for col, entry in basis.rigid_label_map.items():
        dof = entry["dof"]
        if entry["disp"] is not None:
            # Attitude angles map 1:1 onto their steady label (e.g. θ -> ANGLEA).
            out[entry["disp"]] = out.get(entry["disp"], 0.0) + float(dxi_r[col])
        if entry["rate"] is not None:
            out[entry["rate"]] = (
                out.get(entry["rate"], 0.0) + scales[dof] * float(dvxi_r[col]))
    return out


# ---------------------------------------------------------------------------
# Aerodynamic h-set operators
# ---------------------------------------------------------------------------

def build_hset_gafs(
    bulk: BulkData,
    ops: AsetOperators,
    basis: ManeuverBasis,
    aero: AeroModel,
    v_inf: float,
    zeta: float = 0.0,
) -> HsetGafs:
    """Project the aerodynamic operators onto the basis (once per job).

    All returned operators are dynamic-pressure free.  ``B_hh`` carries the
    Level-1 quasi-steady rate aerodynamics: the rigid-rate columns from
    ``build_dj_rigidrate``; the elastic-rate columns are an explicit zero block —
    the documented G0-d (apparent-mass / lag) hook.
    """
    phi = basis.phi
    n_h, n_r = basis.n_h, basis.n_r

    Q_hh = build_gaf(ops.Q_aa, phi)                      # coupling.build_gaf, reused
    Q_hx = phi.T @ ops.Q_ax_a                            # (n_h, n_lab), all labels

    ctrl_labels = sorted(s.label for s in bulk.aesurfs.values())
    ctrl_cols = [ops.label_to_col[l] for l in ctrl_labels]
    Q_hc = Q_hx[:, ctrl_cols] if ctrl_cols else np.zeros((n_h, 0))

    # Rigid-rate aerodynamics: same chain as Q_ax but with the physical-rate
    # normalwash columns.
    dj_rate = build_dj_rigidrate(aero.boxes, basis.rigid_dofs, bulk, v_inf)
    B_ar_g = aero.require_g_load().T @ aero.skj @ aero.ajj_inv_corr @ dj_rate   # (n_g, n_r)
    B_hr = phi.T @ ops.red.reduce_rect(B_ar_g)                        # (n_h, n_r)
    B_hh = np.zeros((n_h, n_h))
    B_hh[:, :n_r] = B_hr

    f_h0 = phi.T @ ops.red.reduce_vector(ops.f_aero_g_unit)           # (n_h,) q-free

    C_hh = np.zeros((n_h, n_h))
    if zeta:
        omega = 2.0 * np.pi * basis.elastic_freqs_hz
        C_hh[n_r:, n_r:] = np.diag(2.0 * zeta * omega)

    return HsetGafs(
        Q_hh=Q_hh, Q_hx=Q_hx, Q_hc=Q_hc,
        ctrl_labels=ctrl_labels, all_labels=list(ops.all_labels),
        B_hh=B_hh, f_h0=f_h0, C_hh=C_hh, zeta=zeta, v_inf=v_inf,
    )
