# wbt_loads tabulated strip-aero database (reference copy)

Carried over from the archived `wbt_loads` project (Sean074/wbt_loads, commit
2ddc791, 12 Oct 2026) on 21 Oct 2026 before that project was archived. Kept
here as reference for a future importer that would feed
`sbeam_tools/corrections/section_data.py` from a CFD or wind-tunnel strip
database. Build it only when a real data set needs it (sbeam rule 5); nothing
in sbeam imports these files.

| File | What it is |
|---|---|
| `loads_aero_db.md` | The spec: two-tier CSV schema (baseline per power × flap configuration, increments per control deflection), column names, interpolation and Mach extrapolation policy |
| `aero_db.py` | Reference implementation: loads the CSVs, 4-D/5-D interpolation of `cn/cm/cc_sec_nd` over station, alpha, beta, Mach (and deflection), Prandtl-Glauert extrapolation above the tabulated Mach range |
| `generate_d328_model.py` | Generator for a synthetic Dornier 328-class sample database, useful as a test fixture for any importer |

`aero_db.py` depends on numpy, pandas and scipy and is written against
wbt_loads' repository layout; treat it as a worked example, not as code to
import.
