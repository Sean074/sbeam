# Compatibility Audit — sbeam vs MSC NASTRAN, ZAERO, NASTRAN-95 and pyNastran (2026-11-16)

**Status:** findings filed 2026-11-16 as #63–#94 (label `audit-2026-11`); roadmap findings
posted as comments on #4, #5, #7, #12–#18, #25–#28, #36, #41–#44, #50, #62. Milestone
assignment of the v0.4.0 defects awaits triage. Process changes P1–P7 (§7) agreed
2026-11-16 and adopted as CLAUDE.md rules 1–3 (‡) and new rules 7–8; documentation changes
D1–D4 (§7.3) are proposed, not yet made.

**Scope:** where sbeam's input, methods and output differ from MSC NASTRAN and ZAERO, which
open sbeam problems MSC/ZAERO already solve, and what NASTRAN-95 and pyNastran offer as
benchmarks, oracles and reusable code. Aim: compatibility, and less development effort.

**State audited:** `release/0.4.0` at `294408c` (after #48, #51, #55, #57–#61).

---

## 1. Sources and method

| Source | Use | Licence / rule |
|---|---|---|
| MSC Nastran 2024.1 Quick Reference Guide (QRG) | card layouts, defaults, remarks; case control | reference |
| MSC Nastran 2023.1 (and 2021.3) Aeroelastic Analysis User's Guide (AAUG) | SOL 144/145/146 theory, example problems HA144x–HA146x, f06 layouts | reference |
| ZAERO 9.2 User's / Theoretical / Applications manuals (ZUM/ZTM/ZAM) | ZAERO card layouts, RFA, MLOADS/GLOADS theory, validation cases | reference |
| NASTRAN-95 (github.com/nasa/NASTRAN-95) | `um/BULK.TXT` card rules, demo decks with reference output | NOSA 1.3: theory, rules and benchmarks only — no code copied (#61) |
| pyNastran (github.com/SteveDoyle2/pyNastran) | independent card parser (oracle), example MSC models and f06, readers | BSD-3: reusable as an optional dependency of `sbeam_tools`/tests |

The manuals are in the user's library (`/Volumes/Data/Library`). **All page numbers in this
review and in the filed issues are PDF pages** (QRG PDF = printed + 33; AAUG PDF = printed + 14).

Six parallel read-only audits: structural/load cards (S), aero/trim cards (A), case control
(C) and output (O), aero methods (M), roadmap mapping, and NASTRAN-95/pyNastran (P, N, B).
Each claim was checked against the manual text, and each suspected misread was probed by
parsing a small deck with sbeam. pyNastran 1.5.0+dev was installed in an isolated venv and
used to cross-parse 58 of the 61 repo decks card by card. About 20 of the High findings
were re-verified independently before filing (probe or manual text), among them S1, S3, S4,
S7, M1, M3, M5, C1, C2, C7, P6, P7, S18 and the MKAERO1 and HA144E citations.

## 2. Headline

1. **The parser still misreads legal NASTRAN input silently.** After #55/#57–#61 the parser
   refuses unknown cards and checks cross-references, but it does not yet check that a
   handler *consumed* everything on the card: continuation lines past what a handler reads
   are dropped (#63), free-field lines past 10 fields land in the wrong columns (#64), and
   several fields are read with a non-NASTRAN meaning (DIVERG field 4 #73, TRIMVAR blanks
   #77, CBAR G0 `13 0 0` #67, MASSSET #78, CONM2 inertia sign #66, GRID CD #65).
2. **Case control never got the #55 rule.** Commands above the first SUBCASE, unknown
   commands, case-control PARAMs, AESYMXZ and SUBCOM are dropped silently; a deck with no
   SUBCASE writes an empty f06 and reports success (#79, #80). ENDDATA does not end the data (#81).
3. **Three aero formulation differences change numbers on the same deck:** WKK is the
   reciprocal of MSC's (#71), the SPLINE2 axis is not projected into the panel plane (a
   CID-0 dihedral wing loses 100 % of its side force, #74), and CAERO1 IGID is ignored (#76).
4. **Output labels mislead a comparison with MSC:** CZ is in basic, not reference, axes
   (opposite sign); "BOX ID" is a sequence number (#82).
5. **Card names clash.** sbeam reuses ZAERO names (MLOADS family, TRIMVAR/TRIMOBJ/TRIMCON,
   CHORDCP, SPLINE0, ATTACH) and MSC names (MASSSET, MONPNT1/MONPNT3) with different layouts
   or meanings (#77, #78, #86, #87).
6. **The roadmap can reuse a lot:** ZAERO GLOADS/DGUST/CGUST + MINSTAT/AEROLAG for #16,
   AESURF/AESURFS for AMODE (#13/#17), MSC `USAGE=FORCE` for #28, and ready-made published
   benchmarks for #14, #16, #41, #42, #44. Estimated saving ≈ 15–20 engineering days.
7. **pyNastran is the cheapest compatibility tool available:** as a CI oracle it found or
   confirmed eight of the card-layout defects in one pass (#83), and as a reader of MSC OP2
   and f06 it removes the need for f06 parity (#93).

## 3. Findings → issues

Severity: **H** silent wrong answer · **M** silent misread of less common input, or a
misleading output · **L** loud refusal, doc error. Finding IDs are the auditors' (S
structural, A aero cards, C case control, O output, M methods, P pyNastran, N NASTRAN-95).

### 3.1 Silent misreads and wrong answers (proposed v0.4.0)

| Issue | Sev | Title | Findings |
|---|---|---|---|
| #63 | H | Continuation lines a handler does not read are dropped (LOAD, PBAR K1/K2/I12, PBUSH flags, AESURF, EIGRL, MONPNT1 …) | S4, S5, S6, S13, M7, A4, P1, P4 |
| #64 | H | Free-field > 10 fields, field-10 markers, large-field GRID* not normalised (repo deck v9 relies on the misread) | S7, S14, S15, P8 |
| #65 | H | GRID CD used only for output | S1 |
| #66 | H | CONM2 products of inertia opposite sign to NASTRAN | S3 |
| #67 | M–H | CBAR offsets ignored, OFFT unvalidated, G0 `13 0 0` read as a vector, blank PID | S2, S17, P2, P7, N1 |
| #68 | M | MAT1 blanks, RBAR CMA/CMB, GRID PS / SUPORT C digits, SPC D in SOL 144, LOAD/GRAV SID rules | S8–S11, S20, P3, P14 |
| #69 | M | Answer-changing PARAMs (INREL, G, W3, W4, LMODES) only warned | S18 |
| #70 | M | EIGRL V1/V2/ND/NORM and TABLED1 LOG/extrapolation | S12, S13, A14, P13 |
| #71 | H | WKK applied as the reciprocal of MSC's | M1, A1 |
| #72 | H | AECORR WT2 target is Γ-units, not Cp; re-ratioed at other Machs | M2 |
| #73 | H | DIVERG field 4 read as RHOREF; MSC field 4 is M1 | M5, A2, P5 |
| #74 | H | SPLINE2 axis not projected into the panel plane | M3, A15 |
| #75 | M | SPLINE2 USAGE ignored; DZ/DTOR out of range only warned | M4, A5, A18 |
| #76 | M | CAERO1 IGID ignored | M6, A6 |
| #77 | H | TRIMVAR blank bounds pin the variable; trim-card labels not cross-referenced; ZAERO field-order clash | P6, A11, A12, M10 |
| #78 | M | MASSSET: MSC name, different layout, read silently | A8, C9 |
| #79 | H | Case control drops commands above the first SUBCASE; no-SUBCASE deck writes an empty f06 | C1, C2, C5 |
| #80 | H | Case control ignores unknown commands (PARAM, AESYMXZ, SUBCOM …) | C3, C4, C10 |
| #81 | H | ENDDATA ignored; INCLUDE placement differs (sample decks unreadable by MSC) | C7, C8, P11 |
| #82 | H | F06 labels that mislead a comparison: CZ frame, URDD3, hinge moments, BOX ID | O1–O4 |
| #83 | — | Optional CI gate: pyNastran cross-parse of every repo deck | P (gate) |

### 3.2 Decisions, compatibility gaps, reuse (unscheduled)

| Issue | Kind | Title | Findings |
|---|---|---|---|
| #84 | decision | Panel normals forced to +z/+y vs MSC point-order normal (signed per-box data) | A7 |
| #85 | defect (output) | Output requests: exact spellings only, NONE/SET ignored | C6 |
| #86 | decision | MONPNT1/MONPNT3: adopt MSC layouts and meaning before v1.0 | M8, A9, P10 |
| #87 | decision | ZAERO-named cards with sbeam layouts; sbeam extensions in MSC fields | A13, A17, M11, P9 |
| #88 | capability | TRIM AEQR (0 = rigid trim) | M9, A10 |
| #89 | compat | Loud refusals of legal input (THRU, AECOMP CAERO, NSPAN+LSPAN, CONM2 CID −1 …) | S16, S17, A16, P12 |
| #90 | compat | F06: static monitor contributions, eigen columns, GPWG, titles, TRIMF | O5–O10, C11 |
| #91 | docs | Docs contradicting code or MSC | S19, A19, M14, C12 |
| #92 | enhancement | Unsupported cards ranked by benchmark consumers (GENEL/CMASS2 first) | S ranking, P (B2/B4) |
| #93 | reuse | `sbeam_tools` comparison via pyNastran (OP2 reader, importer, GPWG oracle) | P15–P17, O10 |
| #94 | benchmark | BAH wing SOL 103 (matches MSC to 0.006 %), aerobeam lateral trim; SOL 103 near-zero-mass anomalies | B1, B3, B5 |

### 3.3 Roadmap reuse (comments on existing issues)

| Issue | What MSC/ZAERO gives | Saving |
|---|---|---|
| #16 | ZAERO GLOADS/DGUST/CGUST, MINSTAT/AEROLAG instead of an invented RFA card (MSC has none); HA146A/HA146C numbers | 4–6 d |
| #13, #17 | AMODE on AESURF + AESURFS with a **y**-axis hinge (design has x); Phase 2 is standard CBAR+CBUSH+RBE2 modelling | ≈ 5 d |
| #14 | Cross-validated gates (HA145E: test/MSC/ZAERO/stick; HA145A printed numbers; NASTRAN-95 d10021a); DLM box rules; V-D3-1 is read off a different case's plots; V-D3-3 needs GENEL (#92) | 2–3 d |
| #28 | MSC SPLINE `USAGE=FORCE`, not a new card; ZAERO SPLINEF means something else | ≈ 2 d |
| #12, #15 | MKAERO1 k > 0 is mandatory (design's k = 0 rule is illegal MSC); ZAERO k = 0 insertion; OP4 with ZAERO names; MKAEROZ/SPLINEM SAVE/ACQUIRE | 2–3 d |
| #25 | Superseded by ZAERO MLOADS state-space (P0 trim term) — recommend closing | — |
| #42 | HA144E rolling pull-out numbers (verified, AAUG p.319); aerobeam roll | ready-made |
| #41, #44, #36, #43, #50, #4, #5, #18, #26, #27, #7 | M144OPEN; ungated HA144A hinge moment 2544.685; MONSUMT; AEPARM; GRIDFRC; ZTM ch. 11 design envelope; v1.0 benchmark set; partial/no reuse for #26/#27/#7 | ≈ 3 d |

## 4. Not filed

- **Integer in a real field** (`FORCE ... 5`): MSC requires a decimal point (QRG p.1047);
  sbeam reads 5.0. Lenient but never wrong — left as is.
- **SIDES sign** relative to sbeam's `SIDES = −β`: not verifiable without an MSC
  antisymmetric run.
- **LOAD SID equal to a FORCE SID**: sbeam uses the LOAD only (`load_vector.py:123`); the
  QRG text read does not state MSC's rule. Unverified.

## 5. Process observations

1. **Two recent sweeps missed members of their class.** #58 ("must be" rules) missed DIVERG
   field 4 and CBAR G0 with zeros; #55 (answer-changing input) refused three PARAMs and
   missed INREL/LMODES and the whole of case control. Both swept by reading sbeam's code
   for the pattern. The audit found the misses by reading the *external* spec card by card
   and by an independent parser. Rule 3's invariant-gate clause has a natural form for the
   card-layout class: #83 (pyNastran cross-parse) plus the consumed-everything check in #63.
2. **Rules quoted from memory were wrong in places.** #62's CBUSH table was from memory,
   and the card reference says WKK = 1.1 is a "10 % uplift", which is MSC's meaning but not
   what the code does. Every rule cited in this audit has a PDF page. The manuals are now
   available locally, so "from memory" citations should stop.
3. **sbeam's own sample decks would not run in MSC** (bulk INCLUDEs before BEGIN BULK,
   ENDDATA mid-stream, TRIM/AEROS/DIVERG extensions in MSC fields). A deck that runs in
   both codes is the cheapest benchmark there is, so #81 and #87 matter beyond tidiness.

## 6. Recommended order

1. **#63 + #64 + #83 together.** They are one change to the reader (normalise the card,
   refuse anything unconsumed), gated by the pyNastran cross-parse. Most card findings then
   become one-line handler fixes.
2. **#79, #80, #81:** the case control and file structure get the #55 rule.
3. **The answer-changers:** #71, #73, #74, #77, #66, #65 (refuse CD ≠ 0 now).
4. **#82** (output labels), then #93 (comparison tooling) and the #94 BAH SOL 103 gate.
5. **The decisions** #84, #86 and #87, before #16 and the v1.0 freeze.

## 7. Process changes (agreed 2026-11-16)

### 7.1 Why the findings were there to find

| Cause | Evidence |
|---|---|
| **C1. Sweeps read sbeam's code, not the external spec.** A sweep finds only the pattern it already knows. | #58 missed DIVERG field 4 and CBAR G0 with zeros; #55 missed INREL/LMODES and all of case control (§5.1) |
| **C2. Rules were quoted from memory.** | #62's CBUSH table; the WKK "10 % uplift" text (§5.2) |
| **C3. Cards were built field by field as needed,** with no account of the fields a handler does not read. | #63, #64, #65, #67, #68, #70, #75, #76 |
| **C4. "Refuse what you don't act on" was applied per issue, not per input surface.** | bulk data got the rule (#55); case control, file structure and most PARAMs did not (#69, #79–#81) |
| **C5. Vendor names were reused with different layouts or meanings.** | MASSSET, the MLOADS family, TRIMVAR, MONPNT1/3, WKK (#71, #77, #78, #86, #87) |
| **C6. Benchmarks were closed-form or self-consistent, never the vendor's printed number.** | WKK reciprocal, SPLINE2 axis, IGID, CONM2 sign and the CZ frame all passed CI (#66, #71, #74, #76, #82) |
| **C7. Designs invented what the vendors already define.** | an RFA card, an illegal MKAERO1 k = 0 rule, an x-axis hinge (§3.3: #16, #12, #13) |

### 7.2 Rules adopted

| # | Change | Answers | CLAUDE.md |
|---|---|---|---|
| P1 | A sweep lists the members of the class from the external manual or an independent parser, not from sbeam's code | C1 | rule 3 ‡ |
| P2 | A NASTRAN/ZAERO rule in code, docs or an issue carries the manual and PDF page; from memory it is labelled *unverified* and cannot justify a refusal, a gate or a doc statement | C2 | rule 8 |
| P3 | A design note opens with what MSC and ZAERO already do, with citations, before a new card or method is proposed | C7 | rule 1 ‡ |
| P4 | Each field of a vendor card is read, refused if non-blank, or documented as ignored with the reason | C3 | rule 7 |
| P5 | A vendor card name keeps the vendor layout (a subset with refusals is fine); an sbeam extension takes a name and fields no vendor defines | C5 | rule 7 |
| P6 | A vendor-named capability is gated on the vendor's published number where the manuals print one | C6 | rule 2 ‡ |
| P7 | Input that is not acted on is refused on every input surface: executive control, case control, bulk data, PARAM, file structure | C4 | rule 7 |

P4 and P1 have mechanical gates already: the unread-line refusal (#63) and the pyNastran
cross-parse (#83). The rules cover what those gates cannot see: a field read with the wrong
meaning, and a surface the gates do not parse.

The rules apply to new and changed work. Existing breaches are the open audit issues;
#86 and #87 decide how P5 applies to the cards already shipped.

### 7.3 Documentation changes proposed, not yet made

| # | Change | Supports |
|---|---|---|
| D1 | **Deviation register**: a single-source document in `10_standard/`, one row per known difference from MSC/ZAERO (card and field, sbeam behaviour, vendor behaviour, citation, refused / warned / different by design, issue). A known difference missing from it is a defect | P2, P5 |
| D2 | **Field-disposition table per card** in `02_card_reference.md` | P4 |
| D3 | **"External reference" column** in the verification tables in `00_program_overview.md`: MSC, ZAERO, NASTRAN-95, closed-form or none | P6 |
| D4 | **Release gate** (`08_release_process.md` §3): the register is reviewed for every card touched in the milestone; each sample deck is tagged MSC-runnable or sbeam-extension | D1, §5.3 |
