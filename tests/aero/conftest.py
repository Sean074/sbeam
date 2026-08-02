"""Shared fixtures for the aero test package.

The Cessna 210 flagship body decks (Step 66) are used by four modules.  At 372
boxes the pure-Python Biot-Savart AIC build is ~11 s, so the parses and builds are
**session**-scoped and shared rather than repeated per module.

Fixtures hand back the live `BulkData`/`AeroModel`.  Tests must not mutate them —
compose with `dataclasses.replace` (as the existing body/strip tests do) instead.
"""

import warnings
from pathlib import Path

import pytest

from sbeam.aero.aero_model import AeroModel, build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.bulk_data import BulkData
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import CaseControl
from sbeam.types import StrPath

# (case control, bulk, aero model, g-set grid index, warnings raised during the build)
Deck = tuple[CaseControl, BulkData, AeroModel, dict[int, int], list[str]]

SAMPLE = Path(__file__).parent.parent.parent / "sample"
FLAGSHIP_CRUCIFORM = SAMPLE / "cessna210_flagship_body.bdf"
FLAGSHIP_STRIP = SAMPLE / "cessna210_flagship_body_strip_drv.bdf"
FLAGSHIP_BARE = SAMPLE / "cessna210_flagship_trim.bdf"
FLAGSHIP_CSV = SAMPLE / "cessna210_flagship_section_data.csv"

BODY_EIDS = (6000, 7000)


def _load(path: StrPath, *, strip_body_cards: bool = False) -> Deck:
    """Parse a flagship driver and build its AeroModel.

    With ``strip_body_cards`` the committed body W2GJ/AECORR/STRIPK are removed
    first, leaving the flying-surface correction in place and the body panels
    UNCORRECTED — the state the body-correction builders expect as input.  Solving
    against the already-corrected deck would be circular: the builder measures its
    baseline from the model it is handed, so it would derive a null correction.
    """
    cc, bulk = parse_bdf(str(path))
    if strip_body_cards:
        for store in (bulk.w2gjs, bulk.aecorrs, bulk.stripks):
            for sid in [s for s, c in store.items() if c.caero_eid in BODY_EIDS]:
                del store[sid]
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        aero = build_aero_model(bulk, grid_index=grid_index)
    return cc, bulk, aero, grid_index, [str(w.message) for w in caught]


@pytest.fixture(scope="session")
def flagship_cruciform() -> Deck:
    """Flagship + cruciform (PAERO1) body panels, correction applied."""
    return _load(FLAGSHIP_CRUCIFORM)


@pytest.fixture(scope="session")
def flagship_strip() -> Deck:
    """Flagship + decoupled strip (PSTRIP) body panels, correction applied."""
    return _load(FLAGSHIP_STRIP)


@pytest.fixture(scope="session")
def flagship_bare() -> Deck:
    """The Step 65 flagship with no body panels at all."""
    return _load(FLAGSHIP_BARE)


@pytest.fixture(scope="session")
def flagship_cruciform_uncorrected() -> Deck:
    return _load(FLAGSHIP_CRUCIFORM, strip_body_cards=True)


@pytest.fixture(scope="session")
def flagship_strip_uncorrected() -> Deck:
    return _load(FLAGSHIP_STRIP, strip_body_cards=True)
