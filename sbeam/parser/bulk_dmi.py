"""MSC's aero direct matrix input: DMIJ W2GJ and DMIK WKK (#104).

MSC has no W2GJ or WKK bulk card: it enters the static-aero corrections as matrices with
the reserved names W2GJ (a downwash column on the j-set) and WKK (a square weight matrix
on the k-set), on DMI or on the box-ID forms DMIJ / DMIK (AAUG 2023.1 PDF p.144; QRG
2024.1 PDF p.1617–1619 DMIJ, p.1623–1625 DMIK).  sbeam reads the DMIJ / DMIK forms and
maps them onto its native per-CAERO1 ``W2gj`` / ``Wkk`` data, which the solver already
uses.

Row and column grids are aero box IDs: a CAERO1's boxes are numbered from its EID,
consecutively (AAUG p.28), chordwise fastest — the native cards' order.  Component 3 is
a CAERO1 box's j-set DOF; components 3 and 5 are its k-set DOFs (QRG p.1618 / p.1624
remark 2).  DMI's row-number form is refused: it needs the order of the CAERO1 entries
in the j- and k-sets, which the manuals give only within one ACPT record (AAUG
p.134–136, Figures 3-7 and 3-8).

Everything sbeam cannot map exactly is refused (CLAUDE.md rule 7): other matrix names,
complex terms, a W2GJ with more than one column, a WKK term off the diagonal, a box
whose force and moment weights differ (sbeam's WKK is one weight per box), a term on a
DOF the set does not have (MSC drops it without a warning, remark 2), and a surface the
deck also corrects with a native card.
"""
from sbeam.model.aero import AeroMatrix, Caero1, W2gj, Wkk
from sbeam.model.bulk_data import BulkData
from sbeam.parser.bulk_fields import (
    ContHandler, FieldHandler, MultiHandler, to_float, to_int, to_int_opt,
)

#: The one matrix name each card may carry in sbeam, and the native card it maps onto.
_NAMES = {"DMIJ": "W2GJ", "DMIK": "WKK"}
#: A CAERO1 box's DOFs in each set (QRG 2024.1 PDF p.1618, p.1624, remark 2 tables).
_COMPONENTS = {"DMIJ": (3,), "DMIK": (3, 5)}


def _handle_matrix(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    card = fields[0]
    name = fields[1].strip().upper()
    if name != _NAMES[card]:
        raise ValueError(
            f"{card} {name}: sbeam reads {card} only for MSC's reserved name "
            f"{_NAMES[card]} (AAUG 2023.1 p.144). Other {card} matrices (AEDW, AEPRESS, "
            "AEFORCE inputs, FA2J, WTFACT) are not implemented and would be dropped")
    matrix = bulk.aero_matrices.setdefault(name, AeroMatrix(card=card, name=name))
    if fields[2].strip() == "0":
        _read_header(matrix, fields, conts)
    else:
        _read_column(matrix, fields, conts)


def _read_header(matrix: AeroMatrix, fields: list[str], conts: list[list[str]]) -> None:
    """``NAME "0" IFO TIN TOUT POLAR blank NCOL`` (QRG p.1617 / p.1623)."""
    where = f"{matrix.card} {matrix.name} header"
    if matrix.header is not None:
        raise ValueError(f"{where}: given twice (names are unique, remark 8)")
    if any(f.strip() for cont in conts for f in cont[1:]):
        raise ValueError(f"{where}: the header entry has no continuation")
    ifo, tin = to_int(fields[3]), to_int(fields[4])
    # TOUT (field 6) is the output precision only; sbeam computes in double whatever it is
    polar = to_int_opt(fields[6])
    if fields[7].strip():
        raise ValueError(f"{where}: field 8 ({fields[7].strip()!r}) must be blank")
    ncol = to_int(fields[8]) if fields[8].strip() else None
    if tin not in (1, 2):
        raise ValueError(
            f"{where}: TIN={tin}; sbeam reads real matrices only (TIN 1 or 2). "
            f"A complex {matrix.name} has no meaning in static aeroelasticity")
    if polar:
        raise ValueError(f"{where}: POLAR={polar} applies to complex terms only; leave it blank")
    matrix.header = (ifo, tin, ncol)


def _read_column(matrix: AeroMatrix, fields: list[str], conts: list[list[str]]) -> None:
    """``NAME GJ CJ blank G1 C1 A1 B1`` then ``G2 C2 A2 B2 …`` rows (QRG p.1617 / p.1623)."""
    gj, cj = to_int(fields[2]), to_int_opt(fields[3])
    where = f"{matrix.card} {matrix.name} column ({gj}, {cj})"
    if fields[4].strip():
        raise ValueError(f"{where}: field 5 ({fields[4].strip()!r}) must be blank")
    stream = list(fields[5:9]) + [f for cont in conts for f in cont[1:9]]
    for k in range(0, len(stream), 4):
        gi, ci, a, b = (s.strip() for s in stream[k:k + 4])
        if not (gi or ci or a or b):
            continue
        if not gi or not a:
            raise ValueError(f"{where}: term {k // 4 + 1} needs a row grid Gi and a value Ai")
        if b:
            raise ValueError(f"{where}: Bi must be blank for a real matrix (got {b!r})")
        key = (gj, cj, to_int(gi), to_int_opt(ci))
        if key in matrix.terms:
            raise ValueError(f"{where}: row ({key[2]}, {key[3]}) given twice (remark 3)")
        matrix.terms[key] = to_float(a)


def _box_ranges(bulk: BulkData) -> dict[int, tuple[int, int]]:
    """{CAERO1 EID: (first box ID, box count)}; box IDs run from the EID (AAUG p.28)."""
    def n_div(n: int, aefact_sid: int) -> int:
        return n if n > 0 else len(bulk.aefacts[aefact_sid].data) - 1

    def count(c: Caero1) -> int:
        return n_div(c.nspan, c.lspan) * n_div(c.nchord, c.lchord)

    return {eid: (eid, count(c)) for eid, c in sorted(bulk.caero1s.items())}


def _locate(box: int, ranges: dict[int, tuple[int, int]], where: str) -> tuple[int, int]:
    """(CAERO1 EID, local box index) of an aero box ID."""
    for eid, (first, n) in ranges.items():
        if first <= box < first + n:
            return eid, box - first
    raise ValueError(f"{where}: box {box} is not on any CAERO1 (box IDs run from each "
                     "CAERO1's EID, AAUG 2023.1 p.28)")


def map_aero_matrices(bulk: BulkData) -> None:
    """Map DMIJ W2GJ / DMIK WKK onto ``bulk.w2gjs`` / ``bulk.wkks`` (after cross-reference).

    Each surface gets one native entry with SID = its CAERO1 EID.  A term not entered is
    zero, as in MSC: a W2GJ surface with no terms has no downwash, and a WKK box with
    no terms has weight 0 — no lift.
    """
    ranges = _box_ranges(bulk)
    for name, matrix in sorted(bulk.aero_matrices.items()):
        where = f"{matrix.card} {name}"
        if matrix.header is None:
            raise ValueError(f"{where}: column entries but no header entry (remark 3)")
        native = bulk.w2gjs if name == "W2GJ" else bulk.wkks
        if native:
            raise ValueError(
                f"{where} and native {name} card(s) (SID {sorted(native)}) both given. MSC "
                f"takes one {name} matrix for the whole model; give either the {matrix.card} "
                f"matrix or the native {name} cards")
        for (_gj, _cj, gi, ci), value in matrix.terms.items():
            if value != 0.0 and ci not in _COMPONENTS[matrix.card]:
                raise ValueError(
                    f"{where}: term at box {gi} component {ci}; a CAERO1 box has component "
                    f"{' and '.join(map(str, _COMPONENTS[matrix.card]))} only in this set "
                    "(remark 2). MSC drops the term without a warning; sbeam refuses it")
        if name == "W2GJ":
            _map_w2gj(bulk, matrix, ranges, where)
        else:
            _map_wkk(bulk, matrix, ranges, where)


def _map_w2gj(bulk: BulkData, matrix: AeroMatrix, ranges: dict[int, tuple[int, int]],
              where: str) -> None:
    ifo, _tin, ncol = matrix.header or (0, 0, None)
    columns = {(gj, cj) for gj, cj, _gi, _ci in matrix.terms}
    if ifo not in (2, 9) or (ncol is not None and ncol != 1) or len(columns) > 1:
        raise ValueError(
            f"{where}: IFO={ifo}, NCOL={ncol}, {len(columns)} column(s). W2GJ is a single "
            "column (QRG p.1618 remark 1): give IFO 9 with NCOL 1, or IFO 2, and one column")
    data: dict[int, list[float]] = {}
    for (_gj, _cj, gi, ci), value in matrix.terms.items():
        if ci != 3:
            continue        # zero (checked above)
        eid, k = _locate(gi, ranges, where)
        data.setdefault(eid, [0.0] * ranges[eid][1])[k] = value
    for eid, values in sorted(data.items()):
        bulk.w2gjs[eid] = W2gj(sid=eid, caero_eid=eid, data=values)


def _map_wkk(bulk: BulkData, matrix: AeroMatrix, ranges: dict[int, tuple[int, int]],
             where: str) -> None:
    ifo = matrix.header[0] if matrix.header else 0
    if ifo not in (1, 6):
        raise ValueError(f"{where}: IFO={ifo}. WKK is a square matrix (AAUG 2023.1 p.144): "
                         "give IFO 1 (square) or 6 (symmetric)")
    strips = [eid for eid, c in bulk.caero1s.items() if c.pid in bulk.pstrips]
    if strips:
        raise ValueError(
            f"{where}: the model has PSTRIP strip panels (CAERO1 {sorted(strips)}). WKK "
            "scales the VLM operator only; correct strip panels with STRIPK")
    weight: dict[tuple[int, int], float] = {}
    for (gj, cj, gi, ci), value in matrix.terms.items():
        if (gj, cj) != (gi, ci):
            if value != 0.0:
                raise ValueError(
                    f"{where}: off-diagonal term, column ({gj}, {cj}) row ({gi}, {ci}). "
                    "sbeam's WKK is diagonal, one weight per box")
            continue
        weight[(gi, ci)] = value
    for gi, _ci in weight:
        _locate(gi, ranges, where)
    for eid, (first, n) in ranges.items():
        values: list[float] = []
        for box in range(first, first + n):
            force, moment = weight.get((box, 3), 0.0), weight.get((box, 5), 0.0)
            if force != moment:
                raise ValueError(
                    f"{where}: box {box} has force weight (component 3) {force} and moment "
                    f"weight (component 5) {moment}. sbeam applies one weight to a box's "
                    "force and moment; give both the same value (an omitted term is 0)")
            values.append(force)
        bulk.wkks[eid] = Wkk(sid=eid, caero_eid=eid, data=values)


FIELD_HANDLERS: dict[str, FieldHandler] = {}
CONT_HANDLERS: dict[str, ContHandler] = {}
MULTI_HANDLERS: dict[str, MultiHandler] = {"DMIJ": _handle_matrix, "DMIK": _handle_matrix}
