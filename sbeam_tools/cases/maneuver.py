"""Maneuver cases: trim recipes, command histories, and the two-pass command builder.

This is case construction: it decides what a maneuver case is and writes the cards of
one.  It lived in the viewer until #114, where it was a second statement of what a case
is beside the families here.  The viewer now calls this module and keeps only the
widgets; a script can call it with no viewer.

Three parts:

* **Trim recipes** (``MANEUVER_PRESETS``): the prescribed ``TRIM`` variables of a
  symmetric pull-up, a steady roll and a steady sideslip, from one scalar each.
* **Command histories** (``gen_step``, ``gen_ramp``, ``gen_cosine_ramp``,
  ``gen_doublet``): the ``(t, y)`` points of a ``TABLED1``.
* **The two-pass command builder** (``IncrementSpec``, ``resolve_increment_tables``):
  a pilot command written as an increment from trim, made absolute once the trim has
  been solved.  It reads solved results to write new cards, a loop across runs that
  the solver package must not own (architecture boundary, ``00_program_overview.md``).

Nothing here knows a unit system: gravity is an argument, angles are radians, rates
are the reduced rates the TRIM card carries (charter §5).  Nothing here imports
``streamlit`` or the viewer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from sbeam.model.bulk_data import BulkData
from sbeam.model.maneuver import Mldcomd, Mloads, Tabled1
from sbeam.model.maneuver_presets import load_factor_to_urdd3
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.results.results import ManeuverResult, Sol144TrimResult


def _next_id(store: Mapping[int, Any]) -> int:
    """The next free card ID in a family: ``max + 1``, or 1 when the family is empty."""
    ids = [key for key in store if key > 0]
    return max(ids) + 1 if ids else 1


# ---------------------------------------------------------------------------
# Trim recipes: the prescribed TRIM variables of a balanced maneuver, from one
# scalar.  Gravity folds into the load factor (``load_factor_to_urdd3``, the
# sign convention's single source, charter §5/§8).
# ---------------------------------------------------------------------------

@dataclass
class ManeuverPreset:
    """A named trim recipe: prescribed variables from one scalar parameter."""
    name: str
    description: str
    param_label: str           # UI label for the scalar input
    param_default: float
    required_labels: list[str] # AESTAT labels the recipe prescribes or frees
    surface_role: str          # which AESURF stays free ('elevator', ...)
    uses_g: bool = False       # parameter needs the gravity constant
    uses_speed: bool = False   # recipe needs the true airspeed and the reference chord

    def prescribed_vars(self, param: float, g: float = 0.0,
                        v_true: Optional[float] = None,
                        c_ref: Optional[float] = None) -> dict[str, float]:
        """The TRIM variables the recipe prescribes for ``param``.

        The pull-up also needs ``g``, the true airspeed ``v_true`` and the reference
        chord ``c_ref`` (AEROS), all in the deck's units; there is no default for the
        speed, and the recipe refuses to guess one.
        """
        if self.name == "Symmetric pull-up / push-over":
            return {"URDD3": load_factor_to_urdd3(param, g),
                    "PITCH": steady_pull_up_pitch_rate(param, g, v_true, c_ref),
                    "URDD5": 0.0}
        if self.name == "Steady roll":
            return {"ROLL": param, "URDD4": 0.0}
        if self.name == "Steady sideslip":
            return {"SIDES": param, "YAW": 0.0}
        raise ValueError(f"unknown preset {self.name!r}")


def steady_pull_up_pitch_rate(n_z: float, g: float, v_true: Optional[float],
                              c_ref: Optional[float]) -> float:
    """``PITCH`` of a steady pull-up or push-over: ``(n_z - 1) g c_ref / (2 V^2)``.

    An airplane holding ``n_z`` on a curved path is rotating: the lift beyond the
    weight, ``(n_z - 1) W``, is the centripetal force, so the pitch rate is
    ``q = (n_z - 1) g / V``.  The TRIM variable ``PITCH`` is the reduced rate
    ``q c / 2V`` (charter §5).  It is zero only at ``n_z = 1`` and negative in a
    push-over.

    ZAERO states the same value for its ``QRATE`` trim variable: "QRATE can be
    pre-determined by QRATE = ((Nz - 1) g / V) (C / 2V)" (ZAERO 9.2 User's Manual,
    TRIMVAR, PDF p.512).  sbeam's standard: ``05c_sol144_maneuver.md``.  Until #127
    the recipe prescribed 0 at every load factor: a pull with no rotation, which on
    the flagship at 2.5 g trims with 1.35 degrees too little elevator.

    All arguments are in the deck's units.  ``v_true`` is the **true** airspeed,
    ``sqrt(2 q / rho)`` for the TRIM's dynamic pressure.
    """
    if v_true is None or c_ref is None or v_true <= 0.0 or c_ref <= 0.0:
        raise ValueError(
            "a steady pull-up needs the true airspeed and the reference chord, both "
            f"positive, for its pitch rate (got V = {v_true}, c_ref = {c_ref})")
    return (n_z - 1.0) * g * c_ref / (2.0 * v_true * v_true)


MANEUVER_PRESETS: list[ManeuverPreset] = [
    ManeuverPreset(
        name="Symmetric pull-up / push-over",
        description="Steady pull-up or push-over. Prescribe URDD3 = -n_z·g, "
                    "PITCH = (n_z - 1)·g·c_ref/(2V²) (the pitch rate of the curved "
                    "path, as qc/2V) and URDD5 = 0; ANGLEA and the elevator trim free.",
        param_label="Load factor n_z",
        # 1.0 is level flight.  The limit load factor of a case is the caller's
        # input (it comes from the airplane's category and weight); no regulatory
        # number is a default here.
        param_default=1.0,
        required_labels=["ANGLEA", "PITCH", "URDD3", "URDD5"],
        surface_role="elevator",
        uses_g=True,
        uses_speed=True,
    ),
    ManeuverPreset(
        name="Steady roll",
        description="Prescribe ROLL = pb/2V (reduced rate; positive = starboard wing down) "
                    "and URDD4 = 0; the aileron trims free. Needs SUPORT 4 (or 46 with the "
                    "rudder free and SIDES = YAW = URDD6 = 0 prescribed) — see "
                    "sample/validation/val_lateral_aileron_rudder.bdf.",
        param_label="Reduced roll rate pb/2V (–)",
        param_default=0.05,
        required_labels=["ROLL", "URDD4"],
        surface_role="aileron",
    ),
    ManeuverPreset(
        name="Steady sideslip",
        description="Prescribe SIDES = beta (positive = wind from PORT, i.e. −β textbook) and "
                    "YAW = 0; the rudder trims free. Needs SUPORT 6 (or 46 with the aileron "
                    "free and ROLL = URDD4 = URDD6 = 0 prescribed).",
        param_label="Sideslip beta (rad)",
        param_default=0.05,
        required_labels=["SIDES", "YAW"],
        surface_role="rudder",
    ),
]


def missing_preset_labels(bulk: BulkData, preset: ManeuverPreset) -> list[str]:
    """AESTAT labels the preset needs that the model does not define yet."""
    have = {a.label for a in bulk.aestats.values()}
    return [l for l in preset.required_labels if l not in have]


# ---------------------------------------------------------------------------
# Command-history shapes.  Each returns the (x, y) points of a TABLED1.
# Prefer the cosine ramp: the slope jumps of a clamped-linear table ring the
# highest retained mode under the modal maneuver solver.
# ---------------------------------------------------------------------------

def _prehold(t1: float, y0: float) -> list[tuple[float, float]]:
    return [(0.0, y0)] if t1 > 0.0 else []


def _posthold(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Append a point that holds the last value.

    TABLED1 extrapolates linearly from its last two points (MSC QRG 2024.1 PDF p.2897
    remark 6), so a shape that ends on a slope would keep going.  Two end points of
    equal y make the extrapolation flat; the hold point sits one shape-length later.
    """
    t_end, y_end = pts[-1]
    span = max(t_end - pts[0][0], 1.0e-3)
    return pts + [(t_end + span, y_end)]


def gen_step(t1: float, y0: float, y1: float,
             rise: float = 1.0e-3) -> list[tuple[float, float]]:
    """Near-instant step from y0 to y1 at t1 (TABLED1 is piecewise linear), then held."""
    return _posthold(_prehold(t1, y0) + [(t1, y0), (t1 + rise, y1)])


def gen_ramp(t1: float, t2: float, y0: float, y1: float) -> list[tuple[float, float]]:
    """Linear ramp y0 -> y1 over [t1, t2], then held."""
    if t2 <= t1:
        raise ValueError("ramp needs t2 > t1")
    return _posthold(_prehold(t1, y0) + [(t1, y0), (t2, y1)])


def gen_cosine_ramp(t1: float, t2: float, y0: float, y1: float,
                    n: int = 21) -> list[tuple[float, float]]:
    """Half-cosine blend y0 -> y1 over [t1, t2], densely sampled (default)."""
    if t2 <= t1:
        raise ValueError("cosine ramp needs t2 > t1")
    pts = _prehold(t1, y0)
    for i in range(n):
        s = i / (n - 1)
        t = t1 + s * (t2 - t1)
        y = y0 + (y1 - y0) * 0.5 * (1.0 - math.cos(math.pi * s))
        pts.append((t, y))
    return _posthold(pts)


def gen_doublet(t1: float, t2: float, amp: float, y0: float,
                n: int = 41) -> list[tuple[float, float]]:
    """Smooth one-cycle sine doublet of amplitude ``amp`` over [t1, t2]."""
    if t2 <= t1:
        raise ValueError("doublet needs t2 > t1")
    pts = _prehold(t1, y0)
    for i in range(n):
        s = i / (n - 1)
        t = t1 + s * (t2 - t1)
        pts.append((t, y0 + amp * math.sin(2.0 * math.pi * s)))
    pts[-1] = (pts[-1][0], y0)          # sin(2π) is not exactly zero in floating point
    return _posthold(pts)


# ---------------------------------------------------------------------------
# Two-pass MANCMD automation (S4): tables authored as increments relative to
# trim, resolved to absolute TABLED1 cards once a solve supplies the trim
# control values (per mass case — command tables are absolute AND mass-case
# specific, so each MANVR/mass-case pair gets its own table).
# ---------------------------------------------------------------------------

@dataclass
class IncrementSpec:
    """A command history authored as a delta from the (unsolved) trim value."""
    mloads_sid: int
    label: str                              # AESURF label to command
    points: list[tuple[float, float]] = field(default_factory=list)  # (t, dy)


def _trim_value_for_subcase(
    bulk: BulkData,
    sc: SubcaseControl,
    mloads: Mloads,
    label: str,
    trim_results: Optional[dict[int, Sol144TrimResult]],
    maneuver_results: Optional[dict[int, ManeuverResult]],
) -> Optional[float]:
    """The solved trim value of ``label`` for one subcase, or None."""
    mr = (maneuver_results or {}).get(sc.subcase_id)
    if mr is not None and mr.steps:
        val = mr.steps[0].trim_vars.get(label)
        if val is not None:
            return float(val)
    mldtrim = bulk.mldtrims.get(mloads.mldtrim)
    ic_trim_sid = mldtrim.trim_sid if mldtrim is not None else None
    candidates = [r for r in (trim_results or {}).values()
                  if r.trim_sid == ic_trim_sid]
    # Prefer the matching mass case; fall back to any solve of the IC trim.
    for r in candidates:
        if r.massset_sid == sc.massset_sid and label in r.trim_vars:
            return float(r.trim_vars[label])
    for r in candidates:
        if label in r.trim_vars:
            return float(r.trim_vars[label])
    return None


@dataclass
class Resolution:
    """What the second pass adds to a deck.

    ``cards`` are ``(family, card)`` pairs: the absolute TABLED1s, then each MANCMD,
    then each MANVR.  ``selectors`` maps a subcase to the MANVR it must now select;
    it is empty unless a loaded card had to be replaced by a new one.
    """
    cards: list[tuple[str, Any]] = field(default_factory=list)
    report: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    resolved: list[IncrementSpec] = field(default_factory=list)
    selectors: dict[int, int] = field(default_factory=dict)


def resolve_increment_tables(
    bulk: BulkData,
    cc: CaseControl,
    specs: list[IncrementSpec],
    trim_results: Optional[dict[int, Sol144TrimResult]] = None,
    maneuver_results: Optional[dict[int, ManeuverResult]] = None,
    loaded: Optional[dict[str, set[int]]] = None,
) -> Resolution:
    """Second pass: turn increment commands into absolute TABLED1 / MANCMD / MANVR cards.

    A command table is absolute, and its value at t0 must equal the trim value of the
    control, which is known only after the trim is solved; it also differs by mass
    case.  So a command is written first as an increment from trim (``IncrementSpec``),
    the deck is solved, and this function adds the solved trim value per mass case.

    ``loaded`` names the cards that belong to the deck as loaded
    (``{"mldcomd": {...}, "mloads": {...}}``) and so are not rewritten: a second card
    with the same ID would not parse.  Where the MANCMD or the MANVR of a command is a
    loaded card, a **new** MANCMD and a new MANVR are written, and ``selectors`` says
    which subcases must select the new MANVR.  A card that is not in ``loaded`` is
    rewritten under its own ID, as when the cards were authored in the same session.

    A spec that cannot be resolved adds a line to ``errors`` and no card.
    """
    loaded = loaded or {}
    cards: list[tuple[str, Any]] = []
    report: list[str] = []
    errors: list[str] = []
    resolved: list[IncrementSpec] = []

    selectors: dict[int, int] = {}
    next_tid = _next_id(bulk.tabled1s)
    next_comd = _next_id(bulk.mldcomds)
    next_mloads = _next_id(bulk.mloads)
    # Pending MANCMD command maps, keyed by mloads sid (specs may stack
    # several labels onto one driver).
    pending: dict[int, dict[str, int]] = {}
    comd_sids: dict[int, int] = {}

    for spec in specs:
        mloads = bulk.mloads.get(spec.mloads_sid)
        if mloads is None:
            errors.append(f"MANVR {spec.mloads_sid} not found.")
            continue
        subcases = [sc for sc in cc.subcases if sc.mloads_sid == spec.mloads_sid]
        if not subcases:
            errors.append(f"No subcase selects MANVR {spec.mloads_sid}.")
            continue
        mass_sids = {sc.massset_sid for sc in subcases}
        if len(mass_sids) > 1:
            errors.append(
                f"MANVR {spec.mloads_sid} is shared by subcases with different "
                "MASSCASEs — command tables are mass-case specific, so give "
                "each mass case its own MANVR (the sample-deck convention)."
            )
            continue
        sc = subcases[0]
        if len(spec.points) < 2:
            errors.append(
                f"MANVR {spec.mloads_sid} {spec.label}: an increment history "
                "needs at least two points.")
            continue
        trim_val = _trim_value_for_subcase(
            bulk, sc, mloads, spec.label, trim_results, maneuver_results)
        if trim_val is None:
            errors.append(
                f"MANVR {spec.mloads_sid} {spec.label}: no solved trim value — "
                "run the trim/maneuver solve first (or author the table as "
                "absolute values).")
            continue

        xs = [t for t, _ in spec.points]
        ys = [trim_val + dy for _, dy in spec.points]
        if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
            errors.append(
                f"MANVR {spec.mloads_sid} {spec.label}: increment abscissae "
                "must be strictly increasing.")
            continue
        table = Tabled1(tid=next_tid, xs=xs, ys=ys)
        next_tid += 1
        cards.append(("tabled1", table))

        if spec.mloads_sid not in pending:
            existing = bulk.mldcomds.get(mloads.mldcomd)
            pending[spec.mloads_sid] = dict(existing.commands) if existing else {}
            if mloads.mldcomd and mloads.mldcomd not in loaded.get("mldcomd", set()):
                comd_sids[spec.mloads_sid] = mloads.mldcomd      # rewritten in place
            else:
                comd_sids[spec.mloads_sid] = next_comd           # none yet, or a loaded one
                next_comd += 1
        pending[spec.mloads_sid][spec.label] = table.tid
        mass_label = (bulk.masssets[sc.massset_sid].label
                      if sc.massset_sid in bulk.masssets else "BASELINE")
        report.append(
            f"MANVR {spec.mloads_sid} ({mass_label}) {spec.label}: trim value "
            f"{trim_val:.6g} + increments -> TABLED1 {table.tid}"
        )
        resolved.append(spec)

    for mloads_sid, commands in pending.items():
        comd = Mldcomd(sid=comd_sids[mloads_sid],
                       commands=list(commands.items()))
        cards.append(("mldcomd", comd))
        mloads = bulk.mloads[mloads_sid]
        if mloads.mldcomd == comd.sid:
            continue
        # The MANVR must name the new MANCMD.  A loaded MANVR is not rewritten: a copy
        # under a new ID takes its place, and its subcases are pointed at the copy.
        new_sid = mloads.sid
        if mloads.sid in loaded.get("mloads", set()):
            new_sid = next_mloads
            next_mloads += 1
            for sc in cc.subcases:
                if sc.mloads_sid == mloads.sid:
                    selectors[sc.subcase_id] = new_sid
            report.append(
                f"MANVR {mloads.sid} is a card of the loaded deck: MANVR {new_sid} "
                f"(with MANCMD {comd.sid}) replaces it in subcase(s) "
                f"{sorted(s for s, m in selectors.items() if m == new_sid)}")
        cards.append(("mloads", Mloads(
            sid=new_sid, mldtrim=mloads.mldtrim, mldtime=mloads.mldtime,
            mldcomd=comd.sid, mldprnt=mloads.mldprnt,
            nmodes=mloads.nmodes, method=mloads.method, zeta=mloads.zeta,
        )))

    return Resolution(cards=cards, report=report, errors=errors,
                      resolved=resolved, selectors=selectors)
