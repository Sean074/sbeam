"""Case construction — deciding which cases exist, which the solver never does.

Families live one per module and share the deck reader, unit systems and atmosphere
in :mod:`sbeam_tools.common`: :mod:`~sbeam_tools.cases.gust` (the 23.341 gust cases)
and :mod:`~sbeam_tools.cases.maneuver` (trim recipes, command histories and the
two-pass command builder, #114; the 23.337 corner points join it with issue #4).
"""

from .gust import (
    GustCase,
    alleviation_factor,
    derived_gust_velocity,
    emit_deck,
    format_summary,
    generate_cases,
    gust_increment,
    mass_ratio,
    write_gustlf_card,
)

__all__ = [
    "GustCase",
    "alleviation_factor",
    "derived_gust_velocity",
    "emit_deck",
    "format_summary",
    "generate_cases",
    "gust_increment",
    "mass_ratio",
    "write_gustlf_card",
]
