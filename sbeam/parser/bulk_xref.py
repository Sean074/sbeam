"""Bulk-data cross-reference checks, run once every card has been read (#48, #51).

Each check reads only resolved cards, so it is independent of card order in the deck.
``cross_reference`` runs them in a fixed order; the order decides only which error a deck
with several faults reports first.

The split with the card handlers is a rule: a handler checks only its own card's fields
and duplicates within its own card type; anything that looks at another card belongs
here.  A check in a handler sees only the cards above it in the deck (#51).
"""
import warnings
from dataclasses import asdict
from typing import Callable

from sbeam.model.aero import Monpnt3
from sbeam.model.bulk_data import BulkData
from sbeam.model.coordinate_system import Cord2r
from sbeam.types import FloatArray


def cross_reference(bulk: BulkData) -> None:
    """Check every cross-card reference in ``bulk``; raise ValueError on the first failure."""
    _check_frames(bulk)
    _check_line_elements(bulk)
    _check_rigid_elements(bulk)
    _check_properties(bulk)
    _check_mass_constraints_loads(bulk)
    _check_aero_panels(bulk)
    _check_aero_references(bulk)
    _check_load_combinations(bulk)
    _check_control_surfaces(bulk)
    _check_monitors(bulk)
    all_trim_labels = _check_trim(bulk)
    _check_maneuver_loads(bulk, all_trim_labels)
    _check_massset(bulk)
    _check_displacement_frames(bulk)


def check_frame_orientations(
    bulk: BulkData,
    get_transform: Callable[[int, dict[int, Cord2r]], tuple[FloatArray, FloatArray]],
) -> None:
    """Checks that need a resolved CORD2R chain, run after ``cross_reference``.

    ``get_transform`` is passed in by ``parse_bulk_data`` so the parser does not import the
    assembly layer here.

    AEROS ACSID (#58): sbeam takes the freestream along basic +x and never reads ACSID, so an
    ACSID whose axes are parallel to basic is equivalent to 0 (HA144A's CORD2R 1 is basic
    moved to x = 12.5). A rotated ACSID would put NASTRAN's flow elsewhere, so it is refused.
    """
    _check_cbush_axes(bulk)
    if bulk.aeros is None or not bulk.aeros.acsid:
        return
    acsid = bulk.aeros.acsid
    _origin, rot = get_transform(acsid, bulk.cord2rs)
    deviation = max(abs(float(rot[i, j]) - (1.0 if i == j else 0.0))
                    for i in range(3) for j in range(3))
    if deviation > 1e-6:
        raise ValueError(
            f"AEROS ACSID={acsid}: CORD2R {acsid} is rotated relative to basic; sbeam takes "
            f"the freestream along basic +x and does not rotate the aero model into ACSID. "
            f"Orient the model so the flow is along basic +x (CAERO1 CP can still place "
            f"panels in any frame), or use an ACSID with axes parallel to basic"
        )


def _check_cbush_axes(bulk: BulkData) -> None:
    """A CBUSH must define its element axes the way NASTRAN requires (#62).

    MSC Nastran 2024.1 QRG PDF p.1379.  Remark 6: "If the distance between GA and GB is
    less than .0001, or if GB is blank, then CID must be specified."  Remark 5: with no
    CID and no orientation the line GA-GB is the element x-axis, which "is valid only
    when K1 ... or K4 ... or both on the PBUSH entry are specified"; any of K2, K3, K5,
    K6 is fatal.  sbeam used to pick basic y or z for the missing axes.  Grid positions
    are resolved before this runs.
    """
    for eid, bush in bulk.cbushs.items():
        if bush.cid is not None:
            continue
        ga = bulk.grids[bush.ga]
        gb = bulk.grids[bush.gb] if bush.gb is not None else None
        if gb is None:
            raise ValueError(
                f"CBUSH {eid}: GB is blank (a grounded spring), so CID must be specified "
                "in field 9 (QRG p.1379 remark 6); CID 0 puts K1-K6 along the basic axes")
        dist = ((gb.x - ga.x) ** 2 + (gb.y - ga.y) ** 2 + (gb.z - ga.z) ** 2) ** 0.5
        if dist < 1.0e-4:
            raise ValueError(
                f"CBUSH {eid}: GA and GB are {dist:g} apart (less than .0001), so CID must "
                "be specified in field 9 (QRG p.1379 remark 6)")
        if bush.x1 == bush.x2 == bush.x3 == 0.0:
            pbush = bulk.pbushs[bush.pid]
            lateral = [f"K{k}" for k in (2, 3, 5, 6) if getattr(pbush, f"k{k}") != 0.0]
            if lateral:
                raise ValueError(
                    f"CBUSH {eid}: no orientation vector and no CID, so only the line "
                    f"GA-GB is defined, but PBUSH {bush.pid} has {', '.join(lateral)}. Give "
                    "X1, X2, X3 in fields 6-8 or a CID (QRG p.1379 remark 5)")


def _check_frame(card: str, ident: object, field: str, cid: int, bulk: BulkData) -> None:
    """A non-zero CID must name a CORD2R (sbeam has no CORD1x/2C/2S and no negative CIDs)."""
    if cid and cid not in bulk.cord2rs:
        raise ValueError(f"{card} {ident}: {field}={cid} not found in CORD2R")


def _check_grid(card: str, ident: object, field: str, gid: int, bulk: BulkData) -> None:
    if gid not in bulk.grids:
        raise ValueError(f"{card} {ident}: grid {field}={gid} not found")


# Structural references.  Before #51 the element checks ran inside the handlers, so a
# CBAR above its PBAR failed; the frame, mass, constraint and load references were not
# checked at all, and a FORCE or CONM2 on a missing grid was dropped from the solve.

def _check_frames(bulk: BulkData) -> None:
    """CORD2R RID and GRID CD frames."""
    for cid, cord in bulk.cord2rs.items():
        _check_frame("CORD2R", cid, "RID", cord.rid, bulk)
    for gid, grid in bulk.grids.items():
        # CP is resolved (and checked) by resolve_grid_positions after this pass
        _check_frame("GRID", gid, "CD", grid.cd, bulk)


def _frame_free(components: str) -> bool:
    """True when a component set means the same in every rectangular frame.

    A whole triad does: T1-T3 together span all translations and R1-R3 all rotations,
    whatever the axes.  A partial triad (``1``, ``35``, ``1245`` ...) names directions.
    """
    digits = set(components)
    return (digits & set("123") in (set(), set("123"))
            and digits & set("456") in (set(), set("456")))


def _check_displacement_frames(bulk: BulkData) -> None:
    """Refuse a GRID CD that would change the answer (#65).

    MSC: CD is the "coordinate system in which the displacements, degrees-of-freedom,
    constraints, and solution vectors are defined at the grid point" (MSC Nastran
    2024.1 QRG PDF p.1944), and a CBAR or CBUSH orientation vector is "in the
    displacement coordinate system at GA" (p.1360, p.1378).  sbeam solves every grid in
    basic and uses CD only to rotate the printed displacements, eigenvectors and SPC
    forces.  That is the whole of NASTRAN's meaning for a grid that nothing addresses
    by component number or orients from.  Where a card does, sbeam would apply it along
    the basic axes instead, so the deck is refused naming the card.
    """
    rotated = {gid: g.cd for gid, g in bulk.grids.items() if g.cd}
    if not rotated:
        return

    def _refuse(gid: int, what: str) -> None:
        raise ValueError(
            f"GRID {gid}: CD={rotated[gid]} is used only to print results in that frame, "
            f"but {what}. NASTRAN would take this in the CD frame (QRG p.1944) and sbeam "
            "takes it in basic, so the two would solve different models. Remove the CD, "
            "or state the card in basic terms on a grid without one.")

    def _components(gid: int, card: str, comps: str) -> None:
        if gid in rotated and comps and not _frame_free(comps):
            _refuse(gid, f"{card} names components {comps} at it")

    for gid in rotated:
        _components(gid, "its own PS field", bulk.grids[gid].ps)
    for sid, spcs in bulk.spcs.items():
        for spc in spcs:
            _components(spc.g1, f"SPC {sid}", spc.c1)
            if spc.g2 is not None:
                _components(spc.g2, f"SPC {sid}", spc.c2 or "")
    for sid, spc1s in bulk.spc1s.items():
        for spc1 in spc1s:
            for gid in spc1.grids:
                _components(gid, f"SPC1 {sid}", spc1.c)
    for sup in bulk.supports:
        _components(sup.gid, "SUPORT", sup.dofs)
    for eid, rbe2 in bulk.rbe2s.items():
        for gid in [rbe2.gn, *rbe2.gm]:
            _components(gid, f"RBE2 {eid}", rbe2.cm)
    for eid, rbar in bulk.rbars.items():
        for gid in (rbar.ga, rbar.gb):
            _components(gid, f"RBAR {eid}", rbar.cna)
            _components(gid, f"RBAR {eid}", rbar.cnb)
    for eid, rbe3 in bulk.rbe3s.items():
        _components(rbe3.refgrid, f"RBE3 {eid}", rbe3.refc)
        for _wt, comps, grids in rbe3.wt_gc:
            for gid in [rbe3.refgrid, *grids]:
                _components(gid, f"RBE3 {eid}", comps)
    for eid, bar in bulk.cbars.items():
        # OFFT B..: the vector is in basic, which is what sbeam uses (QRG p.1363)
        if bar.ga in rotated and bar.offt.startswith("G"):
            _refuse(bar.ga, f"CBAR {eid} takes its orientation vector at this grid (GA, "
                            f"OFFT={bar.offt})")
    for eid, bush in bulk.cbushs.items():
        for gid in (bush.ga, bush.gb):
            if gid in rotated:
                _refuse(gid, f"CBUSH {eid} takes its spring axes at this grid")


def _check_line_elements(bulk: BulkData) -> None:
    """CBAR, CROD, CONROD and CBUSH grids and properties."""
    for eid, bar in bulk.cbars.items():
        _check_grid("CBAR", eid, "GA", bar.ga, bulk)
        _check_grid("CBAR", eid, "GB", bar.gb, bulk)
        if bar.pid not in bulk.pbars:
            raise ValueError(f"CBAR {eid}: property PID={bar.pid} not found")
    for eid, rod in bulk.crods.items():
        _check_grid("CROD", eid, "GA", rod.ga, bulk)
        _check_grid("CROD", eid, "GB", rod.gb, bulk)
        if rod.pid not in bulk.prods:
            raise ValueError(f"CROD {eid}: property PID={rod.pid} not found (PROD)")
        if bulk.prods[rod.pid].mid not in bulk.mat1s:
            raise ValueError(f"CROD {eid}: PROD {rod.pid} material MID={bulk.prods[rod.pid].mid} not found")
    for eid, conrod in bulk.conrods.items():
        _check_grid("CONROD", eid, "GA", conrod.ga, bulk)
        _check_grid("CONROD", eid, "GB", conrod.gb, bulk)
        if conrod.mid not in bulk.mat1s:
            raise ValueError(f"CONROD {eid}: material MID={conrod.mid} not found")
    for eid, bush in bulk.cbushs.items():
        _check_grid("CBUSH", eid, "GA", bush.ga, bulk)
        if bush.gb is not None:
            _check_grid("CBUSH", eid, "GB", bush.gb, bulk)
        if bush.pid not in bulk.pbushs:
            raise ValueError(f"CBUSH {eid}: property PID={bush.pid} not found")
        if bush.cid is not None:
            _check_frame("CBUSH", eid, "CID", bush.cid, bulk)


def _check_rigid_elements(bulk: BulkData) -> None:
    """PLOTEL, RBE2, RBAR and RBE3 grids."""
    for eid, plotel in bulk.plotels.items():
        _check_grid("PLOTEL", eid, "G1", plotel.g1, bulk)
        _check_grid("PLOTEL", eid, "G2", plotel.g2, bulk)
    for eid, rbe2 in bulk.rbe2s.items():
        if rbe2.gn not in bulk.grids:
            raise ValueError(f"RBE2 {eid}: independent grid GN={rbe2.gn} not found")
        for dep_gid in rbe2.gm:
            if dep_gid not in bulk.grids:
                raise ValueError(f"RBE2 {eid}: dependent grid GM={dep_gid} not found")
    for eid, rbar in bulk.rbars.items():
        _check_grid("RBAR", eid, "GA", rbar.ga, bulk)
        _check_grid("RBAR", eid, "GB", rbar.gb, bulk)
    for eid, rbe3 in bulk.rbe3s.items():
        _check_grid("RBE3", eid, "REFGRID", rbe3.refgrid, bulk)
        for _wt, _c, grids in rbe3.wt_gc:
            for gid in grids:
                _check_grid("RBE3", eid, "Gi", gid, bulk)


def _check_properties(bulk: BulkData) -> None:
    """PBAR and PROD materials, including unused properties.  Runs after the elements,
    so a property an element uses keeps the element-specific message."""
    for pid, pbar in bulk.pbars.items():
        if pbar.mid not in bulk.mat1s:
            raise ValueError(f"PBAR {pid}: material MID={pbar.mid} not found")
    for pid, prod in bulk.prods.items():
        if prod.mid not in bulk.mat1s:
            raise ValueError(f"PROD {pid}: material MID={prod.mid} not found")


def _check_mass_constraints_loads(bulk: BulkData) -> None:
    """CONM2, SPC/SPC1/SUPORT and FORCE/MOMENT grids and frames."""
    for eid, conm2 in bulk.conm2s.items():
        _check_grid("CONM2", eid, "GID", conm2.gid, bulk)
        _check_frame("CONM2", eid, "CID", conm2.cid, bulk)
    for sid, spcs in bulk.spcs.items():
        for spc in spcs:
            _check_grid("SPC", sid, "G1", spc.g1, bulk)
            if spc.g2 is not None:
                _check_grid("SPC", sid, "G2", spc.g2, bulk)
    for sid, spc1s in bulk.spc1s.items():
        for spc1 in spc1s:
            for gid in spc1.grids:
                _check_grid("SPC1", sid, "Gi", gid, bulk)
    for sup in bulk.supports:
        if sup.gid not in bulk.grids:
            raise ValueError(f"SUPORT: grid GID={sup.gid} not found")
    for card, sets in (("FORCE", bulk.forces), ("MOMENT", bulk.moments)):
        for sid, loads in sets.items():
            for load in loads:
                _check_grid(card, sid, "GID", load.gid, bulk)
                _check_frame(card, sid, "CID", load.cid, bulk)


def _check_aero_panels(bulk: BulkData) -> None:
    """AEROS presence, CAERO1 property/division refs, STRIPK targets, SPLINE2 and SET1."""
    # CAERO1 cards require an AEROS card to provide reference geometry
    if bulk.caero1s and bulk.aeros is None:
        raise ValueError("CAERO1 card(s) present but no AEROS card found")

    # "aerodynamic elements with different IGIDs are uncoupled" (MSC Nastran 2024.1 QRG
    # PDF p.1343).  sbeam builds one AIC over every panel, so two groups would still
    # interfere; it parsed IGID and never read it (#76)
    groups: dict[int, list[int]] = {}
    for eid, caero in bulk.caero1s.items():
        groups.setdefault(caero.igid, []).append(eid)
    if len(groups) > 1:
        listing = "; ".join(f"IGID {g}: CAERO1 {', '.join(str(e) for e in sorted(eids))}"
                            for g, eids in sorted(groups.items()))
        raise ValueError(
            f"CAERO1 cards use {len(groups)} interference groups ({listing}). NASTRAN "
            "uncouples panels in different groups (QRG p.1343); sbeam couples every panel "
            "with every other. Give all panels the same IGID")

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

    # A PSTRIP and a PAERO1 may not share a PID (was checked by PSTRIP only, #51)
    for pid in sorted(set(bulk.pstrips) & set(bulk.paero1s)):
        raise ValueError(f"PSTRIP PID {pid} collides with a PAERO1 of the same PID")


def _check_aero_references(bulk: BulkData) -> None:
    """Aero frames and the CAERO1 / GRID targets of splines and per-panel cards (#51)."""
    if bulk.aeros is not None:
        _check_frame("AEROS", "card", "ACSID", bulk.aeros.acsid, bulk)
        _check_frame("AEROS", "card", "RCSID", bulk.aeros.rcsid, bulk)
    for eid, caero in bulk.caero1s.items():
        _check_frame("CAERO1", eid, "CP", caero.cp, bulk)
    for eid, sp in bulk.spline2s.items():
        _check_frame("SPLINE2", eid, "CID", sp.cid, bulk)
    for eid, sp0 in bulk.spline0s.items():
        if sp0.caero not in bulk.caero1s:
            raise ValueError(f"SPLINE0 {eid}: CAERO={sp0.caero} not found in CAERO1")
        if sp0.grid:   # 0 = the SUPORT grid
            _check_grid("SPLINE0", eid, "GRID", sp0.grid, bulk)
    for eid, att in bulk.attaches.items():
        if att.caero not in bulk.caero1s:
            raise ValueError(f"ATTACH {eid}: CAERO={att.caero} not found in CAERO1")
        _check_grid("ATTACH", eid, "GRID", att.grid, bulk)
        _check_frame("ATTACH", eid, "CID", att.cid, bulk)
    # Per-panel cards are applied by matching CAERO1 EID; an unknown EID was dropped
    for card, coll in (("W2GJ", bulk.w2gjs), ("WKK", bulk.wkks),
                       ("AECORR", bulk.aecorrs), ("CHORDCP", bulk.chordcps)):
        for sid, entry in coll.items():
            if entry.caero_eid not in bulk.caero1s:
                raise ValueError(f"{card} {sid}: CAERO1 {entry.caero_eid} not found")


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
    # "the SID on a GRAV entry may not be the same as that on a simple load entry" (MSC
    # Nastran 2024.1 QRG PDF p.1941, GRAV remark 3); sbeam summed the two (#68)
    for sid in bulk.gravs:
        for card, sets in (("FORCE", bulk.forces), ("MOMENT", bulk.moments)):
            if sid in sets:
                raise ValueError(
                    f"GRAV {sid}: a {card} card has the same SID. Gravity is combined with "
                    "FORCE and MOMENT loads only through a LOAD card (QRG p.1941 remark 3): "
                    "give the GRAV its own SID and name both on a LOAD")


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
    # Monitor names are unique across all monitor cards (#51: MONSECT checked only
    # names above it, and MONPNT1 against MONPNT3 was not checked at all)
    for name in sorted(set(bulk.monpnt1s) & set(bulk.monpnt3s)):
        raise ValueError(
            f"MONPNT3 {name}: NAME collides with an existing MONPNT1 — "
            "monitor names must be unique across all monitor cards"
        )
    for name in sorted(set(bulk.monsects) & (set(bulk.monpnt1s) | set(bulk.monpnt3s))):
        raise ValueError(
            f"MONSECT {name}: NAME collides with an existing MONPNT1/MONPNT3 — "
            "monitor names must be unique across all monitor cards"
        )
    # Validate AECOMP list references and MONPNT1/MONPNT3 cross-references
    for name, aecomp in bulk.aecomps.items():
        target = bulk.aelists if aecomp.listtype == "AELIST" else bulk.set1s
        for lid in aecomp.list_ids:
            if lid not in target:
                raise ValueError(
                    f"AECOMP {name}: {aecomp.listtype} SID {lid} not found"
                )
    # MSC: one MONPNT1 card, aerodynamic or structural by its COMP (QRG 2024.1 PDF
    # p.2303 remark 2; #86).  A SET1-type AECOMP files it with the structural
    # integrator (``bulk.monpnt3s``, named after sbeam's pre-#86 card)
    for name, mon in list(bulk.monpnt1s.items()):
        if mon.comp not in bulk.aecomps:
            raise ValueError(f"MONPNT1 {name}: COMP '{mon.comp}' not found in AECOMP "
                             "(AECOMPL is not supported)")
        if mon.cp and mon.cp not in bulk.cord2rs:
            raise ValueError(f"MONPNT1 {name}: CP={mon.cp} not found in CORD2R")
        if bulk.aecomps[mon.comp].listtype == "SET1":
            del bulk.monpnt1s[name]
            bulk.monpnt3s[name] = Monpnt3(**asdict(mon))
    for name, cut in bulk.monsects.items():
        if cut.comp not in bulk.aecomps:
            raise ValueError(f"MONSECT {name}: COMP '{cut.comp}' not found in AECOMP")
        if cut.cid and cut.cid not in bulk.cord2rs:
            raise ValueError(f"MONSECT {name}: CID={cut.cid} not found in CORD2R")


def _check_trim_optimisation(bulk: BulkData, all_trim_labels: set[str]) -> None:
    """TRIMVAR / TRIMOBJ / TRIMCON labels and sets (#77).

    The solver used to skip any of these whose label was not a trim variable, so a
    misspelt label, or the card reference's own ``CL`` / ``CM`` examples, dropped the
    bound, weight or constraint without a message.
    """
    def _known(card: str, label: str) -> None:
        if label not in all_trim_labels:
            raise ValueError(
                f"{card}: label '{label}' not defined in any AESTAT or AESURF card")

    bounded: dict[str, int] = {}
    for vid, tv in bulk.trimvars.items():
        _known(f"TRIMVAR {vid}", tv.label)
        if tv.label in bounded:
            raise ValueError(
                f"TRIMVAR {vid}: label '{tv.label}' already has bounds on TRIMVAR "
                f"{bounded[tv.label]}")
        bounded[tv.label] = vid
    for sid, obj in bulk.trimobjs.items():
        for label in obj.labels:
            _known(f"TRIMOBJ {sid}", label)
    for sid, cons in bulk.trimcons.items():
        for con in cons:
            _known(f"TRIMCON {sid}", con.label)
    if len(bulk.trimcons) > 1:
        # No command selects a TRIMCON set, so every card was applied to every
        # over-determined trim whatever its SID.  One set per deck is what is acted on.
        raise ValueError(
            f"TRIMCON cards use {len(bulk.trimcons)} different SIDs "
            f"({', '.join(str(s) for s in sorted(bulk.trimcons))}): sbeam has no command "
            "that selects a TRIMCON set, so all TRIMCON cards must share one SID")


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
    _check_trim_optimisation(bulk, all_trim_labels)
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
    """MASSCASE CONM2 references; records the overlay-only CONM2 EIDs on ``bulk``."""
    # Validate MASSCASE (Step 60) cross-references and mark overlay-only CONM2s.
    # An EID is either baseline (DELETE target / REPLACE old slot) or overlay
    # (ADD / REPLACE new slot) — never both, or the case mass is ill-defined.
    overlay_eids: set[int] = set()
    baseline_eids: dict[int, int] = {}   # eid -> MASSCASE sid using it as a baseline EID
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
                    f"MASSCASE {sid}: {op} references CONM2 EID {eid}, which is not "
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
            f"MASSCASE: CONM2 EID {eid} is named as an overlay (ADD / REPLACE new slot) "
            f"and also as a baseline EID by MASSCASE {baseline_eids[eid]} — an EID must "
            "be one or the other"
        )
    bulk.overlay_conm2_eids = overlay_eids
