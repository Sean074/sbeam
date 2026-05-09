"""Tests for Step 21: deformed shape figure builder (geometry.py extensions)."""

import numpy as np
import pytest
import plotly.graph_objects as go

from sbeam.model.bulk_data import BulkData
from sbeam.assembly.load_vector import build_grid_index
from sbeam.viewer.geometry import build_deformed_figure, build_mode_figure


class TestBuildDeformedFigure:
    def test_returns_figure(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        n_dofs = 6 * len(two_node_bulk.grids)
        displacements = np.zeros(n_dofs)
        displacements[7] = 0.01  # tip Ty
        fig = build_deformed_figure(two_node_bulk, displacements, grid_index, scale=1.0)
        assert isinstance(fig, go.Figure)

    def test_has_deformed_trace(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        displacements = np.zeros(6 * 2)
        displacements[7] = 0.05
        fig = build_deformed_figure(two_node_bulk, displacements, grid_index, scale=1.0)
        trace_names = [t.name for t in fig.data]
        assert "Deformed" in trace_names

    def test_has_undeformed_ghost(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        displacements = np.zeros(12)
        fig = build_deformed_figure(two_node_bulk, displacements, grid_index, scale=1.0)
        trace_names = [t.name for t in fig.data]
        assert "Undeformed" in trace_names

    def test_tip_node_moves_with_scale(self, two_node_bulk):
        """Deformed tip y-coord equals original + scale * displacement."""
        grid_index = build_grid_index(two_node_bulk)
        displacements = np.zeros(12)
        dy = 0.1
        displacements[7] = dy  # GID2 is index 1, DOF Ty = base+1 = 7
        scale = 5.0
        fig = build_deformed_figure(two_node_bulk, displacements, grid_index, scale=scale)
        deformed_trace = next(t for t in fig.data if t.name == "Deformed GRIDs")
        # GID 2 is the second entry (sorted GIDs: 1, 2 → index 1)
        assert deformed_trace.y[1] == pytest.approx(0.0 + scale * dy, rel=1e-9)

    def test_zero_displacement_matches_original(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        displacements = np.zeros(12)
        fig = build_deformed_figure(two_node_bulk, displacements, grid_index, scale=1.0)
        deformed_trace = next(t for t in fig.data if t.name == "Deformed GRIDs")
        # GID 1 at x=0, GID 2 at x=1 (sorted)
        assert deformed_trace.x[0] == pytest.approx(0.0)
        assert deformed_trace.x[1] == pytest.approx(1.0)


class TestBuildModeFigure:
    def test_returns_figure(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        mode_shape = np.zeros(12)
        mode_shape[7] = 1.0
        fig = build_mode_figure(two_node_bulk, mode_shape, grid_index, scale=0.1, freq_hz=100.0)
        assert isinstance(fig, go.Figure)

    def test_has_frames(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        mode_shape = np.zeros(12)
        mode_shape[7] = 1.0
        n_frames = 8
        fig = build_mode_figure(two_node_bulk, mode_shape, grid_index,
                                scale=0.1, freq_hz=50.0, n_frames=n_frames)
        assert len(fig.frames) == n_frames

    def test_has_ghost_trace(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        mode_shape = np.zeros(12)
        mode_shape[7] = 1.0
        fig = build_mode_figure(two_node_bulk, mode_shape, grid_index)
        trace_names = [t.name for t in fig.data]
        assert "Undeformed" in trace_names

    def test_has_mode_shape_trace(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        mode_shape = np.zeros(12)
        mode_shape[7] = 1.0
        fig = build_mode_figure(two_node_bulk, mode_shape, grid_index)
        trace_names = [t.name for t in fig.data]
        assert "Mode shape" in trace_names

    def test_freq_in_title(self, two_node_bulk):
        grid_index = build_grid_index(two_node_bulk)
        mode_shape = np.zeros(12)
        mode_shape[7] = 1.0
        fig = build_mode_figure(two_node_bulk, mode_shape, grid_index, freq_hz=123.456)
        assert "123" in fig.layout.title.text
