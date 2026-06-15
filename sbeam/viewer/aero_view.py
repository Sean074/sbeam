"""Plotly figure builders for the aero box mesh and cp overlay (S44)."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from sbeam.model.bulk_data import BulkData
from sbeam.aero.aero_model import AeroModel


def build_aero_box_figure(
    bulk: BulkData,
    aero_model: AeroModel,
    cp: Optional[np.ndarray] = None,
    cl_section: Optional[dict] = None,
    cp_corr: Optional[np.ndarray] = None,
    box_disp: Optional[np.ndarray] = None,
    show_normals: bool = False,
    strip: bool = True,
    cp_cmid: Optional[float] = None,
    cp_title: str = "Cp",
) -> go.Figure:
    """3D box mesh + optional cp colour map + section-load strip chart.

    When ``box_disp`` (shape ``(3*n_box,)``) is supplied — the spline-interpolated
    per-box structural translation ``g_disp @ u_g`` (optionally scaled) — each box's
    four corners are rigidly translated by ``box_disp[3k:3k+3]`` so the panels move
    with the deflected wing.  The jig (undeflected) wire-frame is always drawn too,
    so rigid-vs-flexible is legible.  Corners are z-bearing (canted ±Γ dihedral
    geometry from Step 58), so this never flattens to an xy-projection.

    ``strip`` (default True) keeps the bottom section-load xy panel.  Set it False to
    return a scene-only figure — the Aero tab renders span loading in a dedicated
    full-width figure (``build_span_loading_figure``), so the empty strip would just
    be visual noise there.
    """
    if strip:
        fig = make_subplots(
            rows=2,
            cols=1,
            specs=[[{"type": "scene"}], [{"type": "xy"}]],
            row_heights=[0.75, 0.25],
            vertical_spacing=0.05,
        )
    else:
        fig = make_subplots(rows=1, cols=1, specs=[[{"type": "scene"}]])
    _add_box_mesh(fig, aero_model.boxes)
    if box_disp is not None:
        _add_box_mesh(
            fig, aero_model.boxes, box_disp=box_disp,
            color="#ff7f0e", name="Deflected mesh",
        )
    if show_normals:
        _add_normal_vectors(fig, aero_model.boxes, box_disp=box_disp)
    cp_boxes_disp = box_disp if box_disp is not None else None
    if cp is not None:
        _add_cp_contour(fig, aero_model.boxes, cp, box_disp=cp_boxes_disp,
                        cmid=cp_cmid, title=cp_title)
    if strip and cl_section is not None:
        _add_section_load_strip(fig, aero_model.boxes, cl_section)
    if strip and cp is not None and cp_corr is not None:
        _add_corrected_vs_inviscid(fig, aero_model.boxes, cp, cp_corr)
    _apply_aero_layout(fig, strip=strip)
    return fig


def _box_corner(box, i: int, box_disp: Optional[np.ndarray]) -> np.ndarray:
    """Corner ``i`` of ``box``, translated by its per-box displacement if given."""
    c = box.corners[i]
    if box_disp is not None:
        d = box_disp[3 * box.k: 3 * box.k + 3]
        return c + d
    return c


def _add_box_mesh(
    fig: go.Figure,
    boxes: list,
    box_disp: Optional[np.ndarray] = None,
    color: str = "#888888",
    name: str = "Aero mesh",
) -> None:
    """Wire-frame quad outline for every aero box — single Scatter3d trace."""
    xs: list = []
    ys: list = []
    zs: list = []
    for box in boxes:
        # corners (4, 3): root-LE(0), tip-LE(1), tip-TE(2), root-TE(3)
        for i in [0, 1, 2, 3, 0]:
            p = _box_corner(box, i, box_disp)
            xs.append(float(p[0]))
            ys.append(float(p[1]))
            zs.append(float(p[2]))
        xs.append(None)
        ys.append(None)
        zs.append(None)
    fig.add_trace(
        go.Scatter3d(
            x=xs, y=ys, z=zs,
            mode="lines",
            line=dict(color=color, width=1),
            name=name,
        ),
        row=1, col=1,
    )


def _add_normal_vectors(
    fig: go.Figure,
    boxes: list,
    box_disp: Optional[np.ndarray] = None,
) -> None:
    """Outward surface-normal arrow at each box collocation point (single Cone trace)."""
    if not boxes:
        return
    # Scale arrows to the median box chord so they are proportioned to the mesh.
    scale = float(np.median([box.chord for box in boxes]))
    xs: list = []
    ys: list = []
    zs: list = []
    us: list = []
    vs: list = []
    ws: list = []
    custom: list = []
    for box in boxes:
        base = box.colloc
        if box_disp is not None:
            base = base + box_disp[3 * box.k: 3 * box.k + 3]
        n = box.normal
        xs.append(float(base[0]))
        ys.append(float(base[1]))
        zs.append(float(base[2]))
        us.append(float(n[0]) * scale)
        vs.append(float(n[1]) * scale)
        ws.append(float(n[2]) * scale)
        custom.append([box.k, box.i_span, box.j_chord,
                       float(n[0]), float(n[1]), float(n[2])])
    hover = (
        "<b>Box %{customdata[0]}</b><br>"
        "i_span %{customdata[1]}, j_chord %{customdata[2]}<br>"
        "n = (%{customdata[3]:.3f}, %{customdata[4]:.3f}, %{customdata[5]:.3f})"
        "<extra></extra>"
    )
    fig.add_trace(
        go.Cone(
            x=xs, y=ys, z=zs,
            u=us, v=vs, w=ws,
            sizemode="scaled",
            sizeref=1,
            anchor="tail",
            colorscale=[[0, "#2ca02c"], [1, "#2ca02c"]],
            showscale=False,
            customdata=custom,
            hovertemplate=hover,
            name="Surface normals",
            showlegend=True,
        ),
        row=1, col=1,
    )


def _add_cp_contour(
    fig: go.Figure,
    boxes: list,
    cp: np.ndarray,
    box_disp: Optional[np.ndarray] = None,
    cmid: Optional[float] = None,
    title: str = "Cp",
) -> None:
    """Fill each box with its cp value using a triangulated Mesh3d trace.

    ``cmid`` centres the colour scale (pass ``0.0`` for a Δcp difference view so the
    diverging RdBu scale is symmetric about zero); ``title`` labels the colour bar.
    """
    vx: list = []
    vy: list = []
    vz: list = []
    ii: list = []
    jj: list = []
    kk: list = []
    intensity: list = []
    for b_idx, box in enumerate(boxes):
        c = [_box_corner(box, i, box_disp) for i in range(4)]  # root-LE,tip-LE,tip-TE,root-TE
        base = len(vx)
        for corner in c:
            vx.append(float(corner[0]))
            vy.append(float(corner[1]))
            vz.append(float(corner[2]))
        # Triangulate the quad into two triangles
        ii += [base, base]
        jj += [base + 1, base + 2]
        kk += [base + 2, base + 3]
        cp_val = float(cp[b_idx])
        for _ in range(4):
            intensity.append(cp_val)
    mesh_kwargs = dict(
        x=vx, y=vy, z=vz,
        i=ii, j=jj, k=kk,
        intensity=intensity,
        colorscale="RdBu_r",
        colorbar=dict(title=title, x=1.05, len=0.6, y=0.7),
        opacity=0.85,
        name=title,
        showscale=True,
    )
    if cmid is not None:
        mesh_kwargs["cmid"] = cmid
    fig.add_trace(go.Mesh3d(**mesh_kwargs), row=1, col=1)


def _add_section_load_strip(fig: go.Figure, boxes: list, cl_section: dict) -> None:
    """Bar chart of spanwise section CL vs span fraction."""
    span_by_ispan: dict = {}
    for box in boxes:
        span_by_ispan.setdefault(box.i_span, box.span_frac)
    span_vals = []
    cl_vals = []
    for i_span in sorted(cl_section.keys()):
        span_vals.append(span_by_ispan.get(i_span, float(i_span)))
        cl_vals.append(float(cl_section[i_span]))
    fig.add_trace(
        go.Bar(
            x=span_vals,
            y=cl_vals,
            name="Section CL",
            marker_color="#1f77b4",
        ),
        row=2, col=1,
    )


def _add_corrected_vs_inviscid(
    fig: go.Figure,
    boxes: list,
    cp_inv: np.ndarray,
    cp_corr: np.ndarray,
) -> None:
    """Overlay spanwise mean cp for inviscid vs corrected solutions on the strip chart."""
    span_by_ispan: dict = {}
    cp_inv_by_ispan: dict = {}
    cp_corr_by_ispan: dict = {}
    for box in boxes:
        span_by_ispan.setdefault(box.i_span, box.span_frac)
        cp_inv_by_ispan.setdefault(box.i_span, []).append(float(cp_inv[box.k]))
        cp_corr_by_ispan.setdefault(box.i_span, []).append(float(cp_corr[box.k]))
    i_spans = sorted(span_by_ispan.keys())
    span_vals = [span_by_ispan[i] for i in i_spans]
    cp_inv_mean = [float(np.mean(cp_inv_by_ispan[i])) for i in i_spans]
    cp_corr_mean = [float(np.mean(cp_corr_by_ispan[i])) for i in i_spans]
    fig.add_trace(
        go.Scatter(
            x=span_vals, y=cp_inv_mean,
            mode="lines+markers",
            name="Cp inviscid",
            line=dict(color="#1f77b4"),
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=span_vals, y=cp_corr_mean,
            mode="lines+markers",
            name="Cp corrected",
            line=dict(color="#d62728", dash="dash"),
        ),
        row=2, col=1,
    )


def _apply_aero_layout(fig: go.Figure, strip: bool = True) -> None:
    fig.update_layout(
        scene=dict(
            aspectmode="data",
            xaxis_title="X",
            yaxis_title="Y",
            zaxis_title="Z",
            camera=dict(projection=dict(type="orthographic")),
        ),
        legend=dict(orientation="v", x=0.01, y=0.99),
        margin=dict(l=0, r=80, t=30, b=0),
        height=700,
    )
    if strip:
        fig.update_xaxes(title_text="Span fraction", row=2, col=1)
        fig.update_yaxes(title_text="CL section", row=2, col=1)


def build_section_correction_figure(boxes, df, data_result, caero_eid):
    """Spanwise section-correction preview for one CAERO1 surface.

    Two stacked panels vs span fraction η: the section force-curve slope ``cn_α`` and
    the zero-incidence section moment ``cm0``.  Each overlays the **user input**
    (markers at the table η-stations of the selected region) with the **achieved**
    correction recovered on the actual mesh strips (line), so interpolation and
    end-clamping (extrapolation) are visible and the build can be eyeballed against
    the data.

    Args:
        boxes:       whole-model AeroBox list (mesh order).
        df:          the section-data table (DataFrame).
        data_result: a ``section_data.MultiSectionDataBuildResult``.
        caero_eid:   the CAERO1 to plot.
    """
    import math
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for k, b in enumerate(boxes):
        if b.caero_eid == caero_eid:
            groups[b.i_span].append(k)
    strips = sorted(groups)
    eta_s, area_s, chord_s = [], [], []
    for s in strips:
        idx = groups[s]
        a = sum(boxes[k].area for k in idx)
        b0 = boxes[idx[0]]
        dy = math.hypot(b0.bound_b[1] - b0.bound_a[1], b0.bound_b[2] - b0.bound_a[2])
        eta_s.append(float(b0.span_frac))
        area_s.append(a)
        chord_s.append(a / max(dy, 1e-14))
    eta_s = np.asarray(eta_s); area_s = np.asarray(area_s); chord_s = np.asarray(chord_s)

    diag = data_result.correction.per_surface[caero_eid]
    rad2deg = 180.0 / np.pi
    ach_cn = diag.achieved_f_slope / (rad2deg * area_s)      # back to per-deg slope
    ach_cm0 = diag.achieved_m0 / (chord_s * area_s)          # back to section cm0

    cond = data_result.conditions[caero_eid]
    sel = df[(df["caero"] == caero_eid)
             & np.isclose(df["mach"], cond.mach)
             & np.isclose(df["a_lo"], cond.a_lo)
             & np.isclose(df["a_hi"], cond.a_hi)].sort_values("eta")
    eta_d = sel["eta"].to_numpy()

    var = cond.var.lower()
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.10,
        subplot_titles=(f"Section force slope cn_{var}  (CAERO {caero_eid}, {cond.var}, "
                        f"region [{cond.a_lo:g}, {cond.a_hi:g}]°)",
                        "Section zero-incidence moment cm0"),
    )
    hov = "η=%{x:.4g}<br>%{y:.5~g}<extra></extra>"
    fig.add_trace(go.Scatter(x=eta_d, y=sel["cn_a"].to_numpy(), mode="markers",
                             name="input", marker=dict(size=10, symbol="x",
                             color="#d62728"), hovertemplate=hov), row=1, col=1)
    fig.add_trace(go.Scatter(x=eta_s, y=ach_cn, mode="lines+markers", name="achieved",
                             line=dict(color="#1f77b4"), hovertemplate=hov), row=1, col=1)
    fig.add_trace(go.Scatter(x=eta_d, y=sel["cm0"].to_numpy(), mode="markers",
                             name="input cm0", marker=dict(size=10, symbol="x",
                             color="#d62728"), showlegend=False, hovertemplate=hov),
                  row=2, col=1)
    fig.add_trace(go.Scatter(x=eta_s, y=ach_cm0, mode="lines+markers", name="achieved cm0",
                             line=dict(color="#1f77b4"), showlegend=False,
                             hovertemplate=hov), row=2, col=1)
    fig.update_xaxes(title_text="span fraction η", row=2, col=1)
    fig.update_yaxes(title_text="cn_α  [1/deg]", tickformat=".5~g", row=1, col=1)
    fig.update_yaxes(title_text="cm0", tickformat=".5~g", row=2, col=1)
    fig.update_layout(height=520, legend=dict(orientation="h", y=1.12),
                      margin=dict(l=60, r=20, t=60, b=40))
    return fig


# SOL 144 raw derivative keys → conventional aero column header.  The vertical-force
# coefficient stays "CZ" (body/global-z: the summed z-component of the surface-normal box
# forces) and is deliberately NOT renamed to "CL".  CL is the wind-axis lift (force ⊥ to
# U∞); it equals CZ only at α≈0 and is related by a rotation through angle of attack
# (CL = CZ·cosα + CX·sinα).  This table carries no reference incidence, so a wind-axis CL
# cannot be formed here — the column is unambiguously body-axis.  Moments map to the
# conventional body-axis symbols Cl/Cm/Cn.
_DERIV_COLS = ["CZ", "CY", "CMX", "CMY", "CMZ", "CX"]
_DERIV_AERO_COLS = {"CZ": "CZ", "CY": "CY", "CMX": "Cl",
                    "CMY": "Cm", "CMZ": "Cn", "CX": "CX"}
_DERIV_AERO_ROWS = {"ANGLEA": "α", "SIDES": "β", "ROLL": "p",
                    "PITCH": "q", "YAW": "r"}


def rigid_derivative_table(aero_model, bulk, naming: str = "aero"):
    """Full rigid aerodynamic stability & control derivative matrix for the Aero tab.

    Reuses the SOL 144 machinery — ``build_djx`` (per-label normalwash columns) and
    ``sol144._compute_rigid_derivs`` (force/moment integration with no structural
    deformation, u_a = 0) — so the table matches the f06 rigid derivatives exactly
    while needing only the aero model (no trim/structure solve).

    Rows are the rigid-body labels ANGLEA/SIDES/ROLL/PITCH/YAW plus every AESURF
    control in the deck; columns are the six force/moment coefficients, all
    per-radian / per-unit-label (matching SOL 144).

    ``naming="aero"`` relabels rows/columns with conventional symbols
    (α, β, p, q, r; CZ, CY, Cl, Cm, Cn, CX); ``naming="raw"`` keeps the SOL 144
    names (ANGLEA…; CZ, CY, CMX, CMY, CMZ, CX) for a 1:1 f06 cross-check.  The
    vertical-force column stays body-axis ``CZ`` (not wind-axis ``CL``; see
    ``_DERIV_AERO_COLS``).

    Returns a ``pandas.DataFrame``, or ``None`` when no AEROS reference card is
    present (the coefficients have no reference geometry to normalise by).
    """
    if bulk.aeros is None:
        return None

    from sbeam.aero.integration import build_djx
    from sbeam.solver.sol144 import _compute_rigid_derivs
    from sbeam.assembly.coord_transform import _get_transform

    labels = ["ANGLEA", "SIDES", "ROLL", "PITCH", "YAW"] + sorted(
        s.label for s in bulk.aesurfs.values()
    )
    d_jx = build_djx(aero_model.boxes, labels, bulk)

    aeros = bulk.aeros
    if aeros.rcsid:
        ref_pt, _R = _get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref = float(ref_pt[0])
    else:
        ref_pt = np.zeros(3)
        x_ref = 0.0

    derivs = _compute_rigid_derivs(aero_model, d_jx, labels, bulk, x_ref, ref_pt)

    data = {col: [derivs[lbl][col] for lbl in labels] for col in _DERIV_COLS}
    df = pd.DataFrame(data, index=labels)
    if naming == "aero":
        df = df.rename(index=_DERIV_AERO_ROWS, columns=_DERIV_AERO_COLS)
    return df


def surface_dihedral_deg(boxes: list, caero_eid: int) -> float:
    """Length-weighted mean dihedral magnitude |Γ| (deg) of a CAERO1 surface.

    0° = horizontal (responds to α), 90° = vertical (responds to β); intermediate
    values are a canted surface that responds to a blend of α and β — the section
    correction (one axis per surface) is approximate there.  Uses each box's span
    edge ``bound_a → bound_b`` and takes ``atan2(|Δz|, |Δy|)`` so left/right sides
    do not cancel.
    """
    import math
    num = den = 0.0
    for b in boxes:
        if b.caero_eid != caero_eid:
            continue
        dy = float(b.bound_b[1] - b.bound_a[1])
        dz = float(b.bound_b[2] - b.bound_a[2])
        w = math.hypot(dy, dz)
        if w <= 1e-14:
            continue
        num += math.degrees(math.atan2(abs(dz), abs(dy))) * w
        den += w
    return num / den if den > 0 else 0.0


def _strip_cn_cm(boxes: list, idx: list, cp: np.ndarray) -> tuple:
    """Section normal-force and quarter-chord moment coefficient for one strip.

    cn = Σ(cp·area)/area_strip — area-weighted surface-normal force coefficient.
    cm = −Σ cp·area·(x_qc − x_¼c)/(area_strip·chord_strip) about the strip's own
    quarter-chord, nose-up positive (same arm/sign as vlm.solve_rigid_cl).
    """
    area = np.array([boxes[k].area for k in idx])
    area_strip = float(area.sum())
    b0 = boxes[idx[0]]
    dy = float(np.hypot(b0.bound_b[1] - b0.bound_a[1],
                        b0.bound_b[2] - b0.bound_a[2]))
    chord_strip = area_strip / dy if dy > 1e-14 else 1.0
    x_qc = np.array([0.5 * (boxes[k].bound_a[0] + boxes[k].bound_b[0]) for k in idx])
    # Strip leading edge from the front (min j_chord) box: its 1/4-chord minus 1/4 box chord.
    front = min(idx, key=lambda k: boxes[k].j_chord)
    bf = boxes[front]
    dy_f = float(np.hypot(bf.bound_b[1] - bf.bound_a[1],
                          bf.bound_b[2] - bf.bound_a[2]))
    chord_front = bf.area / dy_f if dy_f > 1e-14 else chord_strip
    x_le = 0.5 * (bf.bound_a[0] + bf.bound_b[0]) - 0.25 * chord_front
    x_ref_strip = x_le + 0.25 * chord_strip
    cpv = cp[idx]
    cn = float((cpv * area).sum() / area_strip) if area_strip > 1e-14 else 0.0
    denom = area_strip * chord_strip
    cm = (-float((cpv * area * (x_qc - x_ref_strip)).sum()) / denom
          if denom > 1e-14 else 0.0)
    return cn, cm


def build_span_loading_figure(boxes, cp_corr, cp_unc=None, aeros=None,
                              mode: str = "corrected", surfaces=None) -> go.Figure:
    """Per-surface spanwise normal-force and pitching-moment line plots.

    Groups boxes by (caero_eid, i_span) so each CAERO1 surface gets its own
    spanwise station list — fixing the single-surface / global-i_span merge of the
    old bar strip.  Two stacked subplots (section cn(η), then section cm(η) about the
    local quarter-chord); one line per surface.

    ``mode`` selects what is drawn (mirrors the Aero-tab Cp-view toggle):

    * ``"corrected"`` (default) — corrected solid; when ``cp_unc`` is given the
      uncorrected baseline is overlaid dashed in the same colour.
    * ``"uncorrected"`` — the uncorrected baseline solid (falls back to ``cp_corr``
      when no baseline is supplied).
    * ``"diff"`` — the strip-by-strip difference (corrected − uncorrected); requires
      ``cp_unc`` (falls back to ``"corrected"`` when absent).

    ``surfaces`` restricts which CAERO1 surfaces are drawn (a collection of
    caero_eids; ``None`` = all) so a busy multi-surface plot can be thinned to a
    chosen subset.  Each surface keeps a fixed colour from the full surface set, so
    hiding one does not recolour the rest.

    ``aeros`` is accepted for signature symmetry; the section coefficients are
    chord-local and need no global reference.
    """
    from collections import defaultdict

    cp_corr = np.asarray(cp_corr, dtype=float)
    cp_unc = None if cp_unc is None else np.asarray(cp_unc, dtype=float)
    if mode in ("uncorrected", "diff") and cp_unc is None:
        mode = "corrected"

    surf_strips: dict = defaultdict(lambda: defaultdict(list))
    for k, b in enumerate(boxes):
        surf_strips[b.caero_eid][b.i_span].append(k)

    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
               "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

    cn_label = "Δcn" if mode == "diff" else "cn"
    cm_label = "Δcm" if mode == "diff" else "cm"
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.10,
        subplot_titles=(f"Section normal-force coefficient  {cn_label}(η)",
                        f"Section pitching-moment coefficient  {cm_label}(η)  "
                        "(about local ¼-chord, nose-up +)"),
    )
    hov = "η=%{x:.4g}<br>%{y:.5~g}<extra></extra>"

    def _coeffs(cp, order, strips):
        cn, cm = [], []
        for sp in order:
            a, b = _strip_cn_cm(boxes, strips[sp], cp)
            cn.append(a)
            cm.append(b)
        return cn, cm

    all_eids = sorted(surf_strips)
    color_for = {eid: palette[i % len(palette)] for i, eid in enumerate(all_eids)}
    want = set(all_eids) if surfaces is None else set(surfaces)
    draw_eids = [eid for eid in all_eids if eid in want]

    for eid in draw_eids:
        color = color_for[eid]
        strips = surf_strips[eid]
        order = sorted(strips, key=lambda sp: boxes[strips[sp][0]].span_frac)
        eta = [float(boxes[strips[sp][0]].span_frac) for sp in order]

        cn_c, cm_c = _coeffs(cp_corr, order, strips)
        cn_u, cm_u = _coeffs(cp_unc, order, strips) if cp_unc is not None else (None, None)

        if mode == "uncorrected":
            cn_main, cm_main = cn_u, cm_u
        elif mode == "diff":
            cn_main = [c - u for c, u in zip(cn_c, cn_u)]
            cm_main = [c - u for c, u in zip(cm_c, cm_u)]
        else:
            cn_main, cm_main = cn_c, cm_c

        fig.add_trace(go.Scatter(x=eta, y=cn_main, mode="lines+markers",
                                 name=f"CAERO {eid}", legendgroup=str(eid),
                                 line=dict(color=color), hovertemplate=hov), row=1, col=1)
        fig.add_trace(go.Scatter(x=eta, y=cm_main, mode="lines+markers",
                                 name=f"CAERO {eid}", legendgroup=str(eid),
                                 line=dict(color=color), showlegend=False,
                                 hovertemplate=hov), row=2, col=1)

        # In the default corrected view, overlay the uncorrected baseline dashed.
        if mode == "corrected" and cp_unc is not None:
            fig.add_trace(go.Scatter(x=eta, y=cn_u, mode="lines",
                                     name=f"CAERO {eid} (uncorr)", legendgroup=str(eid),
                                     line=dict(color=color, dash="dash"),
                                     hovertemplate=hov), row=1, col=1)
            fig.add_trace(go.Scatter(x=eta, y=cm_u, mode="lines",
                                     name=f"CAERO {eid} (uncorr)", legendgroup=str(eid),
                                     line=dict(color=color, dash="dash"),
                                     showlegend=False, hovertemplate=hov), row=2, col=1)

    fig.update_xaxes(title_text="span fraction η", row=2, col=1)
    fig.update_yaxes(title_text=cn_label, tickformat=".5~g", row=1, col=1)
    fig.update_yaxes(title_text=f"{cm_label} (¼-chord)", tickformat=".5~g", row=2, col=1)
    fig.update_layout(height=560, legend=dict(orientation="h", y=1.12),
                      margin=dict(l=60, r=20, t=60, b=40))
    return fig
