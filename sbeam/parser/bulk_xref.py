"""Bulk-data cross-reference checks, run once every card has been read (#48).

Each check reads only resolved cards, so it is independent of card order in the deck.
``cross_reference`` runs them in a fixed order; the order decides only which error a deck
with several faults reports first.
"""
import warnings

from sbeam.model.bulk_data import BulkData


def cross_reference(bulk: BulkData) -> None:
    """Check every cross-card reference in ``bulk``; raise ValueError on the first failure."""
    _check_aero_panels(bulk)
    _check_load_combinations(bulk)
    _check_control_surfaces(bulk)
    _check_monitors(bulk)
    all_trim_labels = _check_trim(bulk)
    _check_maneuver_loads(bulk, all_trim_labels)
    _check_massset(bulk)


def _check_aero_panels(bulk: BulkData) -> None:
    """AEROS presence, CAERO1 property/division refs, STRIPK targets, SPLINE2 and SET1."""
    # CAERO1 cards require an AEROS card to provide reference geometry
    if bulk.caero1s and bulk.aeros is None:
        raise ValueError("CAERO1 card(s) present but no AEROS card found")

    # Validate CAERO1 cross-references (deferred because AEFACT/PAERO1/PSTRIP may
    # appear after CAERO1).  A CAERO1 PID resolves to either a PAERO1 (ordinary VLM
    # panel) or a PSTRIP (decoupled strip body panel).
    for eid, caero in bulk.caero1s.items():
        if caero.pid not in bulk.paero1s and caero.pid not in bulk.pstrips:
            raise ValueError(
                f"CAERO1 {eid}: PID={caero.pid} not found in PAERO1 or PSTRIP")
        if caero.lspan and caero.lspan not in bulk.aefacts:
            raise ValueError(f"CAERO1 {eid}: LSPAN={caero.lspan} not found in AEFACT")
        if caero.lchord and caero.lchord not in bulk.aefacts:
            raise ValueError(f"CAERO1 {eid}: LCHORD={caero.lchord} not found in AEFACT")

    # Validate STRIPK cross-references: must target a strip (PSTRIP-backed) CAERO1.
    for sid, sk in bulk.stripks.items():
        caero = bulk.caero1s.get(sk.caero_eid)
        if caero is None:
            raise ValueError(f"STRIPK {sid}: CAERO1 {sk.caero_eid} not found")
        if caero.pid not in bulk.pstrips:
            raise ValueError(
                f"STRIPK {sid}: CAERO1 {sk.caero_eid} is not a strip panel "
                f"(PID={caero.pid} is not a PSTRIP)")

    # Validate SPLINE2 cross-references (SET1 SID, CAERO1 EID, grid IDs)
    for eid, sp in bulk.spline2s.items():
        if sp.setg not in bulk.set1s:
            raise ValueError(f"SPLINE2 {eid}: SETG={sp.setg} not found in SET1")
        if sp.caero not in bulk.caero1s:
            raise ValueError(f"SPLINE2 {eid}: CAERO={sp.caero} not found in CAERO1")
    for sid, s1 in bulk.set1s.items():
        for gid in s1.grids:
            if gid not in bulk.grids:
                raise ValueError(f"SET1 {sid}: grid ID {gid} not found in GRID")


def _check_load_combinations(bulk: BulkData) -> None:
    """LOAD components resolve to FORCE, MOMENT or GRAV sets."""
    # Validate LOAD component references after all cards are parsed
    for load_sid, load in bulk.loads.items():
        for _, comp_sid in load.components:
            if (comp_sid not in bulk.forces
                    and comp_sid not in bulk.moments
                    and comp_sid not in bulk.gravs):
                raise ValueError(
                    f"LOAD {load_sid}: component SID {comp_sid} not found in FORCE, MOMENT, or GRAV sets"
                )


def _check_control_surfaces(bulk: BulkData) -> None:
    """AESURF hinge frames and box lists; AELIST boxes inside a CAERO1."""
    # Validate AESURF → AELIST / CORD2R references (#9: the CID2/ALID2 second
    # hinge half is consumed, so it is checked like the first; a box may not
    # belong to both halves of one surface).
    for aid, aesurf in bulk.aesurfs.items():
        if aesurf.alid1 not in bulk.aelists:
            raise ValueError(f"AESURF {aid}: ALID1={aesurf.alid1} not found in AELIST")
        if aesurf.cid1 and aesurf.cid1 not in bulk.cord2rs:
            raise ValueError(f"AESURF {aid}: hinge CID1={aesurf.cid1} not found in CORD2R")
        if bool(aesurf.cid2) != bool(aesurf.alid2):
            raise ValueError(
                f"AESURF {aid}: CID2={aesurf.cid2} and ALID2={aesurf.alid2} must be given "
                "together (the second hinge half needs both its hinge CID and its AELIST)")
        if aesurf.alid2:
            if aesurf.alid2 not in bulk.aelists:
                raise ValueError(f"AESURF {aid}: ALID2={aesurf.alid2} not found in AELIST")
            if aesurf.cid2 not in bulk.cord2rs:
                raise ValueError(f"AESURF {aid}: hinge CID2={aesurf.cid2} not found in CORD2R")
            both = sorted(set(bulk.aelists[aesurf.alid1].elements)
                          & set(bulk.aelists[aesurf.alid2].elements))
            if both:
                raise ValueError(
                    f"AESURF {aid}: box(es) {both[:5]} appear in both ALID1={aesurf.alid1} "
                    f"and ALID2={aesurf.alid2}; a box deflects about one hinge only")

    # Validate AELIST box IDs fall within declared CAERO1 ranges
    if bulk.aelists and bulk.caero1s:
        caero_ranges = [
            range(c.eid, c.eid + c.nspan * c.nchord)
            for c in bulk.caero1s.values()
        ]
        for sid, aelist in bulk.aelists.items():
            for box_id in aelist.elements:
                if not any(box_id in r for r in caero_ranges):
                    raise ValueError(
                        f"AELIST {sid}: box ID {box_id} not within any CAERO1 range"
                    )


def _check_monitors(bulk: BulkData) -> None:
    """AECOMP list references and MONPNT1/MONPNT3/MONSECT components and frames."""
    # Validate AECOMP list references and MONPNT1/MONPNT3 cross-references
    for name, aecomp in bulk.aecomps.items():
        target = bulk.aelists if aecomp.listtype == "AELIST" else bulk.set1s
        for lid in aecomp.list_ids:
            if lid not in target:
                raise ValueError(
                    f"AECOMP {name}: {aecomp.listtype} SID {lid} not found"
                )
    for name, mon in bulk.monpnt1s.items():
        if mon.comp not in bulk.aecomps:
            raise ValueError(f"MONPNT1 {name}: COMP '{mon.comp}' not found in AECOMP")
        if bulk.aecomps[mon.comp].listtype != "AELIST":
            raise ValueError(
                f"MONPNT1 {name}: COMP '{mon.comp}' must reference an AELIST-type AECOMP"
            )
        if mon.cp and mon.cp not in bulk.cord2rs:
            raise ValueError(f"MONPNT1 {name}: CP={mon.cp} not found in CORD2R")
    for name, mon in bulk.monpnt3s.items():
        if mon.comp not in bulk.aecomps:
            raise ValueError(f"MONPNT3 {name}: COMP '{mon.comp}' not found in AECOMP")
        if bulk.aecomps[mon.comp].listtype != "SET1":
            raise ValueError(
                f"MONPNT3 {name}: COMP '{mon.comp}' must reference a SET1-type AECOMP"
            )
        if mon.cp and mon.cp not in bulk.cord2rs:
            raise ValueError(f"MONPNT3 {name}: CP={mon.cp} not found in CORD2R")
    for name, cut in bulk.monsects.items():
        if cut.comp not in bulk.aecomps:
            raise ValueError(f"MONSECT {name}: COMP '{cut.comp}' not found in AECOMP")
        if cut.cid and cut.cid not in bulk.cord2rs:
            raise ValueError(f"MONSECT {name}: CID={cut.cid} not found in CORD2R")


def _check_trim(bulk: BulkData) -> set[str]:
    """TRIM and GUSTLF labels against AESTAT/AESURF, with DOF-count diagnostics.

    Returns the set of trim-variable labels the deck defines.
    """
    # Validate TRIM label cross-references and emit DOF-count diagnostics
    all_trim_labels = (
        {a.label for a in bulk.aestats.values()}
        | {s.label for s in bulk.aesurfs.values()}
    )
    if "RHOREF" in all_trim_labels:
        # RHOREF is reserved as the TRIM density pseudo-label (Step 61); an
        # AESTAT/AESURF of that name could never be prescribed on a TRIM card.
        raise ValueError(
            "AESTAT/AESURF label 'RHOREF' collides with the reserved TRIM "
            "density pseudo-label — rename the trim variable"
        )
    # A TRIM named by a GUSTLF has URDD3 supplied by that card (issue #1), so it
    # is prescribed for DOF-counting even though it is absent from TRIM.vars.
    # Without this the generated gust decks warn "over-determined" on every case.
    gust_trims: dict[int, int] = {}
    for gsid, gust in bulk.gustlfs.items():
        if gust.trimid not in bulk.trims:
            raise ValueError(
                f"GUSTLF {gsid}: TRIMID {gust.trimid} not found in any TRIM card"
            )
        trim = bulk.trims[gust.trimid]
        if "URDD3" in trim.vars:
            raise ValueError(
                f"GUSTLF {gsid}: TRIM {gust.trimid} also prescribes URDD3 — the gust "
                "card supplies it, so the TRIM must leave it free (two sources for "
                "one quantity; cf. DEF-M4)"
            )
        if "URDD3" not in all_trim_labels:
            raise ValueError(
                f"GUSTLF {gsid}: no AESTAT defines URDD3 — a gust load factor cannot "
                "be applied without it"
            )
        prior = gust_trims.get(gust.trimid)
        if prior is not None:
            raise ValueError(
                f"GUSTLF {gsid}: TRIM {gust.trimid} is already driven by GUSTLF {prior} "
                "— one gust case per TRIM"
            )
        gust_trims[gust.trimid] = gsid

    for sid, trim in bulk.trims.items():
        for lbl in trim.vars:
            if lbl not in all_trim_labels:
                raise ValueError(
                    f"TRIM {sid}: label '{lbl}' not defined in any AESTAT or AESURF card"
                )
        prescribed = set(trim.vars.keys())
        if sid in gust_trims:
            prescribed.add("URDD3")
        free = all_trim_labels - prescribed
        if len(free) == 0:
            warnings.warn(
                f"TRIM {sid}: all trim variables are prescribed — no DOFs remain to solve",
                UserWarning, stacklevel=4,
            )
        elif len(free) > len(prescribed):
            obj_sids = set(bulk.trimobjs.keys())
            if not obj_sids:
                warnings.warn(
                    f"TRIM {sid}: over-determined ({len(free)} free vs {len(prescribed)} "
                    "equations) but no TRIMOBJ card present — add TRIMOBJ to specify the "
                    "weighted objective",
                    UserWarning, stacklevel=4,
                )
    return all_trim_labels


def _check_maneuver_loads(bulk: BulkData, all_trim_labels: set[str]) -> None:
    """MLDCOMD/MLDTRIM/MLOADS references (Phase G0 transient maneuver loads)."""
    # Validate ZAERO transient maneuver-loads (Phase G0) cross-references
    for sid, mc in bulk.mldcomds.items():
        for label, tabid in mc.commands:
            if label not in all_trim_labels:
                raise ValueError(
                    f"MLDCOMD {sid}: command label '{label}' not defined in any "
                    "AESTAT or AESURF card"
                )
            if tabid not in bulk.tabled1s:
                raise ValueError(f"MLDCOMD {sid}: TABID {tabid} not found in TABLED1")
    for sid, mt in bulk.mldtrims.items():
        if mt.trim_sid not in bulk.trims:
            raise ValueError(f"MLDTRIM {sid}: TRIMID {mt.trim_sid} not found in TRIM")
    for sid, ml in bulk.mloads.items():
        if ml.mldtrim not in bulk.mldtrims:
            raise ValueError(f"MLOADS {sid}: MLDTRIM {ml.mldtrim} not found")
        if ml.mldtime not in bulk.mldtimes:
            raise ValueError(f"MLOADS {sid}: MLDTIME {ml.mldtime} not found")
        if ml.mldcomd and ml.mldcomd not in bulk.mldcomds:
            raise ValueError(f"MLOADS {sid}: MLDCOMD {ml.mldcomd} not found")
        if ml.mldprnt and ml.mldprnt not in bulk.mldprnts:
            raise ValueError(f"MLOADS {sid}: MLDPRNT {ml.mldprnt} not found")
        if ml.method > 0 and ml.method not in bulk.eigrls:
            raise ValueError(f"MLOADS {sid}: METHOD {ml.method} not found in EIGRL")
        # Step 63: under the free-flight modal solver the rigid-state labels
        # (ANGLEA/PITCH/URDD...) are outputs — only AESURF controls may be
        # commanded.  Deck-time mirror of the run_maneuver_modal check.
        if ml.selects_modal and ml.mldcomd:
            aesurf_labels = {s.label for s in bulk.aesurfs.values()}
            for label, _tabid in bulk.mldcomds[ml.mldcomd].commands:
                if label not in aesurf_labels:
                    raise ValueError(
                        f"MLOADS {sid}: MLDCOMD {ml.mldcomd} commands "
                        f"rigid-state label '{label}' — under the free-flight "
                        "modal solver (NMODES/METHOD/ZETA set) rigid states "
                        "are outputs; command AESURF controls only, or use "
                        "the direct solver (all-zeros MLOADS fields 7-9) for "
                        "prescribed-rigid studies"
                    )


def _check_massset(bulk: BulkData) -> None:
    """MASSSET CONM2 references; records the overlay-only CONM2 EIDs on ``bulk``."""
    # Validate MASSSET (Step 60) cross-references and mark overlay-only CONM2s.
    # An EID is either baseline (DELETE target / REPLACE old slot) or overlay
    # (ADD / REPLACE new slot) — never both, or the case mass is ill-defined.
    overlay_eids: set[int] = set()
    baseline_eids: dict[int, int] = {}   # eid -> MASSSET sid using it as a baseline EID
    for sid, ms in bulk.masssets.items():
        refs = (
            [(e, "ADD") for e in ms.add]
            + [(e, "DELETE") for e in ms.delete]
            + [(old, "REPLACE") for old, _ in ms.replace]
            + [(new, "REPLACE") for _, new in ms.replace]
        )
        for eid, op in refs:
            if eid not in bulk.conm2s:
                raise ValueError(
                    f"MASSSET {sid}: {op} references CONM2 EID {eid}, which is not "
                    "defined by any CONM2 card"
                )
        for eid in ms.add:
            overlay_eids.add(eid)
        for old, new in ms.replace:
            overlay_eids.add(new)
            baseline_eids.setdefault(old, sid)
        for eid in ms.delete:
            baseline_eids.setdefault(eid, sid)
    for eid in sorted(overlay_eids & set(baseline_eids)):
        raise ValueError(
            f"MASSSET: CONM2 EID {eid} is named as an overlay (ADD / REPLACE new slot) "
            f"and also as a baseline EID by MASSSET {baseline_eids[eid]} — an EID must "
            "be one or the other"
        )
    bulk.overlay_conm2_eids = overlay_eids
