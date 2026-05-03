from __future__ import annotations

import math
from typing import Optional

import numpy as np
import plotly.graph_objects as go

from sbeam.model.bulk_data import BulkData
from sbeam.model.load import Force, Moment

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


def build_model_figure(
    bulk: BulkData,
    selected_gid: Optional[int] = None,
    selected_eid: Optional[int] = None,
    load_sid: Optional[int] = None,
) -> go.Figure:
    """Return a Plotly 3D figure for the given BulkData model."""
    fig = go.Figure()
    spc_map = _get_spc_map(bulk)
    _add_grid_trace(fig, bulk, selected_gid, spc_map)
    _add_cbar_traces(fig, bulk, selected_eid)
    _add_plotel_trace(fig, bulk)
    _add_triad(fig, bulk)
    if load_sid is not None:
        _add_load_arrows(fig, bulk, load_sid)
    _apply_layout(fig)
    return fig


def build_deformed_figure(
    bulk: BulkData,
    displacements: np.ndarray,
    grid_index: dict,
    scale: float = 1.0,
    load_sid: Optional[int] = None,
) -> go.Figure:
    """3D figure showing undeformed ghost + deformed overlay for SOL 101."""
    fig = go.Figure()
    _add_ghost_cbar_lines(fig, bulk)
    def_coords = _deformed_grid_coords(bulk, displacements, grid_index, scale)
    xs, ys, zs = _cbar_line_coords(bulk, def_coords)
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(color="#ff7f0e", width=4),
        name="Deformed",
    ))
    gids_sorted = sorted(bulk.grids.keys())
    gxs, gys, gzs = _grid_coord_lists(bulk, def_coords)
    spc_map = _get_spc_map(bulk)
    node_colors = ["#cc2222" if gid in spc_map else "#ff7f0e" for gid in gids_sorted]
    node_sizes = [10 if gid in spc_map else 6 for gid in gids_sorted]
    fig.add_trace(go.Scatter3d(
        x=gxs, y=gys, z=gzs,
        mode="markers",
        marker=dict(size=node_sizes, color=node_colors),
        name="Deformed GRIDs",
    ))
    _add_triad(fig, bulk)
    if load_sid is not None:
        _add_load_arrows(fig, bulk, load_sid)
    _apply_layout(fig)
    return fig


def build_mode_figure(
    bulk: BulkData,
    mode_shape: np.ndarray,
    grid_index: dict,
    scale: float = 1.0,
    freq_hz: float = 0.0,
    n_frames: int = 20,
) -> go.Figure:
    """3D figure with animated cycling mode shape for SOL 103."""
    fig = go.Figure()
    _add_ghost_cbar_lines(fig, bulk)

    # Initial state: zero amplitude (undeformed positions)
    def_coords_0 = _mode_grid_coords(bulk, mode_shape, grid_index, 0.0)
    xs0, ys0, zs0 = _cbar_line_coords(bulk, def_coords_0)
    gxs0, gys0, gzs0 = _grid_coord_lists(bulk, def_coords_0)

    fig.add_trace(go.Scatter3d(  # trace index 1 — deformed lines
        x=xs0, y=ys0, z=zs0,
        mode="lines",
        line=dict(color="#ff7f0e", width=4),
        name="Mode shape",
    ))
    fig.add_trace(go.Scatter3d(  # trace index 2 — deformed nodes
        x=gxs0, y=gys0, z=gzs0,
        mode="markers",
        marker=dict(size=6, color="#ff7f0e"),
        name="Mode GRIDs",
        showlegend=False,
    ))

    _add_triad(fig, bulk)

    # Animation frames
    frames = []
    for i in range(n_frames):
        amp = scale * math.sin(2.0 * math.pi * i / n_frames)
        def_coords = _mode_grid_coords(bulk, mode_shape, grid_index, amp)
        xs, ys, zs = _cbar_line_coords(bulk, def_coords)
        gxs, gys, gzs = _grid_coord_lists(bulk, def_coords)
        frames.append(go.Frame(
            name=str(i),
            data=[
                go.Scatter3d(x=xs, y=ys, z=zs),
                go.Scatter3d(x=gxs, y=gys, z=gzs),
            ],
            traces=[1, 2],
        ))
    fig.frames = frames

    fig.update_layout(
        title=f"f = {freq_hz:.4g} Hz",
        updatemenus=[dict(
            type="buttons",
            showactive=False,
            y=0.02, x=0.1, xanchor="right",
            buttons=[
                dict(
                    label="▶",
                    method="animate",
                    args=[None, {"frame": {"duration": 50, "redraw": True},
                                 "fromcurrent": True, "loop": True}],
                ),
                dict(
                    label="⏸",
                    method="animate",
                    args=[[None], {"frame": {"duration": 0}, "mode": "immediate"}],
                ),
            ],
        )],
    )
    _apply_layout(fig)
    return fig


# ---------------------------------------------------------------------------
# Private helpers — coordinate utilities
# ---------------------------------------------------------------------------

def _deformed_grid_coords(
    bulk: BulkData,
    displacements: np.ndarray,
    grid_index: dict,
    scale: float,
) -> dict:
    """Return {gid: (x, y, z)} with scale*displacement added."""
    coords: dict = {}
    for gid, grid in bulk.grids.items():
        i = grid_index[gid]
        base = 6 * i
        coords[gid] = (
            grid.x + scale * displacements[base],
            grid.y + scale * displacements[base + 1],
            grid.z + scale * displacements[base + 2],
        )
    return coords


def _mode_grid_coords(
    bulk: BulkData,
    mode_shape: np.ndarray,
    grid_index: dict,
    amplitude: float,
) -> dict:
    """Return {gid: (x, y, z)} with amplitude*mode_shape added."""
    coords: dict = {}
    for gid, grid in bulk.grids.items():
        i = grid_index[gid]
        base = 6 * i
        coords[gid] = (
            grid.x + amplitude * mode_shape[base],
            grid.y + amplitude * mode_shape[base + 1],
            grid.z + amplitude * mode_shape[base + 2],
        )
    return coords


def _cbar_line_coords(bulk: BulkData, coords: dict) -> tuple:
    """Return (xs, ys, zs) lists for CBAR lines using given grid coords."""
    xs: list = []
    ys: list = []
    zs: list = []
    for cbar in bulk.cbars.values():
        xa, ya, za = coords[cbar.ga]
        xb, yb, zb = coords[cbar.gb]
        xs += [xa, xb, None]
        ys += [ya, yb, None]
        zs += [za, zb, None]
    return xs, ys, zs


def _grid_coord_lists(bulk: BulkData, coords: dict) -> tuple:
    """Return (xs, ys, zs) lists for all GRIDs in sorted GID order."""
    gids = sorted(bulk.grids.keys())
    xs = [coords[gid][0] for gid in gids]
    ys = [coords[gid][1] for gid in gids]
    zs = [coords[gid][2] for gid in gids]
    return xs, ys, zs


# ---------------------------------------------------------------------------
# Private helpers — original model traces
# ---------------------------------------------------------------------------

def _merge_dofs(spc_map: dict, gid: int, dof_str: str) -> None:
    existing = set(spc_map.get(gid, ""))
    spc_map[gid] = "".join(sorted(existing | set(dof_str.strip())))


def _get_spc_map(bulk: BulkData) -> dict:
    """Return {gid: sorted_dof_string} for every constrained grid."""
    spc_map: dict = {}
    for entries in bulk.spcs.values():
        for spc in entries:
            _merge_dofs(spc_map, spc.g1, spc.c1)
            if spc.g2 is not None and spc.c2:
                _merge_dofs(spc_map, spc.g2, spc.c2)
    for entries in bulk.spc1s.values():
        for spc1 in entries:
            for gid in spc1.grids:
                _merge_dofs(spc_map, gid, spc1.c)
    for gid, grid in bulk.grids.items():
        if grid.ps:
            _merge_dofs(spc_map, gid, grid.ps)
    return spc_map


def _resolve_load_forces(bulk: BulkData, load_sid: int, eff_scale: float = 1.0) -> list:
    """Recursively expand LOAD combinations; return [(Force|Moment, eff_scale)]."""
    results = []
    if load_sid in bulk.loads:
        load = bulk.loads[load_sid]
        for scale_i, sid_i in load.components:
            results.extend(_resolve_load_forces(bulk, sid_i, eff_scale * load.s * scale_i))
    else:
        for f in bulk.forces.get(load_sid, []):
            results.append((f, eff_scale))
        for m in bulk.moments.get(load_sid, []):
            results.append((m, eff_scale))
    return results


def _add_load_arrows(fig: go.Figure, bulk: BulkData, load_sid: int) -> None:
    """Add Cone arrow traces for FORCE and MOMENT loads in the given load set."""
    entries = _resolve_load_forces(bulk, load_sid)
    if not entries:
        return

    force_items = [(e, s) for e, s in entries if isinstance(e, Force)]
    moment_items = [(e, s) for e, s in entries if isinstance(e, Moment)]

    if bulk.grids:
        gc = [(g.x, g.y, g.z) for g in bulk.grids.values()]
        span = max(max(c[i] for c in gc) - min(c[i] for c in gc) for i in range(3))
        span = max(span, 1e-9)
    else:
        span = 1.0
    arrow_len = span * 0.15

    for items, color, label, val_fn in [
        (force_items, "#22aa44", "Forces", lambda e, s: e.f * s),
        (moment_items, "#3366cc", "Moments", lambda e, s: e.m * s),
    ]:
        if not items:
            continue
        vals = [val_fn(e, s) for e, s in items]
        max_mag = max(abs(v) for v in vals) or 1.0
        # Pre-scale so the largest arrow tip sits arrow_len from its node,
        # keeping vectors in model coordinates (sizeref=1 is then correct).
        scale = arrow_len / max_mag

        xs, ys, zs, us, vs, ws, custom = [], [], [], [], [], [], []
        for (entry, _), val in zip(items, vals):
            grid = bulk.grids.get(entry.gid)
            if grid is None:
                continue
            xs.append(grid.x)
            ys.append(grid.y)
            zs.append(grid.z)
            us.append(entry.n1 * val * scale)
            vs.append(entry.n2 * val * scale)
            ws.append(entry.n3 * val * scale)
            custom.append([entry.gid, f"{abs(val):.4g}"])

        if not xs:
            continue

        entity = label[:-1]  # "Force" / "Moment"
        hover = (
            f"<b>{entity} GID %{{customdata[0]}}</b><br>"
            "Magnitude: %{customdata[1]}"
            "<extra></extra>"
        )
        fig.add_trace(go.Cone(
            x=xs, y=ys, z=zs,
            u=us, v=vs, w=ws,
            sizemode="scaled",
            sizeref=1,
            anchor="tail",
            colorscale=[[0, color], [1, color]],
            showscale=False,
            customdata=custom,
            hovertemplate=hover,
            name=label,
            showlegend=False,
        ))


def _add_ghost_cbar_lines(fig: go.Figure, bulk: BulkData) -> None:
    if not bulk.cbars:
        return
    xs: list = []
    ys: list = []
    zs: list = []
    for cbar in bulk.cbars.values():
        ga = bulk.grids[cbar.ga]
        gb = bulk.grids[cbar.gb]
        xs += [ga.x, gb.x, None]
        ys += [ga.y, gb.y, None]
        zs += [ga.z, gb.z, None]
    fig.add_trace(go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(color="#cccccc", width=2),
        name="Undeformed",
        opacity=0.5,
    ))


def _add_grid_trace(
    fig: go.Figure,
    bulk: BulkData,
    selected_gid: Optional[int] = None,
    spc_map: Optional[dict] = None,
) -> None:
    if not bulk.grids:
        return
    grids = list(bulk.grids.values())

    hover = (
        "<b>GRID %{customdata[0]}</b><br>"
        "X: %{x:.4g}<br>"
        "Y: %{y:.4g}<br>"
        "Z: %{z:.4g}<br>"
        "PS: %{customdata[1]}"
        "<extra></extra>"
    )

    # Unconstrained GRIDs (grey solid circle)
    free_grids = [g for g in grids if g.gid != selected_gid and not (spc_map and g.gid in spc_map)]
    if free_grids:
        fig.add_trace(go.Scatter3d(
            x=[g.x for g in free_grids],
            y=[g.y for g in free_grids],
            z=[g.z for g in free_grids],
            mode="markers+text",
            marker=dict(size=6, color="#333333"),
            text=[str(g.gid) for g in free_grids],
            textposition="top center",
            textfont=dict(size=10),
            customdata=[[g.gid, g.ps or "—"] for g in free_grids],
            hovertemplate=hover,
            name="GRIDs",
        ))

    # SPC-constrained GRIDs (grey outline, red fill)
    spc_grids = [g for g in grids if g.gid != selected_gid and spc_map and g.gid in spc_map]
    if spc_grids:
        fig.add_trace(go.Scatter3d(
            x=[g.x for g in spc_grids],
            y=[g.y for g in spc_grids],
            z=[g.z for g in spc_grids],
            mode="markers+text",
            marker=dict(
                size=12,
                color="#cc2222",
                line=dict(color="#888888", width=2),
            ),
            text=[f"{g.gid}\n{spc_map[g.gid]}" for g in spc_grids],
            textposition="top center",
            textfont=dict(size=10),
            customdata=[[g.gid, g.ps or "—"] for g in spc_grids],
            hovertemplate=hover,
            name="GRIDs (SPC)",
        ))

    # Selected GRID (orange, on top of either group)
    if selected_gid is not None and selected_gid in bulk.grids:
        sg = bulk.grids[selected_gid]
        label = f"{sg.gid}\n{spc_map[sg.gid]}" if spc_map and sg.gid in spc_map else str(sg.gid)
        fig.add_trace(go.Scatter3d(
            x=[sg.x], y=[sg.y], z=[sg.z],
            mode="markers+text",
            marker=dict(size=10, color="#ff8800"),
            text=[label],
            textposition="top center",
            textfont=dict(size=10),
            customdata=[[sg.gid, sg.ps or "—"]],
            hovertemplate=hover,
            name="Selected GRID",
            showlegend=False,
        ))


def _add_cbar_traces(
    fig: go.Figure,
    bulk: BulkData,
    selected_eid: Optional[int] = None,
) -> None:
    if not bulk.cbars:
        return

    pid_groups: dict = {}
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

    if selected_eid is not None and selected_eid in bulk.cbars:
        cbar = bulk.cbars[selected_eid]
        ga = bulk.grids[cbar.ga]
        gb = bulk.grids[cbar.gb]
        fig.add_trace(go.Scatter3d(
            x=[ga.x, gb.x], y=[ga.y, gb.y], z=[ga.z, gb.z],
            mode="lines",
            line=dict(color="#ff8800", width=8),
            hoverinfo="skip",
            name=f"CBAR {selected_eid} (selected)",
        ))

    # Midpoint hover markers
    mx: list = []
    my: list = []
    mz: list = []
    customdata: list = []
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
