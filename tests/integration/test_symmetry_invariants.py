"""Symmetry invariant gate (#53).

On every mirror-symmetric SOL 144 sample deck, every symmetric subcase must produce:

  SYM1  zero lateral net-load resultant (Fy, Mx, Mz) — nothing for a lateral pin or SUPORT
        to react;
  SYM2  mirror-equal aero box forces, f[partner] = (fx, -fy, fz) — so a centreline fin
        carries no side force;
  SYM3  mirror-equal displacements under (1, -1, 1, -1, 1, -1);
  SYM4  mirror-equal net nodal loads (the bar forces are linear in SYM3/SYM4);
  SYM5  zero lateral derivatives (CY, CMX, CMZ) of every symmetric label, and zero
        longitudinal derivatives (CX, CZ, CMY) of every antisymmetric one;
  SYM6  zero solved value for every antisymmetric FREE label.

Why: #52 (the WT2 reference sideslipped the fin) was live from 2026-06-14 to 2026-10-25.
The flagship carried up to 171 N·m of spurious aero roll and a ±24 % port/starboard tail
load split, and nothing failed — the trim balances only Tz/Ry and the SPC pins on GRID 900
silently reacted the rest.  Review: docs/50_reviews/2026-10-25_wt2_reference_defect_review.md.

The gate discovers symmetry from the deck (grids, CAERO1 surfaces and boxes, elements,
CONM2s, mass case) instead of a hand-kept list, and classifies each trim label by the
parity of its D_jx column, so new decks and new control surfaces are gated with no edits.
A pinned EXPECTED_SYMMETRIC set makes a deck that SHOULD be symmetric fail loudly if
detection ever stops recognising it.

"CBAR end forces of mirrored pairs" (issue body) is covered by SYM3 + SYM4 rather than by
comparing element-frame forces: mirrored elements have mirrored local axes, and the sign
bookkeeping would make the gate itself a defect risk.
"""

import dataclasses
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_djx
from sbeam.assembly.coord_transform import get_transform
from sbeam.assembly.load_vector import build_grid_index
from sbeam.gpwg import compute_gpwg
from sbeam.model.mass_overlay import resolve_mass_case
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.maneuver_modal import ManeuverBasisCache, run_maneuver_modal
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.solver.sol144 import AeroCache, run_sol144_trim

SAMPLE = Path(__file__).parent.parent.parent / "sample"
REL_TOL = 1e-9          # fixed code sits at <= 1e-13 (prototyped 2026-10-25)
PAIR_TOL = 1e-6         # geometric matching, relative to the semispan

# Decks that must be detected as mirror-symmetric.  Any other SOL 144 deck that is
# detected symmetric is gated automatically; one listed here that is NOT detected fails.
EXPECTED_SYMMETRIC = {
    "cessna210_flagship_trim.bdf", "cessna210_flagship_massset.bdf",
    "cessna210_flagship_mloads.bdf", "cessna210_flagship_gust.bdf",
    "cessna210_flagship_body.bdf", "cessna210_flagship_body_strip_drv.bdf",
    "ha144a_fullspan_sbeam.bdf", "ha144a_fullspan_mloads.bdf",
    "ha144a_massset_sweep.bdf", "ha144a_mloads_massset.bdf", "ha144a_body_trim.bdf",
    "val_dihedral_trim.bdf", "val_thrust_trim.bdf", "val_lateral_aileron_rudder.bdf",
}

# Mirror-symmetric decks with no symmetric subcase by design; detection is still gated.
NO_SYMMETRIC_SUBCASE = {
    "val_lateral_aileron_rudder.bdf":
        "every subcase is a lateral trim or carries the one-handed engine torque",
}

MIRROR6 = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])   # (Tx,Ty,Tz,Rx,Ry,Rz) under y -> -y
MIRROR3 = np.array([1.0, -1.0, 1.0])
# URDD labels have no normalwash column; their parity is the rigid-body axis's.
URDD_PARITY = {"URDD1": 1, "URDD3": 1, "URDD5": 1, "URDD2": -1, "URDD4": -1, "URDD6": -1}


# --------------------------------------------------------------------------- #
# Mirror model
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class Mirror:
    grid: dict[int, int]        # gid -> partner gid
    box: np.ndarray             # box k -> partner box index
    sigma: np.ndarray           # +1 if partner normal is the mirror of n_k, else -1
    span: float


def _match(points: np.ndarray, targets: np.ndarray, tol: float) -> Optional[np.ndarray]:
    """Index into ``targets`` of the point nearest each ``points`` row, or None."""
    out = np.empty(len(points), dtype=int)
    for i, p in enumerate(points):
        d = np.linalg.norm(targets - p, axis=1)
        j = int(np.argmin(d))
        if d[j] > tol:
            return None
        out[i] = j
    return out


def grid_pairs(bulk, tol: float) -> Optional[dict[int, int]]:
    gids = sorted(bulk.grids)
    xyz = np.array([[bulk.grids[g].x, bulk.grids[g].y, bulk.grids[g].z] for g in gids])
    idx = _match(xyz * MIRROR3, xyz, tol)
    return None if idx is None else {g: gids[j] for g, j in zip(gids, idx)}


def surface_box_pairs(aero, tol: float) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Surface-first box pairing.

    Boxes of different CAERO1s can share a force point (a PSTRIP body panel coplanar with
    a canard, ha144a_body_trim), so nearest-point pairing over all boxes mis-pairs.  Each
    surface is matched to the surface whose box set is its mirror image (possibly itself),
    then boxes are matched within that pair.
    """
    boxes = aero.boxes
    by_eid: dict[int, list[int]] = {}
    for k, b in enumerate(boxes):
        by_eid.setdefault(b.caero_eid, []).append(k)
    fp = np.array([b.force_point for b in boxes])
    perm = np.full(len(boxes), -1)
    for eid, ks in by_eid.items():
        mirrored = fp[ks] * MIRROR3
        for other, ks2 in by_eid.items():
            if len(ks2) != len(ks):
                continue
            idx = _match(mirrored, fp[ks2], tol)
            if idx is not None and len(set(idx.tolist())) == len(ks):
                perm[ks] = np.asarray(ks2)[idx]
                break
        else:
            return None
    area = np.array([b.area for b in boxes])
    if not np.allclose(area[perm], area, rtol=1e-9, atol=0.0):
        return None
    nrm = np.array([b.normal for b in boxes])
    sigma = np.sign(np.einsum("ij,ij->i", nrm[perm], nrm * MIRROR3))
    return perm, sigma


def _element_set(bulk) -> set[tuple]:
    els = set()
    for e in bulk.cbars.values():
        els.add(("CBAR", e.pid, frozenset((e.ga, e.gb)), e.pa, e.pb))
    for e in bulk.crods.values():
        els.add(("CROD", e.pid, frozenset((e.ga, e.gb))))
    for e in bulk.conrods.values():
        els.add(("CONROD", e.mid, e.A, e.J, frozenset((e.ga, e.gb))))
    return els


def _mirror_element(el: tuple, g: dict[int, int]) -> tuple:
    grids = next(x for x in el if isinstance(x, frozenset))
    return tuple(frozenset(g[i] for i in grids) if isinstance(x, frozenset) else x for x in el)


def _conm2_signature(bulk, c, g: Optional[dict[int, int]] = None):
    off = np.array([c.x1, c.x2, c.x3])
    if c.cid:
        off = get_transform(c.cid, bulk.cord2rs)[1] @ off
    if g is not None:
        off = off * MIRROR3
    return (g[c.gid] if g is not None else c.gid, round(c.m, 9), tuple(np.round(off, 9)))


def mass_case_is_symmetric(bulk, grid: dict[int, int], massset_sid) -> bool:
    conm2s = resolve_mass_case(bulk, massset_sid).conm2s.values()
    own = sorted(_conm2_signature(bulk, c) for c in conm2s)
    mir = sorted(_conm2_signature(bulk, c, grid) for c in conm2s)
    gp = compute_gpwg(bulk, massset_sid)
    return own == mir and abs(gp.cg_y) <= PAIR_TOL * max(1.0, abs(gp.cg_x))


def mirror_of(bulk, aero) -> Optional[Mirror]:
    """The deck's XZ-plane mirror map, or None if the deck is not mirror-symmetric."""
    span = max((abs(g.y) for g in bulk.grids.values()), default=0.0) or 1.0
    grid = grid_pairs(bulk, PAIR_TOL * span)
    if grid is None:
        return None
    boxes = surface_box_pairs(aero, PAIR_TOL * span) if aero.boxes else (np.zeros(0, int),) * 2
    if boxes is None:
        return None
    els = _element_set(bulk)
    if {_mirror_element(e, grid) for e in els} != els:
        return None
    if not mass_case_is_symmetric(bulk, grid, None):
        return None
    return Mirror(grid=grid, box=boxes[0], sigma=boxes[1], span=span)


def label_parity(m: Mirror, w: np.ndarray, label: str) -> int:
    """+1 symmetric, -1 antisymmetric, 0 mixed, from one D_jx column."""
    scale = np.abs(w).max()
    if scale == 0.0:
        return URDD_PARITY.get(label, 1)
    wp = w[m.box]
    if np.abs(wp - m.sigma * w).max() <= REL_TOL * scale:
        return 1
    if np.abs(wp + m.sigma * w).max() <= REL_TOL * scale:
        return -1
    return 0


def mirror_residual(vec: np.ndarray, gi: dict[int, int], m: Mirror) -> float:
    """max |v(partner) - M v(g)| / max |v| over a g-set (n_grid*6) vector."""
    v = np.asarray(vec).reshape(-1, 6)
    scale = np.abs(v).max()
    if scale == 0.0:
        return 0.0
    rows = np.array([gi[m.grid[g]] for g in sorted(gi, key=gi.get)])
    return float(np.abs(v[rows] - v * MIRROR6).max() / scale)


# --------------------------------------------------------------------------- #
# Deck loading and subcase selection
# --------------------------------------------------------------------------- #
def _sol144_decks() -> list[Path]:
    out = []
    for p in sorted(SAMPLE.glob("*.bdf")):
        text = p.read_text()
        if any(ln.split("$")[0].split() == ["SOL", "144"] for ln in text.splitlines()):
            out.append(p)
    return out


class Deck:
    def __init__(self, path: Path):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.cc, self.bulk = parse_bdf(str(path))
            self.gi = build_grid_index(self.bulk)
            self.aero = build_aero_model(self.bulk, grid_index=self.gi)
        self.cache = AeroCache(self.bulk, self.gi, seed=self.aero)
        self.mirror = mirror_of(self.bulk, self.aero)
        self.labels = sorted([a.label for a in self.bulk.aestats.values()]
                             + [s.label for s in self.bulk.aesurfs.values()])
        self.parity: dict[str, int] = {}
        if self.mirror is not None and self.labels:
            djx = build_djx(self.aero.boxes, self.labels, self.bulk)
            self.parity = {lab: label_parity(self.mirror, djx[:, i], lab)
                           for i, lab in enumerate(self.labels)}

    def labels_symmetric(self, values: dict[str, float]) -> bool:
        return all(self.parity.get(k.upper(), 0) == 1 for k, v in values.items() if v != 0.0)


_DECKS: dict[str, Deck] = {}


def _deck(name: str) -> Deck:
    if name not in _DECKS:
        _DECKS[name] = Deck(SAMPLE / name)
    return _DECKS[name]


def _parseable(p: Path) -> bool:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parse_bdf(str(p))
        return True
    except ValueError:
        return False   # HA144A.bdf is an archive listing, not runnable by design


SOL144_DECKS = [p.name for p in _sol144_decks() if _parseable(p)]


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def check_trim(d: Deck, r) -> list[str]:
    """SYM1-SYM6 on one trim result; returns the failures (empty = pass)."""
    m, fails = d.mirror, []
    f = r.box_forces.reshape(-1, 3)
    fz = abs(f[:, 2].sum()) or 1.0
    cl = r.maneuver_closure
    for i, name, scale in ((1, "Fy", fz), (3, "Mx", fz * m.span), (5, "Mz", fz * m.span)):
        if abs(cl[i]) > REL_TOL * scale:
            fails.append(f"SYM1 closure {name} = {cl[i]:.3e}")
    if len(f):
        err = np.abs(f[m.box] - f * MIRROR3).max() / np.abs(f).max()
        if err > REL_TOL:
            fails.append(f"SYM2 box forces mirror residual {err:.3e}")
    for name, vec in (("SYM3 displacements", r.displacements), ("SYM4 net loads", r.net_loads)):
        err = mirror_residual(vec, d.gi, m)
        if err > REL_TOL:
            fails.append(f"{name} mirror residual {err:.3e}")
    for kind in ("rigid_derivs", "restrained_derivs", "unrestrained_derivs"):
        derivs = getattr(r, kind) or {}
        for lab, coefs in derivs.items():
            p = d.parity.get(lab, 0)
            off_axis = ("CY", "CMX", "CMZ") if p == 1 else ("CX", "CZ", "CMY") if p == -1 else ()
            scale = max(abs(v) for v in coefs.values()) or 1.0
            for c in off_axis:
                if abs(coefs.get(c, 0.0)) > REL_TOL * scale:
                    fails.append(f"SYM5 {kind} {lab} {c} = {coefs[c]:.3e}")
    for lab, val in r.trim_vars.items():
        if d.parity.get(lab) == -1 and abs(val) > REL_TOL:
            fails.append(f"SYM6 antisymmetric label {lab} solved to {val:.3e}")
    return fails


def symmetric_trim_subcases(d: Deck):
    for sc in d.cc.subcases:
        if sc.mloads_sid is not None or (sc.trim_sid is None and sc.gustlf_sid is None):
            continue
        trim_sid = sc.trim_sid
        if sc.gustlf_sid is not None:
            trim_sid = d.bulk.gustlfs[sc.gustlf_sid].trimid
        if not d.labels_symmetric(d.bulk.trims[trim_sid].vars):
            continue
        if not mass_case_is_symmetric(d.bulk, d.mirror.grid, sc.massset_sid):
            continue
        yield sc


def symmetric_mloads_subcases(d: Deck):
    for sc in d.cc.subcases:
        if sc.mloads_sid is None:
            continue
        ml = d.bulk.mloads[sc.mloads_sid]
        ic = d.bulk.trims[d.bulk.mldtrims[ml.mldtrim].trim_sid].vars
        cmds = {lab: 1.0 for lab, _tab in d.bulk.mldcomds[ml.mldcomd].commands}
        if d.labels_symmetric(ic) and d.labels_symmetric(cmds) and \
                mass_case_is_symmetric(d.bulk, d.mirror.grid, sc.massset_sid):
            yield sc


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", SOL144_DECKS)
def test_detection_matches_the_expected_set(name):
    """A deck that should be symmetric but is not detected fails loudly."""
    detected = _deck(name).mirror is not None
    if name in EXPECTED_SYMMETRIC:
        assert detected, f"{name} is expected mirror-symmetric but detection says it is not"


def test_every_expected_deck_exists():
    missing = EXPECTED_SYMMETRIC - set(SOL144_DECKS)
    assert not missing, f"EXPECTED_SYMMETRIC names decks that are gone: {missing}"


@pytest.mark.parametrize("name", [n for n in SOL144_DECKS])
def test_symmetric_trims_have_no_lateral_load(name):
    d = _deck(name)
    if d.mirror is None:
        pytest.skip("not mirror-symmetric")
    assert all(p != 0 for p in d.parity.values()), \
        f"labels with mixed parity cannot be classified: {[k for k, p in d.parity.items() if p == 0]}"
    fails, gated = [], 0
    for sc in symmetric_trim_subcases(d):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = run_sol144_trim(d.bulk, sc, d.aero, d.cache)
        # An applied LOAD that is not mirror-symmetric (a one-handed propeller torque)
        # makes the case genuinely asymmetric: not gated.
        if r.applied_loads is not None and mirror_residual(r.applied_loads, d.gi, d.mirror) > REL_TOL:
            continue
        gated += 1
        fails += [f"SUBCASE {sc.subcase_id}: {msg}" for msg in check_trim(d, r)]
    assert not fails, "\n".join(fails)
    has_mloads = any(sc.mloads_sid is not None for sc in d.cc.subcases)
    if name in NO_SYMMETRIC_SUBCASE:
        assert gated == 0, f"{name} now has a symmetric subcase — drop it from NO_SYMMETRIC_SUBCASE"
    else:
        assert gated or has_mloads, f"{name}: no symmetric subcase — the gate would pass vacuously"


@pytest.mark.parametrize("name", [n for n in SOL144_DECKS])
def test_symmetric_maneuvers_have_no_lateral_load(name):
    d = _deck(name)
    if d.mirror is None:
        pytest.skip("not mirror-symmetric")
    subcases = list(symmetric_mloads_subcases(d))
    if not subcases:
        pytest.skip("no symmetric MLOADS subcase")
    basis = None
    fails = []
    for sc in subcases:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if d.bulk.mloads[sc.mloads_sid].selects_modal:
                basis = basis or ManeuverBasisCache(d.bulk, d.aero)
                mr = run_maneuver_modal(d.bulk, sc, d.aero, aero_cache=d.cache, basis_cache=basis)
            else:
                mr = run_maneuver_qs(d.bulk, sc, d.aero, aero_cache=d.cache)
        assert mr.steps, f"SUBCASE {sc.subcase_id}: no transient steps to check"
        for step in mr.steps:
            fz = abs(step.Fz_aero) or 1.0
            cl = step.closure
            for i, comp, scale in ((1, "Fy", fz), (3, "Mx", fz * d.mirror.span),
                                   (5, "Mz", fz * d.mirror.span)):
                if abs(cl[i]) > REL_TOL * scale:
                    fails.append(f"SUBCASE {sc.subcase_id} t={step.t:g}: SYM1 {comp} = {cl[i]:.3e}")
            for comp, vec in (("SYM3 displacements", step.displacements),
                              ("SYM4 net loads", step.net_loads)):
                err = mirror_residual(vec, d.gi, d.mirror)
                if err > REL_TOL:
                    fails.append(f"SUBCASE {sc.subcase_id} t={step.t:g}: {comp} {err:.3e}")
    assert not fails, "\n".join(fails[:20])


# --------------------------------------------------------------------------- #
# The gate bites
# --------------------------------------------------------------------------- #
def test_gate_catches_the_52_defect(monkeypatch):
    """Restore the pre-#52 uniform WT2 reference: the flagship must fail SYM1/2/5."""
    import sbeam.aero.aero_model as am

    monkeypatch.setattr(am, "wt2_reference_cp",
                        lambda boxes, ajj_inv: ajj_inv @ -np.ones(len(boxes)))
    d = Deck(SAMPLE / "cessna210_flagship_trim.bdf")
    assert d.mirror is not None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = run_sol144_trim(d.bulk, d.cc.subcases[0], d.aero, d.cache)
    fails = check_trim(d, r)
    for tag in ("SYM1", "SYM2", "SYM5"):
        assert any(f.startswith(tag) for f in fails), f"{tag} did not fire: {fails}"


def test_detection_catches_a_one_sided_mass():
    d = _deck("cessna210_flagship_trim.bdf")
    bulk = dataclasses.replace(d.bulk, conm2s=dict(d.bulk.conm2s))
    eid, c = next((e, c) for e, c in bulk.conm2s.items() if abs(bulk.grids[c.gid].y) > 0.1)
    bulk.conm2s[eid] = dataclasses.replace(c, m=c.m * 1.01)
    assert not mass_case_is_symmetric(bulk, d.mirror.grid, None)


def test_detection_catches_a_one_sided_panel():
    d = _deck("cessna210_flagship_trim.bdf")
    bulk = dataclasses.replace(d.bulk, caero1s=dict(d.bulk.caero1s))
    c = bulk.caero1s[1000]
    bulk.caero1s[1000] = dataclasses.replace(c, x12=c.x12 * 1.01)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=d.gi)
    assert mirror_of(bulk, aero) is None
