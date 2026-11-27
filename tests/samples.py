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


# ---------------------------------------------------------------------------
# $ COMPAT: tag in each deck header (#95 D4)
# ---------------------------------------------------------------------------

MSC_RUNNABLE, SBEAM_EXTENSION = "MSC-runnable", "sbeam-extension"

#: Case-control commands no vendor defines (``02_card_reference.md``, "sbeam-only cards").
SBEAM_ONLY_COMMANDS = {"MODEXP", "MASSCASE", "GUSTLF", "MANVR", "TRIMWGT"}

_TAG = "$ COMPAT:"


def compat_tags(path: Path) -> list[str]:
    """Every ``$ COMPAT: <tag>`` value in the comment block that opens the file."""
    tags = []
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("$"):
            break
        if line.startswith(_TAG):
            tags.append(line[len(_TAG):].strip())
    return tags


def deck_names(path: Path) -> tuple[set[str], set[str]]:
    """(case-control commands, bulk card names) of a deck and the files it INCLUDEs.

    A file with no ``BEGIN BULK`` is bulk data (the bulk-only and overlay samples).
    """
    from sbeam.parser.bulk_fields import is_continuation, split_line

    commands: set[str] = set()
    cards: set[str] = set()
    text = path.read_text().splitlines()
    in_bulk = not any(ln.split("$", 1)[0].strip().upper() == "BEGIN BULK" for ln in text)
    for line in text:
        body = line.split("$", 1)[0]
        if not body.strip():
            continue
        upper = body.strip().upper()
        if upper == "BEGIN BULK":
            in_bulk = True
        elif upper.startswith("INCLUDE"):
            inner = deck_names(path.parent / body.split(None, 1)[1].strip().strip("'\""))
            commands |= inner[0]
            cards |= inner[1]
        elif not in_bulk:
            commands.add(upper.replace("=", " ").replace("(", " ").split()[0])
        else:
            fields = split_line(body)
            if not is_continuation(fields):
                cards.add(fields[0].strip().upper().rstrip("*"))
    return commands, cards - {"ENDDATA"}
