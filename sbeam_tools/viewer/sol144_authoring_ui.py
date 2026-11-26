"""Aeroelastic Authoring tab — SOL 144 / MANVR bulk-card editors (P12).

Each card family gets a top-level expander holding a selectbox ("— new —" or
an existing ID, outside the form) and one ``st.form`` with the family's fields.
Applying builds the dataclass and hands it to ``session_deck.commit``, which
writes it into the deck text and re-parses the deck (#113).  A form field's key
carries the card being edited (``_k``, #123).  ``st.session_state.authored_cards``
tracks what this session created, which is the card set the export writes after
the loaded deck's own bulk section.  What a maneuver case *is* (trim recipes,
command shapes, the two-pass builder) lives in ``sbeam_tools.cases.maneuver``
(#114); this module holds its widgets.
"""

import dataclasses
from typing import Any, Callable, Optional, cast

import pandas as pd
import streamlit as st
from sbeam_tools.viewer.widget_keys import wk

from sbeam.model.aero import (
    Aestat, Aesurf, Aelist, Trim, Diverg, Trimvar, Trimobj, Trimcon,
)
from sbeam.model.bulk_data import BulkData
from sbeam.model.constraint import Suport
from sbeam.model.maneuver import (
    Tabled1, Mldtime, Mldcomd, Mldprnt, Mldtrim, Mloads,
)
from sbeam.model.card_writers import write_authored_block
from sbeam.model.gust import Gustlf
from sbeam_tools.cases import gust, maneuver
from sbeam_tools.common.deck import airplane_from_model
from sbeam_tools.viewer import session_deck
from sbeam_tools.viewer import sol144_authoring as logic
from sbeam.parser.case_control import CaseControl
from sbeam_tools.viewer.case_control_ui import deck_bulk_section, export_bdf_text
from sbeam_tools.common.units import UNIT_SYSTEMS


def export_sol144_bdf(cc: CaseControl, bulk: BulkData,
                      authored: dict[str, set[int]],
                      include_paths: Optional[list[str]] = None,
                      title_comment: str = "",
                      bulk_section: Optional[str] = None) -> str:
    """Full driver deck: provenance header + case control + authored cards
    inline + every INCLUDE.  Pure — reused by the export tests."""
    header = logic.AUTHORED_HEADER
    if title_comment:
        header += f"\n{title_comment}"
    block = write_authored_block(bulk, authored, header)
    return export_bdf_text(cc, include_paths=include_paths,
                           authored_block=block, bulk_section=bulk_section)


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------

_NEW = "— new —"


def _authored() -> dict[str, set[int]]:
    return st.session_state.setdefault("authored_cards", {})


def _family_ids(bulk: BulkData, family: str) -> list[int]:
    store = logic.family_store(bulk, family)
    if family == "suport":
        return sorted(s.gid for s in store)
    return sorted(store.keys())


_EDIT_SUFFIX = "_auth_edit_suffix"


def _k(key: str) -> str:
    """The widget key of a card-form field, distinct for each card being edited.

    Streamlit identifies a keyed widget by its key alone: a new ``value=`` default
    is ignored once the key holds a value.  With one fixed key per field, choosing
    another card under "Edit existing" left the form showing the previous values,
    and Apply wrote those over the chosen card (#123).  The key therefore carries
    the selection (``auth_trim_q`` for a new card, ``auth_trim_q@7`` for TRIM 7),
    so each card gets its own widgets, initialised from that card.
    """
    return wk(key) + st.session_state.get(_EDIT_SUFFIX, "")


def _same_card(card: Any, existing: Any) -> bool:
    """True when the form rebuilt exactly the card it was opened on."""
    try:
        return bool(card == existing)
    except ValueError:          # an array-valued field: not comparable, treat as edited
        return False


def _family_editor(
    bulk: BulkData,
    family: str,
    title: str,
    render_form: Callable[[BulkData, Optional[Any], int], Optional[Any]],
) -> None:
    """Selector + form + apply/delete skeleton shared by every card family.

    ``render_form(bulk, existing_card, default_id)`` renders the family's
    widgets (inside the form) and returns the built card — or None when the
    inputs are incomplete (it should st.warning the reason).
    """
    with st.expander(title, expanded=False):
        ids = _family_ids(bulk, family)
        sel = st.selectbox(
            "Edit existing or create new", [_NEW] + ids,
            key=wk(f"auth_sel_{family}"),
        )
        editing = sel != _NEW
        existing = None
        if editing:
            store = logic.family_store(bulk, family)
            if family == "suport":
                existing = next(s for s in store if s.gid == sel)
            else:
                existing = store[sel]
        default_id = cast(int, sel) if editing else logic.next_free_sid(bulk, family)

        with st.form(f"auth_form_{family}"):
            st.session_state[_EDIT_SUFFIX] = f"@{sel}" if editing else ""
            try:
                card = render_form(bulk, existing, default_id)
            finally:
                st.session_state[_EDIT_SUFFIX] = ""
            col_apply, col_new = st.columns([1, 2])
            applied = col_apply.form_submit_button("Apply", type="primary")
            save_new = False
            if editing and sel not in _authored().get(family, set()):
                save_new = col_new.form_submit_button(
                    "Save as new SID",
                    help="This card comes from the loaded deck and is not "
                         "changed in place: the deck would hold two cards "
                         "with its ID.  Saving as a new SID adds your edit "
                         "as a new card.",
                )

        # A loaded card submitted unchanged is not an edit: it stays the file's card
        # (#123).  Any other Apply goes through the deck text and the parser (#113).
        unchanged = (applied and not save_new and editing and card is not None
                     and _same_card(card, existing))
        if unchanged:
            st.info("No change.")
        elif (applied or save_new) and card is not None:
            if save_new:
                new_key = logic.next_free_sid(bulk, family)
                for one in (card if isinstance(card, list) else [card]):
                    setattr(one, logic.key_attr(family, one), new_key)
            key = logic.card_key(family, card[0] if isinstance(card, list) else card)
            session_deck.commit(
                bulk, changes=[(family, card)],
                done=f"{logic.CARD_NAMES[family]} {key} applied to the deck.")

        if editing and sel in _authored().get(family, set()):
            if st.button("Delete", key=wk(f"auth_del_{family}")):
                session_deck.commit(
                    bulk, deletes=[(family, cast(int, sel))],
                    done=f"{logic.CARD_NAMES[family]} {sel} deleted.")


def _pairs_editor(key: str, columns: dict[str, Any],
                  rows: list[dict[str, Any]]) -> pd.DataFrame:
    """A dynamic-row data editor (allowed inside forms; commits on submit)."""
    df = pd.DataFrame(rows, columns=pd.Index(list(columns)))
    return st.data_editor(
        df, key=_k(key), num_rows="dynamic", column_config=columns,
        use_container_width=True, hide_index=True,
    )


# ---------------------------------------------------------------------------
# Panel 1 — Control surfaces & states
# ---------------------------------------------------------------------------

def _aestat_form(bulk: BulkData, card: Optional[Aestat], default_id: int):
    aid = st.number_input("ID", min_value=1, value=(card.id if card else default_id),
                          key=_k("auth_aestat_id"))
    label = st.selectbox(
        "Label", logic.AESTAT_LABELS,
        index=(logic.AESTAT_LABELS.index(card.label)
               if card and card.label in logic.AESTAT_LABELS else 0),
        key=_k("auth_aestat_label"),
        help="Canonical rigid-body trim-variable labels.",
    )
    return Aestat(id=int(aid), label=label)


def _aesurf_form(bulk: BulkData, card: Optional[Aesurf], default_id: int):
    aid = st.number_input("ID", min_value=1, value=(card.id if card else default_id),
                          key=_k("auth_aesurf_id"))
    label = st.text_input("Label", value=(card.label if card else ""),
                          key=_k("auth_aesurf_label")).strip().upper()
    cids = [0] + sorted(bulk.cord2rs.keys())
    alids = sorted(bulk.aelists.keys())
    col1, col2 = st.columns(2)
    cid1 = col1.selectbox(
        "Hinge CID (CID1)", cids,
        index=cids.index(card.cid1) if card and card.cid1 in cids else 0,
        key=_k("auth_aesurf_cid1"),
        help="The CID's y-axis is the hinge line.",
    )
    alid1 = col2.selectbox(
        "Box list (ALID1, an AELIST SID)", alids,
        index=alids.index(card.alid1) if card and card.alid1 in alids else 0,
        key=_k("auth_aesurf_alid1"),
    ) if alids else None
    # Second hinge half (#9): an antisymmetric aileron pair is ONE label with
    # CID1 = starboard half, CID2 = port half, both hinge +y pointing outboard.
    col3, col4 = st.columns(2)
    cid2 = col3.selectbox(
        "Second hinge CID (CID2, 0 = none)", cids,
        index=cids.index(card.cid2) if card and card.cid2 in cids else 0,
        key=_k("auth_aesurf_cid2"),
        help="Port half of an aileron pair: its own CORD2R with +y outboard (charter §6).",
    )
    alid2_opts = [0] + alids
    alid2 = col4.selectbox(
        "Second box list (ALID2, 0 = none)", alid2_opts,
        index=alid2_opts.index(card.alid2) if card and card.alid2 in alid2_opts else 0,
        key=_k("auth_aesurf_alid2"),
    )
    eff = st.number_input("Effectiveness (EFF)", value=(card.eff if card else 1.0),
                          key=_k("auth_aesurf_eff"))
    if not label:
        st.warning("AESURF needs a label.")
        return None
    if alid1 is None:
        st.warning("Define an AELIST first — AESURF needs a box list.")
        return None
    if bool(cid2) != bool(alid2):
        st.warning("CID2 and ALID2 go together — give both or neither.")
        return None
    return Aesurf(id=int(aid), label=label, cid1=int(cid1), alid1=int(alid1),
                  cid2=int(cid2), alid2=int(alid2), eff=float(eff))


def _aelist_form(bulk: BulkData, card: Optional[Aelist], default_id: int):
    sid = st.number_input("SID", min_value=1, value=(card.sid if card else default_id),
                          key=_k("auth_aelist_sid"))
    ranges = logic.caero_box_ranges(bulk)
    if ranges:
        st.caption("Valid box IDs: " +
                   ", ".join(f"{lo}–{hi}" for lo, hi in ranges))
    default_text = " ".join(str(e) for e in card.elements) if card else ""
    text = st.text_input("Box IDs (THRU allowed, e.g. '1101 THRU 1112')",
                         value=default_text, key=_k("auth_aelist_boxes"))
    try:
        elements = logic.expand_int_tokens(text)
    except ValueError:
        st.warning("Box list is not a valid integer/THRU list.")
        return None
    if not elements:
        st.warning("AELIST needs at least one box ID.")
        return None
    outside = logic.boxes_outside_ranges(elements, ranges)
    if outside:
        st.warning(f"Boxes outside every CAERO1 range: {outside}")
        return None
    return Aelist(sid=int(sid), elements=elements)


def _suport_form(bulk: BulkData, card: Optional[Suport], default_id: int):
    gids = sorted(bulk.grids.keys())
    gid = st.selectbox(
        "Grid (GID)", gids,
        index=gids.index(card.gid) if card and card.gid in gids else 0,
        key=_k("auth_suport_gid"),
    ) if gids else None
    dofs = st.text_input("DOF components (e.g. '35' = Tz + Ry)",
                         value=(card.dofs if card else "35"),
                         key=_k("auth_suport_dofs")).strip()
    if gid is None or not dofs or not dofs.isdigit():
        st.warning("SUPORT needs a grid and a digit-string DOF list.")
        return None
    return Suport(gid=int(gid), dofs=dofs)


# ---------------------------------------------------------------------------
# Panel 2 — Trim conditions
# ---------------------------------------------------------------------------

def _trim_form(bulk: BulkData, card: Optional[Trim], default_id: int):
    col1, col2, col3 = st.columns(3)
    sid = col1.number_input("SID", min_value=1,
                            value=(card.sid if card else default_id),
                            key=_k("auth_trim_sid"))
    mach = col2.number_input("Mach", value=(card.mach if card else 0.0),
                             key=_k("auth_trim_mach"), format="%.4f")
    q = col3.number_input("Dynamic pressure Q", value=(card.q if card else 0.0),
                          key=_k("auth_trim_q"), format="%.6g")
    labels = logic.label_options(bulk)
    prefill: Optional[dict[str, float]] = st.session_state.get("auth_trim_prefill")
    if card is not None:
        rows = [{"label": k, "value": v} for k, v in card.vars.items()]
    elif prefill:
        rows = [{"label": k, "value": v} for k, v in prefill.items()]
    else:
        rows = [{"label": labels[0] if labels else "", "value": 0.0}]
    # The editor key is versioned so a preset pre-fill replaces the persisted
    # editor state instead of being ignored by it.
    ver = st.session_state.get("auth_trim_vars_ver", 0)
    df = _pairs_editor(
        f"auth_trim_vars_{ver}",
        {"label": st.column_config.SelectboxColumn("Label", options=labels),
         "value": st.column_config.NumberColumn("Prescribed value", format="%.6g")},
        rows,
    )
    vars_: dict[str, float] = {}
    for _, row in df.iterrows():
        label = row["label"]
        if isinstance(label, str) and label.strip():
            vars_[label.strip().upper()] = float(row["value"] or 0.0)
    if not labels:
        st.warning("Define AESTAT/AESURF labels first.")
        return None
    return Trim(sid=int(sid), mach=float(mach), q=float(q), vars=vars_)


def _trimvar_form(bulk: BulkData, card: Optional[Trimvar], default_id: int):
    labels = logic.label_options(bulk)
    col1, col2 = st.columns(2)
    vid = col1.number_input("ID", min_value=1,
                            value=(card.id if card else default_id),
                            key=_k("auth_trimvar_id"))
    label = col2.selectbox(
        "Label", labels,
        index=labels.index(card.label) if card and card.label in labels else 0,
        key=_k("auth_trimvar_label"),
    ) if labels else None
    col3, col4, col5 = st.columns(3)
    init = col3.number_input("Initial", value=(card.init if card else 0.0),
                             key=_k("auth_trimvar_init"), format="%.6g")
    lb = col4.number_input("Lower bound", value=(card.lb if card else -1.0),
                           key=_k("auth_trimvar_lb"), format="%.6g")
    ub = col5.number_input("Upper bound", value=(card.ub if card else 1.0),
                           key=_k("auth_trimvar_ub"), format="%.6g")
    if label is None:
        st.warning("Define AESTAT/AESURF labels first.")
        return None
    if not lb < ub:
        st.warning("The lower bound must be less than the upper bound.")
        return None
    return Trimvar(id=int(vid), label=label, init=float(init),
                   lb=float(lb), ub=float(ub))


def _trimobj_form(bulk: BulkData, card: Optional[Trimobj], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key=_k("auth_trimobj_sid"))
    labels = logic.label_options(bulk)
    rows = ([{"label": l, "weight": w} for l, w in zip(card.labels, card.weights)]
            if card else [{"label": labels[0] if labels else "", "weight": 1.0}])
    df = _pairs_editor(
        "auth_trimobj_pairs",
        {"label": st.column_config.SelectboxColumn("Label", options=labels),
         "weight": st.column_config.NumberColumn("Weight", format="%.6g")},
        rows,
    )
    out_labels: list[str] = []
    weights: list[float] = []
    for _, row in df.iterrows():
        label = row["label"]
        if isinstance(label, str) and label.strip():
            out_labels.append(label.strip().upper())
            weights.append(float(row["weight"] or 0.0))
    if not out_labels:
        st.warning("TRIMWGT needs at least one label/weight pair.")
        return None
    return Trimobj(sid=int(sid), labels=out_labels, weights=weights)


def _trimcon_form(bulk: BulkData, cards: Optional[list[Trimcon]],
                  default_id: int) -> Optional[list[Trimcon]]:
    sid = st.number_input("SID", min_value=1,
                          value=(cards[0].sid if cards else default_id),
                          key=_k("auth_trimcon_sid"))
    labels = logic.label_options(bulk)
    rows = ([{"label": c.label, "sense": c.sense, "rhs": c.rhs} for c in cards]
            if cards else
            [{"label": labels[0] if labels else "", "sense": "LE", "rhs": 0.0}])
    df = _pairs_editor(
        "auth_trimcon_rows",
        {"label": st.column_config.SelectboxColumn("Label", options=labels),
         "sense": st.column_config.SelectboxColumn("Sense", options=["LE", "GE"]),
         "rhs": st.column_config.NumberColumn("RHS", format="%.6g")},
        rows,
    )
    cons: list[Trimcon] = []
    for _, row in df.iterrows():
        label = row["label"]
        if isinstance(label, str) and label.strip():
            cons.append(Trimcon(sid=int(sid), label=label.strip().upper(),
                                sense=str(row["sense"]), rhs=float(row["rhs"] or 0.0)))
    if not cons:
        st.warning("TRIMINEQ needs at least one constraint row.")
        return None
    return cons


def _diverg_form(bulk: BulkData, card: Optional[Diverg], default_id: int):
    col1, col2 = st.columns(2)
    sid = col1.number_input("SID", min_value=1,
                            value=(card.sid if card else default_id),
                            key=_k("auth_diverg_sid"))
    nroots = col2.number_input("Roots (NROOTS)", min_value=1,
                               value=(card.nroots if card else 1),
                               key=_k("auth_diverg_nroots"))
    machs_text = st.text_input(
        "Mach list", value=(" ".join(f"{m:g}" for m in card.machs) if card else "0.0"),
        key=_k("auth_diverg_machs"),
    )
    try:
        machs = logic.parse_float_list(machs_text)
    except ValueError:
        st.warning("Mach list is not a valid float list.")
        return None
    if not machs:
        st.warning("DIVERG needs at least one Mach number.")
        return None
    if len(set(machs)) != len(machs):
        st.warning("DIVERG Mach numbers must be distinct (QRG p.1603 remark 3).")
        return None
    return Diverg(sid=int(sid), nroots=int(nroots), machs=machs)


# ---------------------------------------------------------------------------
# Panel 3 — Maneuver (MANVR family)
# ---------------------------------------------------------------------------

def _mloads_form(bulk: BulkData, card: Optional[Mloads], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key=_k("auth_mloads_sid"))
    trims = sorted(bulk.mldtrims.keys())
    times = sorted(bulk.mldtimes.keys())
    comds = [0] + sorted(bulk.mldcomds.keys())
    prnts = [0] + sorted(bulk.mldprnts.keys())
    col1, col2 = st.columns(2)
    mldtrim = col1.selectbox(
        "MANTRIM (initial condition)", trims,
        index=trims.index(card.mldtrim) if card and card.mldtrim in trims else 0,
        key=_k("auth_mloads_mldtrim")) if trims else None
    mldtime = col2.selectbox(
        "MANTIME (integration window)", times,
        index=times.index(card.mldtime) if card and card.mldtime in times else 0,
        key=_k("auth_mloads_mldtime")) if times else None
    col3, col4 = st.columns(2)
    mldcomd = col3.selectbox(
        "MANCMD (0 = hold trim)", comds,
        index=comds.index(card.mldcomd) if card and card.mldcomd in comds else 0,
        format_func=lambda v: "— none (hold trim) —" if v == 0 else str(v),
        key=_k("auth_mloads_mldcomd"))
    mldprnt = col4.selectbox(
        "MANPRNT (0 = no ASCII print)", prnts,
        index=prnts.index(card.mldprnt) if card and card.mldprnt in prnts else 0,
        format_func=lambda v: "— none —" if v == 0 else str(v),
        key=_k("auth_mloads_mldprnt"))
    st.caption(
        "Solver selection: any of NMODES/METHOD/ZETA nonzero runs the "
        "free-flight modal solver (METHOD = −1 is the all-defaults-modal "
        "sentinel); all zeros runs the direct restrained l-set solver.  The "
        "modal solver only accepts AESURF labels in MANCMD and needs RHO "
        "on the MANTRIM."
    )
    col5, col6, col7 = st.columns(3)
    nmodes = col5.number_input("NMODES (0 = all elastic)", min_value=0,
                               value=(card.nmodes if card else 0),
                               key=_k("auth_mloads_nmodes"))
    methods = [-1, 0] + sorted(bulk.eigrls.keys())
    method = col6.selectbox(
        "METHOD", methods,
        index=methods.index(card.method) if card and card.method in methods else 1,
        format_func=lambda v: {-1: "−1 — all-defaults modal", 0: "0 — default"}.get(v, f"EIGRL {v}"),
        key=_k("auth_mloads_method"))
    zeta = col7.number_input("ZETA (elastic damping)", min_value=0.0,
                             value=(card.zeta if card else 0.0),
                             key=_k("auth_mloads_zeta"), format="%.4f")
    if mldtrim is None or mldtime is None:
        st.warning("Define an MANTRIM and an MANTIME first.")
        return None
    return Mloads(sid=int(sid), mldtrim=int(mldtrim), mldtime=int(mldtime),
                  mldcomd=int(mldcomd), mldprnt=int(mldprnt),
                  nmodes=int(nmodes), method=int(method), zeta=float(zeta))


def _mldtrim_form(bulk: BulkData, card: Optional[Mldtrim], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key=_k("auth_mldtrim_sid"))
    trims = sorted(bulk.trims.keys())
    trim_sid = st.selectbox(
        "TRIM SID (steady initial condition)", trims,
        index=trims.index(card.trim_sid) if card and card.trim_sid in trims else 0,
        format_func=lambda v: f"{v} (q={bulk.trims[v].q:g}, M={bulk.trims[v].mach:g})",
        key=_k("auth_mldtrim_trim")) if trims else None
    rho = st.number_input(
        "RHO (0 = unset)", value=(card.rho if card else 0.0),
        key=_k("auth_mldtrim_rho"), format="%.6g", min_value=0.0,
        help="Freestream density; required by the modal (free-flight) MANVR "
             "solver for V = sqrt(2q/rho).")
    if trim_sid is None:
        st.warning("Define a TRIM condition first.")
        return None
    return Mldtrim(sid=int(sid), trim_sid=int(trim_sid), rho=float(rho))


def _mldtime_form(bulk: BulkData, card: Optional[Mldtime], default_id: int):
    col1, col2, col3, col4, col5 = st.columns(5)
    sid = col1.number_input("SID", min_value=1,
                            value=(card.sid if card else default_id),
                            key=_k("auth_mldtime_sid"))
    t0 = col2.number_input("T0", value=(card.t0 if card else 0.0),
                           key=_k("auth_mldtime_t0"), format="%.4g")
    tend = col3.number_input("TEND", value=(card.tend if card else 1.0),
                             key=_k("auth_mldtime_tend"), format="%.4g")
    dt = col4.number_input("DT", value=(card.dt if card else 0.01),
                           key=_k("auth_mldtime_dt"), format="%.4g")
    tout = col5.number_input("TOUT (0 = every step)", min_value=0.0,
                             value=(card.tout if card else 0.0),
                             key=_k("auth_mldtime_tout"), format="%.4g")
    if dt <= 0.0 or tend <= t0:
        st.warning("MANTIME needs DT > 0 and TEND > T0.")
        return None
    return Mldtime(sid=int(sid), t0=float(t0), tend=float(tend),
                   dt=float(dt), tout=float(tout))


def _mldcomd_form(bulk: BulkData, card: Optional[Mldcomd], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key=_k("auth_mldcomd_sid"))
    # Restrict to AESURF labels when any modal MANVR references this card —
    # rigid-state commands under the modal solver are a hard parse error.
    modal_owner = any(m.mldcomd == (card.sid if card else 0) and m.selects_modal
                      for m in bulk.mloads.values())
    labels = logic.label_options(bulk, modal_only=modal_owner)
    if modal_owner:
        st.caption("A modal MANVR references this card — AESURF labels only.")
    tabids = sorted(bulk.tabled1s.keys())
    rows = ([{"label": l, "tabid": t} for l, t in card.commands]
            if card else
            [{"label": labels[0] if labels else "", "tabid": tabids[0] if tabids else 0}])
    df = _pairs_editor(
        "auth_mldcomd_rows",
        {"label": st.column_config.SelectboxColumn("Label", options=labels),
         "tabid": st.column_config.SelectboxColumn("TABLED1", options=tabids)},
        rows,
    )
    commands: list[tuple[str, int]] = []
    for _, row in df.iterrows():
        label = row["label"]
        if isinstance(label, str) and label.strip():
            commands.append((label.strip().upper(), int(row["tabid"] or 0)))
    if not labels or not tabids:
        st.warning("Define AESURF/AESTAT labels and at least one TABLED1 first.")
        return None
    if not commands:
        st.warning("MANCMD needs at least one label/table pair.")
        return None
    return Mldcomd(sid=int(sid), commands=commands)


def _mldprnt_form(bulk: BulkData, card: Optional[Mldprnt], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key=_k("auth_mldprnt_sid"))
    st.caption("Item keywords are recorded on the card but do not filter the "
               "ASCII output — the full column set is always printed.")
    return Mldprnt(sid=int(sid), items=list(card.items) if card else [])


# ---------------------------------------------------------------------------
# Panel 4 — Tables (TABLED1)
# ---------------------------------------------------------------------------

def _tabled1_form(bulk: BulkData, card: Optional[Tabled1], default_id: int):
    tid = st.number_input("TID", min_value=1,
                          value=(card.tid if card else default_id),
                          key=_k("auth_tabled1_tid"))
    rows = ([{"x": x, "y": y} for x, y in zip(card.xs, card.ys)]
            if card else [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}])
    df = _pairs_editor(
        "auth_tabled1_points",
        {"x": st.column_config.NumberColumn("x (time)", format="%.6g"),
         "y": st.column_config.NumberColumn("y (value)", format="%.6g")},
        rows,
    )
    xs, ys = [], []
    for _, row in df.iterrows():
        if row["x"] is not None and row["y"] is not None:
            xs.append(float(row["x"]))
            ys.append(float(row["y"]))
    if len(xs) < 2:
        st.warning("TABLED1 needs at least two points.")
        return None
    if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
        st.warning("Abscissae must be strictly increasing.")
        return None
    return Tabled1(tid=int(tid), xs=xs, ys=ys)


# ---------------------------------------------------------------------------
# S4 — presets, table generators, two-pass increment builder
# ---------------------------------------------------------------------------

def _render_preset_panel(bulk: BulkData) -> None:
    with st.expander("Preset maneuvers — pre-fill the TRIM form", expanded=False):
        names = [p.name for p in maneuver.MANEUVER_PRESETS]
        sel = st.selectbox("Maneuver", names, key=wk("auth_preset_sel"))
        preset = next(p for p in maneuver.MANEUVER_PRESETS if p.name == sel)
        st.caption(preset.description)
        col1, col2 = st.columns(2)
        param = col1.number_input(preset.param_label, value=preset.param_default,
                                  key=wk("auth_preset_param"), format="%.4g")
        g = 0.0
        if preset.uses_g:
            # #30: the solver is unit-neutral (charter §7), so the deck's unit
            # system must be declared to prefill g; the value stays editable.
            # Keyed per system so switching re-prefills instead of keeping the
            # previous system's number under a new label.
            units = UNIT_SYSTEMS[col2.selectbox(
                "Deck unit system", list(UNIT_SYSTEMS), key=wk("auth_preset_units"))]
            g = col2.number_input(
                f"Gravity g ({units.length_unit}/s², {units.name})", value=units.g,
                key=wk(f"auth_preset_g_{units.name}"), format="%.6g",
            )
        missing = maneuver.missing_preset_labels(bulk, preset)
        if missing:
            st.warning(f"Missing AESTAT labels: {', '.join(missing)}")
            if st.button("Create missing AESTATs", key=wk("auth_preset_mkstat")):
                first = logic.next_free_sid(bulk, "aestat")
                session_deck.commit(
                    bulk,
                    changes=[("aestat", Aestat(id=first + i, label=label))
                             for i, label in enumerate(missing)],
                    done=f"AESTAT created for {', '.join(missing)}.")
        if not any(s for s in bulk.aesurfs.values()):
            st.warning(f"The {preset.surface_role} (an AESURF) must exist and "
                       "stay un-prescribed so it can trim free.")
        if st.button("Pre-fill TRIM form", key=wk("auth_preset_fill")):
            st.session_state["auth_trim_prefill"] = preset.prescribed_vars(param, g)
            st.session_state["auth_trim_vars_ver"] = \
                st.session_state.get("auth_trim_vars_ver", 0) + 1
            st.session_state[wk("auth_sel_trim")] = _NEW
            st.rerun()


_GENERATORS = ["Cosine ramp (recommended)", "Linear ramp", "Step", "Doublet"]


def _generator_points(shape: str, key_prefix: str,
                      y0_label: str = "Start value y0",
                      y1_label: str = "End value y1",
                      ) -> Optional[list[tuple[float, float]]]:
    """Shared generator parameter widgets; returns (x, y) points or None."""
    col1, col2 = st.columns(2)
    t1 = col1.number_input("t1 (shape start)", min_value=0.0, value=0.0,
                           key=wk(f"{key_prefix}_t1"), format="%.4g")
    t2 = col2.number_input("t2 (shape end)", min_value=0.0, value=0.2,
                           key=wk(f"{key_prefix}_t2"), format="%.4g")
    col3, col4 = st.columns(2)
    y1 = amp = 0.0  # each branch overwrites the values its shapes consume
    if shape == "Doublet":
        y0 = col3.number_input("Baseline y0", value=0.0,
                               key=wk(f"{key_prefix}_y0"), format="%.6g")
        amp = col4.number_input("Amplitude", value=0.1,
                                key=wk(f"{key_prefix}_amp"), format="%.6g")
    else:
        y0 = col3.number_input(y0_label, value=0.0,
                               key=wk(f"{key_prefix}_y0"), format="%.6g")
        y1 = col4.number_input(y1_label, value=0.1,
                               key=wk(f"{key_prefix}_y1"), format="%.6g")
    try:
        if shape == "Step":
            return maneuver.gen_step(t1, y0, y1)
        if shape == "Linear ramp":
            return maneuver.gen_ramp(t1, t2, y0, y1)
        if shape == "Doublet":
            return maneuver.gen_doublet(t1, t2, amp, y0)
        return maneuver.gen_cosine_ramp(t1, t2, y0, y1)
    except ValueError as exc:
        st.warning(str(exc))
        return None


def _render_table_generator(bulk: BulkData) -> None:
    with st.expander("Generate a TABLED1 from a shape", expanded=False):
        st.caption(
            "Cosine ramps are the recommended default — clamped-linear slope "
            "jumps ring the highest retained mode under the modal solver."
        )
        shape = st.selectbox("Shape", _GENERATORS, key=wk("auth_gen_shape"))
        tid = st.number_input("TID", min_value=1,
                              value=logic.next_free_sid(bulk, "tabled1"),
                              key=wk("auth_gen_tid"))
        points = _generator_points(shape, "auth_gen")
        if points is not None and st.button("Create TABLED1", key=wk("auth_gen_apply")):
            table = Tabled1(tid=int(tid),
                            xs=[p[0] for p in points], ys=[p[1] for p in points])
            session_deck.commit(bulk, changes=[("tabled1", table)],
                                done=f"TABLED1 {table.tid} applied to the deck.")


def _render_increment_builder(bulk: BulkData) -> None:
    """Two-pass MANCMD authoring: increments now, absolute tables post-solve."""
    with st.expander("Two-pass command builder (increments from trim)",
                     expanded=False):
        st.caption(
            "Command tables are absolute and mass-case specific: the table "
            "value at t0 must equal the solved trim control value, which is "
            "only known after a solve.  Author the command as an increment "
            "here; after running the analysis, one click offsets it by the "
            "solved trim value per mass case and writes the absolute TABLED1."
        )
        specs: dict[tuple[int, str], maneuver.IncrementSpec] = (
            st.session_state.setdefault("mldcomd_increments", {}))
        mloads_sids = sorted(bulk.mloads.keys())
        surf_labels = logic.label_options(bulk, modal_only=True)
        if not mloads_sids or not surf_labels:
            st.info("Define an MANVR driver and at least one AESURF first.")
            return
        col1, col2 = st.columns(2)
        msid = col1.selectbox("MANVR", mloads_sids, key=wk("auth_inc_mloads"))
        label = col2.selectbox("Control (AESURF label)", surf_labels,
                               key=wk("auth_inc_label"))
        shape = st.selectbox("Increment shape (Δ from trim)", _GENERATORS,
                             key=wk("auth_inc_shape"))
        points = _generator_points(shape, "auth_inc",
                                   y0_label="Start Δ", y1_label="End Δ")
        if points is not None and st.button("Add increment command",
                                            key=wk("auth_inc_add")):
            specs[(msid, label)] = maneuver.IncrementSpec(
                mloads_sid=msid, label=label, points=points)
            st.rerun()

        if specs:
            st.markdown("**Pending increment commands**")
            for (m, l), spec in list(specs.items()):
                col_a, col_b = st.columns([4, 1])
                dys = [dy for _, dy in spec.points]
                col_a.markdown(
                    f"- MANVR {m} · {l}: {len(spec.points)} points, "
                    f"Δ ∈ [{min(dys):g}, {max(dys):g}]")
                if col_b.button("Remove", key=wk(f"auth_inc_rm_{m}_{l}")):
                    del specs[(m, l)]
                    st.rerun()

            trim_results = st.session_state.get("sol144_result")
            maneuver_results = st.session_state.get("maneuver_result")
            have_solve = bool(trim_results or maneuver_results)
            if not have_solve:
                st.button("Resolve → absolute TABLED1s", disabled=True,
                          key=wk("auth_inc_resolve"),
                          help="Run the trim/maneuver solve first (or author "
                               "the table as absolute values).")
            elif st.button("Resolve → absolute TABLED1s", type="primary",
                           key=wk("auth_inc_resolve")):
                cc = st.session_state.get("case_control")
                if cc is None:
                    st.error("Load or author SOL 144 case control before "
                             "resolving increment commands.")
                    return
                res = maneuver.resolve_increment_tables(
                    bulk, cc, list(specs.values()),
                    trim_results=trim_results,
                    maneuver_results=maneuver_results,
                    loaded=st.session_state.get("file_card_sids"),
                )
                for err in res.errors:
                    st.error(err)
                if res.cards:
                    _commit_resolution(bulk, cc, specs, res)


def _commit_resolution(bulk: BulkData, cc: CaseControl,
                       specs: dict[tuple[int, str], maneuver.IncrementSpec],
                       res: maneuver.Resolution) -> None:
    """Put the second pass's cards into the deck, and select any new MANVR.

    ``commit`` restarts the run on success.  It returns only when the deck refused the
    cards; the specs and the case control are then put back as they were.
    """
    for spec in res.resolved:
        specs.pop((spec.mloads_sid, spec.label), None)
    if res.selectors:
        st.session_state.case_control = dataclasses.replace(cc, subcases=[
            dataclasses.replace(sc, mloads_sid=res.selectors.get(sc.subcase_id, sc.mloads_sid))
            for sc in cc.subcases])
        st.session_state.cc_subcases = None          # the subcase editor rebuilds from it
    if not session_deck.commit(bulk, changes=res.cards, done="  \n".join(res.report)):
        for spec in res.resolved:
            specs[(spec.mloads_sid, spec.label)] = spec
        st.session_state.case_control = cc


# ---------------------------------------------------------------------------
# Gust cases (#117).  Two routes on opposite sides of the architecture boundary:
# the GUSTLF card form is unit-neutral, like every card; the generator panel
# collects speeds, altitudes and a unit system and hands them to
# sbeam_tools.cases.gust, which owns the formula, the atmosphere and the
# regulation's constants.  Nothing is computed here.
# ---------------------------------------------------------------------------

def _gustlf_form(bulk: BulkData, card: Optional[Gustlf], default_id: int):
    trims = sorted(bulk.trims)
    col1, col2 = st.columns(2)
    sid = col1.number_input("SID", min_value=1, value=(card.sid if card else default_id),
                            key=_k("auth_gustlf_sid"))
    trimid = col2.selectbox(
        "TRIM it rides on (TRIMID)", trims,
        index=trims.index(card.trimid) if card and card.trimid in trims else 0,
        key=_k("auth_gustlf_trimid"),
        help="Supplies Q, Mach and every prescribed label except URDD3. One gust "
             "case per TRIM.",
    ) if trims else None
    col3, col4 = st.columns(2)
    n = col3.number_input("Load factor N (used: URDD3 = −N·G)",
                          value=(card.n if card else 1.0),
                          key=_k("auth_gustlf_n"), format="%.6g")
    g = col4.number_input("Gravity G (used; model units)",
                          value=(card.g if card else 0.0), min_value=0.0,
                          key=_k("auth_gustlf_g"), format="%.6g")
    st.caption("Recorded only — echoed to the f06, never used in the solution. "
               "0 means not recorded.")
    r1 = st.columns(4)
    ude = r1[0].number_input("U_de", value=(card.ude if card else 0.0),
                             key=_k("auth_gustlf_ude"), format="%.6g")
    veas = r1[1].number_input("V (EAS)", value=(card.veas if card else 0.0),
                              key=_k("auth_gustlf_veas"), format="%.6g")
    kg = r1[2].number_input("K_g", value=(card.kg if card else 0.0),
                            key=_k("auth_gustlf_kg"), format="%.6g")
    mu = r1[3].number_input("μ", value=(card.mu if card else 0.0),
                            key=_k("auth_gustlf_mu"), format="%.6g")
    r2 = st.columns(3)
    a = r2[0].number_input("Normal-force slope a (/rad)", value=(card.a if card else 0.0),
                           key=_k("auth_gustlf_a"), format="%.6g")
    asrc = r2[1].selectbox("Slope source", _ASRC,
                           index=_ASRC.index(card.asrc) if card and card.asrc in _ASRC else 0,
                           key=_k("auth_gustlf_asrc"))
    alt_text = r2[2].text_input(
        "Altitude (blank = not recorded)",
        value=("" if card is None or card.alt is None else repr(float(card.alt))),
        key=_k("auth_gustlf_alt"),
        help="Sea level is a real altitude, so 0 is a reading and blank is its absence.",
    ).strip()
    if trimid is None:
        st.warning("Define a TRIM condition first.")
        return None
    try:
        alt = float(alt_text) if alt_text else None
    except ValueError:
        st.warning("Altitude must be a number or blank.")
        return None
    return Gustlf(sid=int(sid), trimid=int(trimid), n=float(n), g=float(g),
                  ude=float(ude), veas=float(veas), kg=float(kg), mu=float(mu),
                  a=float(a), asrc=str(asrc), alt=alt)


_ASRC = ["RIGID", "RESTRAINED"]
_BASELINE = "Baseline mass"


def _render_gust_panel(bulk: BulkData) -> None:
    """Generate FAR/CS 23.341 gust cases with sbeam_tools.cases.gust and add them."""
    with st.expander("Generate gust cases (FAR/CS 23.341, Pratt formula)", expanded=False):
        st.caption(
            "Speeds are **equivalent** airspeeds and altitudes are in the deck's own "
            "units; the unit system supplies sea-level density, g and the ISA "
            "atmosphere. The cases, the load factors and the cards come from "
            "`sbeam_tools.cases.gust`, the same code `sbeam-cases` runs."
        )
        cc: Optional[CaseControl] = st.session_state.get("case_control")
        if cc is None or cc.sol != 144:
            st.info("Gust cases need a SOL 144 case control.")
            return
        if not bulk.trims:
            st.info("Define a TRIM first: the cases inherit its prescribed labels.")
            return
        col1, col2, col3 = st.columns(3)
        units = UNIT_SYSTEMS[cast(str, col1.selectbox(
            "Deck unit system", list(UNIT_SYSTEMS), key=wk("auth_gust_units")))]
        template = cast(int, col2.selectbox(
            "TRIM template", sorted(bulk.trims), key=wk("auth_gust_template"),
            help="The cases inherit every prescribed label of this TRIM except URDD3."))
        g = col3.number_input(
            f"Gravity g ({units.length_unit}/s²)", value=units.g, min_value=0.0,
            key=wk(f"auth_gust_g_{units.name}"), format="%.6g")
        sp = st.columns(3)
        speeds = {
            name: sp[i].number_input(
                f"{label} ({units.speed_unit} EAS; 0 = not used)", value=0.0, min_value=0.0,
                key=wk(f"auth_gust_{name.lower()}"), format="%.6g")
            for i, (name, label) in enumerate(
                (("VC", "V_C design cruise"), ("VD", "V_D design dive"),
                 ("VB", "V_B rough air")))
        }
        col4, col5, col6 = st.columns(3)
        alt_text = col4.text_input(
            f"Altitudes ({units.length_unit}, space or comma separated)", value="0",
            key=wk("auth_gust_alts"))
        mass_options: list[Any] = [_BASELINE] + sorted(bulk.masssets)
        picked = col5.multiselect(
            "Mass cases", mass_options, default=[_BASELINE], key=wk("auth_gust_mass"),
            format_func=lambda v: v if v == _BASELINE else f"{v} {bulk.masssets[v].label}")
        sid_base = col6.number_input(
            "First SID", min_value=1, value=9000, key=wk("auth_gust_sid_base"),
            help="Each case takes one SID for its TRIM, its GUSTLF and its subcase.")

        if not st.button("Generate and add to the deck", type="primary",
                         key=wk("auth_gust_add")):
            return
        try:
            altitudes = logic.parse_float_list(alt_text) or [0.0]
            used = {name: float(v) for name, v in speeds.items() if v > 0.0}
            if not used:
                raise ValueError("give at least one of V_C, V_D and V_B")
            if not picked:
                raise ValueError("choose at least one mass case")
            massets = [None if m == _BASELINE else int(m) for m in picked]
            airplane = airplane_from_model(
                cc, bulk, int(template), massets,
                where=st.session_state.get("_uploaded_filename") or "the deck")
            cases = gust.generate_cases(airplane, units, used, altitudes,
                                        float(g), int(sid_base))
        except (ValueError, KeyError) as exc:
            st.error(f"No case was added: {exc}")
            return
        taken = sorted({sc.subcase_id for sc in cc.subcases} & {c.sid for c in cases})
        if taken:
            st.error(f"No case was added: subcase(s) {taken} already exist. "
                     "Choose another first SID.")
            return
        changes: list[tuple[str, Any]] = []
        subcases = list(cc.subcases)
        for case in cases:
            changes += [("trim", gust.trim_card(case, airplane)),
                        ("gustlf", gust.gustlf_card(case))]
            mass = bulk.masssets.get(case.mass_case.sid) if case.mass_case.sid else None
            subcases.append(gust.gust_subcase(
                case, airplane, "MASSSET" if mass is not None and mass.msc else "MASSCASE"))
        # The subcases go in with the cards: commit restarts the run on success and
        # returns only when the deck refused, and the case control is then put back.
        st.session_state.case_control = dataclasses.replace(cc, subcases=subcases)
        st.session_state.cc_subcases = None
        st.session_state["_auth_gust_summary"] = gust.format_summary(cases, units)
        if not session_deck.commit(
                bulk, changes=changes,
                done=f"{len(cases)} gust case(s) added: TRIM, GUSTLF and subcase "
                     f"{cases[0].sid} to {cases[-1].sid}."):
            st.session_state.case_control = cc
            st.session_state.pop("_auth_gust_summary", None)


def _show_gust_summary() -> None:
    summary = st.session_state.get("_auth_gust_summary")
    if summary:
        st.markdown("**Gust cases last generated** (the table `sbeam-cases` prints)")
        st.code(summary, language="text")


# ---------------------------------------------------------------------------
# Tab entry point
# ---------------------------------------------------------------------------

def render_sol144_authoring(bulk: BulkData) -> None:
    st.subheader("Aeroelastic Authoring")
    st.caption(
        "Author the SOL 144 / MANVR condition cards, then reference them from the "
        "Case Control tab.  Each Apply writes the card into the deck and reads the "
        "deck again, so the parser's rules apply to it; the same deck is run and "
        "exported.  A card of the loaded deck is not changed in place: save your "
        "edit under a new SID."
    )
    session_deck.show_flash()
    tab_surf, tab_trim, tab_gust, tab_mloads, tab_tables = st.tabs(
        ["Surfaces & States", "Trim Conditions", "Gust (GUSTLF)", "Maneuver (MANVR)",
         "Tables"]
    )
    with tab_gust:
        _render_gust_panel(bulk)
        _show_gust_summary()
        _family_editor(bulk, "gustlf", "GUSTLF — quasi-static gust load case", _gustlf_form)
    with tab_surf:
        _family_editor(bulk, "aestat", "AESTAT — rigid-body trim variable", _aestat_form)
        _family_editor(bulk, "aesurf", "AESURF — control surface", _aesurf_form)
        _family_editor(bulk, "aelist", "AELIST — control-surface box list", _aelist_form)
        _family_editor(bulk, "suport", "SUPORT — free-body support DOFs", _suport_form)
    with tab_trim:
        _render_preset_panel(bulk)
        _family_editor(bulk, "trim", "TRIM — static trim condition", _trim_form)
        _family_editor(bulk, "trimvar", "TRIMVAR — variable bounds (over-determined)", _trimvar_form)
        _family_editor(bulk, "trimobj", "TRIMWGT — weighted objective (over-determined)", _trimobj_form)
        _family_editor(bulk, "trimcon", "TRIMINEQ — inequality constraints (over-determined)", _trimcon_form)
        _family_editor(bulk, "diverg", "DIVERG — divergence sweep", _diverg_form)
    with tab_mloads:
        _render_increment_builder(bulk)
        _family_editor(bulk, "mldtrim", "MANTRIM — initial-condition trim", _mldtrim_form)
        _family_editor(bulk, "mldtime", "MANTIME — integration window", _mldtime_form)
        _family_editor(bulk, "mldcomd", "MANCMD — pilot command histories", _mldcomd_form)
        _family_editor(bulk, "mldprnt", "MANPRNT — ASCII time-history output", _mldprnt_form)
        _family_editor(bulk, "mloads", "MANVR — transient maneuver driver", _mloads_form)
    with tab_tables:
        _render_table_generator(bulk)
        _family_editor(bulk, "tabled1", "TABLED1 — tabular time function", _tabled1_form)

    _render_authoring_export(bulk)


def _render_authoring_export(bulk: BulkData) -> None:
    """Download buttons for the authored driver deck and the cards snippet."""
    authored = _authored()
    if not any(authored.values()):
        return
    st.divider()
    st.markdown("**Export authored cards**")
    cc = st.session_state.get("case_control")
    errors: list[str] = []
    if cc is not None and cc.sol == 144:
        errors, _ = logic.check_case_control(
            bulk, cc,
            unresolved_increments=list(
                st.session_state.get("mldcomd_increments", {}).values()),
        )
        for err in errors:
            st.error(err)
    stem = (st.session_state.get("_uploaded_filename") or "model").rsplit(".", 1)[0]
    col1, col2 = st.columns(2)
    if cc is not None:
        col1.download_button(
            "Download run BDF (driver + INCLUDEs)",
            data=export_bdf_text(
                cc, authored_block=session_deck.session_cards_text(bulk),
                bulk_section=deck_bulk_section(
                    st.session_state.get("_uploaded_source_text"))),
            file_name=logic.suggest_run_name(stem, cc),
            mime="text/plain",
            disabled=bool(errors),
            key=wk("auth_export_driver"),
        )
    else:
        col1.caption("Define a case control to export a run deck.")
    col2.download_button(
        "Download authored cards only (.bdf snippet)",
        data=write_authored_block(bulk, authored, logic.AUTHORED_HEADER),
        file_name=f"{stem}_authored_cards.bdf",
        mime="text/plain",
        key=wk("auth_export_cards"),
    )
