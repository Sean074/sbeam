"""Tests for the shared RBE3+SPC a-set reduction (Step 59).

The equivalence tests reimplement the pre-refactor reduction logic from
``sol144._compute_aset_data`` / ``sol144._build_qaa_aset`` verbatim as a local
reference and assert ``reduce_to_aset`` products match exactly on an RBE3+SPC
model — the acceptance criterion for the Step 59 behaviour-identical refactor.
"""

import numpy as np
import pytest
import scipy.sparse

from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.model.element import Rbe3
from sbeam.model.constraint import Spc1
from sbeam.assembly.rbe3 import build_rbe3_transformation
from sbeam.assembly.stiffness import get_spc_dofs
from sbeam.assembly.reduction import reduce_to_aset, expand_to_g


def _rbe3_spc_bulk():
    """3 grids; RBE3 makes grid 3 dependent on grids 1-2; SPC1 fixes grid 1."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
    bulk.grids[3] = Grid(gid=3, x=0.5, y=0.0, z=0.0)
    bulk.rbe3s[10] = Rbe3(eid=10, refgrid=3, refc="123456",
                          wt_gc=[(1.0, "123456", [1, 2])])
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    return bulk


def _plain_spc_bulk():
    """2 grids, no rigid elements; SPC1 fixes grid 1 (identity-T path)."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    return bulk


def _grid_index(bulk):
    return {gid: i for i, gid in enumerate(sorted(bulk.grids.keys()))}


def _old_compute_aset_data(bulk, grid_index, spc_sid):
    """Pre-Step-59 sol144._compute_aset_data, reproduced verbatim as reference."""
    n_g = 6 * len(grid_index)
    T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, grid_index)
    if dep_dofs:
        dep_set = set(dep_dofs)
        red_map = {g: i for i, g in enumerate(red_dofs)}
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs_local = [red_map[d] for d in spc_dofs_full if d not in dep_set]
    else:
        red_dofs = list(range(n_g))
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs_local = spc_dofs_full
    constrained = set(spc_dofs_local)
    free_local = [i for i in range(len(red_dofs)) if i not in constrained]
    free_dofs = [red_dofs[i] for i in free_local]
    return T, dep_dofs, red_dofs, free_local, free_dofs


def _sym_matrix(n, seed=0):
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n))
    return A + A.T


class TestEquivalenceRbe3Spc:
    """reduce_to_aset must equal the old _compute_aset_data on an RBE3+SPC model."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.bulk = _rbe3_spc_bulk()
        self.gi = _grid_index(self.bulk)
        self.red = reduce_to_aset(self.bulk, self.gi, spc_sid=1)
        self.ref = _old_compute_aset_data(self.bulk, self.gi, spc_sid=1)

    def test_partition_data_equal(self):
        T, dep_dofs, red_dofs, free_local, free_dofs = self.ref
        np.testing.assert_array_equal(self.red.T, T)
        assert self.red.dep_dofs == dep_dofs
        assert self.red.red_dofs == red_dofs
        assert self.red.free_local == free_local
        assert self.red.free_dofs == free_dofs
        assert self.red.n_red == len(red_dofs)

    def test_reduce_matrix_matches_old_build_qaa_aset(self):
        # Old _build_qaa_aset dep-branch: T.T @ A @ T then np.ix_ slice.
        T, _dep, _red, free_local, _free = self.ref
        n_g = 6 * len(self.gi)
        K_gg = scipy.sparse.csr_matrix(_sym_matrix(n_g, seed=1))
        Q_gg = _sym_matrix(n_g, seed=2)

        K_ref = T.T @ K_gg @ T
        if hasattr(K_ref, "toarray"):
            K_ref = K_ref.toarray()
        K_ref = K_ref[np.ix_(free_local, free_local)]
        Q_ref = (T.T @ Q_gg @ T)[np.ix_(free_local, free_local)]

        np.testing.assert_array_equal(self.red.reduce_matrix(K_gg, dense=True), K_ref)
        np.testing.assert_array_equal(self.red.reduce_matrix(Q_gg), Q_ref)

    def test_reduce_vector_and_rect(self):
        T, _dep, _red, free_local, _free = self.ref
        n_g = 6 * len(self.gi)
        rng = np.random.default_rng(3)
        f_g = rng.standard_normal(n_g)
        A_gx = rng.standard_normal((n_g, 4))

        np.testing.assert_array_equal(
            self.red.reduce_vector(f_g), (T.T @ f_g)[free_local])
        np.testing.assert_array_equal(
            self.red.reduce_rect(A_gx), (T.T @ A_gx)[free_local, :])

    def test_expand_to_g_matches_module_function(self):
        n_a = len(self.red.free_local)
        u_a = np.arange(1.0, n_a + 1.0)
        via_method = self.red.expand_to_g(u_a)
        via_func = expand_to_g(u_a, self.red.T, self.red.free_local, self.red.n_red)
        np.testing.assert_array_equal(via_method, via_func)
        assert via_method.shape == (6 * len(self.gi),)


class TestNoRigidElements:
    """Identity-T path: red_dofs = range(n_g); sparsity must be preserved."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.bulk = _plain_spc_bulk()
        self.gi = _grid_index(self.bulk)
        self.red = reduce_to_aset(self.bulk, self.gi, spc_sid=1)

    def test_partition(self):
        assert self.red.dep_dofs == []
        assert self.red.red_dofs == list(range(12))
        # Grid 1 fully fixed → a-set is grid 2's six DOFs.
        assert self.red.free_local == [6, 7, 8, 9, 10, 11]
        assert self.red.free_dofs == [6, 7, 8, 9, 10, 11]

    def test_sparse_input_stays_sparse(self):
        K = scipy.sparse.csr_matrix(_sym_matrix(12, seed=4))
        K_aa = self.red.reduce_matrix(K)
        assert scipy.sparse.issparse(K_aa)
        np.testing.assert_array_equal(
            K_aa.toarray(), K.toarray()[np.ix_(self.red.free_local, self.red.free_local)])

    def test_dense_flag_forces_dense(self):
        K = scipy.sparse.csr_matrix(_sym_matrix(12, seed=5))
        K_aa = self.red.reduce_matrix(K, dense=True)
        assert isinstance(K_aa, np.ndarray)

    def test_reduce_vector_no_transform(self):
        f = np.arange(12.0)
        np.testing.assert_array_equal(self.red.reduce_vector(f), f[6:])

    def test_expand_scatter_roundtrip(self):
        u_a = np.arange(1.0, 7.0)
        u_g = self.red.expand_to_g(u_a)
        np.testing.assert_array_equal(u_g[6:], u_a)
        np.testing.assert_array_equal(u_g[:6], np.zeros(6))


class TestNoSpc:
    """spc_sid=None (free-free): the a-set is the whole reduced set."""

    def test_free_free_all_dofs_free(self):
        bulk = _plain_spc_bulk()
        gi = _grid_index(bulk)
        red = reduce_to_aset(bulk, gi, spc_sid=None)
        assert red.free_local == list(range(12))
        assert red.free_dofs == list(range(12))

    def test_rbe3_free_free(self):
        bulk = _rbe3_spc_bulk()
        gi = _grid_index(bulk)
        red = reduce_to_aset(bulk, gi, spc_sid=None)
        ref = _old_compute_aset_data(bulk, gi, spc_sid=None)
        assert red.free_local == ref[3]
        assert red.free_dofs == ref[4]


# ---------------------------------------------------------------------------
# DEF-M9 — an SPC on a rigid-dependent DOF must be fatal, not silently dropped
# ---------------------------------------------------------------------------

def _rbe2_spc_on_dependent_grid():
    """2-CBAR cantilever, grid 3 RBE2-slaved to grid 2, SPC1 also fixing grid 3.

    The reproduction from the defect report: this used to solve with
    u_z(3) following its master and zero warnings — the SPC never applied and
    no reaction reported.
    """
    from sbeam.model.element import Rbe2
    bulk = BulkData()
    for gid, x in ((1, 0.0), (2, 1.0), (3, 2.0)):
        bulk.grids[gid] = Grid(gid=gid, x=x, y=0.0, z=0.0)
    bulk.rbe2s[100] = Rbe2(eid=100, gn=2, cm="123456", gm=[3])
    bulk.spc1s[5] = [Spc1(sid=5, c="123456", grids=[3])]
    return bulk


class TestSpcOnDependentDof:

    def test_spc_on_a_dependent_dof_raises(self):
        bulk = _rbe2_spc_on_dependent_grid()
        with pytest.raises(ValueError, match=r"SPC set 5 constrains 6 DOF\(s\) already"):
            reduce_to_aset(bulk, _grid_index(bulk), 5)

    def test_error_names_the_grid_dof_and_owning_element(self):
        bulk = _rbe2_spc_on_dependent_grid()
        with pytest.raises(ValueError) as exc:
            reduce_to_aset(bulk, _grid_index(bulk), 5)
        msg = str(exc.value)
        assert "GRID 3 DOF 1" in msg and "GRID 3 DOF 6" in msg
        assert "RBE2 100" in msg and "GM 3" in msg
        assert "Move the SPC to the independent grid" in msg

    def test_rbar_dependent_dof_names_the_rbar(self):
        from sbeam.model.element import Rbar
        bulk = BulkData()
        for gid, x in ((1, 0.0), (2, 1.0)):
            bulk.grids[gid] = Grid(gid=gid, x=x, y=0.0, z=0.0)
        bulk.rbars[7] = Rbar(eid=7, ga=1, gb=2)
        bulk.spc1s[3] = [Spc1(sid=3, c="3", grids=[2])]
        with pytest.raises(ValueError, match=r"RBAR 7 \(GB 2, C3\)"):
            reduce_to_aset(bulk, _grid_index(bulk), 3)

    def test_rbe3_dependent_dof_names_the_rbe3(self):
        bulk = _rbe3_spc_bulk()
        bulk.spc1s[1] = [Spc1(sid=1, c="3", grids=[3])]     # grid 3 is the REFGRID
        with pytest.raises(ValueError, match=r"RBE3 10 \(REFGRID 3, C3\)"):
            reduce_to_aset(bulk, _grid_index(bulk), 1)

    def test_spc_on_the_independent_grid_is_unaffected(self):
        """The legitimate arrangement must keep working untouched."""
        bulk = _rbe3_spc_bulk()
        red = reduce_to_aset(bulk, _grid_index(bulk), 1)
        assert len(red.free_dofs) == 6           # grid 2 free; grid 1 SPC'd; grid 3 dependent

    def test_no_spc_set_is_unaffected(self):
        bulk = _rbe2_spc_on_dependent_grid()
        assert reduce_to_aset(bulk, _grid_index(bulk), None) is not None


class TestDepOwnerMapAgreesWithDepDofs:
    """The owner map and dep_dofs come from one derivation — pin them together.

    ``build_rbe3_transformation``'s ``dep_dofs`` is literally ``sorted()`` of the
    owner map's keys.  If that ever stops being true the error message would name
    the wrong element, or the check would miss a DOF.
    """

    @pytest.mark.parametrize("factory", [
        _rbe3_spc_bulk, _rbe2_spc_on_dependent_grid,
    ])
    def test_keys_match_dep_dofs(self, factory):
        from sbeam.assembly.rbe3 import dep_dof_owners
        bulk = factory()
        gi = _grid_index(bulk)
        _T, dep_dofs, _red = build_rbe3_transformation(bulk, gi)
        assert sorted(dep_dof_owners(bulk, gi)) == dep_dofs

    def test_rbar_keys_match_dep_dofs(self):
        from sbeam.assembly.rbe3 import dep_dof_owners
        from sbeam.model.element import Rbar
        bulk = BulkData()
        for gid, x in ((1, 0.0), (2, 1.0)):
            bulk.grids[gid] = Grid(gid=gid, x=x, y=0.0, z=0.0)
        bulk.rbars[7] = Rbar(eid=7, ga=1, gb=2)
        gi = _grid_index(bulk)
        _T, dep_dofs, _red = build_rbe3_transformation(bulk, gi)
        assert sorted(dep_dof_owners(bulk, gi)) == dep_dofs
        assert dep_dofs, "fixture must actually produce dependent DOFs"

    def test_no_rigid_elements_gives_an_empty_map(self):
        from sbeam.assembly.rbe3 import dep_dof_owners
        bulk = _plain_spc_bulk()
        assert dep_dof_owners(bulk, _grid_index(bulk)) == {}
