"""Per-station section-cut and per-monitor envelopes over a transient maneuver.

Section cuts: Step 68.  Monitor points: #2, the same reduction over the six
cp-frame components of each ``MonitorLoad``.

Increment 1 answers "what are the running loads at the worst instant?".  This
module answers the question that makes the first one defensible: "and is any
other instant worse, at any other station?"

The envelope is a reduction over the samples of ONE subcase: for every cut,
every station and every labelled component, the maximum and minimum across time
together with the sample that drove each.  Two properties are deliberate:

* **The driving sample is per station, per component** — and is generally NOT
  the run's critical sample.  ``ManeuverResult.crit_index`` is selected by one
  global severity metric (``peak_grid_force``, DEF-M5); outboard bending can
  peak at a different instant than the peak grid force, which is precisely why a
  stress group needs the envelope rather than the critical sample alone.  Both
  are reported, and the f06/CSV name them differently so they cannot be
  conflated.
* **The reduction is within a subcase, not across subcases or mass cases.**
  Enveloping a maneuver × mass-case sweep is a groupby over the CSV (whose
  ``case``/``massset`` columns exist for exactly that) and belongs with the
  sweep post-processing, not here.
"""

from typing import Optional

import numpy as np

from sbeam.results.results import (
    ManeuverResult, MonitorEnvelope, MonitorEnvelopeEntry,
    SectionCutEnvelope, SectionCutEnvelopeEntry,
)
from sbeam.results.section_cuts import labelled


def build_section_envelope(
    result: "ManeuverResult",
) -> Optional[dict[str, SectionCutEnvelope]]:
    """Reduce a run's per-sample section cuts to ``{name: SectionCutEnvelope}``.

    Returns ``None`` when the run carries no section cuts, so the field stays
    absent rather than empty for a deck with no MONSECT cards.

    Ties (the same extreme reached at several samples) resolve to the earliest
    sample: ``np.argmax``/``argmin`` semantics, stated here because "which
    sample drove this" must be reproducible run to run.
    """
    samples = [(i, s, s.section_loads) for i, s in enumerate(result.steps)
               if s.section_loads]
    if not samples:
        return None

    names = sorted(samples[0][2].keys())
    out: dict[str, SectionCutEnvelope] = {}

    for name in names:
        # A cut present at some samples but not others would make the stacked
        # array ragged; take the samples that carry this cut, in time order.
        rows = [(i, s, sl) for i, s, sl in samples if name in sl]
        first = rows[0][2][name]
        n_st = len(first.stations)

        # (n_sample, n_station, 6) of LABELLED components — the envelope is
        # reported in the same N/V/Mt/M order the tables use, not raw cid order.
        values = np.array([
            [labelled(st.totals, first.comp_map)
             for st in sl[name].stations]
            for _i, _s, sl in rows
        ])
        idx = np.array([i for i, _s, _sl in rows])
        times = np.array([s.t for _i, s, _sl in rows])

        i_max = values.argmax(axis=0)          # (n_station, 6)
        i_min = values.argmin(axis=0)

        entries = []
        for j in range(n_st):
            station = first.stations[j].station
            for c in range(6):
                a, b = int(i_max[j, c]), int(i_min[j, c])
                entries.append(SectionCutEnvelopeEntry(
                    station=float(station), comp=c,
                    max_value=float(values[a, j, c]),
                    max_sample=int(idx[a]) + 1,        # 1-based, as everywhere
                    max_time=float(times[a]),
                    min_value=float(values[b, j, c]),
                    min_sample=int(idx[b]) + 1,
                    min_time=float(times[b]),
                ))

        out[name] = SectionCutEnvelope(
            name=first.name, label=first.label, comp=first.comp,
            listtype=first.listtype, cid=first.cid, axis=first.axis,
            side=first.side, comp_map=first.comp_map,
            half_model=first.half_model, n_samples=len(rows), entries=entries,
        )
    return out


def build_monitor_envelope(
    result: "ManeuverResult",
) -> Optional[dict[str, MonitorEnvelope]]:
    """Reduce a run's per-sample monitor loads to ``{name: MonitorEnvelope}`` (#2).

    Same contract as :func:`build_section_envelope`: within one subcase, per
    monitor and per cp-frame component, the max and min over the output samples
    with the sample that drove each; ties resolve to the earliest sample.
    Returns ``None`` when the run carries no monitor points.
    """
    samples = [(i, s, s.monitor_loads) for i, s in enumerate(result.steps)
               if s.monitor_loads]
    if not samples:
        return None

    out: dict[str, MonitorEnvelope] = {}
    for name in sorted(samples[0][2].keys()):
        rows = [(i, s, ml) for i, s, ml in samples if name in ml]
        first = rows[0][2][name]
        values = np.array([ml[name].totals for _i, _s, ml in rows])   # (n_sample, 6)
        idx = np.array([i for i, _s, _ml in rows])
        times = np.array([s.t for _i, s, _ml in rows])
        i_max = values.argmax(axis=0)
        i_min = values.argmin(axis=0)
        entries = []
        for c in range(6):
            a, b = int(i_max[c]), int(i_min[c])
            entries.append(MonitorEnvelopeEntry(
                comp=c,
                max_value=float(values[a, c]), max_sample=int(idx[a]) + 1,
                max_time=float(times[a]),
                min_value=float(values[b, c]), min_sample=int(idx[b]) + 1,
                min_time=float(times[b]),
            ))
        out[name] = MonitorEnvelope(
            name=first.name, label=first.label, mtype=first.mtype,
            axes=first.axes, cid=first.cid, whole_airplane=first.whole_airplane,
            n_samples=len(rows), entries=entries,
        )
    return out
