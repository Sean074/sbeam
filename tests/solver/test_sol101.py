"""Tests for Step 10: SOL 101 solve and displacement recovery."""

import math
import numpy as np
import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Force
from sbeam.model.constraint import Spc1
from sbeam.model.bulk_data import BulkData
from sbeam.assembly.stiffness import (
    assemble_global_stiffness,
    get_spc_dofs,
    apply_spcs,
)
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.solver.sol101 import solve_static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_cantilever_bulk(L=1.0, E=2e11, I=8.333e-4, A=0.05, P=1000.0):
    """Single-element cantilever along X, tip load in Y."""
    G = E / (2 * (1 + 0.3))
    J = 2 * I
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=L,   y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=E, G=G, nu=0.3, rho=7850.0)
    bulk.pbars[10] = Pbar(pid=10, mid=1, A=A, I1=I, I2=I, J=J,
                          c1=0.0, c2=0.0)
    bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    bulk.forces[10] = [Force(sid=10, gid=2, cid=0, f=P, n1=0.0, n2=1.0, n3=0.0)]
    return bulk


def make_simply_supported_bulk(n_elem=10, L_total=1.0, E=2e11, I=8.333e-4, A=0.05, P=1000.0):
    """n_elem-element simply supported beam along X, mid-span load in Y."""
    G = E / (2 * (1 + 0.3))
    J = 2 * I
    bulk = BulkData()

    dx = L_total / n_elem
    for i in range(n_elem + 1):
        gid = i + 1
        bulk.grids[gid] = Grid(gid=gid, x=i * dx, y=0.0, z=0.0)

    bulk.mat1s[1] = Mat1(mid=1, E=E, G=G, nu=0.3, rho=7850.0)
    bulk.pbars[10] = Pbar(pid=10, mid=1, A=A, I1=I, I2=I, J=J)

    for i in range(n_elem):
        eid = i + 1
        bulk.cbars[eid] = Cbar(eid=eid, pid=10, ga=i+1, gb=i+2, x1=0.0, x2=1.0, x3=0.0)

    # Simple pin supports (Euler-Bernoulli, bending in XY plane):
    # Left pin:  Tx(1), Ty(2), Tz(3), Rx(4) fixed — rotations Ry,Rz free
    # Right pin: Ty(2), Tz(3), Rx(4) fixed — Tx free (roller), rotations free
    bulk.spc1s[1] = [
        Spc1(sid=1, c="1234", grids=[1]),
        Spc1(sid=1, c="234",  grids=[n_elem + 1]),
    ]

    # Mid-span load in Y
    mid_gid = n_elem // 2 + 1
    bulk.forces[10] = [Force(sid=10, gid=mid_gid, cid=0, f=P, n1=0.0, n2=1.0, n3=0.0)]

    return bulk


# ---------------------------------------------------------------------------
# Step 10 tests
# ---------------------------------------------------------------------------

class TestSolveSingular:
    def test_singular_raises(self):
        """Unconstrained model → singular stiffness → ValueError."""
        K_sing = np.zeros((6, 6))
        f = np.zeros(6)
        with pytest.raises(ValueError, match="[Ss]ingular"):
            solve_static(K_sing, f, list(range(6)), 12)


class TestCantileverTipLoad:
    """Single-element cantilever: verify tip deflection and rotation."""

    def setup_method(self):
        self.E = 2e11
        self.I = 8.333e-4
        self.A = 0.05
        self.L = 1.0
        self.P = 1000.0
        self.bulk = make_cantilever_bulk(
            L=self.L, E=self.E, I=self.I, A=self.A, P=self.P
        )
        grid_index = build_grid_index(self.bulk)
        n_dofs = 6 * len(grid_index)
        K = assemble_global_stiffness(self.bulk)
        f = assemble_load_vector(self.bulk, load_sid=10)
        spc_dofs = get_spc_dofs(self.bulk, spc_sid=1, grid_index=grid_index)
        K_free, f_free, free_dofs = apply_spcs(K, f, spc_dofs)
        self.u = solve_static(K_free, f_free, free_dofs, n_dofs)
        self.grid_index = grid_index

    def test_tip_displacement_ty(self):
        """Tip Ty = P*L³ / (3*E*I)."""
        expected = self.P * self.L**3 / (3 * self.E * self.I)
        # Tip is grid 2, index 1, Ty = dof 6*1+1 = 7
        tip_ty = self.u[7]
        assert tip_ty == pytest.approx(expected, rel=1e-3)

    def test_tip_rotation_rz(self):
        """Tip Rz = P*L² / (2*E*I)."""
        expected = self.P * self.L**2 / (2 * self.E * self.I)
        # Tip Rz = dof 6*1+5 = 11
        tip_rz = self.u[11]
        assert tip_rz == pytest.approx(expected, rel=1e-3)

    def test_fixed_end_zero(self):
        """All DOFs at fixed end must be zero."""
        for d in range(6):
            assert self.u[d] == pytest.approx(0.0, abs=1e-20)


class TestSimplySupportedMidSpanLoad:
    """10-element simply supported beam: mid-span deflection."""

    def test_midspan_deflection(self):
        E = 2e11
        I = 8.333e-4
        A = 0.05
        L = 2.0
        P = 1000.0
        n_elem = 10

        bulk = make_simply_supported_bulk(
            n_elem=n_elem, L_total=L, E=E, I=I, A=A, P=P
        )
        grid_index = build_grid_index(bulk)
        n_dofs = 6 * len(grid_index)
        K = assemble_global_stiffness(bulk)
        f = assemble_load_vector(bulk, load_sid=10)
        spc_dofs = get_spc_dofs(bulk, spc_sid=1, grid_index=grid_index)
        K_free, f_free, free_dofs = apply_spcs(K, f, spc_dofs)
        u = solve_static(K_free, f_free, free_dofs, n_dofs)

        expected = P * L**3 / (48 * E * I)

        # Mid-span grid: gid = n_elem//2 + 1 = 6
        mid_gid = n_elem // 2 + 1
        mid_idx = grid_index[mid_gid]
        ty = u[6 * mid_idx + 1]

        assert ty == pytest.approx(expected, rel=1e-3)
