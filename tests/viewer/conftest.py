from pathlib import Path

import pytest

from sbeam.model.bulk_data import BulkData
from sbeam.model.element import Cbar, Plotel
from sbeam.model.grid import Grid
from sbeam.model.material import Mat1
from sbeam.model.property import Pbar
from sbeam.parser.bdf_reader import parse_bdf

_BDF_DIR = Path(__file__).parent.parent / "integration" / "bdf"
_SAMPLE_DIR = Path(__file__).parent.parent.parent / "sample"


@pytest.fixture
def two_node_bulk() -> BulkData:
    """Two grids, one CBAR (PID=1) — no PLOTEL."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=2e11, G=7.7e10, nu=0.3, rho=7850.0)
    bulk.pbars[1] = Pbar(pid=1, mid=1, A=0.01, I1=1e-4, I2=1e-4, J=2e-4)
    bulk.cbars[1] = Cbar(eid=1, pid=1, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    return bulk


@pytest.fixture
def simple_bulk(two_node_bulk: BulkData) -> BulkData:
    """two_node_bulk plus a PLOTEL connecting the same two grids."""
    two_node_bulk.plotels[2] = Plotel(eid=2, g1=1, g2=2)
    return two_node_bulk


@pytest.fixture(scope="module")
def cantilever_sol101_parsed():
    """Parse v1_v2_cantilever.bdf once — returns (CaseControl, BulkData)."""
    return parse_bdf(_BDF_DIR / "v1_v2_cantilever.bdf")


@pytest.fixture(scope="module")
def cantilever_sol103_parsed():
    """Parse v5_cantilever_modal.bdf once — returns (CaseControl, BulkData)."""
    return parse_bdf(_BDF_DIR / "v5_cantilever_modal.bdf")


@pytest.fixture(scope="module")
def dihedral_sol144_parsed():
    """Parse the ±Γ dihedral SOL 144 trim deck — returns (CaseControl, BulkData).

    Out-of-plane (z≠0) lifting surface so the viewer's deflected aero mesh must
    render the canted geometry, not a flat xy-projection (Step 57 acceptance).
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parse_bdf(_SAMPLE_DIR / "val_dihedral_trim.bdf")
