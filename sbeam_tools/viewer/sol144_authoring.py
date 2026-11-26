"""Streamlit-free logic for the viewer's SOL 144 / MANVR authoring tab (P12).

Everything here is plain-Python and unit-testable: SID allocation, CAERO1
box-range bounds for AELIST authoring, THRU-aware integer list parsing, and the
candidate model a card edit is tried on before the deck is re-parsed (#113).
The Streamlit layer lives in ``sol144_authoring_ui.py`` and ``session_deck.py``.
"""

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from sbeam.model.bulk_data import BulkData
from sbeam.model.card_writers import FAMILIES, write_authored_block
from sbeam.model.maneuver import Mldcomd, Mloads, Tabled1
from sbeam.model.maneuver_presets import load_factor_to_urdd3
from sbeam.parser.bulk_fields import expand_int_list_with_thru
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.results.results import ManeuverResult, Sol144TrimResult

# Canonical AESTAT rigid-body trim-variable labels.
AESTAT_LABELS = [
    "ANGLEA", "SIDES", "ROLL", "PITCH", "YAW",
    "URDD2", "URDD3", "URDD4", "URDD5", "URDD6",
]

# family key -> BulkData attribute (shared with the card writers so the two
# can never disagree about where a family lives).
FAMILY_ATTRS: dict[str, str] = {fam: attr for fam, (attr, _) in FAMILIES.items()}


# family key -> the card's name in a deck and in every message to the user.
CARD_NAMES: dict[str, str] = {
    "aestat": "AESTAT", "aesurf": "AESURF", "aelist": "AELIST", "suport": "SUPORT",
    "trim": "TRIM", "trimvar": "TRIMVAR", "trimobj": "TRIMWGT", "trimcon": "TRIMINEQ",
    "diverg": "DIVERG", "gustlf": "GUSTLF", "tabled1": "TABLED1",
    "mldtrim": "MANTRIM", "mldtime": "MANTIME", "mldcomd": "MANCMD",
    "mldprnt": "MANPRNT", "mloads": "MANVR",
}
assert set(CARD_NAMES) == set(FAMILIES)

AUTHORED_HEADER = "Authored in the sbeam viewer (SOL 144 / MANVR authoring tab)"


def family_store(bulk: BulkData, family: str) -> Any:
    return getattr(bulk, FAMILY_ATTRS[family])


def key_attr(family: str, card: Any) -> str:
    """The name of the field that identifies a card: GID for SUPORT, else SID/ID/TID."""
    if family == "suport":
        return "gid"
    for name in ("sid", "id", "tid"):
        if hasattr(card, name):
            return name
    raise AttributeError(f"{type(card).__name__} has no SID, ID or TID field")


def card_key(family: str, card: Any) -> int:
    """The tracking key for a card: its SID/ID/TID (GID for SUPORT)."""
    return getattr(card, key_attr(family, card))


def next_free_sid(bulk: BulkData, family: str) -> int:
    """Default ID for a new card: max(existing) + 1, or 1 on an empty family."""
    store = family_store(bulk, family)
    if family == "suport":
        ids = [s.gid for s in store]
    else:
        ids = [k for k in store.keys() if k > 0]
    return (max(ids) + 1) if ids else 1


def apply_card(bulk: BulkData, family: str, card: Any,
               authored: dict[str, set[int]]) -> int:
    """Insert/replace ``card`` in the session model and track it as authored.

    For 'trimcon' pass the full list of constraints sharing one SID.
    Returns the tracking key.
    """
    if family == "trimcon":
        cons = card if isinstance(card, list) else [card]
        key = cons[0].sid
        family_store(bulk, family)[key] = list(cons)
    elif family == "suport":
        key = card.gid
        store = family_store(bulk, family)
        store[:] = [s for s in store if s.gid != key]
        store.append(card)
    else:
        key = card_key(family, card)
        family_store(bulk, family)[key] = card
    authored.setdefault(family, set()).add(key)
    return key


def candidate(
    bulk: BulkData,
    authored: dict[str, set[int]],
    changes: Sequence[tuple[str, Any]] = (),
    deletes: Sequence[tuple[str, int]] = (),
) -> tuple[BulkData, dict[str, set[int]]]:
    """The model and the authored-card record as they would be after an edit.

    The session model is not touched: the result is a shallow copy whose card-family
    stores are new containers.  It exists only to write the authored cards as text;
    the model the session keeps is the one the parser returns for that text (#113).
    """
    trial = copy.copy(bulk)
    for attr in FAMILY_ATTRS.values():
        setattr(trial, attr, copy.copy(getattr(bulk, attr)))
    record = {family: set(keys) for family, keys in authored.items()}
    for family, key in deletes:
        delete_card(trial, family, key, record)
    for family, card in changes:
        apply_card(trial, family, card, record)
    return trial, record


def loaded_card_edits(
    file_sids: Optional[dict[str, set[int]]],
    changes: Sequence[tuple[str, Any]] = (),
    deletes: Sequence[tuple[str, int]] = (),
) -> list[str]:
    """A message for each edit that would change or remove a card of the loaded deck.

    A loaded card is not changed in place.  The deck text the viewer runs and exports
    is the loaded deck plus the authored cards; an edited copy of a loaded card would
    be a second card with the same ID beside the original.  The edit is saved under a
    new ID instead ("Save as new SID").  The parser refuses most such duplicates, but
    not a second SUPORT on one grid, so the rule is checked here for every family.
    """
    file_sids = file_sids or {}
    touched = [(family, card_key(family, card[0] if isinstance(card, list) else card))
               for family, card in changes]
    touched += list(deletes)
    return [
        f"{CARD_NAMES[family]} {key} comes from the loaded deck and is not changed "
        "here: the deck would then hold two cards with that ID. Use 'Save as new "
        "SID', then select the new card where the old one was used."
        for family, key in dict.fromkeys(touched)
        if key in file_sids.get(family, set())
    ]


def cards_text(bulk: BulkData, authored: dict[str, set[int]],
               blocks: Optional[dict[str, str]] = None) -> str:
    """The bulk text the viewer adds to the loaded deck: authored cards, then each
    named block another panel contributes (the aero-correction cards)."""
    parts = [write_authored_block(bulk, authored, AUTHORED_HEADER)]
    parts += [text for _, text in sorted((blocks or {}).items()) if text]
    return "".join(part if part.endswith("\n") else part + "\n" for part in parts if part)


def delete_card(bulk: BulkData, family: str, key: int,
                authored: dict[str, set[int]]) -> None:
    """Remove a card from the session model and from the authored set."""
    store = family_store(bulk, family)
    if family == "suport":
        store[:] = [s for s in store if s.gid != key]
    else:
        store.pop(key, None)
    authored.get(family, set()).discard(key)


def caero_box_ranges(bulk: BulkData) -> list[tuple[int, int]]:
    """Valid AELIST box-ID ranges: [EID, EID + NSPAN*NCHORD - 1] per CAERO1."""
    ranges = []
    for c in bulk.caero1s.values():
        n = c.nspan * c.nchord
        if n > 0:
            ranges.append((c.eid, c.eid + n - 1))
    return sorted(ranges)


def boxes_outside_ranges(elements: list[int],
                         ranges: list[tuple[int, int]]) -> list[int]:
    """Box IDs not covered by any CAERO1 range (empty ranges = no check)."""
    if not ranges:
        return []
    return [e for e in elements
            if not any(lo <= e <= hi for lo, hi in ranges)]


def expand_int_tokens(text: str) -> list[int]:
    """Parse '1101 THRU 1112, 1120' style text into a flat integer list.

    Uses the parser's own THRU expansion so UI entry and BDF cards agree.
    Raises ValueError on non-integer tokens.
    """
    tokens = [t for t in text.replace(",", " ").split() if t]
    return expand_int_list_with_thru(tokens)


def parse_float_list(text: str) -> list[float]:
    """Parse a whitespace/comma-separated float list."""
    return [float(t) for t in text.replace(",", " ").split() if t]


def label_options(bulk: BulkData, modal_only: bool = False) -> list[str]:
    """Trim-variable labels an MANCMD/TRIM row may use.

    ``modal_only`` restricts to AESURF labels — under the modal (free-flight)
    solver, rigid-state AESTAT labels are outputs and commanding one is a
    hard parse error.
    """
    surf = [s.label for s in bulk.aesurfs.values()]
    if modal_only:
        return sorted(surf)
    stat = [a.label for a in bulk.aestats.values()]
    return sorted(set(stat + surf))


# ---------------------------------------------------------------------------
# Maneuver presets (S4) — the three balanced-maneuver recipes from
# ``model/maneuver_presets.py``, encoded so a preset button can pre-fill the
# TRIM form.  Gravity folds into the load factor (NASTRAN convention).
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

    def prescribed_vars(self, param: float, g: float = 0.0) -> dict[str, float]:
        if self.name == "Symmetric pull-up / push-over":
            return {"URDD3": load_factor_to_urdd3(param, g),
                    "PITCH": 0.0, "URDD5": 0.0}
        if self.name == "Steady roll":
            return {"ROLL": param, "URDD4": 0.0}
        if self.name == "Steady sideslip":
            return {"SIDES": param, "YAW": 0.0}
        raise ValueError(f"unknown preset {self.name!r}")


MANEUVER_PRESETS: list[ManeuverPreset] = [
    ManeuverPreset(
        name="Symmetric pull-up / push-over",
        description="Prescribe URDD3 = -n_z·g and PITCH = URDD5 = 0; "
                    "ANGLEA and the elevator trim free.",
        param_label="Load factor n_z",
        param_default=2.5,
        required_labels=["ANGLEA", "PITCH", "URDD3", "URDD5"],
        surface_role="elevator",
        uses_g=True,
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
# TABLED1 generators (S4).  Each returns (x, y) points for the point editor.
# The cosine ramp is the default in the UI: clamped-linear slope jumps ring
# the highest retained mode under the modal solver (backlog risk 3).
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


def resolve_increment_tables(
    bulk: BulkData,
    cc: CaseControl,
    specs: list[IncrementSpec],
    trim_results: Optional[dict[int, Sol144TrimResult]] = None,
    maneuver_results: Optional[dict[int, ManeuverResult]] = None,
) -> tuple[list[tuple[str, Any]], list[str], list[str], list["IncrementSpec"]]:
    """Resolve increment command specs into absolute TABLED1/MANCMD/MANVR cards.

    Returns ``(cards, report, errors, resolved)`` where ``cards`` is a list of
    ``(family, card)`` pairs ready for ``apply_card`` (tables first, then the
    rewritten MLDCOMDs, then any MANVR whose MANCMD reference changed),
    ``report`` describes the offsets used, ``errors`` lists specs that could
    not be resolved (nothing is returned for a spec that errors), and
    ``resolved`` is the subset of ``specs`` that produced cards.
    """
    cards: list[tuple[str, Any]] = []
    report: list[str] = []
    errors: list[str] = []
    resolved: list[IncrementSpec] = []

    next_tid = next_free_sid(bulk, "tabled1")
    next_comd = next_free_sid(bulk, "mldcomd")
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
            if mloads.mldcomd:
                comd_sids[spec.mloads_sid] = mloads.mldcomd
            else:
                comd_sids[spec.mloads_sid] = next_comd
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
        if mloads.mldcomd != comd.sid:
            cards.append(("mloads", Mloads(
                sid=mloads.sid, mldtrim=mloads.mldtrim, mldtime=mloads.mldtime,
                mldcomd=comd.sid, mldprnt=mloads.mldprnt,
                nmodes=mloads.nmodes, method=mloads.method, zeta=mloads.zeta,
            )))

    return cards, report, errors, resolved


# ---------------------------------------------------------------------------
# Pre-launch check of the case control against the model.
#
# Card rules are the parser's: every card the viewer authors is written as text and
# the deck is re-parsed (#113), so a label that no AESTAT defines, a MANVR that names
# a missing MANTIME, a TABLED1 out of order, an AELIST box outside every CAERO1 and a
# duplicate ID are all refused with the parser's own message.  What is left here is
# what the parser does not look at: whether each subcase's selectors name cards that
# exist and make one runnable case.  The solver raises on these at run time; the
# viewer reports them before Launch.  (They are solver rules restated, the class of
# #122; #124 moves them into the solver package so there is one statement.)
# ---------------------------------------------------------------------------

def snapshot_family_ids(bulk: BulkData) -> dict[str, set[int]]:
    """IDs per family as loaded from the deck: the cards that are not changed in place."""
    out: dict[str, set[int]] = {}
    for family in FAMILY_ATTRS:
        store = family_store(bulk, family)
        if family == "suport":
            out[family] = {s.gid for s in store}
        else:
            out[family] = set(store.keys())
    return out


def check_case_control(
    bulk: BulkData,
    cc: Optional[CaseControl],
    unresolved_increments: Optional[list["IncrementSpec"]] = None,
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a SOL 144 case control against its model.

    Errors block Launch and export; warnings inform.  Card-level rules are not
    checked here: they are the parser's, applied when the deck is re-parsed.
    """
    errors: list[str] = []
    warns: list[str] = []
    if cc is None or cc.sol != 144:
        return errors, warns

    # --- per-subcase driver / reference checks ---
    for sc in cc.subcases:
        tag = f"Subcase {sc.subcase_id}"
        # A GUSTLF subcase is a trim subcase: the card names its own TRIM, so the
        # TRIM selector may be blank (run_sol144_trim, #1; found by #111).
        has_trim = sc.trim_sid is not None or sc.gustlf_sid is not None
        drivers = [d for d in (sc.trim_sid, sc.diverg_sid, sc.mloads_sid,
                               sc.gustlf_sid) if d is not None]
        if not drivers:
            errors.append(f"{tag}: no TRIM, DIVERG, MANVR or GUSTLF selected — "
                          "a SOL 144 subcase needs a driver.")
        if sc.gustlf_sid is not None:
            gust = bulk.gustlfs.get(sc.gustlf_sid)
            if gust is None:
                errors.append(f"{tag}: GUSTLF {sc.gustlf_sid} not found in the "
                              "bulk data.")
            elif sc.trim_sid is not None and sc.trim_sid != gust.trimid:
                errors.append(f"{tag}: TRIM = {sc.trim_sid} but GUSTLF "
                              f"{gust.sid} names TRIM {gust.trimid}.")
        if sc.mloads_sid is not None and (has_trim
                                          or sc.diverg_sid is not None):
            errors.append(f"{tag}: MANVR cannot combine with TRIM/GUSTLF/DIVERG "
                          "in one subcase.")
        # #6: a TRIM subcase takes a LOAD set (applied structural load in the
        # trim RHS); MANVR and DIVERG-only subcases do not (the solver raises).
        if sc.load_sid is not None:
            if not has_trim:
                errors.append(f"{tag}: LOAD combines only with a TRIM subcase "
                              "(an applied structural load enters the trim "
                              "balance; MANVR and DIVERG-only subcases drop "
                              "it, so the solver refuses the request).")
            else:
                sids = [sc.load_sid]
                if sc.load_sid in bulk.loads:
                    sids += [s for _, s in bulk.loads[sc.load_sid].components]
                known = (set(bulk.loads) | set(bulk.forces) | set(bulk.moments)
                         | set(bulk.gravs))
                if sc.load_sid not in known:
                    errors.append(f"{tag}: LOAD {sc.load_sid} not found in the "
                                  "bulk data.")
                gravs = sorted({s for s in sids if s in bulk.gravs})
                if gravs:
                    errors.append(f"{tag}: LOAD {sc.load_sid} references GRAV "
                                  f"{gravs}; gravity enters a trim through URDD3 "
                                  "only, so a GRAV in the trim LOAD set is refused.")
        for sid, family, name in [
            (sc.trim_sid, "trim", "TRIM"), (sc.trimobj_sid, "trimobj", "TRIMWGT"),
            (sc.diverg_sid, "diverg", "DIVERG"), (sc.mloads_sid, "mloads", "MANVR"),
        ]:
            if sid is not None and sid not in family_store(bulk, family):
                errors.append(f"{tag}: {name} {sid} not found in the bulk data.")
        if sc.massset_sid is not None and sc.massset_sid not in bulk.masssets:
            errors.append(f"{tag}: MASSCASE {sc.massset_sid} not found in the "
                          "bulk data.")

    # --- trim determinacy: information, not a rule ---
    all_labels = ({a.label for a in bulk.aestats.values()}
                  | {s.label for s in bulk.aesurfs.values()})
    for sid, trim in bulk.trims.items():
        prescribed = set(trim.vars.keys()) & all_labels
        free = all_labels - prescribed
        if all_labels and not free:
            warns.append(f"TRIM {sid}: all trim variables are prescribed — "
                         "no DOFs remain to solve.")
        elif len(free) > len(prescribed) and not bulk.trimobjs:
            warns.append(f"TRIM {sid}: over-determined ({len(free)} free vs "
                         f"{len(prescribed)} prescribed) with no TRIMWGT card.")

    # --- MANVR subcases: what the solver needs that no card rule states ---
    mloads_selected = [sc.mloads_sid for sc in cc.subcases
                       if sc.mloads_sid is not None]
    if mloads_selected and not bulk.supports:
        errors.append("An MANVR subcase needs a SUPORT card (free-flight "
                      "r-set) — none is defined.")
    for sid in dict.fromkeys(mloads_selected):
        ml = bulk.mloads.get(sid)
        if ml is None:
            continue
        mldtrim = bulk.mldtrims.get(ml.mldtrim)
        if mldtrim is not None and ml.selects_modal and mldtrim.rho <= 0.0:
            errors.append(
                f"MANVR {sid}: the modal (free-flight) solver needs RHO "
                f"on MANTRIM {mldtrim.sid} (V = sqrt(2q/rho)).")
        comd = bulk.mldcomds.get(ml.mldcomd) if ml.mldcomd else None
        for _label, tabid in (comd.commands if comd is not None else []):
            table = bulk.tabled1s.get(tabid)
            if table is not None and ml.selects_modal and len(table.xs) < 5:
                warns.append(
                    f"TABLED1 {tabid} (modal MANVR {sid}): "
                    "sparse clamped-linear table — slope jumps "
                    "ring the highest retained mode; consider a "
                    "densely-sampled cosine ramp.")
        for sc in cc.subcases:
            if sc.mloads_sid == sid and sc.massset_sid is not None \
                    and ml.selects_modal:
                warns.append(
                    f"Subcase {sc.subcase_id}: MASSCASE {sc.massset_sid} with "
                    "the modal solver uses the fixed baseline basis (fixed-Φ); "
                    "the solver warns if the case CG shifts more than 5% of "
                    "c_ref.")

    # --- viewer state: a command still written as an increment from trim ---
    for key in (unresolved_increments or []):
        msid, label = key.mloads_sid, key.label
        errors.append(
            f"MANVR {msid} {label}: unresolved increment command — resolve "
            "to absolute TABLED1s (after a solve) before exporting.")

    return errors, warns


def suggest_run_name(stem: str, cc: Optional[CaseControl]) -> str:
    """Filesystem-safe driver filename for an exported SOL 144 run deck."""
    base = "".join(ch if (ch.isalnum() or ch in "-_") else "_"
                   for ch in (stem or "model"))
    kinds = set()
    for sc in (cc.subcases if cc is not None else []):
        if sc.mloads_sid is not None:
            kinds.add("mloads")
        elif sc.gustlf_sid is not None:
            kinds.add("gust")
        elif sc.diverg_sid is not None and sc.trim_sid is None:
            kinds.add("diverg")
        elif sc.trim_sid is not None:
            kinds.add("trim")
    suffix = "_".join(sorted(kinds)) or "run"
    return f"{base}_{suffix}.bdf"
