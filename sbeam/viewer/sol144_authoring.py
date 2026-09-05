"""Streamlit-free logic for the viewer's SOL 144 / MLOADS authoring tab (P12).

Everything here is plain-Python and unit-testable: SID allocation and clash
detection, CAERO1 box-range bounds for AELIST authoring, THRU-aware integer
list parsing, and the apply/delete card operations on the in-session BulkData.
The Streamlit layer lives in ``sol144_authoring_ui.py``.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from sbeam.model.bulk_data import BulkData
from sbeam.model.card_writers import FAMILIES
from sbeam.model.maneuver import Mldcomd, Mloads, Tabled1
from sbeam.model.maneuver_presets import load_factor_to_urdd3
from sbeam.parser.bdf_reader import expand_int_list_with_thru
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


def family_store(bulk: BulkData, family: str) -> Any:
    return getattr(bulk, FAMILY_ATTRS[family])


def card_key(family: str, card: Any) -> int:
    """The tracking key for a card: its SID/ID (GID for SUPORT)."""
    if family == "suport":
        return card.gid
    return card.sid if hasattr(card, "sid") else card.id


def next_free_sid(bulk: BulkData, family: str) -> int:
    """Default ID for a new card: max(existing) + 1, or 1 on an empty family."""
    store = family_store(bulk, family)
    if family == "suport":
        ids = [s.gid for s in store]
    else:
        ids = [k for k in store.keys() if k > 0]
    return (max(ids) + 1) if ids else 1


def find_sid_conflicts(
    bulk: BulkData, family: str, sid: int, authored: dict[str, set[int]]
) -> list[str]:
    """Messages when ``sid`` collides with a card NOT authored this session.

    The parser raises on duplicate SIDs, so a driver deck that inlines an
    authored card whose SID also lives in an INCLUDE file is unparseable —
    the fix is to save under a new SID (clone-as-new).
    """
    store = family_store(bulk, family)
    exists = (any(s.gid == sid for s in store) if family == "suport"
              else sid in store)
    if exists and sid not in authored.get(family, set()):
        return [
            f"{family.upper()} {sid} already exists in the loaded bulk data — "
            "applying will edit it in-session, but the driver export would "
            "duplicate the SID against the INCLUDE file.  Save under a new "
            "SID to export."
        ]
    return []


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
    """Trim-variable labels an MLDCOMD/TRIM row may use.

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
        description="Prescribe ROLL = p and URDD4 = 0; the aileron trims free.",
        param_label="Roll rate p (rad/s)",
        param_default=1.0,
        required_labels=["ROLL", "URDD4"],
        surface_role="aileron",
    ),
    ManeuverPreset(
        name="Steady sideslip",
        description="Prescribe SIDES = beta and YAW = 0; the rudder trims free.",
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


def gen_step(t1: float, y0: float, y1: float,
             rise: float = 1.0e-3) -> list[tuple[float, float]]:
    """Near-instant step from y0 to y1 at t1 (TABLED1 is piecewise linear)."""
    return _prehold(t1, y0) + [(t1, y0), (t1 + rise, y1)]


def gen_ramp(t1: float, t2: float, y0: float, y1: float) -> list[tuple[float, float]]:
    """Linear ramp y0 -> y1 over [t1, t2], held clamped outside."""
    if t2 <= t1:
        raise ValueError("ramp needs t2 > t1")
    return _prehold(t1, y0) + [(t1, y0), (t2, y1)]


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
    return pts


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
    return pts


# ---------------------------------------------------------------------------
# Two-pass MLDCOMD automation (S4): tables authored as increments relative to
# trim, resolved to absolute TABLED1 cards once a solve supplies the trim
# control values (per mass case — command tables are absolute AND mass-case
# specific, so each MLOADS/mass-case pair gets its own table).
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
    """Resolve increment command specs into absolute TABLED1/MLDCOMD/MLOADS cards.

    Returns ``(cards, report, errors, resolved)`` where ``cards`` is a list of
    ``(family, card)`` pairs ready for ``apply_card`` (tables first, then the
    rewritten MLDCOMDs, then any MLOADS whose MLDCOMD reference changed),
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
    # Pending MLDCOMD command maps, keyed by mloads sid (specs may stack
    # several labels onto one driver).
    pending: dict[int, dict[str, int]] = {}
    comd_sids: dict[int, int] = {}

    for spec in specs:
        mloads = bulk.mloads.get(spec.mloads_sid)
        if mloads is None:
            errors.append(f"MLOADS {spec.mloads_sid} not found.")
            continue
        subcases = [sc for sc in cc.subcases if sc.mloads_sid == spec.mloads_sid]
        if not subcases:
            errors.append(f"No subcase selects MLOADS {spec.mloads_sid}.")
            continue
        mass_sids = {sc.massset_sid for sc in subcases}
        if len(mass_sids) > 1:
            errors.append(
                f"MLOADS {spec.mloads_sid} is shared by subcases with different "
                "MASSSETs — command tables are mass-case specific, so give "
                "each mass case its own MLOADS (the sample-deck convention)."
            )
            continue
        sc = subcases[0]
        if len(spec.points) < 2:
            errors.append(
                f"MLOADS {spec.mloads_sid} {spec.label}: an increment history "
                "needs at least two points.")
            continue
        trim_val = _trim_value_for_subcase(
            bulk, sc, mloads, spec.label, trim_results, maneuver_results)
        if trim_val is None:
            errors.append(
                f"MLOADS {spec.mloads_sid} {spec.label}: no solved trim value — "
                "run the trim/maneuver solve first (or author the table as "
                "absolute values).")
            continue

        xs = [t for t, _ in spec.points]
        ys = [trim_val + dy for _, dy in spec.points]
        if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
            errors.append(
                f"MLOADS {spec.mloads_sid} {spec.label}: increment abscissae "
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
            f"MLOADS {spec.mloads_sid} ({mass_label}) {spec.label}: trim value "
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
# Validation (S5) — parser-rule parity so authored cards fail in the UI, not
# at parse/solve time.  Cards injected by ``apply_card`` bypass the parser's
# deck-time cross-reference pass, so these checks re-implement it (plus the
# solver preconditions) as a pure pre-launch/pre-export gate.
# ---------------------------------------------------------------------------

def snapshot_family_ids(bulk: BulkData) -> dict[str, set[int]]:
    """IDs per family as loaded from file — the clone-as-new baseline."""
    out: dict[str, set[int]] = {}
    for family in FAMILY_ATTRS:
        store = family_store(bulk, family)
        if family == "suport":
            out[family] = {s.gid for s in store}
        else:
            out[family] = set(store.keys())
    return out


def validate_sol144_authoring(
    bulk: BulkData,
    cc: Optional[CaseControl],
    unresolved_increments: Optional[list["IncrementSpec"]] = None,
    file_sids: Optional[dict[str, set[int]]] = None,
    authored: Optional[dict[str, set[int]]] = None,
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a SOL 144 case-control + card set.

    Errors block Launch and export; warnings inform.  ``file_sids`` (the
    upload-time :func:`snapshot_family_ids`) with ``authored`` enables the
    clone-as-new duplicate-SID export check.
    """
    errors: list[str] = []
    warns: list[str] = []
    if cc is None or cc.sol != 144:
        return errors, warns

    all_labels = ({a.label for a in bulk.aestats.values()}
                  | {s.label for s in bulk.aesurfs.values()})
    aesurf_labels = {s.label for s in bulk.aesurfs.values()}

    # --- per-subcase driver / reference checks ---
    for sc in cc.subcases:
        tag = f"Subcase {sc.subcase_id}"
        drivers = [d for d in (sc.trim_sid, sc.diverg_sid, sc.mloads_sid)
                   if d is not None]
        if not drivers:
            errors.append(f"{tag}: no TRIM, DIVERG, or MLOADS selected — "
                          "a SOL 144 subcase needs a driver.")
        if sc.mloads_sid is not None and (sc.trim_sid is not None
                                          or sc.diverg_sid is not None):
            errors.append(f"{tag}: MLOADS cannot combine with TRIM/DIVERG "
                          "in one subcase.")
        if sc.load_sid is not None:
            errors.append(f"{tag}: LOAD does not combine with SOL 144 "
                          "(the aeroelastic drivers supply the loading).")
        for sid, family, name in [
            (sc.trim_sid, "trim", "TRIM"), (sc.trimobj_sid, "trimobj", "TRIMOBJ"),
            (sc.diverg_sid, "diverg", "DIVERG"), (sc.mloads_sid, "mloads", "MLOADS"),
        ]:
            if sid is not None and sid not in family_store(bulk, family):
                errors.append(f"{tag}: {name} {sid} not found in the bulk data.")
        if sc.massset_sid is not None and sc.massset_sid not in bulk.masssets:
            errors.append(f"{tag}: MASSSET {sc.massset_sid} not found in the "
                          "bulk data.")

    # --- TRIM cards (parser parity: labels, DOF-count warnings) ---
    for sid, trim in bulk.trims.items():
        for lbl in trim.vars:
            if lbl not in all_labels:
                errors.append(f"TRIM {sid}: label '{lbl}' not defined in any "
                              "AESTAT or AESURF card.")
        prescribed = set(trim.vars.keys()) & all_labels
        free = all_labels - prescribed
        if all_labels and not free:
            warns.append(f"TRIM {sid}: all trim variables are prescribed — "
                         "no DOFs remain to solve.")
        elif len(free) > len(prescribed) and not bulk.trimobjs:
            warns.append(f"TRIM {sid}: over-determined ({len(free)} free vs "
                         f"{len(prescribed)} prescribed) with no TRIMOBJ card.")

    # --- MLOADS family cross-references + solver preconditions ---
    mloads_selected = [sc.mloads_sid for sc in cc.subcases
                       if sc.mloads_sid is not None]
    if mloads_selected and not bulk.supports:
        errors.append("An MLOADS subcase needs a SUPORT card (free-flight "
                      "r-set) — none is defined.")
    for sid in mloads_selected:
        ml = bulk.mloads.get(sid)
        if ml is None:
            continue
        mldtrim = bulk.mldtrims.get(ml.mldtrim)
        if mldtrim is None:
            errors.append(f"MLOADS {sid}: MLDTRIM {ml.mldtrim} not found.")
        elif mldtrim.trim_sid not in bulk.trims:
            errors.append(f"MLDTRIM {mldtrim.sid}: TRIM {mldtrim.trim_sid} "
                          "not found.")
        elif ml.selects_modal and bulk.trims[mldtrim.trim_sid].rhoref <= 0.0:
            errors.append(
                f"MLOADS {sid}: the modal (free-flight) solver needs RHOREF "
                f"on the initial-condition TRIM {mldtrim.trim_sid} "
                "(V = sqrt(2q/rho)).")
        mldtime = bulk.mldtimes.get(ml.mldtime)
        if mldtime is None:
            errors.append(f"MLOADS {sid}: MLDTIME {ml.mldtime} not found.")
        elif mldtime.dt <= 0.0 or mldtime.tend <= mldtime.t0:
            errors.append(f"MLDTIME {mldtime.sid}: needs DT > 0 and TEND > T0.")
        if ml.mldprnt and ml.mldprnt not in bulk.mldprnts:
            errors.append(f"MLOADS {sid}: MLDPRNT {ml.mldprnt} not found.")
        if ml.method > 0 and ml.method not in bulk.eigrls:
            errors.append(f"MLOADS {sid}: METHOD {ml.method} is not an EIGRL "
                          "SID.")
        if ml.mldcomd:
            comd = bulk.mldcomds.get(ml.mldcomd)
            if comd is None:
                errors.append(f"MLOADS {sid}: MLDCOMD {ml.mldcomd} not found.")
            else:
                for label, tabid in comd.commands:
                    if label not in all_labels:
                        errors.append(f"MLDCOMD {comd.sid}: label '{label}' "
                                      "not defined in any AESTAT or AESURF "
                                      "card.")
                    elif ml.selects_modal and label not in aesurf_labels:
                        errors.append(
                            f"MLOADS {sid}: MLDCOMD {comd.sid} commands "
                            f"rigid-state label '{label}' — under the modal "
                            "solver rigid states are outputs; command AESURF "
                            "controls only.")
                    table = bulk.tabled1s.get(tabid)
                    if table is None:
                        errors.append(f"MLDCOMD {comd.sid}: TABLED1 {tabid} "
                                      "not found.")
                    else:
                        if len(table.xs) < 2:
                            errors.append(f"TABLED1 {tabid}: needs at least "
                                          "two points.")
                        elif any(table.xs[i + 1] <= table.xs[i]
                                 for i in range(len(table.xs) - 1)):
                            errors.append(f"TABLED1 {tabid}: abscissae must "
                                          "be strictly increasing.")
                        elif ml.selects_modal and len(table.xs) < 5:
                            warns.append(
                                f"TABLED1 {tabid} (modal MLOADS {sid}): "
                                "sparse clamped-linear table — slope jumps "
                                "ring the highest retained mode; consider a "
                                "densely-sampled cosine ramp.")
        for sc in cc.subcases:
            if sc.mloads_sid == sid and sc.massset_sid is not None \
                    and ml.selects_modal:
                warns.append(
                    f"Subcase {sc.subcase_id}: MASSSET {sc.massset_sid} with "
                    "the modal solver uses the fixed baseline basis (fixed-Φ); "
                    "the solver warns if the case CG shifts more than 5% of "
                    "c_ref.")

    # --- AELIST box ranges ---
    ranges = caero_box_ranges(bulk)
    for sid, ael in bulk.aelists.items():
        outside = boxes_outside_ranges(ael.elements, ranges)
        if outside:
            errors.append(f"AELIST {sid}: boxes outside every CAERO1 range: "
                          f"{outside}.")

    # --- export-only gates ---
    for key in (unresolved_increments or []):
        msid, label = key.mloads_sid, key.label
        errors.append(
            f"MLOADS {msid} {label}: unresolved increment command — resolve "
            "to absolute TABLED1s (after a solve) before exporting.")
    if file_sids and authored:
        for family, ids in authored.items():
            dups = sorted(ids & file_sids.get(family, set()))
            for sid in dups:
                errors.append(
                    f"{family.upper()} {sid} is authored but its SID is also "
                    "defined in the loaded file — the driver export would "
                    "duplicate it against the INCLUDE.  Save it as a new SID.")

    return errors, warns


def suggest_run_name(stem: str, cc: Optional[CaseControl]) -> str:
    """Filesystem-safe driver filename for an exported SOL 144 run deck."""
    base = "".join(ch if (ch.isalnum() or ch in "-_") else "_"
                   for ch in (stem or "model"))
    kinds = set()
    for sc in (cc.subcases if cc is not None else []):
        if sc.mloads_sid is not None:
            kinds.add("mloads")
        elif sc.diverg_sid is not None and sc.trim_sid is None:
            kinds.add("diverg")
        elif sc.trim_sid is not None:
            kinds.add("trim")
    suffix = "_".join(sorted(kinds)) or "run"
    return f"{base}_{suffix}.bdf"
