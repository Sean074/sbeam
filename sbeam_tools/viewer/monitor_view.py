"""Monitors drawn on the model: reference points, cut planes and members (#116).

A monitor placed on the wrong side of a wing, or a cut line that does not follow the
elastic axis, is seen in a picture and not in a card.  Everything drawn here comes from
the solver package's own plans (``prepare_monitor_point``, ``prepare_section_cut``): the
reference point a monitor's moments are taken about, the grids or boxes it sums, and each
station's cut plane.  The viewer places nothing itself, so the picture is the geometry
the run will use.  No Streamlit in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import plotly.graph_objects as go

from sbeam.aero.aero_model import AeroModel
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.bulk_data import BulkData
from sbeam.results.monitor_points import prepare_monitor_point
from sbeam.results.section_cuts import prepare_section_cut
from sbeam.types import FloatArray


@dataclass
class MonitorGeometry:
    """Where one monitor sits, in basic axes."""
    name: str
    card: str                        # 'MONPNT1' or 'MONSECT'
    kind: str                        # 'aerodynamic' (boxes) or 'structural' (grids)
    refs: FloatArray                 # (n, 3) reference points: one, or one per station
    members: FloatArray              # (m, 3) the grids or box points the monitor sums
    stations: list[float] = field(default_factory=list)       # MONSECT only
    normal: Optional[FloatArray] = None                       # MONSECT cut normal, basic
    on_side: list[int] = field(default_factory=list)          # MONSECT: members beyond each cut


def monitor_geometry(bulk: BulkData, aero: Optional[AeroModel]) -> dict[str, MonitorGeometry]:
    """The geometry of every MONPNT1 and MONSECT in the model, by name.

    ``aero`` is needed for a monitor whose component is an AELIST (its members are aero
    boxes); with ``aero=None`` such a monitor is left out.
    """
    grid_index = build_grid_index(bulk)
    out: dict[str, MonitorGeometry] = {}
    for mon in [*bulk.monpnt1s.values(), *bulk.monpnt3s.values()]:
        aerodynamic = bulk.aecomps[mon.comp].listtype == "AELIST"
        if aerodynamic and aero is None:
            continue
        plan = prepare_monitor_point(mon, bulk, aero, grid_index)
        out[mon.name] = MonitorGeometry(
            name=mon.name, card="MONPNT1",
            kind="aerodynamic" if aerodynamic else "structural",
            refs=np.asarray(plan.ref_basic, dtype=float).reshape(1, 3),
            members=np.asarray(plan.pos, dtype=float).reshape(-1, 3))
    for cut in bulk.monsects.values():
        aerodynamic = bulk.aecomps[cut.comp].listtype == "AELIST"
        if aerodynamic and aero is None:
            continue
        cplan = prepare_section_cut(cut, bulk, aero, grid_index)
        axis = np.asarray(cplan.R, dtype=float)[:, cut.axis - 1]
        out[cut.name] = MonitorGeometry(
            name=cut.name, card="MONSECT",
            kind="aerodynamic" if aerodynamic else "structural",
            refs=np.asarray(cplan.refs, dtype=float).reshape(-1, 3),
            members=np.asarray(cplan.pos, dtype=float).reshape(-1, 3),
            stations=list(cut.stations),
            normal=np.asarray(cplan.normal if cplan.normal is not None else axis, dtype=float),
            on_side=[int(mask.sum()) for mask in cplan.masks])
    return out


def cut_line(ref: FloatArray, normal: FloatArray, half_length: float) -> FloatArray:
    """Two end points of a line in the cut plane through ``ref``.

    The line lies in the plane (perpendicular to ``normal``) and as near horizontal as
    the plane allows: its direction is ``normal × z`` (or ``normal × x`` when the normal
    is vertical).  It shows the sweep of the cut in plan view.
    """
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    along = np.cross(n, [0.0, 0.0, 1.0])
    if np.linalg.norm(along) < 1e-9:
        along = np.cross(n, [1.0, 0.0, 0.0])
    along = along / np.linalg.norm(along)
    ref = np.asarray(ref, dtype=float)
    return np.array([ref - half_length * along, ref + half_length * along])


def add_monitor_traces(fig: go.Figure, geometry: dict[str, MonitorGeometry],
                       highlight: Optional[str], model_span: float) -> None:
    """Draw every monitor's reference point(s); for ``highlight`` also its members and,
    for a MONSECT, each station's cut line."""
    points = [(g, i) for g in geometry.values() for i in range(len(g.refs))]
    if points:
        fig.add_trace(go.Scatter3d(
            x=[g.refs[i][0] for g, i in points], y=[g.refs[i][1] for g, i in points],
            z=[g.refs[i][2] for g, i in points], mode="markers", name="monitor references",
            marker=dict(size=5, symbol="diamond", color="#d62728"),
            text=[g.name if not g.stations else f"{g.name} @ {g.stations[i]:g}"
                  for g, i in points],
            hovertemplate="<b>%{text}</b><br>X: %{x:.4g}<br>Y: %{y:.4g}<br>Z: %{z:.4g}"
                          "<extra>reference point</extra>"))
    chosen = geometry.get(highlight) if highlight else None
    if chosen is None:
        return
    if len(chosen.members):
        what = "boxes" if chosen.kind == "aerodynamic" else "grids"
        fig.add_trace(go.Scatter3d(
            x=chosen.members[:, 0], y=chosen.members[:, 1], z=chosen.members[:, 2],
            mode="markers", name=f"{chosen.name}: {what} summed",
            marker=dict(size=4, color="#ff7f0e", opacity=0.8),
            hovertemplate=f"{chosen.name} member<br>X: %{{x:.4g}}<br>Y: %{{y:.4g}}"
                          "<br>Z: %{z:.4g}<extra></extra>"))
    if chosen.card == "MONSECT" and chosen.normal is not None:
        xs: list[Optional[float]] = []
        ys: list[Optional[float]] = []
        zs: list[Optional[float]] = []
        for ref in chosen.refs:
            a, b = cut_line(ref, chosen.normal, 0.08 * model_span)
            xs += [a[0], b[0], None]
            ys += [a[1], b[1], None]
            zs += [a[2], b[2], None]
        fig.add_trace(go.Scatter3d(
            x=xs, y=ys, z=zs, mode="lines", name=f"{chosen.name}: cut planes",
            line=dict(color="#d62728", width=5), hoverinfo="skip"))
