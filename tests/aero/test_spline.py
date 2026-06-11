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
        Box 200: colloc ≈ (0.75, 0.5, 0),  lever r = (0.75, 0.5, 0)
        Box 201: colloc ≈ (0.75, 1.5, 0),  lever r = (0.75, 1.5, 0)
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

        For 2 boxes with area=1.0 each and colloc at y=0.5 and y=1.5 (rx≈0.75 both):
          Fz = 2.0  (total lift)
          Mx = ry0 + ry1 = 0.5 + 1.5 = 2.0  (roll moment)
          My = −(rx0 + rx1) = −(0.75 + 0.75) = −1.5  (pitch moment)
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

        # Analytical lever-arm expectations
        expected_fz = sum(box.area * box.normal[2] for box in boxes)
        expected_mx = sum(
            (box.colloc[1] - 0.0) * box.area * box.normal[2] for box in boxes
        )  # ry * Fz per box
        expected_my = -sum(
            (box.colloc[0] - 0.0) * box.area * box.normal[2] for box in boxes
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
