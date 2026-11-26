"""Where the shipped sample decks live (#108).

``sample/`` is one folder per model family (``sample/README.md``).  Tests name a deck by its
file name and this module finds the folder, so the layout is written down once.
"""
from __future__ import annotations

from pathlib import Path

SAMPLE_ROOT = Path(__file__).resolve().parent.parent / "sample"

_DECK_SUFFIXES = {".bdf", ".dat", ".csv"}


def _index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in sorted(SAMPLE_ROOT.rglob("*")):
        if path.is_file() and path.suffix in _DECK_SUFFIXES:
            if path.name in index:
                raise RuntimeError(
                    f"sample file name {path.name!r} is used twice: "
                    f"{index[path.name]} and {path}"
                )
            index[path.name] = path
    return index


_INDEX = _index()


def sample_path(name: str) -> Path:
    """The path of the sample file called ``name``, whichever family folder holds it."""
    try:
        return _INDEX[name]
    except KeyError:
        raise FileNotFoundError(f"no sample file named {name!r} under {SAMPLE_ROOT}") from None


def sample_decks(pattern: str = "*.bdf") -> list[Path]:
    """Every sample file matching ``pattern``, across all family folders, sorted by name.

    Raises if nothing matches: a gate that sweeps the samples must not pass on an empty sweep.
    """
    decks = sorted(SAMPLE_ROOT.rglob(pattern), key=lambda p: p.name)
    if not decks:
        raise RuntimeError(f"no sample file matches {pattern!r} under {SAMPLE_ROOT}")
    return decks
