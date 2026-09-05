"""The architecture boundary, enforced rather than described (issue #33).

`docs/10_standard/00_program_overview.md` states:

    The solver reads a deck and writes results for the cases it is given.
    It never decides which cases exist, and it never reduces across runs.

Relocating code into `sbeam_tools/` enforces nothing on its own — Python will
happily import across any boundary you draw. This gate is what actually holds
the line: the dependency runs one way, and the solver stays free of the GUI's
dependencies so `pip install sbeam` needs no web framework.

**Scope note.** `sbeam/viewer/` is deliberately excluded until it relocates to
`sbeam_tools/viewer/` (issue #34). Tightening this gate to cover all of `sbeam/`
is that issue's acceptance criterion — the moment the boundary stops having an
exception.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
SOLVER = REPO / "sbeam"

# Relocates to sbeam_tools/viewer/ under #34; until then it is the one part of
# sbeam/ allowed to import streamlit/plotly.
_EXCLUDED = {"viewer"}

_FORBIDDEN_IN_SOLVER = {"sbeam_tools", "streamlit", "plotly"}


def _solver_modules() -> list[Path]:
    out = [
        p for p in sorted(SOLVER.rglob("*.py"))
        if not any(part in _EXCLUDED for part in p.relative_to(SOLVER).parts)
        and "__pycache__" not in p.parts
    ]
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
    """No module under sbeam/ (excluding the viewer) may import the forbidden roots."""
    offending = _imported_roots(module) & _FORBIDDEN_IN_SOLVER
    rel = module.relative_to(REPO)
    assert not offending, (
        f"{rel} imports {sorted(offending)} — the solver core must not depend on "
        f"the toolchain or the GUI's dependencies. Move the code to sbeam_tools/, "
        f"or invert the dependency."
    )


def test_the_gate_covers_the_whole_solver_but_the_viewer() -> None:
    """Guard the guard: the exclusion list must not quietly grow."""
    assert _EXCLUDED == {"viewer"}, (
        "the import-boundary exclusion list changed — every entry is a hole in "
        "the architecture rule and needs its own issue"
    )


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
