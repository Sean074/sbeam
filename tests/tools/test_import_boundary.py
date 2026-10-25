"""The architecture boundary, enforced rather than described (issue #33).

`docs/10_standard/00_program_overview.md` states:

    The solver reads a deck and writes results for the cases it is given.
    It never decides which cases exist, and it never reduces across runs.

Relocating code into `sbeam_tools/` enforces nothing on its own — Python will
happily import across any boundary you draw. This gate is what actually holds
the line: the dependency runs one way, and the solver stays free of the GUI's
dependencies so `pip install sbeam` needs no web framework.

**Scope.** Every module under `sbeam/`, with no exceptions. The viewer was
excluded until it relocated to `sbeam_tools/viewer/` (issue #34); since then the
boundary has no hole.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
SOLVER = REPO / "sbeam"

# `pandas` joined this list with issue #32: once the section-data CSV ingestion
# moved to sbeam_tools/corrections/, nothing in the solver read a DataFrame. The
# solver works in numpy arrays and BDF cards; a DataFrame arriving in `sbeam/` now
# means external tabular data has been dragged across the boundary again.
_FORBIDDEN_IN_SOLVER = {"sbeam_tools", "streamlit", "plotly", "pandas"}


def _solver_modules() -> list[Path]:
    out = [p for p in sorted(SOLVER.rglob("*.py")) if "__pycache__" not in p.parts]
    assert out, "found no solver modules — the gate would pass vacuously"
    return out


def _imported_roots(path: Path) -> set[str]:
    """Top-level package names imported by ``path``, absolute imports only."""
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import — never crosses a top-level package.
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module", _solver_modules(), ids=lambda p: str(p.name))
def test_solver_does_not_import_tools_or_gui(module: Path) -> None:
    """No module under sbeam/ may import the forbidden roots."""
    offending = _imported_roots(module) & _FORBIDDEN_IN_SOLVER
    rel = module.relative_to(REPO)
    assert not offending, (
        f"{rel} imports {sorted(offending)} — the solver core must not depend on "
        f"the toolchain or the GUI's dependencies. Move the code to sbeam_tools/, "
        f"or invert the dependency."
    )


def test_the_viewer_lives_in_the_toolchain() -> None:
    """Guard the guard (#34): the GUI is not in the solver package, so the gate
    above covers all of sbeam/ without an exclusion list to grow back."""
    assert not (SOLVER / "viewer").exists(), "sbeam/viewer/ is back inside the solver"
    assert (REPO / "sbeam_tools" / "viewer" / "app.py").is_file()


def test_tools_may_import_the_solver() -> None:
    """The dependency is one-way, not absent — assert the allowed direction works."""
    tools = REPO / "sbeam_tools"
    importers = [
        p for p in tools.rglob("*.py")
        if "sbeam" in _imported_roots(p) and "__pycache__" not in p.parts
    ]
    assert importers, (
        "no sbeam_tools module imports sbeam — either the tools were gutted or "
        "this gate is looking in the wrong place"
    )
