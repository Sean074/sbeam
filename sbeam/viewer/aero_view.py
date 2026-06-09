"""Plotly figure builders for the aero box mesh and cp overlay (S44)."""
from __future__ import annotations

from typing import Optional

import numpy as np
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
) -> go.Figure:
    """3D box mesh + optional cp colour map + section-load strip chart."""
    fig = make_subplots(
        rows=2,
        cols=1,
        specs=[[{"type": "scene"}], [{"type": "xy"}]],
        row_heights=[0.75, 0.25],
        vertical_spacing=0.05,
    )
    _add_box_mesh(fig, aero_model.boxes)
    if cp is not None:
        _add_cp_contour(fig, aero_model.boxes, cp)
    if cl_section is not None:
        _add_section_load_strip(fig, aero_model.boxes, cl_section)
    if cp is not None and cp_corr is not None:
        _add_corrected_vs_inviscid(fig, aero_model.boxes, cp, cp_corr)
    _apply_aero_layout(fig)
    return fig


def _add_box_mesh(fig: go.Figure, boxes: list) -> None:
    """Wire-frame quad outline for every aero box — single Scatter3d trace."""
    xs: list = []
    ys: list = []
    zs: list = []
    for box in boxes:
        c = box.corners  # (4, 3): root-LE(0), tip-LE(1), tip-TE(2), root-TE(3)
        for i in [0, 1, 2, 3, 0]:
            xs.append(float(c[i, 0]))
            ys.append(float(c[i, 1]))
            zs.append(float(c[i, 2]))
        xs.append(None)
        ys.append(None)
        zs.append(None)
    fig.add_trace(
        go.Scatter3d(
            x=xs, y=ys, z=zs,
            mode="lines",
            line=dict(color="#888888", width=1),
            name="Aero mesh",
        ),
        row=1, col=1,
    )


def _add_cp_contour(fig: go.Figure, boxes: list, cp: np.ndarray) -> None:
    """Fill each box with its cp value using a triangulated Mesh3d trace."""
    vx: list = []
    vy: list = []
    vz: list = []
    ii: list = []
    jj: list = []
    kk: list = []
    intensity: list = []
    for b_idx, box in enumerate(boxes):
        c = box.corners  # root-LE(0), tip-LE(1), tip-TE(2), root-TE(3)
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
    fig.add_trace(
        go.Mesh3d(
            x=vx, y=vy, z=vz,
            i=ii, j=jj, k=kk,
            intensity=intensity,
            colorscale="RdBu_r",
            colorbar=dict(title="Cp", x=1.05, len=0.6, y=0.7),
            opacity=0.85,
            name="Cp",
            showscale=True,
        ),
        row=1, col=1,
    )


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


def _apply_aero_layout(fig: go.Figure) -> None:
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
    fig.update_xaxes(title_text="Span fraction", row=2, col=1)
    fig.update_yaxes(title_text="CL section", row=2, col=1)
