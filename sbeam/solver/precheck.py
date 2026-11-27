"""Is the case control a set of cases the solver can run on this model?  (#124)

The parser checks cards against cards.  It does not check the case control against the
bulk data: a subcase that selects ``TRIM = 77`` with no TRIM 77 parses.  Until #124 such
a deck failed inside the solver when its subcase was reached, with every earlier
subcase's work lost, and two faults did not fail at all:

* ``MANVR`` and ``TRIM`` in one subcase ran the maneuver and ignored the TRIM;
* ``TRIMWGT = n`` naming no card ran the trim with no objective.

Input that is not acted on is refused (CLAUDE.md rule 7), so both are errors here.

``check_case_control`` states the rules once.  ``sbeam.main`` calls it before the first
solve and stops with every fault listed; the viewer shows the same list before Launch.
It is not part of ``parse_bdf``: a deck that cannot yet run can still be read, which is
how a tool opens one to complete it.

These are sbeam's own consistency rules.  No MSC rule is claimed for them; what MSC
does with a selector that names no bulk entry was not looked up.

Only SOL 144 is checked.  SOL 101 and 103 report a missing LOAD, SPC or METHOD from
the solver, as before.
"""

from __future__ import annotations

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl


def check_case_control(cc: CaseControl, bulk: BulkData) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a case control against its model.

    An error is a subcase the solver cannot run, or would run while ignoring part of
    the request.  A warning informs.  Both are empty for a deck that is not SOL 144.

    Where the solver enforces a rule itself, the function is named beside it; the two
    rules marked *not enforced* had no check anywhere before this one.
    """
    errors: list[str] = []
    warns: list[str] = []
    if cc.sol != 144:
        return errors, warns

    # --- per-subcase driver / reference checks ---
    for sc in cc.subcases:
        tag = f"Subcase {sc.subcase_id}"
        # A GUSTLF subcase is a trim subcase: the card names its own TRIM, so the
        # TRIM selector may be blank (run_sol144_trim, #1; found by #111).
        has_trim = sc.trim_sid is not None or sc.gustlf_sid is not None
        drivers = [d for d in (sc.trim_sid, sc.diverg_sid, sc.mloads_sid,
                               sc.gustlf_sid) if d is not None]
        # run_sol144_trim raises "TRIM SID None not found", which names no cause
        if not drivers:
            errors.append(f"{tag}: no TRIM, DIVERG, MANVR or GUSTLF selected — "
                          "a SOL 144 subcase needs a driver.")
        # run_sol144_trim: GUSTLF not found; TRIM selector against the card's TRIMID
        if sc.gustlf_sid is not None:
            gust = bulk.gustlfs.get(sc.gustlf_sid)
            if gust is None:
                errors.append(f"{tag}: GUSTLF {sc.gustlf_sid} not found in the "
                              "bulk data.")
            elif sc.trim_sid is not None and sc.trim_sid != gust.trimid:
                errors.append(f"{tag}: TRIM = {sc.trim_sid} but GUSTLF "
                              f"{gust.sid} names TRIM {gust.trimid}.")
        # *not enforced* by the solver: the dispatch ran the MANVR and ignored the rest
        if sc.mloads_sid is not None and (has_trim
                                          or sc.diverg_sid is not None):
            errors.append(f"{tag}: MANVR cannot combine with TRIM/GUSTLF/DIVERG "
                          "in one subcase.")
        # #6: a TRIM subcase takes a LOAD set (applied structural load in the trim
        # RHS).  run_maneuver_qs and run_sol144_diverg raise for a LOAD on theirs; the
        # load-vector assembly raises for a set that does not exist.
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
        # run_sol144_trim / run_sol144_diverg / run_maneuver_qs raise for TRIM, DIVERG
        # and MANVR.  TRIMWGT is *not enforced*: the trim ran with no objective.
        for sid, store, name in [
            (sc.trim_sid, bulk.trims, "TRIM"), (sc.trimobj_sid, bulk.trimobjs, "TRIMWGT"),
            (sc.diverg_sid, bulk.divergs, "DIVERG"), (sc.mloads_sid, bulk.mloads, "MANVR"),
        ]:
            if sid is not None and sid not in store:
                errors.append(f"{tag}: {name} {sid} not found in the bulk data.")
        # mass_overlay.resolve_mass_case raises
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
    # run_sol144_trim (the maneuver's initial trim): no SUPORT card
    if mloads_selected and not bulk.supports:
        errors.append("An MANVR subcase needs a SUPORT card (free-flight "
                      "r-set) — none is defined.")
    for sid in dict.fromkeys(mloads_selected):
        ml = bulk.mloads.get(sid)
        if ml is None:
            continue
        mldtrim = bulk.mldtrims.get(ml.mldtrim)
        # run_maneuver_modal: needs RHO for V = sqrt(2q/rho)
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

    return errors, warns


def require_runnable(cc: CaseControl, bulk: BulkData) -> None:
    """Raise ``ValueError`` listing every fault of ``check_case_control``, if any."""
    errors, _ = check_case_control(cc, bulk)
    if errors:
        raise ValueError(
            "the case control cannot be run on this model:\n"
            + "\n".join(f"  - {message}" for message in errors))
