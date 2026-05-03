from __future__ import annotations

import math

import plotly.graph_objects as go

from sbeam.model.bulk_data import BulkData

_PID_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
]


def build_model_figure(bulk: BulkData) -> go.Figure:
    """Return a Plotly 3D figure for the given BulkData model."""
    fig = go.Figure()
    _add_grid_trace(fig, bulk)
    _add_cbar_traces(fig, bulk)
    _add_plotel_trace(fig, bulk)
    _add_triad(fig, bulk)
    _apply_layout(fig)
    return fig


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _add_grid_trace(fig: go.Figure, bulk: BulkData) -> None:
    if not bulk.grids:
        return
    grids = list(bulk.grids.values())
    x = [g.x for g in grids]
    y = [g.y for g in grids]
    z = [g.z for g in grids]
    text = [str(g.gid) for g in grids]
    customdata = [[g.gid, g.ps or "—"] for g in grids]
    hover = (
        "<b>GRID %{customdata[0]}</b><br>"
        "X: %{x:.4g}<br>"
        "Y: %{y:.4g}<br>"
        "Z: %{z:.4g}<br>"
        "PS: %{customdata[1]}"
        "<extra></extra>"
    )
    fig.add_trace(go.Scatter3d(
        x=x, y=y, z=z,
        mode="markers+text",
        marker=dict(size=6, color="#333333"),
        text=text,
        textposition="top center",
        textfont=dict(size=10),
        customdata=customdata,
        hovertemplate=hover,
        name="GRIDs",
    ))


def _add_cbar_traces(fig: go.Figure, bulk: BulkData) -> None:
    if not bulk.cbars:
        return

    # Group by PID for colour coding
    pid_groups: dict[int, list] = {}
    for cbar in bulk.cbars.values():
        pid_groups.setdefault(cbar.pid, []).append(cbar)

    pid_list = sorted(pid_groups.keys())
    color_map = {pid: _PID_COLORS[i % len(_PID_COLORS)] for i, pid in enumerate(pid_list)}

    for pid, cbars in sorted(pid_groups.items()):
        color = color_map[pid]
        xs: list = []
        ys: list = []
        zs: list = []
        for cbar in cbars:
            ga = bulk.grids[cbar.ga]
            gb = bulk.grids[cbar.gb]
            xs += [ga.x, gb.x, None]
            ys += [ga.y, gb.y, None]
            zs += [ga.z, gb.z, None]
        fig.add_trace(go.Scatter3d(
            x=xs, y=ys, z=zs,
            mode="lines",
            line=dict(color=color, width=4),
            hoverinfo="skip",
            name=f"CBAR PID={pid}",
        ))

    # Invisible midpoint markers carry per-element hover data
    mx: list[float] = []
    my: list[float] = []
    mz: list[float] = []
    customdata: list[list] = []
    for cbar in bulk.cbars.values():
        ga = bulk.grids[cbar.ga]
        gb = bulk.grids[cbar.gb]
        L = math.sqrt(
            (gb.x - ga.x) ** 2 + (gb.y - ga.y) ** 2 + (gb.z - ga.z) ** 2
        )
        pbar = bulk.pbars.get(cbar.pid)
        mat1 = bulk.mat1s.get(pbar.mid) if pbar else None
        mx.append((ga.x + gb.x) / 2)
        my.append((ga.y + gb.y) / 2)
        mz.append((ga.z + gb.z) / 2)
        customdata.append([
            cbar.eid,
            cbar.pid,
            mat1.mid if mat1 else "—",
            f"{pbar.A:.4g}" if pbar else "—",
            f"{pbar.I1:.4g}" if pbar else "—",
            f"{pbar.I2:.4g}" if pbar else "—",
            f"{pbar.J:.4g}" if pbar else "—",
            f"{L:.4g}",
            cbar.pa or "—",
            cbar.pb or "—",
        ])

    hover = (
        "<b>CBAR %{customdata[0]}</b><br>"
        "PID: %{customdata[1]},  MID: %{customdata[2]}<br>"
        "A: %{customdata[3]},  I1: %{customdata[4]},  I2: %{customdata[5]},  J: %{customdata[6]}<br>"
        "L: %{customdata[7]}<br>"
        "PA: %{customdata[8]},  PB: %{customdata[9]}"
        "<extra></extra>"
    )
    fig.add_trace(go.Scatter3d(
        x=mx, y=my, z=mz,
        mode="markers",
        marker=dict(size=8, opacity=0, color="#ffffff"),
        customdata=customdata,
        hovertemplate=hover,
        name="CBAR hover",
        showlegend=False,
    ))


def _add_plotel_trace(fig: go.Figure, bulk: BulkData) -> None:
    if not bulk.plotels:
        return
    xs: list = []
    ys: list = []
    zs: list = []
    for plotel in bulk.plotels.values():
        g1 = bulk.grids[plotel.g1]
        g2 = bulk.grids[plotel.g2]
        xs += [g1.x, g2.x, None]
        ys += [g1.y, g2.y, None]
        zs += [g1.z, g2.z, None]
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(color="#aaaaaa", width=2, dash="dash"),
        name="PLOTEL",
        hoverinfo="skip",
    ))


def _add_triad(fig: go.Figure, bulk: BulkData) -> None:
    if bulk.grids:
        coords = [(g.x, g.y, g.z) for g in bulk.grids.values()]
        ranges = [
            max(c[i] for c in coords) - min(c[i] for c in coords)
            for i in range(3)
        ]
        L = max(max(ranges) * 0.1, 1.0)
    else:
        L = 1.0

    axes = [
        ([0.0, L], [0.0, 0.0], [0.0, 0.0], "#cc3333", "X"),
        ([0.0, 0.0], [0.0, L], [0.0, 0.0], "#33aa33", "Y"),
        ([0.0, 0.0], [0.0, 0.0], [0.0, L], "#3366cc", "Z"),
    ]
    for xs, ys, zs, color, label in axes:
        fig.add_trace(go.Scatter3d(
            x=xs, y=ys, z=zs,
            mode="lines+text",
            line=dict(color=color, width=3),
            text=["", label],
            textfont=dict(color=color, size=12),
            hoverinfo="skip",
            showlegend=False,
        ))


def _apply_layout(fig: go.Figure) -> None:
    fig.update_layout(
        scene=dict(
            aspectmode="data",
            xaxis_title="X",
            yaxis_title="Y",
            zaxis_title="Z",
        ),
        legend=dict(orientation="v", x=0.01, y=0.99),
        margin=dict(l=0, r=0, t=30, b=0),
        height=600,
    )
