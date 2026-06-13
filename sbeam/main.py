"""sbeam command-line solver entry point."""

import argparse
import sys
from pathlib import Path

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.f06_writer import (
    build_f06_sol101_text,
    build_f06_sol103_text,
    build_f06_sol144_text,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sbeam",
        description="sbeam — Simple Beam FEA solver",
    )
    parser.add_argument("bdf", help="Input BDF file (must contain a SOL case control statement)")
    args = parser.parse_args()

    bdf_path = Path(args.bdf).resolve()
    if not bdf_path.exists():
        sys.exit(f"Error: file not found: {bdf_path}")

    f06_path = bdf_path.with_suffix(".f06")

    try:
        cc, bulk = parse_bdf(str(bdf_path))
    except Exception as exc:
        sys.exit(f"Parse error: {exc}")

    sol144_results = None
    try:
        if cc.sol == 101:
            from sbeam.solver.sol101 import run_sol101
            results = {sc.subcase_id: run_sol101(bulk, sc) for sc in cc.subcases}
            build_text = build_f06_sol101_text
        elif cc.sol == 103:
            from sbeam.solver.sol103 import run_sol103
            results = {sc.subcase_id: run_sol103(bulk, sc) for sc in cc.subcases}
            build_text = build_f06_sol103_text
        elif cc.sol == 144:
            # SOL 144 needs a prebuilt AeroModel + grid_index (not the two-arg
            # solver pattern of 101/103). Build the aero model once, share an
            # AeroCache across subcases so multi-Mach decks build each AIC once.
            from sbeam.aero.aero_model import build_aero_model
            from sbeam.assembly.load_vector import build_grid_index
            from sbeam.solver.sol144 import run_sol144_trim, AeroCache
            grid_index = build_grid_index(bulk)
            aero = build_aero_model(bulk, grid_index=grid_index)
            cache = AeroCache(bulk, grid_index, seed=aero)
            results = {
                sc.subcase_id: run_sol144_trim(bulk, sc, aero, aero_cache=cache)
                for sc in cc.subcases
            }
            build_text = build_f06_sol144_text
            sol144_results = results
        else:
            sys.exit(f"Error: SOL {cc.sol} is not supported")
    except Exception as exc:
        sys.exit(f"Solver error: {exc}")

    with open(f06_path, "w") as fh:
        for sc_id, result in results.items():
            fh.write(build_text(cc, bulk, result, sc_id))

    print(f"Written: {f06_path}")

    # SOL 144: also export the trimmed flight loads as FORCE/MOMENT cards for
    # downstream stress analysis (one card block per subcase, SID = subcase id).
    if sol144_results is not None:
        from sbeam.results.load_export import (
            write_aero_load_cards, write_maneuver_load_cards,
        )
        loads_path = bdf_path.with_suffix(".aero_loads.bdf")
        write_aero_load_cards(str(loads_path), bulk, sol144_results)
        print(f"Written: {loads_path}")
        # Step 53: net (aero + inertial) balanced-maneuver loads for stress.
        man_path = bdf_path.with_suffix(".maneuver_loads.bdf")
        write_maneuver_load_cards(str(man_path), bulk, sol144_results)
        print(f"Written: {man_path}")
