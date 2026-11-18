# SPLINE2 — spline axis projected into the panel plane (#74)

**Status:** implemented 2026-11-18 (#74). Agreed with the v0.4.0 completion plan.
**Finding:** M3 / A15 of `docs/50_reviews/2026-11-16_nastran_zaero_audit.md`.

## What MSC does

MSC Nastran 2024.1 Quick Reference Guide, PDF p.2849, SPLINE2:

- CID: "Rectangular coordinate system for which the y-axis defines the axis of the
  spline."
- Remark 2: "The spline axis for panels is the projection of the y-axis of coordinate
  system CID, projected onto the plane of the panel."

So MSC reads one axis of CID. The plane the spline deflects out of is the panel's.

## What sbeam did, and the assumption that stops holding

`_build_spline2_block` took all three CID axes: ŝ = CID y, ĉ = CID x, ẑ = CID z. The
assumption "**the CID z-axis is the panel normal**" holds only when the author cants the
CID by hand. Where it fails:

- `g_disp` carries the box displacement as `w·ẑ_CID`, so the transposed force transfer
  delivers `F·ẑ_CID` along ẑ_CID. With CID 0 on a dihedral wing that is the basic-z
  component only: the side force is dropped.
- `g_slope` is built from the same `w`, so the normalwash is that of a deflection along
  ẑ_CID, not along the normal.

DEF-M11 removed the same assumption from ATTACH; SPLINE2 was not swept then.

## Change

Per SPLINE2, over the boxes it covers (`spline._spline2_frame`):

    ẑ = panel normal (the boxes' common normal)
    ŝ = unit(y_CID − (y_CID·ẑ) ẑ)
    ĉ = ŝ × ẑ
    origin = CID origin

Refused: a y-axis normal to the panel (no projection); a box range not in one plane.
Conventions charter: no convention changes (`09_conventions.md` §1–2 keep basic axes and
the panel normal as meshed).

## Predictions and what was observed

| Case | Prediction | Observed |
|---|---|---|
| `val_dihedral_trim.bdf` with SPLINE2 CID 0, unit pressure, per semi-span | grid ΣF = box ΣF = (0, ∓0.69459, 3.93923) | equal to 1e-12 (was Fy = 0) |
| Same deck, trim ANGLEA vs the hand-canted deck | close, not identical: CID 0 puts the axis through the basic origin, 0.25 ahead of the spar | −0.0520601 vs −0.0520617 (3e-5) |
| Uncanted CID at the canted CID's origin | same operators as the canted deck | equal to 2e-9 (the canted CORD2Rs carry 8 digits) |
| Decks whose CID y is in the panel plane and CID z is the normal (HA144A family, lateral, thrust, cantilever) | operators unchanged | max difference 0.0 |
| Flagship | **not predicted in the plan, which called it planar.** Its wing has 1.5° dihedral and a swept elastic axis; CID 991/992 z was "global Z made orthogonal to y", which is 0.024° off the panel normal (x-component 4.22e-4) | operators move by 4.18e-4 = sin 0.024° |

The flagship difference is the defect at small scale. The old operator put a chordwise
force of 4.22e-4 × Fz on the wing grids: the starboard wing-root monitor read
FX = 1.48 N, and reads 0 after the change. Flagship numbers that move:

| Quantity | Before | After |
|---|---|---|
| 1g ANGLEA (rad) | 0.04174227 | 0.04174605 |
| 1g ELEV (rad) | −0.06792834 | −0.06796414 |
| 2.5g ELEV (rad) | −0.1719408 | −0.1720284 |
| Unrestrained Cm_α | −1.624168 | −1.625212 |
| Q-DIV | 5.373047E+04 | 5.373092E+04 |
| MWROOT FX / MX / MZ at 1g | 1.48 / 8355.9 / −6.19 | 0.00 / 8356.7 / −1.57 |

Rigid and restrained derivatives are unchanged to six figures. The MLOADS deck's absolute
elevator table (`TABLED1 300`) starts at the 1g trim and was re-baked to −0.06796414.

## Gates

`tests/aero/test_spline2_panel_plane.py`:

- CID-0 dihedral: force and moment transfer per semi-span equal the box resultants.
- Only the y-axis is read: an uncanted CID gives the canted deck's operators.
- A y-axis normal to the panel is refused.
- **Invariant, every repo deck with a SPLINE2:** each of the six rigid-body motions moves
  every splined box by `n(n·(t + ω×r))` and gives it the incidence `ω_y n_z − ω_z n_y`.
  This holds only if the deflection direction is the box normal; the flagship decks fail
  it at 4e-4 on the old code.

## Sweep for the assumption (rule 3)

Every use of a card CID in `sbeam/aero/` and `sbeam/solver/sol144*.py` was read:

- ATTACH: general in the box normal since DEF-M11 / DEF-H1.
- AESURF hinge (`integration.aesurf_hinges`): reads CID y as the hinge axis and takes the
  normalwash from `−(ĥ × n)·x̂` with the box normal. No CID-z assumption.
- AEROS RCSID, CAERO1 CP: frames for reference axes and point input, not normals.

SPLINE2 was the only remaining user.
