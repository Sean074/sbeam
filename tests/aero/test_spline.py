"""Phase B spline tests — V-B1 rigid-body gate and energy round-trip.

Geometry: 4-grid cantilever beam along global Y axis.
  Grids: G1=(0,0,0), G2=(0,1,0), G3=(0,2,0), G4=(0,3,0)
  CAERO1: flat rectangular panel above the beam, 3 span × 1 chord boxes.
  SPLINE2 CID: x-axis = global Y (span), y-axis = global X (bending-slope axis),
               z-axis = global Z (surface normal).

For this CID:
  x_hat = [0, 1, 0]  (spline axis = global Y)
  y_hat = [1, 0, 0]  (bending-slope axis = global X)
  z_hat = [0, 0, 1]  (normal = global Z)

DOF contributions:
  Deflection: Ty (d=1, z_hat[1]=0) → no contribution; Tz (d=2, z_hat[2]=1) → YES
  Bending slope: Rx (d=0 in rotation space = col 3, y_hat[0]=1) → YES
  Torsion: Ry (d=1 in rotation space = col 4, x_hat[1]=1) → YES (via dthx)

Rigid-body tests (machine-precision gate):
  V-B1a: uniform Tz=1, all others zero → g_slope @ u_g = 0 everywhere
  V-B1b: uniform Rx=1 (pitch about X = bending slope) → g_slope @ u_g = -1 everywhere
  V-B1c: uniform Ry=1 (torsion about Y) with dthx=1 → g_slope @ u_g = 1 everywhere

Energy round-trip (V-B1d):
  g_disp.T @ (normal unit forces) → total force in Z equals sum of box areas.
"""

import warnings

import numpy as np
import pytest

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import (
    Aeros, Caero1, Paero1, Set1, Spline2, Attach, Spline0
)
from sbeam.model.grid import Grid
from sbeam.model.coordinate_system import Cord2r
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.coupling import build_qaa
from sbeam.aero.spline import build_g_spline


# ---------------------------------------------------------------------------
# Fixture: 4 grids along Y, CAERO1 3span×1chord, SPLINE2 with CID spanning Y
# ---------------------------------------------------------------------------

def _build_spline_bulk():
    """Minimal BulkData for beam-along-Y spline tests."""
    bulk = BulkData()

    # Structural grids along global Y at z=0
    for gid, y in enumerate([0.0, 1.0, 2.0, 3.0], start=1):
        g = Grid(gid=gid, cp=0, x=0.0, y=y, z=0.0, cd=0)
        bulk.grids[gid] = g

    # CORD2R for the spline:
    #   A = origin (0,0,0), B = point on z-axis = (0,0,1), C = point in xz-plane = (1,0,0)
    #   → local z = B-A = [0,0,1], local x = C-A projected ⊥ z = [1,0,0]
    #   BUT we want CID x-axis along global Y.
    #   A = (0,0,0), B = point on local z-axis:
    #   For CID x = global Y, y = global X, z = global Z:
    #     local z = B - A → B = (0,0,1)  [z ← global Z]
    #     local x = (C - A) projected onto plane ⊥ z → C = (0,1,0)  [C-A = [0,1,0] ← global Y]
    #   So: A=(0,0,0), B=(0,0,1), C=(0,1,0)
    #   Check: z_hat = [0,0,1], v = C-A = [0,1,0], x_hat = v - (v·z)z = [0,1,0], y_hat = z×x = [1,0,0] wait...
    #   The code in coord_transform: k = B-A = [0,0,1], i = (C-A) - ((C-A)·k)k = [0,1,0], j = cross(k, i)
    #   j = cross([0,0,1], [0,1,0]) = [-1, 0, 0]?  No: cross([0,0,1],[0,1,0]) = [0*0-1*1, 1*0-0*0, 0*1-0*0]
    #     = [-1, 0, 0]
    #   So R = [i|j|k] = [[0,-1,0],[1,0,0],[0,0,1]]
    #   x_hat = [0,1,0] ✓ (spans Y)
    #   y_hat = [-1,0,0] (spans -X)
    #   z_hat = [0,0,1] ✓ (normal)
    #   Bending slope: y_hat = [-1,0,0] → Rx contributes with factor y_hat[0]=-1
    #
    # Simpler: use CID=0 (basic) with x-axis=X, y-axis=Y, z-axis=Z.
    # Then SPLINE2 span axis = X. Grids along X. Ry = bending slope.
    # Let's restructure: grids along X for CID=0 simplicity.
    #
    # RESTART: grids along global X at y=z=0; CAERO1 above them; CID=0.
    # x_hat=[1,0,0], y_hat=[0,1,0], z_hat=[0,0,1]
    # Deflection: Tz (d=2, z_hat[2]=1) → YES
    # Bending slope: Ry (d=1 in rotation space = col 4, y_hat[1]=1) → YES
    # Torsion: Rx (d=0 in rotation space = col 3, x_hat[0]=1) → YES
    return None  # placeholder; rebuild below


def _build_bulk_x_beam():
    """4 grids along global X (y=z=0). CAERO1: 3-span×1-chord at z=0. CID=0."""
    bulk = BulkData()

    # Structural grids along X
    for gid, x in enumerate([0.0, 1.0, 2.0, 3.0], start=1):
        bulk.grids[gid] = Grid(gid=gid, cp=0, x=x, y=0.0, z=0.0, cd=0)

    # AEROS (required for build_aero_model — set ACSID=0 so aero x-axis = global X)
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=3.0, sref=3.0, symxz=0, symxy=0)

    # PAERO1 (stub)
    bulk.paero1s[10] = Paero1(pid=10)

    # CAERO1: spans from y=0..3 with x from 0..1 (chord=1)
    # P1 = root leading edge, P4 = tip leading edge; x12/x43 = chord
    # To put boxes above the structural grids (which are at y=0):
    # span along X: P1=(0,0,0), P4=(3,0,0), x12=1, x43=1, nspan=3, nchord=1
    # freestream = +X, so panel is oriented span-along-X... but then x-direction IS the span.
    # The VLM needs the panel to be in the XY plane with freestream along X.
    # Let's put the panel in the XZ plane (vertical) at y=0: this is unusual.
    # Better: span along Y, but then it's a different orientation.
    #
    # For a flat horizontal panel (in XZ plane would be degenerate for VLM, needs XY plane).
    # Standard VLM: panel in XY plane (z≈0), freestream along X.
    # But our grids are along X at y=z=0. So we need span ALONG X.
    # Let's put P1=(0,0,0), x12=3 (span along X), nspan=3, nchord=1, P4=(0,3,0)...
    #
    # Actually, restructure: grids along Y at x=z=0; panel in XY plane spanning Y;
    # SPLINE2 with CID having x-axis along Y. This is the standard configuration.
    # For simplicity use a CORD2R where x-axis = global Y.
    #
    # CID 1: A=(0,0,0), B=(0,0,1) [z-axis direction], C=(0,1,0) [y-axis direction in XZ plane]
    # From coord_transform: k = B-A = (0,0,1); v = C-A = (0,1,0);
    #   i = v - (v·k)k = (0,1,0); j = cross(k,i) = cross((0,0,1),(0,1,0)) = (-1,0,0)
    # So R = [i|j|k] = [(0,-1,0),(1,0,0),(0,0,1)]
    # x_hat = R[:,0] = (0,1,0) ✓  y_hat = R[:,1] = (-1,0,0)  z_hat = R[:,2] = (0,0,1) ✓
    # Bending slope via y_hat=(-1,0,0): Rx (col 3) contributes with y_hat[0]=-1
    # Torsion via x_hat=(0,1,0): Ry (col 4) contributes with x_hat[1]=1
    # For rigid Rx=1 test: g_slope = -y_hat[0] * (d_slopes) = -(-1) * 1 = +1 everywhere
    #   Wait: g_slope += -y_comp * d_slopes, y_comp = y_hat[0] = -1 → += -(-1)*1 = +1
    #   But physically, Rx=1 (positive roll about X) on a panel spanning Y means nose-up → positive incidence
    #   We want that to give negative normalwash (since Djk=-I: w = -g_slope @ u, positive incidence → w<0 → lift)
    #   So g_slope should be -1 for unit Rx=1, and w = -(-1) = +1 = positive normalwash → lift ✓
    #
    # This is getting complicated. Let me use CID=0 with grids along X for the cleanest test.

    # RESTART (final): grids along X at y=z=0; CAERO1 spanning X, chord along Y; CID=0.
    # For VLM: panel in XY plane, freestream along X.
    # P1=(0,0,0) root-LE, x12=1 (chord=1 along X), P4=(0,3,0) tip-LE, x43=1
    # Wait — that puts chord along X AND span along Y simultaneously? No: in CAERO1,
    # P1=root-LE, P4=tip-LE, x12=root chord, x43=tip chord, chord is in freestream (+X) direction.
    # So span = P4-P1 direction = (0,3,0)-aligned = Y. Chord = X-direction.
    # Grids are along X at y=0 — but the panel spans along Y.
    # These are orthogonal! The grids are NOT below the panel.
    #
    # To have grids below the panel (panel spans along Y, grids also along Y):
    # Put grids at (0, 0..3, 0): gid→(0,y,0).

    # Re-rebuild with grids along Y:
    bulk.grids.clear()
    for gid, y in enumerate([0.0, 1.0, 2.0, 3.0], start=1):
        bulk.grids[gid] = Grid(gid=gid, cp=0, x=0.0, y=y, z=0.0, cd=0)

    # CORD2R CID=1: x-axis along global Y, z-axis along global Z
    # A=(0,0,0), B=(0,0,1), C=(0,1,0)
    # → x_hat=[0,1,0], y_hat=[-1,0,0], z_hat=[0,0,1]
    bulk.cord2rs[1] = Cord2r(cid=1, rid=0, a=(0.0, 0.0, 0.0), b=(0.0, 0.0, 1.0), c=(0.0, 1.0, 0.0))

    # CAERO1: panel in XY plane, span along Y (P1 to P4), chord along X
    # EID=100, PID=10, CP=0, NSPAN=3, NCHORD=1
    # P1=(0,0,0) root-LE, x12=1.0 root-chord, P4=(0,3,0) tip-LE, x43=1.0 tip-chord
    bulk.caero1s[100] = Caero1(
        eid=100, pid=10, cp=0, nspan=3, nchord=1,
        lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=1.0,
        p4=(0.0, 3.0, 0.0), x43=1.0,
    )

    # SET1: all 4 structural grids
    bulk.set1s[20] = Set1(sid=20, grids=[1, 2, 3, 4])

    # SPLINE2: link CAERO1 100 boxes to SET1 20 via CID=1
    # Box ID range: EID + 0 = 100 (box 0) to EID + 2 = 102 (box 2); nchord=1
    bulk.spline2s[200] = Spline2(
        eid=200, caero=100, id1=100, id2=102, setg=20,
        dz=0.0, dtor=1.0, cid=1, dthx=1.0, dthz=0.0, usage="BOTH",
    )

    return bulk


@pytest.fixture(scope="module")
def spline_operators():
    """Build g_slope and g_disp for the test geometry."""
    bulk = _build_bulk_x_beam()
    # Mesh boxes via build_aero_model (needs AEROS for build call even though we skip ajj)
    from sbeam.aero.panel import mesh_caero1
    caero = bulk.caero1s[100]
    boxes = mesh_caero1(caero, bulk.paero1s[10], bulk.aefacts, bulk.cord2rs, start_k=0)
    gids = sorted(bulk.grids.keys())
    grid_index = {gid: i for i, gid in enumerate(gids)}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
    return g_slope, g_disp, boxes, grid_index, bulk


# ---------------------------------------------------------------------------
# Parser round-trip tests (Step 45)
# ---------------------------------------------------------------------------

class TestSet1Parse:
    def test_single_line(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "GRID, 3, 0, 2.0, 0.0, 0.0",
            "SET1, 10, 1, 2, 3",
        ]
        bulk = parse_bulk_data(lines)
        assert 10 in bulk.set1s
        assert bulk.set1s[10].grids == [1, 2, 3]

    def test_multi_continuation(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        lines = ["GRID, %d, 0, %f, 0.0, 0.0" % (i, float(i)) for i in range(1, 13)]
        lines += [
            "SET1, 20, 1, 2, 3, 4, 5, 6, 7",
            "+, 8, 9, 10, 11, 12",
        ]
        bulk = parse_bulk_data(lines)
        assert bulk.set1s[20].grids == list(range(1, 13))

    def test_duplicate_raises(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "SET1, 5, 1",
            "SET1, 5, 1",
        ]
        with pytest.raises(ValueError, match="Duplicate SET1"):
            parse_bulk_data(lines)


class TestSpline2Parse:
    def _minimal_aero_lines(self):
        return [
            "AEROS, 0, 0, 1.0, 4.0, 4.0, 1, 0",
            "PAERO1, 10",
            "CAERO1, 100, 10, 0, 2, 1, 0, 0, 0",
            "+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0",
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 0.0, 2.0, 0.0",
            "GRID, 3, 0, 0.0, 4.0, 0.0",
            "SET1, 20, 1, 2, 3",
        ]

    def test_defaults(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        lines = self._minimal_aero_lines() + [
            "SPLINE2, 200, 100, 100, 101, 20",
        ]
        bulk = parse_bulk_data(lines)
        sp = bulk.spline2s[200]
        assert sp.eid == 200
        assert sp.caero == 100
        assert sp.id1 == 100
        assert sp.id2 == 101
        assert sp.setg == 20
        assert sp.dz == pytest.approx(0.0)
        assert sp.dtor == pytest.approx(1.0)
        assert sp.cid == 0
        assert sp.dthx == pytest.approx(1.0)
        assert sp.dthz == pytest.approx(0.0)
        assert sp.usage == "BOTH"

    def test_explicit_continuation(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        lines = self._minimal_aero_lines() + [
            "SPLINE2, 200, 100, 100, 101, 20, 0.0, 1.0, 0",
            "+, 0.5, 0.1, , FORCE",
        ]
        bulk = parse_bulk_data(lines)
        sp = bulk.spline2s[200]
        assert sp.dthx == pytest.approx(0.5)
        assert sp.dthz == pytest.approx(0.1)
        assert sp.usage == "FORCE"

    def test_missing_set1_raises(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        lines = self._minimal_aero_lines() + [
            "SPLINE2, 200, 100, 100, 101, 99",   # SET1 SID=99 doesn't exist
        ]
        with pytest.raises(ValueError, match="SETG=99 not found"):
            parse_bulk_data(lines)

    def test_missing_caero1_raises(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        lines = self._minimal_aero_lines() + [
            "SPLINE2, 200, 999, 100, 101, 20",   # CAERO1 EID=999 doesn't exist
        ]
        with pytest.raises(ValueError, match="CAERO=999 not found"):
            parse_bulk_data(lines)


# ---------------------------------------------------------------------------
# Spline operator shape tests
# ---------------------------------------------------------------------------

class TestGSplinesShapes:
    def test_g_slope_shape(self, spline_operators):
        g_slope, g_disp, boxes, grid_index, bulk = spline_operators
        n_k = len(boxes)
        n_g = 6 * len(grid_index)
        assert g_slope is not None
        assert g_slope.shape == (n_k, n_g)

    def test_g_disp_shape(self, spline_operators):
        g_slope, g_disp, boxes, grid_index, bulk = spline_operators
        n_k = len(boxes)
        n_g = 6 * len(grid_index)
        assert g_disp is not None
        assert g_disp.shape == (3 * n_k, n_g)

    def test_no_splines_returns_none(self):
        from sbeam.aero.panel import mesh_caero1
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, cp=0, x=0.0, y=0.0, z=0.0, cd=0)
        bulk.paero1s[10] = Paero1(pid=10)
        bulk.caero1s[100] = Caero1(
            eid=100, pid=10, cp=0, nspan=2, nchord=1,
            lspan=0, lchord=0, igid=0,
            p1=(0.0, 0.0, 0.0), x12=1.0, p4=(0.0, 2.0, 0.0), x43=1.0,
        )
        boxes = mesh_caero1(bulk.caero1s[100], bulk.paero1s[10], {}, {}, start_k=0)
        grid_index = {1: 0}
        gs, gd = build_g_spline(bulk, boxes, grid_index)
        assert gs is None
        assert gd is None


# ---------------------------------------------------------------------------
# V-B1: Rigid-body exactness (machine-precision gate)
# ---------------------------------------------------------------------------

class TestRigidBodyGate:
    """These tests MUST pass to machine precision for Phase C trim to be valid."""

    def _u_g(self, grid_index, dof, value=1.0):
        """Build displacement vector with 'value' at DOF 'dof' for all grids."""
        n_g = 6 * len(grid_index)
        u = np.zeros(n_g)
        for gi in grid_index.values():
            u[6 * gi + dof] = value
        return u

    def test_rigid_tz_translation_zero_downwash(self, spline_operators):
        """Uniform Tz=1: constant normal deflection → zero streamwise slope everywhere."""
        g_slope, _, boxes, grid_index, bulk = spline_operators
        # CID=1 has z_hat=[0,0,1], so Tz (dof=2) is the normal DOF
        u = self._u_g(grid_index, dof=2)
        downwash = g_slope @ u
        assert np.allclose(downwash, 0.0, atol=1e-12), (
            f"Rigid Tz translation must give zero downwash; "
            f"max |w| = {np.max(np.abs(downwash)):.2e}"
        )

    def test_rigid_ry_torsion_uniform_downwash(self, spline_operators):
        """Uniform Ry=1 (rotation about span axis Y = torsion in CID frame): uniform downwash = 1.

        CID=1: x_hat=[0,1,0], so Ry (dof=4, d=1 in rotation) has x_hat[1]=1.
        Torsion contribution: dthx × x_comp × phi_f[i] = 1 × 1 × phi_f[i].
        Partition of unity: Σ_i phi_f[i](s) = 1 for all s.
        Therefore g_slope @ u_Ry = 1.0 everywhere to machine precision.
        """
        g_slope, _, boxes, grid_index, bulk = spline_operators
        u = self._u_g(grid_index, dof=4)
        downwash = g_slope @ u
        assert np.allclose(downwash, 1.0, atol=1e-12), (
            f"Rigid Ry torsion must give uniform downwash=1; values: {downwash}"
        )

    def test_uniform_tz_exactly_zero_slope(self, spline_operators):
        """Uniform Tz=1 (tested separately from fixture to confirm column isolation).

        The Hermite derivative of a piecewise-constant function is exactly 0.
        This is the core rigid-body exactness property.
        """
        g_slope, _, boxes, grid_index, bulk = spline_operators
        n_g = 6 * len(grid_index)
        u = np.zeros(n_g)
        for gi in grid_index.values():
            u[6 * gi + 2] = 1.0
        assert np.max(np.abs(g_slope @ u)) < 1e-12

    def test_tz_and_ry_combined(self, spline_operators):
        """Combined Tz=1 + Ry=1: slope = 0 (Tz) + 1 (Ry) = 1 everywhere."""
        g_slope, _, boxes, grid_index, bulk = spline_operators
        n_g = 6 * len(grid_index)
        u = np.zeros(n_g)
        for gi in grid_index.values():
            u[6 * gi + 2] = 1.0  # Tz: contributes 0
            u[6 * gi + 4] = 1.0  # Ry: contributes 1
        downwash = g_slope @ u
        assert np.allclose(downwash, 1.0, atol=1e-12)


# ---------------------------------------------------------------------------
# V-B1d: Energy round-trip — virtual work consistency
# ---------------------------------------------------------------------------

class TestEnergyRoundTrip:
    def test_total_z_force_from_unit_pressure(self, spline_operators):
        """g_disp.T @ (unit normal forces) sums correctly to total Z force.

        For each box j: force vector = area_j * normal_j (from Skj diagonal block).
        g_disp.T @ force_vec = structural load vector.
        Total Z-component of structural loads = total lift = sum(area_j * normal_j[2]).
        """
        from sbeam.aero.integration import build_skj
        g_slope, g_disp, boxes, grid_index, bulk = spline_operators

        n_k = len(boxes)
        skj = build_skj(boxes)   # (3n, n)

        # Unit cp at all boxes
        cp = np.ones(n_k)
        force_vec = skj @ cp     # (3n,) global force contributions per box

        f_g = g_disp.T @ force_vec  # (n_g,) structural load vector

        # Total Z-force = sum of Fz contributions = sum(area_j * normal_j[2])
        expected_fz = sum(box.area * box.normal[2] for box in boxes)
        actual_fz = sum(
            f_g[6 * gi + 2] for gi in grid_index.values()
        )
        assert np.isfinite(actual_fz)
        # For this horizontal panel (normal=[0,0,1]), expected_fz = total area = 3.0
        assert abs(actual_fz - expected_fz) < 1e-10, (
            f"Virtual-work Z-force mismatch: got {actual_fz:.6f}, expected {expected_fz:.6f}"
        )


# ---------------------------------------------------------------------------
# V-B3: ATTACH rigid-body gate + SPLINE0 zero-force (machine-precision)
# ---------------------------------------------------------------------------

def _build_attach_bulk():
    """Minimal BulkData for ATTACH tests.

    Geometry:
      GRID 1 at (0, 0, 0) — master structural grid
      CAERO1 EID=200: span along Y (0..2), chord along X (0..1), 2span×1chord
        Box 200: force_point ≈ (0.25, 0.5, 0),  lever r = (0.25, 0.5, 0)
        Box 201: force_point ≈ (0.25, 1.5, 0),  lever r = (0.25, 1.5, 0)
      ATTACH EID=300: covers boxes 200–201, master GRID=1, CID=0
    """
    bulk = BulkData()

    bulk.grids[1] = Grid(gid=1, cp=0, x=0.0, y=0.0, z=0.0, cd=0)

    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=2.0, sref=2.0, symxz=0, symxy=0)
    bulk.paero1s[10] = Paero1(pid=10)

    # Panel spans Y (P1→P4 direction), chord along X
    bulk.caero1s[200] = Caero1(
        eid=200, pid=10, cp=0, nspan=2, nchord=1,
        lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=1.0,
        p4=(0.0, 2.0, 0.0), x43=1.0,
    )

    bulk.attaches[300] = Attach(eid=300, caero=200, id1=200, id2=201, grid=1, cid=0)

    return bulk


def _build_spline0_bulk():
    """Minimal BulkData for SPLINE0 zero-force test.

    Same geometry as _build_attach_bulk() but using SPLINE0 instead of ATTACH.
    GRID 1 exists only so grid_index is non-empty; SPLINE0 leaves all rows zero.
    """
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, cp=0, x=0.0, y=0.0, z=0.0, cd=0)

    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=2.0, sref=2.0, symxz=0, symxy=0)
    bulk.paero1s[10] = Paero1(pid=10)

    bulk.caero1s[200] = Caero1(
        eid=200, pid=10, cp=0, nspan=2, nchord=1,
        lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=1.0,
        p4=(0.0, 2.0, 0.0), x43=1.0,
    )

    bulk.spline0s[300] = Spline0(eid=300, caero=200, id1=200, id2=201)

    return bulk


@pytest.fixture(scope="module")
def attach_operators():
    """Build g_slope and g_disp for the ATTACH test geometry."""
    from sbeam.aero.panel import mesh_caero1
    bulk = _build_attach_bulk()
    caero = bulk.caero1s[200]
    boxes = mesh_caero1(caero, bulk.paero1s[10], bulk.aefacts, bulk.cord2rs, start_k=0)
    grid_index = {1: 0}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
    return g_slope, g_disp, boxes, grid_index, bulk


@pytest.fixture(scope="module")
def spline0_operators():
    """Build g_slope and g_disp for the SPLINE0 test geometry (all rows zero)."""
    from sbeam.aero.panel import mesh_caero1
    bulk = _build_spline0_bulk()
    caero = bulk.caero1s[200]
    boxes = mesh_caero1(caero, bulk.paero1s[10], bulk.aefacts, bulk.cord2rs, start_k=0)
    grid_index = {1: 0}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
    return g_slope, g_disp, boxes, grid_index, bulk


class TestAttachRigidBodyGate:
    """V-B3: ATTACH lever-arm kinematics must hold to machine precision."""

    def test_v_b3a_rigid_tz_zero_downwash(self, attach_operators):
        """V-B3a: Rigid Tz translation → zero downwash (plunge has zero slope)."""
        g_slope, _, boxes, grid_index, _ = attach_operators
        n_g = 6 * len(grid_index)
        u = np.zeros(n_g)
        u[6 * 0 + 2] = 1.0  # Tz at grid index 0
        downwash = g_slope @ u
        assert np.allclose(downwash, 0.0, atol=1e-14), (
            f"ATTACH rigid Tz must give zero downwash; max |w|={np.max(np.abs(downwash)):.2e}"
        )

    def test_v_b3b_rigid_ry_uniform_downwash(self, attach_operators):
        """V-B3b: Rigid Ry pitch → uniform downwash = −1 at all ATTACH boxes."""
        g_slope, _, boxes, grid_index, _ = attach_operators
        n_g = 6 * len(grid_index)
        u = np.zeros(n_g)
        u[6 * 0 + 4] = 1.0  # Ry at grid index 0
        downwash = g_slope @ u
        assert np.allclose(downwash, -1.0, atol=1e-14), (
            f"ATTACH rigid Ry pitch must give uniform downwash=−1; values: {downwash}"
        )

    def test_v_b3d_force_transfer_lever_arm(self, attach_operators):
        """V-B3d: Force transfer — uniform pressure → correct Fz, Mx, My at master GRID.

        For 2 boxes with area=1.0 each and force_point at y=0.5 and y=1.5 (rx=0.25 both):
          Fz = 2.0  (total lift)
          Mx = ry0 + ry1 = 0.5 + 1.5 = 2.0  (roll moment)
          My = −(rx0 + rx1) = −(0.25 + 0.25) = −0.5  (pitch moment, lever at ¼-chord)
        """
        from sbeam.aero.integration import build_skj
        g_slope, g_disp, boxes, grid_index, _ = attach_operators
        n_k = len(boxes)
        skj = build_skj(boxes)

        cp = np.ones(n_k)
        force_vec = skj @ cp          # (3*n_k,) global force contributions
        f_g = g_disp.T @ force_vec    # (n_g,) structural load at master DOFs

        gi = 0  # grid index for GRID 1
        col_base = 6 * gi
        fz = f_g[col_base + 2]
        mx = f_g[col_base + 3]
        my = f_g[col_base + 4]

        # Lever arms use force_point (¼-chord midpoint), not colloc (¾-chord)
        expected_fz = sum(box.area * box.normal[2] for box in boxes)
        expected_mx = sum(
            (box.force_point[1] - 0.0) * box.area * box.normal[2] for box in boxes
        )  # ry * Fz per box
        expected_my = -sum(
            (box.force_point[0] - 0.0) * box.area * box.normal[2] for box in boxes
        )  # −rx * Fz per box

        assert abs(fz - expected_fz) < 1e-12, f"Fz mismatch: {fz:.6f} vs {expected_fz:.6f}"
        assert abs(mx - expected_mx) < 1e-12, f"Mx mismatch: {mx:.6f} vs {expected_mx:.6f}"
        assert abs(my - expected_my) < 1e-12, f"My mismatch: {my:.6f} vs {expected_my:.6f}"


class TestSpline0ZeroForce:
    """V-B3c: SPLINE0 rows remain zero — no structural force contribution."""

    def test_v_b3c_zero_force_contribution(self, spline0_operators):
        """SPLINE0 boxes: g_disp.T @ any_pressure_force = 0 for all structural DOFs."""
        from sbeam.aero.integration import build_skj
        _, g_disp, boxes, grid_index, _ = spline0_operators
        n_k = len(boxes)
        skj = build_skj(boxes)

        cp = np.ones(n_k)
        force_vec = skj @ cp
        f_g = g_disp.T @ force_vec

        assert np.allclose(f_g, 0.0, atol=1e-14), (
            f"SPLINE0 must give zero structural force; max |f|={np.max(np.abs(f_g)):.2e}"
        )

    def test_v_b3c_g_slope_zero(self, spline0_operators):
        """SPLINE0 boxes: g_slope rows are zero (no incidence coupling)."""
        g_slope, _, boxes, grid_index, _ = spline0_operators
        assert np.allclose(g_slope, 0.0, atol=1e-14), (
            f"SPLINE0 g_slope must be all-zero; max |w|={np.max(np.abs(g_slope)):.2e}"
        )


# ---------------------------------------------------------------------------
# V-AE2: Swept-spline rigid-body gate (HA144A CID-2 wing, DTHX=−1)
# ---------------------------------------------------------------------------

def _build_ha144a_wing_spline_bulk():
    """HA144A CID-2 wing spline geometry for V-AE2 test.

    Wing grids: 100, 110, 120 are the elastic-axis CBAR endpoints (root, mid,
    tip). 111/112/121/122 are RBAR-slaved LE/TE stringers and 99 is the
    fuselage centreline; they live in the bulk so other tests can reference
    them but are deliberately NOT in SET1 1100 — SPLINE2 is a 1-D beam spline
    so its SET1 must lie along the EA (see AE1 Step B in the backlog and
    spline.py SET1 collinearity check).

    CAERO1 1100: 8-span × 4-chord.
    CID 2: x_hat=(−0.5,0.866,0), y_hat=(−0.866,−0.5,0), z_hat=(0,0,1).
    SPLINE2 1601: CAERO=1100, SETG=1100, CID=2, DTHX=+1 (attached: torsion
    rides through master Rx now that LE/TE stringers are out of SET1).
    """
    bulk = BulkData()

    # Wing structural grids (positions from HA144A). EA grids 100/110/120
    # sit on the swept elastic axis from (30, 0) at 60° from x — verify
    # collinearity: chord offset Δ = (r−origin)·ŷ_spline = 0 for all three.
    wing_grids = {
        99:  (20.00000, 0.0,  0.0),  # fuselage centreline
        100: (30.00000, 0.0,  0.0),  # EA root
        110: (27.11325, 5.0,  0.0),  # EA mid
        111: (24.61325, 5.0,  0.0),  # LE stringer (RBAR slave of 110)
        112: (29.61325, 5.0,  0.0),  # TE stringer (RBAR slave of 110)
        120: (21.33975, 15.0, 0.0),  # EA tip
        121: (18.83975, 15.0, 0.0),  # LE stringer (RBAR slave of 120)
        122: (23.83975, 15.0, 0.0),  # TE stringer (RBAR slave of 120)
    }
    for gid, (x, y, z) in wing_grids.items():
        bulk.grids[gid] = Grid(gid=gid, cp=0, x=x, y=y, z=z, cd=0)

    # CID 2: A=(30,0,0), B=(30,0,10), C=(25,8.66025,0)
    # Derived: x_hat=(−0.5,0.866,0), y_hat=(−0.866,−0.5,0), z_hat=(0,0,1)
    bulk.cord2rs[2] = Cord2r(cid=2, rid=0,
                              a=(30.0, 0.0, 0.0),
                              b=(30.0, 0.0, 10.0),
                              c=(25.0, 8.66025, 0.0))

    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=10.0, bref=40.0, sref=200.0,
                       symxz=0, symxy=0)
    bulk.paero1s[1000] = Paero1(pid=1000)

    # CAERO1 1100: 8-span × 4-chord, chord=10 ft
    bulk.caero1s[1100] = Caero1(
        eid=1100, pid=1000, cp=0, nspan=8, nchord=4,
        lspan=0, lchord=0, igid=1,
        p1=(25.0,     0.0,  0.0), x12=10.0,
        p4=(13.45299, 20.0, 0.0), x43=10.0,
    )

    # EA-only SET1: only grids on the swept elastic axis. The 1-D beam spline
    # requires collinearity along x_hat; LE/TE stringers carry no spanwise
    # bending information distinct from the EA grids and would alias as
    # spurious slope under any chordwise-asymmetric deformation.
    bulk.set1s[1100] = Set1(sid=1100, grids=[100, 110, 120])

    # SPLINE2 1601: DTHX=+1 (attached). With the AE1 Step B spline-formula fix
    # (multiplication-bending + corrected torsion), the attached path is what
    # reproduces global basic-frame rigid-body modes on the swept spline.
    bulk.spline2s[1601] = Spline2(
        eid=1601, caero=1100, id1=1100, id2=1131, setg=1100,
        dz=0.0, dtor=1.0, cid=2, dthx=1.0, dthz=-1.0, usage="BOTH",
    )

    return bulk


class TestSweptSplineRigidBody:
    """V-AE2 gate — HA144A CID-2 swept wing spline.

    AE4 fix verification: swept-axis slope projection and nodal-slope sign.
    AE6 fix verification: force transfer moment conservation at ¼-chord.
    """

    @pytest.fixture(scope="class")
    def vae2_ops(self):
        """Build g_slope and g_disp for the HA144A CID-2 wing spline."""
        from sbeam.aero.panel import mesh_caero1

        bulk = _build_ha144a_wing_spline_bulk()
        caero = bulk.caero1s[1100]
        boxes = mesh_caero1(caero, bulk.paero1s[1000], bulk.aefacts, bulk.cord2rs, start_k=0)
        gids_sorted = sorted(bulk.grids.keys())
        grid_index = {gid: i for i, gid in enumerate(gids_sorted)}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
        return g_slope, g_disp, boxes, grid_index, bulk

    def test_vae2a_rigid_plunge_zero_downwash(self, vae2_ops):
        """V-AE2a: Uniform Tz=1 at all wing grids → zero downwash at all boxes."""
        g_slope, _, boxes, grid_index, _ = vae2_ops
        n_g = 6 * len(grid_index)
        u = np.zeros(n_g)
        for gi in grid_index.values():
            u[6 * gi + 2] = 1.0   # Tz = 1 at every grid
        downwash = g_slope @ u
        assert np.allclose(downwash, 0.0, atol=1e-12), (
            f"V-AE2a: rigid plunge must give zero downwash; "
            f"max |w| = {np.max(np.abs(downwash)):.3e}"
        )

    def test_vae2b_rigid_pitch_uniform_incidence(self, vae2_ops):
        """V-AE2b: Rigid beam pitch → uniform incidence θ at all boxes.

        For the 1D beam spline, the rigid pitch is defined along the spline axis:
          Tz_i = −x_hat[0] · s_i · θ  (linear in s → exact Hermite reproduction)
          Ry_i = θ  (nodal slope = −(θ·y_hat[1]) = 0.5θ = −x_hat[0]·θ)
        Result: dh/ds = −x_hat[0]·θ everywhere → w = −(dh/ds)/x_hat[0] = θ.
        """
        from sbeam.assembly.coord_transform import _get_transform
        g_slope, _, boxes, grid_index, bulk = vae2_ops
        sp = bulk.spline2s[1601]
        origin, R_cid = _get_transform(sp.cid, bulk.cord2rs)
        x_hat = R_cid[:, 0]   # (−0.5, 0.866, 0) for CID-2
        x0 = x_hat[0]          # −0.5

        theta = 1e-3
        n_g = 6 * len(grid_index)
        u = np.zeros(n_g)
        for gid, gi in grid_index.items():
            g = bulk.grids[gid]
            r = np.array([g.x, g.y, g.z])
            s_i = float(np.dot(r - origin, x_hat))
            u[6 * gi + 2] = -x0 * s_i * theta   # Tz = 0.5·s·θ (linear in s)
            u[6 * gi + 4] = theta                 # Ry = θ

        downwash = g_slope @ u
        assert np.allclose(downwash, theta, atol=1e-12), (
            f"V-AE2b: rigid beam pitch must give uniform downwash={theta}; "
            f"range [{downwash.min():.4e}, {downwash.max():.4e}], "
            f"max |err| = {np.max(np.abs(downwash - theta)):.3e}"
        )

    def test_vae2c_gdisp_uses_force_point(self, vae2_ops):
        """V-AE2c: g_disp is evaluated at force_point (¼-chord), not at colloc (¾-chord).

        Directly verifies AE6 fix: for the translation Tz DOF of the first sorted
        grid, g_disp[3k+2, col_Tz] must equal the Hermite function-value basis
        evaluated at t_force = (force_point − origin)·x_hat, NOT at
        t_slope = (colloc − origin)·x_hat.
        """
        from scipy.interpolate import CubicHermiteSpline
        from sbeam.assembly.coord_transform import _get_transform

        g_slope, g_disp, boxes, grid_index, bulk = vae2_ops
        sp = bulk.spline2s[1601]
        origin, R_cid = _get_transform(sp.cid, bulk.cord2rs)
        x_hat = R_cid[:, 0]
        z_hat = R_cid[:, 2]

        # Sorted grids — same ordering as _build_spline2_block
        set1 = bulk.set1s[sp.setg]
        s_gid = sorted(
            (float(np.dot(np.array([bulk.grids[g].x, bulk.grids[g].y, bulk.grids[g].z]) - origin, x_hat)), g)
            for g in set1.grids
        )
        s_sorted = np.array([s for s, _ in s_gid])
        gids_sorted = [gid for _, gid in s_gid]

        # Hermite function-value basis for the first grid (unit value at node 0)
        n_s = len(s_sorted)
        y_f = np.zeros(n_s); y_f[0] = 1.0
        cs = CubicHermiteSpline(s_sorted, y_f, np.zeros(n_s))

        box0 = boxes[0]
        t_force = float(np.dot(box0.force_point - origin, x_hat))
        t_slope = float(np.dot(box0.colloc     - origin, x_hat))

        # Sanity: the two evaluation points must differ for the test to be meaningful
        assert abs(t_force - t_slope) > 1e-3, (
            f"V-AE2c: force_point and colloc must project to different t values; "
            f"t_force={t_force:.4f}, t_slope={t_slope:.4f}"
        )

        gi_0 = grid_index[gids_sorted[0]]
        col_tz = 6 * gi_0 + 2     # Tz DOF column for first sorted grid
        k0 = box0.k

        z_sq = float(z_hat[2] ** 2)   # = 1.0 for CID-2 (z_hat = (0,0,1))
        expected_force = z_sq * float(cs(t_force))
        expected_slope = z_sq * float(cs(t_slope))

        actual = float(g_disp[3 * k0 + 2, col_tz])

        assert abs(actual - expected_force) < 1e-12, (
            f"V-AE2c: g_disp[Tz row, col_Tz_0] must equal Hermite φ_0(t_force)="
            f"{expected_force:.8f}; got {actual:.8f} "
            f"(old colloc value would be {expected_slope:.8f})"
        )


# ---------------------------------------------------------------------------
# V-AE1b: Global rigid-body kinematic gate
# ---------------------------------------------------------------------------

def _apply_rigid_body(
    bulk: BulkData,
    grid_index: dict,
    mode: str,
    ref_point=(0.0, 0.0, 0.0),
) -> np.ndarray:
    """Build a g-set displacement vector for a basic-frame rigid-body mode.

    For translations the mode DOF is set to 1 at every grid (all other DOFs zero).
    For rotations the nodal rotation ω = ê_d is set on every grid, and the
    translation DOFs are filled with the lever-arm displacement ω × (r − ref).

    Args:
        bulk:       Bulk data with grid positions.
        grid_index: {gid: i} mapping from build_grid_index.
        mode:       One of 'Tx', 'Ty', 'Tz', 'Rx', 'Ry', 'Rz'.
        ref_point:  Reference point for rotation lever arms (basic frame).

    Returns:
        u_g of shape (6 * n_grid,) with the requested rigid-body motion applied
        uniformly to every grid. No structural reduction is performed; this is
        the kinematic input that a correct spline must reproduce exactly.
    """
    n_g = 6 * len(grid_index)
    u = np.zeros(n_g)
    ref = np.asarray(ref_point, dtype=float)

    trans = {'Tx': 0, 'Ty': 1, 'Tz': 2}
    rot   = {'Rx': 0, 'Ry': 1, 'Rz': 2}

    if mode in trans:
        d = trans[mode]
        for gi in grid_index.values():
            u[6 * gi + d] = 1.0
        return u

    if mode in rot:
        d = rot[mode]
        omega = np.zeros(3)
        omega[d] = 1.0
        for gid, gi in grid_index.items():
            g = bulk.grids[gid]
            r = np.array([g.x, g.y, g.z]) - ref
            u[6 * gi + 0:6 * gi + 3] = np.cross(omega, r)
            u[6 * gi + 3:6 * gi + 6] = omega
        return u

    raise ValueError(f"Unknown rigid-body mode: {mode!r}")


def _expected_planar_downwash(boxes, mode: str) -> np.ndarray:
    """Analytic streamwise downwash w = −∂u_z/∂x_basic for a flat wing in xy-plane.

    A flat planar wing in the basic xy-plane senses non-zero w only under a
    basic-frame pitch about y (Ry). All other rigid-body modes produce zero
    streamwise downwash because they neither tilt the surface in the streamwise
    direction nor change u_z linearly with x.
    """
    n_box = len(boxes)
    w = np.zeros(n_box)
    if mode == 'Ry':
        w[:] = 1.0
    return w


def _expected_planar_disp(boxes, mode: str, ref_point=(0.0, 0.0, 0.0)) -> np.ndarray:
    """Analytic 3-D displacement at every box force_point for a flat wing.

    Returns shape (3 * n_box,) with components interleaved as (ux, uy, uz, …)
    per box, matching the layout of g_disp.
    """
    n_box = len(boxes)
    disp = np.zeros(3 * n_box)
    ref = np.asarray(ref_point, dtype=float)

    if mode in ('Tx', 'Ty', 'Tz'):
        d = {'Tx': 0, 'Ty': 1, 'Tz': 2}[mode]
        for j in range(n_box):
            disp[3 * j + d] = 1.0
        return disp

    if mode in ('Rx', 'Ry', 'Rz'):
        d = {'Rx': 0, 'Ry': 1, 'Rz': 2}[mode]
        omega = np.zeros(3)
        omega[d] = 1.0
        for j, box in enumerate(boxes):
            r = np.asarray(box.force_point, dtype=float) - ref
            disp[3 * j:3 * (j + 1)] = np.cross(omega, r)
        return disp

    raise ValueError(f"Unknown rigid-body mode: {mode!r}")


class TestGlobalRigidBody:
    """V-AE1b — Global rigid-body kinematic gate for `g_slope` / `g_disp`.

    For each of the 6 basic-frame rigid-body modes applied to *every* grid (not
    just SET1), assert that a correct spline reproduces the analytic
    streamwise downwash and box-surface displacement field. The gate is the
    only test that catches the SET1-collinearity defect that contaminated Q_aa
    in the V-AE1 trim solve — V-AE2b passed by feeding a kinematic state
    pre-projected onto the spline parameter, which is not the case the trim
    solver actually produces.

    Tolerance: 1e-5 for HA144A (the BDF coordinates are rounded to ~5 decimals
    so the Hermite slope match is limited by grid-position precision, not the
    spline math). 1e-12 for the math-exact rectangular fixture where the
    floor is floating-point arithmetic. A correct spline on mathematically
    exact input is exact to machine precision; on HA144A the residual is
    dominated by 5-decimal coordinate rounding (the position difference
    between e.g. GRID 110 at 27.11325 vs the math-exact 27.113248... is
    ~3e-6, which propagates linearly to the slope mismatch).
    """

    ATOL_HA144A = 1e-5
    ATOL_RECT   = 1e-12

    # ------------------------------------------------------------------ #
    # Fixture 1: HA144A swept wing (CID-2), EA-only SET1 (B2 fix)
    # ------------------------------------------------------------------ #
    @pytest.fixture(scope="class")
    def ha144a_wing_ops(self):
        from sbeam.aero.panel import mesh_caero1
        bulk = _build_ha144a_wing_spline_bulk()
        caero = bulk.caero1s[1100]
        boxes = mesh_caero1(caero, bulk.paero1s[1000], bulk.aefacts, bulk.cord2rs, start_k=0)
        gids_sorted = sorted(bulk.grids.keys())
        grid_index = {gid: i for i, gid in enumerate(gids_sorted)}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
        # Reference point for pitch lever-arm: HA144A trim reference x = 15
        return g_slope, g_disp, boxes, grid_index, bulk, (15.0, 0.0, 0.0)

    @pytest.mark.parametrize("mode", ["Tx", "Ty", "Tz", "Rx", "Ry", "Rz"])
    def test_ha144a_wing_downwash(self, ha144a_wing_ops, mode):
        """Swept wing g_slope reproduces the analytic streamwise downwash."""
        g_slope, _, boxes, grid_index, bulk, ref = ha144a_wing_ops
        u = _apply_rigid_body(bulk, grid_index, mode, ref_point=ref)
        w = g_slope @ u
        w_expected = _expected_planar_downwash(boxes, mode)
        err = np.max(np.abs(w - w_expected))
        assert err < self.ATOL_HA144A, (
            f"V-AE1b HA144A wing mode={mode}: g_slope·u_rb residual {err:.3e} "
            f"exceeds tol {self.ATOL_HA144A:.0e}; "
            f"got range [{w.min():.4e}, {w.max():.4e}], expected uniform "
            f"{w_expected[0] if len(w_expected) else 0.0}."
        )

    @pytest.mark.parametrize("mode", ["Tx", "Ty", "Tz", "Rx", "Ry", "Rz"])
    def test_ha144a_wing_disp(self, ha144a_wing_ops, mode):
        """Swept wing g_disp at each box force_point matches rigid-body kinematics."""
        _, g_disp, boxes, grid_index, bulk, ref = ha144a_wing_ops
        u = _apply_rigid_body(bulk, grid_index, mode, ref_point=ref)
        disp = g_disp @ u
        disp_expected = _expected_planar_disp(boxes, mode, ref_point=ref)
        # g_disp ships only the z-row contribution today (a flat wing assumption);
        # check the z-component, which is what the trim force transfer integrates.
        z_actual   = disp[2::3]
        z_expected = disp_expected[2::3]
        err = np.max(np.abs(z_actual - z_expected))
        assert err < self.ATOL_HA144A, (
            f"V-AE1b HA144A wing mode={mode}: g_disp_z residual {err:.3e} "
            f"exceeds tol {self.ATOL_HA144A:.0e}; "
            f"got range [{z_actual.min():.4e}, {z_actual.max():.4e}], "
            f"expected range [{z_expected.min():.4e}, {z_expected.max():.4e}]."
        )

    # ------------------------------------------------------------------ #
    # Fixture 2: Unswept rectangular wing — regression guard (no RBARs)
    # ------------------------------------------------------------------ #
    @pytest.fixture(scope="class")
    def rect_wing_ops(self):
        """Rectangular unswept wing — math-exact grid positions, CID-3 spline.

        Spline CID 3: A=(0,0,0), B=(0,0,1), C=(0,1,0) → x_hat=(0,1,0),
        y_hat=(−1,0,0), z_hat=(0,0,1). EA grids at x=0 (on the spline axis,
        chord offset = 0) from y=0 to y=8. Five-grid SET1 covers the span.

        The unswept case must pass to machine precision; included as a
        regression guard so a future swept-spline fix doesn't regress it.
        """
        from sbeam.aero.panel import mesh_caero1
        from sbeam.model.aero import Aeros, Paero1, Caero1, Set1, Spline2

        bulk = BulkData()
        # EA grids on the spline axis (x = 0), exact integer y positions
        for i in range(5):
            gid = 100 + i
            bulk.grids[gid] = Grid(gid=gid, cp=0, x=0.0, y=2.0 * i, z=0.0, cd=0)

        bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=8.0, sref=8.0,
                           symxz=0, symxy=0)
        bulk.paero1s[1000] = Paero1(pid=1000)
        # CAERO1 leading edge at x=−0.25 so the EA (x=0) sits at ¼-chord
        bulk.caero1s[1100] = Caero1(
            eid=1100, pid=1000, cp=0, nspan=8, nchord=4,
            lspan=0, lchord=0, igid=1,
            p1=(-0.25, 0.0, 0.0), x12=1.0,
            p4=(-0.25, 8.0, 0.0), x43=1.0,
        )
        bulk.set1s[1100] = Set1(sid=1100, grids=[100, 101, 102, 103, 104])
        # CID 3: x_hat=(0,1,0) (spanwise), y_hat=(−1,0,0), z_hat=(0,0,1)
        bulk.cord2rs[3] = Cord2r(cid=3, rid=0,
                                  a=(0.0, 0.0, 0.0),
                                  b=(0.0, 0.0, 1.0),
                                  c=(0.0, 1.0, 0.0))
        bulk.spline2s[1601] = Spline2(
            eid=1601, caero=1100, id1=1100, id2=1131, setg=1100,
            dz=0.0, dtor=1.0, cid=3, dthx=1.0, dthz=-1.0, usage="BOTH",
        )
        boxes = mesh_caero1(bulk.caero1s[1100], bulk.paero1s[1000], bulk.aefacts,
                            bulk.cord2rs, start_k=0)
        grid_index = {gid: i for i, gid in enumerate(sorted(bulk.grids))}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
        return g_slope, g_disp, boxes, grid_index, bulk, (0.0, 4.0, 0.0)

    @pytest.mark.parametrize("mode", ["Tx", "Ty", "Tz", "Rx", "Ry", "Rz"])
    def test_rect_wing_downwash(self, rect_wing_ops, mode):
        """Unswept rectangular wing g_slope reproduces the analytic downwash."""
        g_slope, _, boxes, grid_index, bulk, ref = rect_wing_ops
        u = _apply_rigid_body(bulk, grid_index, mode, ref_point=ref)
        w = g_slope @ u
        w_expected = _expected_planar_downwash(boxes, mode)
        err = np.max(np.abs(w - w_expected))
        assert err < self.ATOL_RECT, (
            f"V-AE1b rect wing mode={mode}: g_slope·u_rb residual {err:.3e} "
            f"exceeds tol {self.ATOL_RECT:.0e}."
        )

    # ------------------------------------------------------------------ #
    # Fixture 3: 30° dihedral wing — out-of-plane (z != 0) geometry
    # ------------------------------------------------------------------ #
    @pytest.fixture(scope="class")
    def dihedral_wing_ops(self):
        """30° dihedral wing — CAERO, grids, and spline CID all tilted about x.

        The only fixture with z != 0 grids and a non-vertical surface normal.
        Tilting the surface about the streamwise x-axis by Γ=30° gives the
        normal a y-component, so a rigid YAW (Rz) now LOADS the aero
        (g_slope·u_Rz = sin Γ) where it is null for a planar wing. Rigid
        translations and ROLL (Rx) stay in the Q_aa null space. This is the
        out-of-plane coupling the two planar fixtures cannot exercise.

            span   ŝ = (0, cosΓ, sinΓ)
            normal n̂ = (0, −sinΓ, cosΓ)
        Spline CID 3: A=origin, B=A+n̂ (z-axis = normal), C=A+ŝ (xz-plane) →
            x_hat = ŝ, z_hat = n̂, y_hat = (−1, 0, 0).
        Math-exact: the spline is built from the same float coordinates the
        analytic null space assumes, so the null residual is the FP floor.
        """
        from sbeam.aero.panel import mesh_caero1
        from sbeam.model.aero import Aeros, Paero1, Caero1, Set1, Spline2

        gamma = np.deg2rad(30.0)
        c, s = float(np.cos(gamma)), float(np.sin(gamma))
        span = np.array([0.0, c, s])

        bulk = BulkData()
        # EA grids along the tilted span axis (x = 0)
        for i in range(5):
            gid = 100 + i
            p = 2.0 * i * span
            bulk.grids[gid] = Grid(gid=gid, cp=0, x=0.0, y=p[1], z=p[2], cd=0)

        bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=8.0, sref=8.0,
                           symxz=0, symxy=0)
        bulk.paero1s[1000] = Paero1(pid=1000)
        # CAERO leading edge at x=−0.25 (EA at ¼-chord), span swept into z
        bulk.caero1s[1100] = Caero1(
            eid=1100, pid=1000, cp=0, nspan=8, nchord=4,
            lspan=0, lchord=0, igid=1,
            p1=(-0.25, 0.0, 0.0), x12=1.0,
            p4=(-0.25, 8.0 * c, 8.0 * s), x43=1.0,
        )
        bulk.set1s[1100] = Set1(sid=1100, grids=[100, 101, 102, 103, 104])
        # CID 3: z-axis = tilted surface normal, x-axis = tilted span
        bulk.cord2rs[3] = Cord2r(cid=3, rid=0,
                                 a=(0.0, 0.0, 0.0),
                                 b=(0.0, -s, c),
                                 c=(0.0, c, s))
        bulk.spline2s[1601] = Spline2(
            eid=1601, caero=1100, id1=1100, id2=1131, setg=1100,
            dz=0.0, dtor=1.0, cid=3, dthx=1.0, dthz=-1.0, usage="BOTH",
        )
        boxes = mesh_caero1(bulk.caero1s[1100], bulk.paero1s[1000], bulk.aefacts,
                            bulk.cord2rs, start_k=0)
        grid_index = {gid: i for i, gid in enumerate(sorted(bulk.grids))}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
        # Reference point: mid-span on the tilted elastic axis
        return g_slope, g_disp, boxes, grid_index, bulk, (0.0, 4.0 * c, 4.0 * s)

    # ------------------------------------------------------------------ #
    # Composed Q_aa rigid-body null-space gate (AE1 Step C)
    # ------------------------------------------------------------------ #
    #
    # Q_aa = G_disp^T S_kj (A_jj*)^-1 D_jk G_slope is the flexible aero
    # stiffness fed into K_eff = K_aa − q·Q_aa.  A rigid-body mode that does
    # not load the aero must lie in its null space: Q_aa·u_rb ≈ 0.  The
    # methods above gate the factors (g_slope, g_disp); these gate the
    # COMPOSED operator end-to-end, the quantity the trim solver actually
    # uses.  Per fixture the null set differs by geometry:
    #   planar swept (HA144A) : {Tx,Ty,Tz,Rz} exact; Rx rounding-limited; Ry loads
    #   planar rect           : {Tx,Ty,Tz,Rx,Rz} exact; Ry loads
    #   30° dihedral          : {Tx,Ty,Tz,Rx} exact; Ry AND Rz load (out-of-plane)
    # Pitch (Ry) — and yaw (Rz) on the dihedral wing — legitimately load the
    # aero and serve as positive discriminators, so the gate can never pass
    # trivially on an all-zero Q_aa.

    ATOL_QAA = 1e-10        # machine-precision null-space residual

    @staticmethod
    def _build_qaa(ops):
        """Assemble Q_aa for a fixture via the real build_aero_model chain.

        Returns (Q_aa, bulk, grid_index, ref_point).
        """
        _g_slope, _g_disp, _boxes, grid_index, bulk, ref = ops
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero = build_aero_model(bulk, grid_index=grid_index)
        Q_aa = build_qaa(aero, aero.g_disp, aero.g_slope)
        return Q_aa, bulk, grid_index, ref

    @staticmethod
    def _qaa_residual(Q_aa, bulk, grid_index, mode, ref):
        """‖Q_aa · u_rb‖∞ for a basic-frame rigid-body mode."""
        u = _apply_rigid_body(bulk, grid_index, mode, ref_point=ref)
        return float(np.max(np.abs(Q_aa @ u)))

    @pytest.fixture(scope="class")
    def ha144a_qaa(self, ha144a_wing_ops):
        return self._build_qaa(ha144a_wing_ops)

    @pytest.fixture(scope="class")
    def rect_qaa(self, rect_wing_ops):
        return self._build_qaa(rect_wing_ops)

    @pytest.fixture(scope="class")
    def dihedral_qaa(self, dihedral_wing_ops):
        return self._build_qaa(dihedral_wing_ops)

    # ---- null-space residuals (machine precision) -------------------- #

    @pytest.mark.parametrize("mode", ["Tx", "Ty", "Tz", "Rz"])
    def test_qaa_nullspace_ha144a(self, ha144a_qaa, mode):
        """Swept-planar HA144A: translations and yaw lie in the Q_aa null space."""
        Q_aa, bulk, gi, ref = ha144a_qaa
        res = self._qaa_residual(Q_aa, bulk, gi, mode, ref)
        assert res < self.ATOL_QAA, (
            f"AE1 Step C HA144A mode={mode}: ‖Q_aa·u_rb‖∞ {res:.3e} "
            f"exceeds null-space tol {self.ATOL_QAA:.0e}."
        )

    def test_qaa_ha144a_rx_bounded(self, ha144a_qaa):
        """Rx on HA144A is null only to ~1e-4: g_slope·u_Rx is coordinate-
        rounding limited (5-decimal BDF coords on the swept EA line) and
        amplified by ‖Q_aa‖≈2.1e3 (measured 1.4e-4). Gate it BOUNDED so a
        gross spline regression still trips; the machine-precision Rx null is
        proved on the math-exact rect and dihedral fixtures instead."""
        Q_aa, bulk, gi, ref = ha144a_qaa
        res = self._qaa_residual(Q_aa, bulk, gi, "Rx", ref)
        assert res < 1e-3, (
            f"AE1 Step C HA144A Rx: ‖Q_aa·u_rb‖∞ {res:.3e} exceeds the "
            f"coordinate-rounding bound 1e-3 (expected ~1.4e-4)."
        )

    @pytest.mark.parametrize("mode", ["Tx", "Ty", "Tz", "Rx", "Rz"])
    def test_qaa_nullspace_rect(self, rect_qaa, mode):
        """Planar rect (math-exact): translations, roll, and yaw all null."""
        Q_aa, bulk, gi, ref = rect_qaa
        res = self._qaa_residual(Q_aa, bulk, gi, mode, ref)
        assert res < self.ATOL_QAA, (
            f"AE1 Step C rect mode={mode}: ‖Q_aa·u_rb‖∞ {res:.3e} "
            f"exceeds null-space tol {self.ATOL_QAA:.0e}."
        )

    @pytest.mark.parametrize("mode", ["Tx", "Ty", "Tz", "Rx"])
    def test_qaa_nullspace_dihedral(self, dihedral_qaa, mode):
        """30° dihedral (math-exact, z != 0): translations and roll null.

        Yaw (Rz) is deliberately excluded — for a dihedral surface it LOADS
        the aero (see test_qaa_dihedral_yaw_loads), which is the whole point
        of this out-of-plane fixture."""
        Q_aa, bulk, gi, ref = dihedral_qaa
        res = self._qaa_residual(Q_aa, bulk, gi, mode, ref)
        assert res < self.ATOL_QAA, (
            f"AE1 Step C dihedral mode={mode}: ‖Q_aa·u_rb‖∞ {res:.3e} "
            f"exceeds null-space tol {self.ATOL_QAA:.0e}."
        )

    # ---- positive discriminators (rigid modes that LOAD the aero) ---- #

    @pytest.mark.parametrize("fixture_name", ["ha144a_qaa", "rect_qaa", "dihedral_qaa"])
    def test_qaa_pitch_loads(self, request, fixture_name):
        """Rigid pitch (Ry) is NOT a null-space member — it loads the aero on
        every fixture, so a degenerate all-zero Q_aa cannot pass the gate."""
        Q_aa, bulk, gi, ref = request.getfixturevalue(fixture_name)
        res = self._qaa_residual(Q_aa, bulk, gi, "Ry", ref)
        assert res > 1.0, (
            f"AE1 Step C {fixture_name}: rigid pitch ‖Q_aa·u_Ry‖∞ {res:.3e} "
            f"is suspiciously small — Q_aa may be degenerate."
        )

    def test_qaa_dihedral_yaw_loads(self, dihedral_qaa):
        """Out-of-plane signature: on a 30° dihedral wing, rigid YAW (Rz)
        loads the aero (g_slope·u_Rz = sin Γ = 0.5), unlike a planar wing
        where it is null. Confirms the fixture exercises real out-of-plane
        coupling rather than a relabelled planar case."""
        Q_aa, bulk, gi, ref = dihedral_qaa
        res = self._qaa_residual(Q_aa, bulk, gi, "Rz", ref)
        assert res > 1.0, (
            f"AE1 Step C dihedral yaw: ‖Q_aa·u_Rz‖∞ {res:.3e} is too small — "
            f"the dihedral surface is not coupling yaw into the aero."
        )


# ─────────────────────────────────────────────────────────────────────────────
# AE12 — SPLINE2 DTOR / DTHZ warning gates
# ─────────────────────────────────────────────────────────────────────────────

class TestSpline2DtorDthzWarnings:
    """AE12 — DTOR/DTHZ are parsed and stored but not modelled by the beam
    spline. sbeam must warn when a card carries a value it will ignore:
    DTOR ≠ 1.0, or DTHZ requesting Rz attachment. DTHZ ∈ {0.0, −1.0}
    (blank/default, NASTRAN "Rz detached") matches sbeam's actual behaviour
    and stays silent — the HA144A decks carry DTHZ=−1.0 throughout."""

    def _build(self, dtor=1.0, dthz=-1.0):
        from sbeam.aero.panel import mesh_caero1

        bulk = _build_ha144a_wing_spline_bulk()
        sp = bulk.spline2s[1601]
        sp.dtor = dtor
        sp.dthz = dthz
        caero = bulk.caero1s[1100]
        boxes = mesh_caero1(caero, bulk.paero1s[1000], bulk.aefacts,
                            bulk.cord2rs, start_k=0)
        gids_sorted = sorted(bulk.grids.keys())
        grid_index = {gid: i for i, gid in enumerate(gids_sorted)}
        return bulk, boxes, grid_index

    def test_dtor_nondefault_warns(self):
        bulk, boxes, grid_index = self._build(dtor=0.5)
        with pytest.warns(UserWarning, match=r"SPLINE2 1601: DTOR=0\.5"):
            build_g_spline(bulk, boxes, grid_index)

    def test_dthz_attached_warns(self):
        bulk, boxes, grid_index = self._build(dthz=1.0)
        with pytest.warns(UserWarning, match=r"SPLINE2 1601: DTHZ=1\.0"):
            build_g_spline(bulk, boxes, grid_index)

    @pytest.mark.parametrize("dthz", [0.0, -1.0])
    def test_default_and_detached_stay_silent(self, dthz):
        """DTOR=1.0 with DTHZ blank (0.0) or NASTRAN-detached (−1.0) must not
        warn — the HA144A validation decks would otherwise spam every run."""
        bulk, boxes, grid_index = self._build(dtor=1.0, dthz=dthz)
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            build_g_spline(bulk, boxes, grid_index)
        offenders = [str(w.message) for w in rec
                     if "DTOR" in str(w.message) or "DTHZ" in str(w.message)]
        assert offenders == []
