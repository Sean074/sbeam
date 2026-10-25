"""Aero-correction data preparation — external CFD/wind-tunnel data into cards.

The user's section-coefficient CSV is dimensional (angles in degrees,
coefficients per degree) and the solver's card fields are unit-neutral by
charter §7, so the ingestion, validation, unit conversion and condition
selection live here — the same split that put the gust regulation in
:mod:`sbeam_tools.cases`.

What stays in ``sbeam/aero/``: the correction **solvers**
(``section_correction.build_section_correction_multi``,
``body_correction.build_body_correction``). Those run a min-norm solve against
the global AIC and genuinely need solver data. The line is that ingesting
external dimensional data and deciding model content is tooling; serialising a
computed result is not.
"""

from .section_data import (
    Condition,
    MultiSectionDataBuildResult,
    SectionDataBuildResult,
    available_conditions,
    build_from_section_data,
    build_from_section_data_multi,
    operating_region,
    parse_body_targets,
    split_total_rows,
    surface_var,
    template_dataframe,
    validate_section_data,
)

__all__ = [
    "Condition",
    "MultiSectionDataBuildResult",
    "SectionDataBuildResult",
    "available_conditions",
    "build_from_section_data",
    "build_from_section_data_multi",
    "operating_region",
    "parse_body_targets",
    "split_total_rows",
    "surface_var",
    "template_dataframe",
    "validate_section_data",
]
