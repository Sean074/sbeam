"""G4 (#100): pyNastran reads sbeam's OP4 back to the same matrices.

pyNastran is an independent OUTPUT4 reader (test-only dependency, requirements-compat.txt).
MHH and KHH rebuilt from the PHIA read back, with sbeam's assembled a-set matrices, must
match the MHH and KHH in the file.
"""
import warnings

import numpy as np
import pytest

pytest.importorskip("pyNastran")
from pyNastran.op4.op4 import read_op4  # noqa: E402

from sbeam.parser.bdf_reader import parse_bdf  # noqa: E402
from sbeam.results.modal_export import build_modal_model, export_modal_model  # noqa: E402
from sbeam.solver.sol103 import run_sol103  # noqa: E402
from tests.samples import sample_path



def _case(deck, set_grids=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(sample_path(deck))
        sc = cc.subcases[0]
        if set_grids is not None:
            sc.modexp_set, sc.sets = 1, {1: set_grids}
        r = run_sol103(bulk, sc)
        return cc, bulk, sc, r, build_modal_model(cc, bulk, sc, r)


@pytest.mark.parametrize("deck, grids", [("goland_wing_modes.bdf", None),
                                         ("val_free_free_modes.bdf", [1, 6, 11])])
def test_pynastran_reads_every_matrix(deck, grids, tmp_path):
    cc, bulk, sc, r, mm = _case(deck, grids)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        export_modal_model(str(tmp_path / "m"), cc, bulk, sc, r, formats=("OP4",))
    with warnings.catch_warnings():
        warnings.simplefilter("error")          # G4: "reads with no warnings"
        got = read_op4(str(tmp_path / "m.op4"), debug=False)
    assert sorted(got) == ["KHH", "MHH", "PHIA", "PHIX"]
    for name, ref in (("MHH", mm.mhh), ("KHH", mm.khh), ("PHIA", mm.phia), ("PHIX", mm.phix)):
        mat = got[name][1] if isinstance(got[name], tuple) else got[name].data
        mat = mat.toarray() if hasattr(mat, "toarray") else np.asarray(mat)
        assert mat.shape == ref.shape, name
        assert np.allclose(mat, ref, rtol=1e-12, atol=1e-12 * max(1.0, np.abs(ref).max())), name

    phia = got["PHIA"][1] if isinstance(got["PHIA"], tuple) else got["PHIA"].data
    m_free, k_free = r.M_free, r.K_free
    assert np.allclose(phia.T @ (m_free @ phia), mm.mhh, atol=1e-8)
    scale = np.abs(mm.khh).max()
    assert np.allclose(phia.T @ (k_free @ phia), mm.khh, atol=1e-8 * scale)
