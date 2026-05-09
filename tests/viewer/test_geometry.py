import pytest
import plotly.graph_objects as go

from sbeam.model.bulk_data import BulkData
from sbeam.model.element import Cbar, Plotel
from sbeam.model.grid import Grid
from sbeam.model.mass import Conm2
from sbeam.model.material import Mat1
from sbeam.model.property import Pbar
from sbeam.viewer.geometry import build_model_figure


# ---------------------------------------------------------------------------
# Basic tests
# ---------------------------------------------------------------------------

def test_returns_figure(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    assert isinstance(fig, go.Figure)


def test_empty_model_returns_figure() -> None:
    fig = build_model_figure(BulkData())
    assert isinstance(fig, go.Figure)


# ---------------------------------------------------------------------------
# GRID trace
# ---------------------------------------------------------------------------

def test_grid_trace_coordinates(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    grid_trace = next(t for t in fig.data if t.name == "GRIDs")
    assert list(grid_trace.x) == [0.0, 1.0]
    assert list(grid_trace.y) == [0.0, 0.0]
    assert list(grid_trace.z) == [0.0, 0.0]


def test_grid_hover_contains_gid(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    grid_trace = next(t for t in fig.data if t.name == "GRIDs")
    assert "GRID" in grid_trace.hovertemplate


def test_grid_text_labels(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    grid_trace = next(t for t in fig.data if t.name == "GRIDs")
    assert list(grid_trace.text) == ["1", "2"]


# ---------------------------------------------------------------------------
# CBAR line traces
# ---------------------------------------------------------------------------

def test_cbar_line_trace_uses_ga_gb(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    cbar_trace = next(t for t in fig.data if t.name.startswith("CBAR PID="))
    assert cbar_trace.x[0] == pytest.approx(0.0)
    assert cbar_trace.x[1] == pytest.approx(1.0)
    assert cbar_trace.x[2] is None


def test_cbar_midpoint_at_centre(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    hover_trace = next(t for t in fig.data if t.name == "CBAR hover")
    assert hover_trace.x[0] == pytest.approx(0.5)
    assert hover_trace.y[0] == pytest.approx(0.0)
    assert hover_trace.z[0] == pytest.approx(0.0)


def test_cbar_midpoint_hover_contains_eid(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    hover_trace = next(t for t in fig.data if t.name == "CBAR hover")
    assert hover_trace.customdata[0][0] == 1  # EID=1


def test_cbar_hover_template_contains_eid_label(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    hover_trace = next(t for t in fig.data if t.name == "CBAR hover")
    assert "CBAR" in hover_trace.hovertemplate


# ---------------------------------------------------------------------------
# PLOTEL trace
# ---------------------------------------------------------------------------

def test_plotel_uses_dashed_style(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    plotel_trace = next(t for t in fig.data if t.name == "PLOTEL")
    assert plotel_trace.line.dash == "dash"


def test_plotel_distinct_from_cbar(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    cbar_trace = next(t for t in fig.data if t.name.startswith("CBAR PID="))
    plotel_trace = next(t for t in fig.data if t.name == "PLOTEL")
    assert plotel_trace.line.dash == "dash"
    assert getattr(cbar_trace.line, "dash", None) != "dash"


# ---------------------------------------------------------------------------
# Multi-PID colour coding
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CONM2 traces
# ---------------------------------------------------------------------------

def test_conm2_trace_present_when_masses_exist(simple_bulk: BulkData) -> None:
    simple_bulk.conm2s[10] = Conm2(eid=10, gid=1, cid=0, m=5.0)
    fig = build_model_figure(simple_bulk)
    conm2_trace = next((t for t in fig.data if t.name == "CONM2"), None)
    assert conm2_trace is not None


def test_conm2_marker_at_grid_when_no_offset(simple_bulk: BulkData) -> None:
    simple_bulk.conm2s[10] = Conm2(eid=10, gid=1, cid=0, m=5.0)
    fig = build_model_figure(simple_bulk)
    conm2_trace = next(t for t in fig.data if t.name == "CONM2")
    assert conm2_trace.x[0] == pytest.approx(0.0)
    assert conm2_trace.y[0] == pytest.approx(0.0)
    assert conm2_trace.z[0] == pytest.approx(0.0)


def test_conm2_marker_at_offset_cg(simple_bulk: BulkData) -> None:
    simple_bulk.conm2s[10] = Conm2(eid=10, gid=1, cid=0, m=5.0, x1=0.1, x2=0.2, x3=0.3)
    fig = build_model_figure(simple_bulk)
    conm2_trace = next(t for t in fig.data if t.name == "CONM2")
    assert conm2_trace.x[0] == pytest.approx(0.1)
    assert conm2_trace.y[0] == pytest.approx(0.2)
    assert conm2_trace.z[0] == pytest.approx(0.3)


def test_conm2_offset_line_trace_present_when_offset(simple_bulk: BulkData) -> None:
    simple_bulk.conm2s[10] = Conm2(eid=10, gid=1, cid=0, m=5.0, x1=0.1, x2=0.0, x3=0.0)
    fig = build_model_figure(simple_bulk)
    offset_traces = [t for t in fig.data if getattr(t, "legendgroup", None) == "conm2" and t.name != "CONM2"]
    assert len(offset_traces) == 1


def test_conm2_no_offset_line_trace_when_no_offset(simple_bulk: BulkData) -> None:
    simple_bulk.conm2s[10] = Conm2(eid=10, gid=1, cid=0, m=5.0)
    fig = build_model_figure(simple_bulk)
    offset_traces = [t for t in fig.data if getattr(t, "legendgroup", None) == "conm2" and t.name != "CONM2"]
    assert len(offset_traces) == 0


def test_conm2_marker_style(simple_bulk: BulkData) -> None:
    simple_bulk.conm2s[10] = Conm2(eid=10, gid=1, cid=0, m=5.0)
    fig = build_model_figure(simple_bulk)
    conm2_trace = next(t for t in fig.data if t.name == "CONM2")
    assert conm2_trace.marker.symbol == "circle-open"
    assert conm2_trace.marker.size == 14


def test_conm2_hover_contains_eid(simple_bulk: BulkData) -> None:
    simple_bulk.conm2s[10] = Conm2(eid=10, gid=1, cid=0, m=5.0)
    fig = build_model_figure(simple_bulk)
    conm2_trace = next(t for t in fig.data if t.name == "CONM2")
    assert "CONM2" in conm2_trace.hovertemplate
    assert conm2_trace.customdata[0][0] == 10  # EID


def test_conm2_absent_from_figure_when_no_masses(simple_bulk: BulkData) -> None:
    fig = build_model_figure(simple_bulk)
    conm2_trace = next((t for t in fig.data if t.name == "CONM2"), None)
    assert conm2_trace is None


def test_two_pids_produce_two_cbar_traces() -> None:
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
    bulk.grids[3] = Grid(gid=3, x=2.0, y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=2e11, G=7.7e10, nu=0.3, rho=7850.0)
    bulk.pbars[1] = Pbar(pid=1, mid=1, A=0.01, I1=1e-4, I2=1e-4, J=2e-4)
    bulk.pbars[2] = Pbar(pid=2, mid=1, A=0.02, I1=2e-4, I2=2e-4, J=4e-4)
    bulk.cbars[1] = Cbar(eid=1, pid=1, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    bulk.cbars[2] = Cbar(eid=2, pid=2, ga=2, gb=3, x1=0.0, x2=1.0, x3=0.0)

    fig = build_model_figure(bulk)
    cbar_traces = [t for t in fig.data if t.name and t.name.startswith("CBAR PID=")]
    assert len(cbar_traces) == 2
    assert cbar_traces[0].line.color != cbar_traces[1].line.color
