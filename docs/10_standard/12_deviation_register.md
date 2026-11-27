# sbeam — Deviation Register (sbeam vs MSC NASTRAN / ZAERO)

**The single list of known differences between sbeam and its reference programs.** One row
per difference: what sbeam does, what the vendor does, where the vendor says so, and how
sbeam handles it. Started from the 2026-11-16 compatibility audit
(`docs/50_reviews/2026-11-16_nastran_zaero_audit.md` §3–§4) and brought up to the code as
of 2026-11-26 (#95, D1). Last reviewed at a release gate: 2026-11-28, for v0.4.1. Differences the audit found that have since been fixed are not
listed; they are in `docs/40_history/`.

## Rules

1. **A known difference that is not in this register is a defect.** File it, then add the
   row.
2. **A change to a card adds, edits or removes its rows in the same commit**, and the
   release gate reviews the register for every card touched in the milestone
   (`08_release_process.md` §3).
3. **Every vendor statement carries its manual and PDF page** (CLAUDE.md rule 8). A
   statement from memory is marked *unverified* and cannot justify a refusal or a gate.
4. **This register says what differs; it does not repeat the card.** Fields, defaults and
   validation stay in `02_card_reference.md`. The whole-card lists are also kept there
   and are not copied here:
   - cards sbeam defines that no vendor has:
     [sbeam-only cards](02_card_reference.md#sbeam-only-cards);
   - vendor cards sbeam refuses outright:
     [Unsupported cards](02_card_reference.md#unsupported-cards).

**Dispositions**

| Disposition | Meaning |
|---|---|
| **refused** | Legal vendor input that sbeam does not act on. The deck is refused with a message (CLAUDE.md rule 7) |
| **warned** | Accepted with a warning; the result may differ from the vendor's as the row says |
| **ignored** | Accepted with no message. The field or command changes no sbeam result, for the reason given |
| **by design** | sbeam differs on purpose and will stay different |
| **defect** | sbeam should match the vendor and does not. The issue is in the last column |

**Manuals.** Page numbers are PDF pages. QRG = MSC Nastran 2024.1 Quick Reference Guide;
AAUG = MSC Nastran 2023.1 Aeroelastic Analysis User's Guide; ZUM = ZAERO 9.2 User's
Manual; COSMIC = NASTRAN-93 `um/BULK.TXT`.

---

## 1. File structure and input format

| Item | sbeam | Vendor | Citation | Disposition | Issue |
|---|---|---|---|---|---|
| Executive section | Not separated from case control. `CEND` is accepted and not required; `ID`, `TIME`, `DIAG`, `NASTRAN`, `ASSIGN` are skipped | Executive control ends at `CEND`, which is optional: "If CEND is not specified, then the program will automatically insert one" | QRG p.150 | ignored | — |
| `INCLUDE` relative filename | Resolved against the directory of the file holding the `INCLUDE` | Left to the installation | QRG p.1984 | by design | — |
| Bulk cards in a file INCLUDEd above `BEGIN BULK` | Refused, naming the file | The case-control INCLUDE page shows this form; the File Management and Bulk Data pages place the INCLUDE below `BEGIN BULK` | QRG p.465, p.131, p.1984 | refused | — |
| Card after `ENDDATA` | Refused | `ENDDATA` ends the bulk data; what MSC does with a later card is not stated | QRG p.1808 | refused | — |
| Integer in a real field (`FORCE … 5`) | Read as `5.0` | A real "must contain a decimal point" | QRG p.1047 | by design (lenient) | — |
| Free-field real longer than 8 characters | Kept at full precision | Rounded to 8 characters | QRG p.1048 | by design | — |
| Large field switching to small field within one row | Refused | The QRG's examples do not settle where the fields land | QRG p.1048–1052 | refused | — |
| Element ID spaces | CONM2, RBAR, RBE2, RBE3 and PLOTEL each keep their own EID space | COSMIC: every element ID unique across all elements. MSC does not enforce it for CONM2 (HA144A) | COSMIC CONM2/CRBAR/CRBE2/CRBE3 entries (#61) | by design (decided 2026-11-15) | — |
| `THRU` in an ID list | Read on AELIST. Refused on SET1, SPC1 and RBE2 with a Python `int()` message | Read on all four | QRG p.2813 (SET1), p.2835 remark 5 (SPC1) | defect | #89 |
| AELIST `a THRU b` with b < a | Accepted, giving `[a]` only, no message | Not stated | *unverified* | defect | #89 |
| Unknown `PARAM` | Skipped with a warning | Read | — | warned | — |
| Data in a field the vendor layout leaves blank | Accepted and dropped with no message on 15 cards (the "Not checked" rows of the Vendor fields tables in `02_card_reference.md`) | Not read for this case | *unverified* | defect | #109 |

## 2. Case control

Full command tables: `02_card_reference.md`, "Case Control Keywords".

| Item | sbeam | Vendor | Citation | Disposition | Issue |
|---|---|---|---|---|---|
| `SOL` | 101, 103, 144 (and `SESTATIC`, `SEMODES`, `AESTAT`) only | Many solutions | QRG p.186–187 | refused | — |
| Deck with no `SUBCASE` | Runs as one subcase, numbered 1 | The number is not stated | QRG p.465 (deck shape only) | by design | — |
| `TITLE`, `SUBTITLE`, `LABEL` continuation | Never continued | Not checked | *unverified* | by design | — |
| Abbreviations | Unique four-character prefix, checked against sbeam's command table | Checked against MSC's full command list | QRG p.209 | by design | — |
| Describers in parentheses (`DISPLACEMENT(PRINT,PUNCH) = ALL`) | Refused (`MODEXP` alone takes describers) | Read | QRG p.209 | defect | #85 |
| `DISPLACEMENT`, `SPCFORCES`, `FORCE`, `STRESS` | Always printed, whatever the value, `= NONE` included | Printed on request; `= NONE` cancels | QRG p.634 (SPCFORCES) | defect | #85 |
| Output request `= n` (a SET) | Read as "on" for every point | Output for the points of SET n | QRG p.625 | defect | #85 |
| `SET` | Integer lists and `ALL`. Real, `101/T1` and literal forms refused | All forms | QRG p.625 | refused | — |
| `GPFORCE` | Accepted with a warning; nothing written | Grid point force balance | QRG p.434 | warned | #103 |
| `TRIMF` | Accepted with a warning; the trim-load BDFs are written in every SOL 144 run, in sbeam's own layout | Trim loads to punch per its describers | QRG p.683–684 | warned | #105 |
| `OLOAD` | Prints a GRAV echo only; no applied-load vector | Applied load vector | *unverified* | defect | #22 |
| `AESYMXZ`, `AESYMXY` | Refused; symmetry is read from `AEROS` only | Override the `AEROS` symmetry | QRG p.251, p.252 remark 1 | refused | — |
| `SUBCOM`, `SYMCOM`, `SYM`, `REPCASE`, `SUBSEQ`, `SYMSEQ` | Refused | Subcase combinations | QRG p.210, p.654, p.667 | refused | — |
| `GUST` | Refused, so it is not read as an abbreviation of sbeam's `GUSTLF` | SOL 146 gust selector | QRG p.452 | refused | — |
| SOL 144 subcase with neither `TRIM` nor `DIVERG` | Refused before the run: sbeam has no case to solve for it | Not stated on the command pages | QRG p.682 (TRIM), p.316 (DIVERG) (#124) | refused | — |
| `LOAD` in a SOL 144 subcase with `DIVERG` and no `TRIM` | Refused before the run: the divergence eigenproblem takes no applied load | Not stated | QRG p.316 (#6, #124) | refused | — |
| `COMPILE`, `ALTER`, `MALTER`, `ENDALTER` | Refused | DMAP | — | refused | — |
| Any other MSC command (`MPC`, `STRAIN`, …) | Refused as unknown | Read | — | refused | — |
| `MODEXP`, `MASSCASE`, `GUSTLF`, `MANVR`, `TRIMWGT` | sbeam-only selectors | None of these names | [sbeam-only cards](02_card_reference.md#sbeam-only-cards) | by design | — |

## 3. Structure

| Item | sbeam | Vendor | Citation | Disposition | Issue |
|---|---|---|---|---|---|
| Beam theory | Euler–Bernoulli, uniform section, uncoupled bending planes | CBAR with optional shear flexibility (K1, K2) and I12 | `02_card_reference.md` PBAR | by design | — |
| PBAR `K1`, `K2`, `I12` | Non-blank K1/K2 and I12 ≠ 0 refused | Shear flexibility; coupled bending | `02_card_reference.md` PBAR (#63); QRG page *unverified* | refused | — |
| Element mass matrix | Consistent, always | Lumped by default (`COUPMASS` default −1); coupled when `PARAM,COUPMASS` > 0 | QRG p.859 | by design. A deck with no `PARAM,COUPMASS` is accepted and gives different modal results; `COUPMASS ≤ 0` written out is refused | — |
| GPWG inertias (`PARAM,GRDPNT`) | From the consistent mass matrix, so they include each CBAR's distributed rotary inertia. Mass and C.G. are the same | From the lumped mass matrix by default | QRG p.885, p.859 | by design | — |
| GRID `CD` | Degrees of freedom are not rotated. CD only rotates printed output; a partial component set or an orientation vector at a CD ≠ 0 grid is refused | CD is the frame of the grid's degrees of freedom, constraints and solution vectors | QRG p.1944 (#65) | refused | — |
| GRID `SEID` | Non-zero refused | Superelement ID | `02_card_reference.md` GRID (#58) | refused | — |
| MAT1 `A`, `TREF`, `GE` | Ignored: no thermal loads, no structural damping in any supported solution | Thermal expansion and structural damping | `02_card_reference.md` MAT1 | ignored | — |
| MAT1 stress-limit line (`ST SC SS MCSID`) | Refused as an unread line | Read | #63 | refused | — |
| CBAR offsets `W1A`–`W3B` | Non-zero refused | Applied | `02_card_reference.md` CBAR (#67) | refused | — |
| CBAR `G0` orientation | An integer in field 6 is refused | Orientation by grid | QRG p.1362 | refused | — |
| CBAR `OFFT` | Checked against the eight legal words; the offset letters have no effect because offsets are refused | Sets the offset frame | QRG p.1363 remark 7 | ignored | — |
| PBUSH `B`, `GE`, `M`, `T` lines | Refused unless every value is blank or zero. `RCV` is ignored (output only) | Damping, mass, thermal | QRG p.2494 remark 6 | refused | — |
| CBUSH `GO`, `OCID` | Refused. The element is massless | Orientation by grid; spring offset frame | QRG p.1378–1379 | refused | — |
| RBAR component sets | `CNA = 123456`, `CNB` blank only. A partial `CMB` is refused | Any legal independent/dependent split | QRG p.2692 remark 4 (#68) | refused | — |
| RBAR, RBE3 `ALPHA`, `TREF` | Ignored (RBE3 warns): no thermal loads | Thermal expansion of the rigid element | `02_card_reference.md` RBAR, RBE3 | ignored | — |
| RBE2 `ALPHA`, `TREF` | Refused with a Python `int()` message | Thermal expansion | *unverified* | defect | #89 |
| Chained rigid elements | A grid made dependent by one rigid element may not be independent in another (RBE2 GN, RBAR GA, RBE3 Gi) | Allowed | COSMIC CRBE3 remark 4 (#60) | refused | — |
| RBE3 kinematics | Same-DOF weighted average, no lever arms. Warns when an independent grid is offset from REFGRID; refuses a REFC DOF in no Ci. Full table: `02_card_reference.md` RBE3 | Weighted least-squares rigid-body fit with lever arms | COSMIC CRBE3 (#60) | warned / refused | parked |
| RBE3 `UM` | Refused | Supported | COSMIC CRBE3 remark 3 (#59) | refused | — |
| Rod-only grids | No AUTOSPC. `PARAM,AUTOSPC` is ignored with a warning and a singular stiffness is reported | Singular DOFs constrained automatically | QRG p.850 | warned | — |
| Coordinate systems | `CORD2R` only | Rectangular, cylindrical, spherical; CORD1x | [Unsupported cards](02_card_reference.md#unsupported-cards) | refused | — |
| CONM2 `CID = −1` | Refused, with the misleading message "CID=-1 not found in CORD2R" | X1–X3 are the C.G. in basic | QRG p.1449 | defect | #89 |

## 4. Loads, constraints and eigenvalue extraction

| Item | sbeam | Vendor | Citation | Disposition | Issue |
|---|---|---|---|---|---|
| SPC `D` | Non-zero refused | Enforced displacement | `02_card_reference.md` SPC (#68) | refused | — |
| GRAV `CID` | Non-zero refused | Any coordinate system | `02_card_reference.md` GRAV | refused | — |
| GRAV `MB` | Ignored: it says where a superelement run finds CID | Superelement control | QRG p.1941 | ignored | — |
| Nested `LOAD` | A LOAD naming another LOAD is refused | Permitted | QRG p.2008 remark 5 | defect | #89 |
| `LOAD` SID equal to a `FORCE` SID | Accepted; the LOAD is used alone | Not stated in the text read | *unverified* (audit §4) | by design | — |
| `GRAV` in a SOL 144 trim `LOAD` | Refused: gravity enters a trim through `URDD3` | Not read for this case | *unverified* (#6) | refused | — |
| `PARAM,INREL` | Non-zero refused: SOL 101 has no inertia relief | Inertia relief | QRG p.888 (#69) | refused | — |
| EIGRL `V1`, `V2` | Refused; also refused with every field blank. Only "ND given: lowest ND roots" is implemented | Roots chosen from V1, V2 and ND together | QRG p.1802 Table 9-13 (#70) | refused | — |
| EIGRL `MSGLVL`, `MAXSET`, `SHFSCL` | Ignored: they steer MSC's Lanczos, not the roots | Lanczos controls | `02_card_reference.md` EIGRL | ignored | — |
| EIGRL option line (`NORM=MAX`) | Refused as an unread line; NORM is read in field 9 | Read | #63 | refused | — |
| `PARAM,G`, `W3`, `W4`, `LMODES` | Non-zero refused | Structural damping; modes kept | QRG p.884, p.956, p.895 (#69) | refused | — |
| `PARAM,WTMASS` | ≠ 1 refused: sbeam never scales mass | Scales mass | `09_conventions.md` §7 (#39) | refused | — |

## 5. Aerodynamics, splines and trim

| Item | sbeam | Vendor | Citation | Disposition | Issue |
|---|---|---|---|---|---|
| Aerodynamic method | Steady vortex lattice | MSC: doublet lattice at k = 0. ZAERO: ZONA6 | `05a_aero_vlm.md`; vendor page *unverified* | by design until the DLM | #14 |
| Symmetry | Full-span models only. AEROS `SYMXZ`/`SYMXY` non-zero refused | Half models with symmetry | `02_card_reference.md` AEROS | refused | — |
| Derivatives against MSC's half-model listings | Twice MSC's on a full-span deck of the same airplane | Half-model values | AAUG p.234–235 (`09_conventions.md` §6) | by design | — |
| Derivative coefficient frame | Basic axes; the f06 prints MSC's basic-to-reference transformation `[T]` | Reference (RCSID) axes | AAUG p.233 (`09_conventions.md` §1, #82) | by design | — |
| AEROS `ACSID` | A CORD2R rotated from basic is refused: the freestream is basic +x | Any rectangular system | `02_card_reference.md` AEROS (#58) | refused | — |
| `PARAM,AUNITS` | ≠ 1 refused: TRIM `URDD*` are in model units | Accelerations entered in g | `09_conventions.md` §7 (#55) | refused | — |
| CAERO1 `IGID` | More than one value in a deck refused: one AIC over every panel | Groups with different IGIDs are uncoupled | QRG p.1343 (#76) | refused | — |
| CAERO1 `NSPAN` and `LSPAN` both given | Refused (same for `NCHORD`/`LCHORD`) | LSPAN used "only if NSPAN is zero or blank" | QRG p.1343 | defect | #89 |
| Panel normal | Solved on a normal forced to +z or +y; signed card data and the printed `DELTA-CP` are along MSC's element normal, so the cards read as MSC's | Element normal from the point order | `09_conventions.md` §2–§3 (#84) | by design (no difference at the card) | — |
| PAERO1 `B1`–`B6` | Ignored: sbeam has no CAERO2, and a deck holding one is refused | IDs of the CAERO2 bodies associated with the panel | QRG p.2413 | ignored | — |
| AEFACT end points | Not checked | End points other than 0.0 and 1.0 allowed | QRG p.1344 (CAERO1 remark 2) | by design | — |
| `W2GJ`, `WKK` as cards | sbeam-only cards | Matrices by `DMI`, `DMIJ`, `DMIK` | AAUG p.144 | by design | — |
| `DMI` W2GJ / WKK | Refused: the row numbers need the j-set order of the CAERO1 entries, which the manuals do not state. `sample/ha144a/HA144A.bdf` does not run | Read | AAUG p.134–136 (#104) | refused | — |
| `DMIJ` / `DMIK` | Read for `W2GJ` / `WKK` only. Refused: other names (FA2J, WTFACT), complex terms, more than one W2GJ column, a WKK off the diagonal or with unequal force and moment terms | Any matrix | QRG p.1617–1619, p.1623–1625 (#104) | refused | — |
| DMIJ/DMIK term on a component MSC does not use | Refused | Dropped without a warning | QRG p.1617–1619, p.1623–1625 (remark 2) | by design (stricter) | — |
| AESTAT labels | MSC's standard labels only; any other refused | A user label needs AELINK or DMI data | QRG p.1153 Table 1, p.1154 remark 3 | refused | — |
| `SUPORT` naming one grid twice | Accepted with no message; both entries are kept | Not stated. One entry may hold several grid/component pairs, and r-set degrees of freedom "may not be specified on other entries that define mutually exclusive sets" | QRG p.2870 remarks 4–5 | defect | #125 |
| AESURF `NOLDW` and continuation (`CREFC`, `CREFS`, limits) | Refused | Read | #63 | refused | #44 |
| AECOMP `LISTTYPE` | `AELIST` and `SET1`. `CAERO` and `CMPID` refused; `AECOMPL` not supported | All list types | QRG p.1138 | defect | #89 |
| `SPLINE1` | Not implemented; the card is refused | Infinite-plate spline | QRG p.2847 | refused | parked |
| SPLINE2 `USAGE` | `BOTH` or blank. `FORCE` and `DISP` refused | Separate force and displacement splines | QRG p.2848 remark 5, p.2850 remark 9 (#75) | refused | #28 |
| TRIM `AEQR` | Blank or 1.0. Any other value refused | 0.0 = rigid trim; intermediate values scale the elastic feedback | QRG p.2992; AAUG p.143 | refused | #88 |
| DIVERG Mach 0.0 | Accepted | The QRG says Mi > 0.0; MSC's own example enters 0.0 | QRG p.1603; AAUG p.148 | by design | — |
| TRIMVAR (ZAERO) | `TRIMLNK`, `DMI` and `DCD`–`DCN` refused unless blank. `SYM` ignored: sbeam prints longitudinal and lateral derivatives in every run. `LABEL` is an sbeam AESTAT/AESURF label | Linked variables, user derivatives, ZAERO's labels | ZUM p.511 (#87) | refused / ignored | — |
| MSC `MASSSET` increment sections | CONM2 only; every other card refused. `BEGIN SUPER=n MASSID=m` refused | Element mass properties and materials are also taken; grids and parameters are ignored | QRG p.482 remark 2 (#102) | refused | — |
| TABLED1 `XAXIS`/`YAXIS` | `LINEAR` only; `LOG` refused | Linear or log | `02_card_reference.md` TABLED1 (#70) | refused | — |
| TABLED1 `ENDT` | A table that does not end in `ENDT` is accepted | The layout ends the table with `ENDT` | QRG p.2896 | by design (lenient) | — |

## 6. Monitor points and output

| Item | sbeam | Vendor | Citation | Disposition | Issue |
|---|---|---|---|---|---|
| MONPNT1 `CD` | Blank or equal to CP; output is in CP | Output in CD | `02_card_reference.md` MONPNT1 (#86) | refused | — |
| MONPNT1 names | An aerodynamic and a structural MONPNT1 may not share a NAME: output is keyed by name | May share a name | QRG p.2303–2304 remark 2 (#86) | refused | — |
| `MONPNT3` | Refused: no grid point forces | Sums grid point forces to a monitor point | QRG p.2307–2308 | refused | #103 |
| Monitor output | Columns TOTAL, AERO, INERTIA, APPLIED, REACTION; type printed as `MONPNT1` (aerodynamic) or `MONPNT3` (structural) | Columns RIGID AIR, ELASTIC RESTRAINED, INERTIAL, RIGID APPLIED, ELASTIC APPLIED; aerodynamic and structural headings | AAUG p.236, p.238 | defect | #103 |
| f06 layouts | MSC's layout for the blocks listed in `03`/`04`/`05c`; not a byte-for-byte copy. Comparison with MSC goes through OP2/pyNastran | — | #90 | by design | #93 |

---

## Adding a row

- Name the card and field, not the symptom.
- State the vendor's behaviour from the manual, with the PDF page. If the manual was not
  read for it, write *unverified*.
- A **defect** row names its issue and is deleted by the commit that fixes it. A
  **refused** row whose capability is later implemented is deleted the same way.
- Field-by-field dispositions of each vendor card (read / refused / ignored) are in the
  "Vendor fields" table of the card's section of `02_card_reference.md`, gated by
  `tests/docs/test_field_dispositions.py`; this register carries only the fields where
  the difference matters to a result or to whether a vendor deck runs.
