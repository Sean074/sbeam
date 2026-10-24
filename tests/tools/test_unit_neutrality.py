"""Charter §7, enforced rather than described (issue #30).

`docs/10_standard/09_conventions.md` §7: *user-defined consistent units throughout —
sbeam never converts*, and tools, not the solver, may know units. The 2026-09-05
architecture audit found four leaks anyway (a `32.174` gravity default under a
"model units" label, a `0.002377` density in an error message, `Pa` in a docstring,
stale §7 citations). This gate greps every module under `sbeam/` — the viewer
included, since a GUI default is the leak most likely to produce a wrong deck — for
unit-system constants and unit words.

Patterns are word-bounded so the known false positives stay quiet: `lb` is the
TRIMVAR lower bound, `kg` the GUSTLF gust factor `K_g`, "lift/sideforce" contains
`ft/s` without the boundary.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
SOLVER = REPO / "sbeam"

#: Unit-system constants and unit words that must not appear in solver code,
#: messages, defaults or docstrings.  Each entry: (name, compiled regex).
_FORBIDDEN = [
    ("g in ft/s²", re.compile(r"\b32\.17\d*\b")),
    ("g in m/s²", re.compile(r"\b9\.8(0665|1)\b")),
    ("rho0 in slug/ft³", re.compile(r"\b0\.002377\b")),
    ("rho0 in kg/m³", re.compile(r"\b1\.225\b")),
    ("slug", re.compile(r"\bslugs?\b", re.IGNORECASE)),
    ("lbf", re.compile(r"\blbf\b", re.IGNORECASE)),
    ("kg/m³", re.compile(r"\bkg/m")),
    ("ft/s", re.compile(r"\bft/s")),
    ("Pa", re.compile(r"\bPa\b")),
    ("psi", re.compile(r"\bpsi\b")),
]

#: Prose that *explains* the boundary is allowed to name the units it keeps out.
#: (module relative to sbeam/, pattern name).  Guarded by the test below so an
#: entry cannot outlive the text it excuses.
_ALLOWED = {
    ("model/gust.py", "ft/s"),   # docstring: why U_de (50 ft/s, feet) lives in sbeam_tools
}


def _solver_modules() -> list[Path]:
    out = [p for p in sorted(SOLVER.rglob("*.py")) if "__pycache__" not in p.parts]
    assert out, "no solver modules found — the gate would pass vacuously"
    return out


def _hits(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {name for name, rx in _FORBIDDEN if rx.search(text)}


@pytest.mark.parametrize("module", _solver_modules(), ids=lambda p: str(p.relative_to(SOLVER)))
def test_solver_module_names_no_unit_system(module: Path) -> None:
    rel = str(module.relative_to(SOLVER))
    leaks = {n for n in _hits(module) if (rel, n) not in _ALLOWED}
    assert not leaks, (
        f"{rel} mentions {sorted(leaks)}: the solver is unit-neutral (charter §7). Say "
        "'in the deck's consistent units', or move the dimensional code to sbeam_tools/.")


def test_allow_list_entries_are_still_needed() -> None:
    """Each allowed (module, pattern) must still match, or the entry is stale."""
    for rel, name in _ALLOWED:
        assert name in _hits(SOLVER / rel), f"stale allow-list entry: {(rel, name)}"


def test_the_gate_covers_the_viewer() -> None:
    """Unlike the import gate (#33), the viewer is in scope: a GUI default is the
    most likely place for a unit constant to produce a wrong deck."""
    assert any("viewer" in p.parts for p in _solver_modules())


def test_tools_still_own_the_constants() -> None:
    """The constants exist — on the tools side, where charter §7 puts them."""
    units = (REPO / "sbeam_tools/common/units.py").read_text()
    assert "9.80665" in units and "32.174" in units
