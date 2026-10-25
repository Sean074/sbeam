"""Case construction — deciding which cases exist, which the solver never does.

Families live one per module (:mod:`~sbeam_tools.cases.gust` today; the 23.337
maneuver corner points join it with issue #4) and share the deck reader, unit
systems and atmosphere in :mod:`sbeam_tools.common`.
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
