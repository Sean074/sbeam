"""SOL 144 stability-derivative computation (P13/DEF-R1 split from sol144.py).

Rigid, elastic-restrained (u_r = 0) and elastic-unrestrained (mean-axis /
inertia-relief, AE8b) stability derivatives, and the per-AESURF hinge-moment
derivatives about the cid1 hinge axis (AE11).
All names remain importable from ``sbeam.solver.sol144`` (facade).
"""

import warnings
from typing import Optional

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.assembly.reduction import expand_to_g
from sbeam.assembly.coord_transform import get_transform
from sbeam.aero.aero_model import AeroModel
from sbeam.aero.integration import build_djk
from sbeam.model.aero import require_aeros
from sbeam.solver.sol144_util import pitch_moment, aero_moment_resultant
from sbeam.types import FloatArray, LuFactor


def yaw_force_column(
    label: str, f_box_yaw: Optional[FloatArray], n_box: int
) -> FloatArray:
    """The Step-67a force-side increment belonging to ``label``.

    The yaw-rate wing term (theory §7.2 Eq. 28, ``aero.integration.build_fjx_yaw``)
    is a load *scaling* rather than a normalwash, so it never appears in ``D_jx``
    and every per-column force recovery has to add it explicitly for the ``YAW``
    label.  Returns zeros for every other label, and for decks with no yaw-rate
    case (``f_box_yaw is None``) — which is what keeps their results
    bit-identical to the pre-Step-67 solver.
    """
    if f_box_yaw is None or label.upper() != "YAW":
        return np.zeros(3 * n_box)
    return f_box_yaw


def compute_rigid_derivs(
    aero: AeroModel,
    D_jx: FloatArray,
    all_labels: list[str],
    bulk: BulkData,
    x_ref: float,
    ref_pt: FloatArray,
    f_box_yaw: Optional[FloatArray] = None,
) -> dict[str, dict[str, float]]:
    """Rigid aerodynamic stability and control derivatives.

    For each label, computes the change in total force/moment per unit label
    value without any structural deformation (u_a = 0).

    Longitudinal (single-source nose-up-positive pitch arm, AE1 Step E):
        CZ = Fz / S_ref,    CMY = My / (S_ref * c_ref)
    Lateral/directional (full 3-component resultant about ``ref_pt``, Step 52):
        CMX = Mx / (S_ref * b_ref)   — roll  (gives C_lp from ROLL, C_lβ from SIDES)
        CMZ = Mz / (S_ref * b_ref)   — yaw   (gives C_nr from YAW)

    ``CMX``/``CMZ`` use ``aero_moment_resultant`` so the roll/yaw moments carry
    the side force ``Fy`` of any canted (±Γ dihedral) panel; on a planar wing
    the roll column decouples cleanly from Fz/My (V-LAT gate).

    ``f_box_yaw`` (Step 67a) is the force-side yaw-rate column evaluated at the
    trim loading; when given it is added to the ``YAW`` column's box forces, so
    C_lr picks up the wing's dynamic-pressure asymmetry.  These are still
    *rigid* derivatives (u_a = 0) about a trim-dependent reference loading —
    the one place a rigid derivative here is not purely geometric.
    """
    sref = require_aeros(bulk).sref
    cref = require_aeros(bulk).cref
    bref = require_aeros(bulk).bref

    n_box = len(aero.boxes)
    boxes = aero.boxes
    rigid_derivs: dict[str, dict[str, float]] = {}

    for col, label in enumerate(all_labels):
        # Normalwash from unit perturbation of this label alone
        w_pert = D_jx[:, col]
        gamma = aero.ajj_inv_corr @ w_pert          # (n_box,)
        f_box_vec = (aero.skj @ gamma
                     + yaw_force_column(label, f_box_yaw, n_box))  # (3*n_box,)

        Fz_sens = f_box_vec[2::3].sum()
        My_sens = pitch_moment(f_box_vec, boxes, x_ref)   # nose-up-positive
        Fx_sens = f_box_vec[0::3].sum()
        Fy_sens = f_box_vec[1::3].sum()
        Mx, _, Mz = aero_moment_resultant(
            f_box_vec.reshape(n_box, 3), boxes, ref_pt)

        rigid_derivs[label] = {
            'CZ':  Fz_sens / sref,
            'CMY': My_sens / (sref * cref),
            'CMX': Mx / (sref * bref) if bref > 0 else 0.0,
            'CMZ': Mz / (sref * bref) if bref > 0 else 0.0,
            'CX':  Fx_sens / sref,
            'CY':  Fy_sens / sref,
        }

    return rigid_derivs


def compute_hinge_moments(
    aero: AeroModel,
    D_jx: FloatArray,
    all_labels: list[str],
    bulk: BulkData,
    f_box_trim: FloatArray,
    f_box_yaw: Optional[FloatArray] = None,
) -> dict[str, dict[str, float]]:
    """Hinge-moment derivatives and trimmed hinge moment per AESURF control.

    The hinge moment is the moment of the aero box forces on a surface's AELIST
    boxes about its hinge axis ĥ (the cid1 y-axis) through the hinge origin o:

        HM = Σ_{j∈AELIST} [(r_j − o) × F_j] · ĥ          (r_j = box force point)

    Returns ``{label: {'total': HM_trim, <trim_label>: dHM/dδ, ...}}`` where each
    ``dHM/dδ`` uses the rigid box forces from that label's normalwash column
    alone (u_a = 0, force/q units), mirroring ``compute_rigid_derivs``.  The
    ``'total'`` entry uses the full trimmed box-force field ``f_box_trim``
    (force/q units; multiply by q for the physical hinge moment).
    """

    # NASTRAN-box-ID → global-k index — the one shared, collision-checked map (F1)
    id_to_k = aero.require_box_id_to_k()

    hinge_moments: dict[str, dict[str, float]] = {}
    for aesurf in bulk.aesurfs.values():
        aelist = bulk.aelists.get(aesurf.alid1)
        if aelist is None:
            continue
        o, R = get_transform(aesurf.cid1, bulk.cord2rs)
        h_hat = R[:, 1]                                   # hinge axis = cid1 y-axis
        ks = [id_to_k[bid] for bid in aelist.elements if bid in id_to_k]

        def _hm(f_box: FloatArray, _ks: list[int] = ks,
                _o: FloatArray = o, _h: FloatArray = h_hat) -> float:
            total = 0.0
            for k in _ks:
                F = f_box[3 * k:3 * k + 3]
                r = aero.boxes[k].force_point - _o
                total += float(np.dot(np.cross(r, F), _h))
            return total

        entry = {'total': _hm(f_box_trim)}
        for col, lbl in enumerate(all_labels):
            f_box_col = (aero.skj @ (aero.ajj_inv_corr @ D_jx[:, col])
                         + yaw_force_column(lbl, f_box_yaw, len(aero.boxes)))
            entry[lbl] = _hm(f_box_col)
        hinge_moments[aesurf.label.upper()] = entry

    return hinge_moments


def compute_restrained_derivs(
    K_ll_lu: LuFactor,
    l_idx: list[int],
    Q_ax_a: FloatArray,
    M_ax_a: FloatArray,
    all_labels: list[str],
    aero: AeroModel,
    D_jx: FloatArray,
    T: FloatArray,
    free_local: list[int],
    n_red: int,
    bulk: BulkData,
    x_ref: float,
    q: float,
    ref_pt: FloatArray,
    f_box_yaw: Optional[FloatArray] = None,
) -> dict[str, dict[str, float]]:
    """Elastic restrained stability derivatives — exact analytic form (AE1 Step G).

    Restrained means the SUPORT (r-set) DOFs are held at zero; the l-set responds
    elastically.  The trim problem is linear in each label δ, so the derivative is
    obtained directly from the Schur factorisation instead of by finite difference
    (which the prior one-pass hybrid approximated and which converged to neither
    NASTRAN's restrained nor unrestrained column — see AE8).

    For label column ``col`` with combined aero + inertial sensitivity
    ``C_ax_l = q·Q_ax_a + M_ax_a`` on the l-set:

        ∂u_l/∂δ = K_ll⁻¹ · C_ax_l[:, col]        (K_ll already carries q·Q_aa,
                                                   so this is the restrained,
                                                   aero-coupled sensitivity)
        ∂w/∂δ   = D_jx[:, col] + D_jk·G_slope·∂u/∂δ
        ∂γ/∂δ   = A_jj*⁻¹ · ∂w/∂δ
        ∂f_box/∂δ = S_kj · ∂γ/∂δ
        CZ = Σ∂Fz/∂δ / S_ref,   CMY = ∂My/∂δ / (S_ref·c_ref)

    My uses the nose-up-positive ``pitch_moment`` convention (AE1 Step E).  Each
    g-set displacement derivative is expanded through the RBE3/RBAR T matrix so
    slave DOFs move with their masters (AE1 Step B1).  The result is exact (no FD
    truncation) and the URDD/inertial columns are carried by M_ax_a.
    """

    sref = require_aeros(bulk).sref
    cref = require_aeros(bulk).cref
    bref = require_aeros(bulk).bref
    djk  = build_djk(aero.boxes)
    n_a  = Q_ax_a.shape[0]
    n_box = len(aero.boxes)
    boxes = aero.boxes

    # Combined aero + inertial sensitivity on the l-set (one column per label).
    C_ax_l = (q * Q_ax_a[np.ix_(l_idx, list(range(len(all_labels))))]
              + M_ax_a[np.ix_(l_idx, list(range(len(all_labels))))])

    # ∂u_l/∂δ for every label at once: K_ll⁻¹ · C_ax_l  (n_l, n_labels)
    du_l_all = scipy.linalg.lu_solve(K_ll_lu, C_ax_l)

    rest_derivs: dict[str, dict[str, float]] = {}
    for col, label in enumerate(all_labels):
        # Scatter the l-set sensitivity into a full a-set vector, then expand to
        # the g-set so RBAR/RBE3 slaves follow their masters.
        u_a_d = np.zeros(n_a)
        for li_idx, li in enumerate(l_idx):
            u_a_d[li] = du_l_all[li_idx, col]
        u_full_d = expand_to_g(u_a_d, T, free_local, n_red)

        # Linear normalwash sensitivity: direct trim term + elastic feedback.
        dw = D_jx[:, col] + djk @ (aero.require_g_slope() @ u_full_d)
        dgamma = aero.ajj_inv_corr @ dw
        # Step 67a: the direct force-side yaw term.  Its elastic feedback is
        # already inside du_l — Q_ax_a carries the column — so only the direct
        # part is added here.
        df_box = (aero.skj @ dgamma
                  + yaw_force_column(label, f_box_yaw, n_box))  # (3·n_box,) force/q

        Mx, _, Mz = aero_moment_resultant(
            df_box.reshape(n_box, 3), boxes, ref_pt)
        rest_derivs[label] = {
            'CZ':  df_box[2::3].sum() / sref,
            'CMY': pitch_moment(df_box, boxes, x_ref) / (sref * cref),
            'CMX': Mx / (sref * bref) if bref > 0 else 0.0,
            'CMZ': Mz / (sref * bref) if bref > 0 else 0.0,
        }

    return rest_derivs


def compute_unrestrained_derivs(
    K_aa: FloatArray,
    M_aa: FloatArray,
    Q_aa: FloatArray,
    Q_ax_a: FloatArray,
    f_aero_a: FloatArray,
    all_labels: list[str],
    l_idx: list[int],
    r_idx: list[int],
    free_dofs: list[int],
    grid_index: dict[int, int],
    bulk: BulkData,
    q: float,
    ref_pt: FloatArray,
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Unrestrained (mean-axis / inertia-relief) stability derivatives — AE8b.

    Implements the MSC Nastran SOL 144 unrestrained-derivative algorithm
    verbatim (MSC Aeroelastic Analysis User's Guide, Static Aeroelasticity,
    Eqs. 2-111 … 2-134; DMAP matrix names kept in the comments for audit).
    Cross-checked against the ZAERO Theoretical Manual Ch. 12 modal mean-axis
    form (Eqs. 12.14–12.16).

    The unrestrained derivative is NOT the aero force integrated over a
    converged free-free aeroelastic response (both reverted AE8b attempts —
    see docs/40_history).  It is the rigid-body inertial reaction m_r·ü_r per
    unit trim variable, from a three-block system in (u_l, u_r, ü_r):

        1. l-set equilibrium:      K^a_ll·u_l + K^a_lr·u_r + (M_ll·D+M_lr)·ü_r
                                       = −K^a_lx·u_x + P_l
        2. mean-axis constraint:   (DᵀM_ll+M_rl)·u_l + (DᵀM_lr+M_rr)·u_r = 0
        3. rigid equilibrium:      Dᵀ·(row l) + (row r)

    where D = −K_ll⁻¹·K_lr (STRUCTURAL K only, Eq. 2-111) and
    K^a = K_aa − q̄·Q_aa.  u_l is eliminated through the aeroelastic K^a_ll,
    u_r through the mass-weighted mean-axis row (2-129/2-130), leaving
    MIRR·ü_r + KR1ZX·u_x = IPZF, whence Z1ZX = −m_r·MIRR⁻¹·KR1ZX (2-133).

    Note: the manual's KARZX line prints "KAZL − KAXL·ALX", which is
    dimensionally impossible (KAXL is n_r×n_x, ALX is n_l×n_x); the correct
    reading is KARZX = KAXL − KAZL·ALX.

    Only aero labels are computed (URDD acceleration columns are the ü_r
    unknowns of this formulation, handled by NASTRAN via TRX; not needed for
    the Phase C derivative deliverable).  Returns ``(derivs, intercepts)``:
    ``derivs`` shaped like ``restrained_derivs`` and ``intercepts`` holding the
    unrestrained {CZ0, CMY0} from the IPZF chain (w_g baseline).
    """
    n_r = len(r_idx)
    if n_r == 0:
        return {}, {}

    aero_cols = [c for c, lbl in enumerate(all_labels)
                 if not lbl.upper().startswith("URDD")]
    if not aero_cols:
        return {}, {}

    ll = np.ix_(l_idx, l_idx)
    lr = np.ix_(l_idx, r_idx)
    rl = np.ix_(r_idx, l_idx)
    rr = np.ix_(r_idx, r_idx)
    lx = np.ix_(l_idx, aero_cols)
    rx = np.ix_(r_idx, aero_cols)

    # Structural rigid-body modes (2-111) — STRUCTURAL K only, no aero in D.
    K_ll_s = K_aa[ll]
    K_lr_s = K_aa[lr]
    D = -scipy.linalg.lu_solve(scipy.linalg.lu_factor(K_ll_s), K_lr_s)  # (n_l, n_r)

    # The mean-axis formulation requires genuine free-flight rigid modes in the
    # SUPORT directions: K_rl·D + K_rr must vanish for a floating structure.
    res = np.linalg.norm(K_aa[rl] @ D + K_aa[rr]) / max(np.linalg.norm(K_aa), 1e-30)
    if res > 1e-8:
        warnings.warn(
            f"unrestrained derivatives skipped: SUPORT directions are not "
            f"free rigid-body modes (‖K_rl·D + K_rr‖/‖K‖ = {res:.2e}); "
            "check SPC/SUPORT consistency.", UserWarning)
        return {}, {}

    M_ll = M_aa[ll]; M_lr = M_aa[lr]; M_rl = M_aa[rl]; M_rr = M_aa[rr]
    m_r = M_rr + M_rl @ D + D.T @ M_lr + D.T @ M_ll @ D   # total rigid mass (2-114)
    MR = D.T @ M_ll + M_rl                                 # mean-axis row operator

    # Aeroelastic partitions (K^a = K − q̄·Q; K^a_ax = −q̄·Q_ax, Eq. 2-110).
    K_eff = K_aa - q * Q_aa
    Ka_ll = K_eff[ll]; Ka_lr = K_eff[lr]; Ka_rl = K_eff[rl]; Ka_rr = K_eff[rr]
    Ka_lx = -q * Q_ax_a[lx]
    Ka_rx = -q * Q_ax_a[rx]
    intl = f_aero_a[l_idx]                                 # INTL: aero part of P_l
    intz = D.T @ intl + f_aero_a[r_idx]                    # INTZ: aero part of DᵀP_l+P_r

    try:
        lu_a = scipy.linalg.lu_factor(Ka_ll)
        ARLR  = scipy.linalg.lu_solve(lu_a, Ka_lr)                 # (2-128)
        AMLR  = scipy.linalg.lu_solve(lu_a, M_ll @ D + M_lr)
        ALX   = scipy.linalg.lu_solve(lu_a, Ka_lx)
        UINTL = scipy.linalg.lu_solve(lu_a, intl)

        # Mean-axis row eliminates u_r through the MASS matrix (2-129/2-130).
        M2RR = (D.T @ M_lr + M_rr) - MR @ ARLR
        M3RR = -MR @ AMLR
        K3LX = -MR @ ALX
        TMP1 = MR @ UINTL
        M4RR = np.linalg.solve(M2RR, M3RR)
        K4LX = np.linalg.solve(M2RR, K3LX)
        TMP2 = np.linalg.solve(M2RR, TMP1)

        # Rigid-equilibrium row (2-131).
        KAZL  = D.T @ Ka_ll + Ka_rl
        KAXL  = D.T @ Ka_lx + Ka_rx
        K2RR  = -KAZL @ ARLR + (D.T @ Ka_lr + Ka_rr)
        KARZX = KAXL - KAZL @ ALX
        IPZ   = intz - KAZL @ UINTL

        # (2-132): MIRR·ü_r + KR1ZX·u_x = IPZF.
        M5RR  = -K2RR @ M4RR + m_r
        MIRR  = -KAZL @ AMLR + M5RR
        KR1ZX = -K2RR @ K4LX + KARZX
        IPZF  = K2RR @ TMP2 + IPZ

        # (2-133): dimensional derivatives Z1ZX = m_r·ü_r per unit u_x.
        Z1ZX  = -m_r @ np.linalg.solve(MIRR, KR1ZX)        # (n_r, n_x)
        IPZF2 = m_r @ np.linalg.solve(MIRR, IPZF)          # (n_r,)  intercepts
    except (np.linalg.LinAlgError, ValueError) as exc:
        warnings.warn(
            f"unrestrained derivatives skipped: singular mean-axis system "
            f"({exc}); q may be at/near divergence.", UserWarning)
        return {}, {}

    # TR (2-122): transfer the r-set force rows to a 6-component resultant
    # (Fx,Fy,Fz,Mx,My,Mz) about the aero reference point.  Right-hand My about
    # +y equals the nose-up-positive pitch_moment convention.
    idx_to_gid = {i: gid for gid, i in grid_index.items()}
    TR = np.zeros((6, n_r))
    for row, a_loc in enumerate(r_idx):
        g_dof = free_dofs[a_loc]
        gid = idx_to_gid[g_dof // 6]
        comp = g_dof % 6
        g = bulk.grids[gid]
        r_vec = np.array([g.x, g.y, g.z]) - ref_pt
        if comp < 3:
            TR[comp, row] = 1.0
            e = np.zeros(3); e[comp] = 1.0
            TR[3:, row] += np.cross(r_vec, e)
        else:
            TR[comp, row] = 1.0
    R6  = TR @ Z1ZX          # (6, n_x) physical force/moment per unit label
    R60 = TR @ IPZF2         # (6,)     physical intercept resultant

    # Non-dimensionalisation (NDIM, 2-123) — sbeam sign sense (CZ up-positive,
    # CMY nose-up-positive), matching the rigid/restrained columns.
    sref = require_aeros(bulk).sref
    cref = require_aeros(bulk).cref
    bref = require_aeros(bulk).bref
    qS = q * sref
    unrest_derivs: dict[str, dict[str, float]] = {}
    for j, c in enumerate(aero_cols):
        unrest_derivs[all_labels[c]] = {
            'CZ':  R6[2, j] / qS,
            'CMY': R6[4, j] / (qS * cref),
            'CMX': R6[3, j] / (qS * bref) if bref > 0 else 0.0,
            'CMZ': R6[5, j] / (qS * bref) if bref > 0 else 0.0,
        }
    unrest_intercepts = {
        'CZ0':  R60[2] / qS,
        'CMY0': R60[4] / (qS * cref),
    }
    return unrest_derivs, unrest_intercepts


