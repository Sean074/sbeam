"""Design-review verification script — HA144A trim vs MSC Nastran reference.

NOT part of the test suite; throwaway review artifact.
"""
import warnings
import numpy as np

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.assembly.load_vector import build_grid_index
from sbeam.aero.aero_model import build_aero_model
from sbeam.solver.sol144 import run_sol144_trim

np.set_printoptions(precision=5, suppress=True, linewidth=160)

cc, bulk = parse_bdf("sample/ha144a_fullspan_sbeam.bdf")
grid_index = build_grid_index(bulk)

print("=== Parse check ===")
print("aeros:", bulk.aeros)
print("n grids:", len(bulk.grids), "caero1s:", list(bulk.caero1s))
print("trims:", {k: (t.mach, t.q, t.vars) for k, t in bulk.trims.items()})
print("w2gj first/last:", bulk.w2gjs[1].data[0], bulk.w2gjs[1].data[-1],
      "len", len(bulk.w2gjs[1].data))
print("subcases:", [(s.subcase_id, s.trim_sid, s.spc_sid) for s in cc.subcases])

with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    aero = build_aero_model(bulk, grid_index=grid_index)

print("\nn boxes:", len(aero.boxes), "mach used:", aero.mach)

# ---------------------------------------------------------------------------
# Rigid-body spline kinematics checks
# ---------------------------------------------------------------------------
print("\n=== Spline rigid-body checks ===")
n_g = 6 * len(grid_index)

# (a) uniform plunge Tz=1 on every grid -> incidence should be 0 everywhere
u = np.zeros(n_g)
for gid, gi in grid_index.items():
    u[6 * gi + 2] = 1.0
inc = aero.g_slope @ u
print("plunge: max|incidence| =", np.abs(inc).max(), "(expect 0)")
disp = aero.g_disp @ u
print("plunge: g_disp z rows min/max =", disp[2::3].min(), disp[2::3].max(), "(expect 1,1)")

# (b) rigid pitch theta=1e-3 about y-axis through x0=15 (GRID 90):
#     u_z = -theta*(x-x0), Ry = +theta everywhere (nose-up).
#     Expect uniform incidence = +theta at every box.
theta = 1e-3
x0 = 15.0
u = np.zeros(n_g)
for gid, gi in grid_index.items():
    g = bulk.grids[gid]
    u[6 * gi + 2] = -theta * (g.x - x0)
    u[6 * gi + 4] = theta
inc = aero.g_slope @ u
wing = [b.k for b in aero.boxes if b.caero_eid == 1100]
can = [b.k for b in aero.boxes if b.caero_eid == 1000]
print(f"rigid pitch {theta=}: wing incidence min/max = {inc[wing].min():.3e} {inc[wing].max():.3e} (expect {theta:.1e})")
print(f"rigid pitch {theta=}: canard incidence min/max = {inc[can].min():.3e} {inc[can].max():.3e} (expect {theta:.1e})")
dz = (aero.g_disp @ u)[2::3]
exp_dz = np.array([-theta * (b.colloc[0] - x0) for b in aero.boxes])
print("rigid pitch: max|g_disp_z - (-theta*(x_colloc-x0))| =", np.abs(dz - exp_dz).max())

# (c) pure twist of wing elastic axis: rotate wing grids about the EA
#     axis x_hat=(-0.5,0.866,0) by phi=1e-3 (positive about that axis).
#     Physical streamwise incidence = +phi*x_hat_y = 0.866e-3 (alpha = omega_y).
phi = 1e-3
ax = np.array([-0.5, 0.8660254, 0.0])
omega = phi * ax
ea_origin = np.array([30.0, 0.0, 0.0])
u = np.zeros(n_g)
wing_grids = [100, 110, 111, 112, 120, 121, 122]
for gid in wing_grids:
    g = bulk.grids[gid]
    r = np.array([g.x, g.y, g.z]) - ea_origin
    uz = np.cross(omega, r)
    gi = grid_index[gid]
    u[6 * gi + 0:6 * gi + 3] = uz
    u[6 * gi + 3:6 * gi + 6] = omega
inc = aero.g_slope @ u
print(f"EA twist phi={phi}: wing incidence min/max = {inc[wing].min():.3e} {inc[wing].max():.3e} "
      f"(physical expectation = omega_y = {omega[1]:.3e})")

# ---------------------------------------------------------------------------
# Force application point check: lift a single unit cp on one wing box and
# see where the equivalent load lands on the structure (moment vs force).
# ---------------------------------------------------------------------------
print("\n=== Force transfer point check ===")
j = wing[0]
b0 = aero.boxes[j]
cp = np.zeros(len(aero.boxes))
cp[j] = 1.0
fbox = aero.skj @ cp
fg = aero.g_disp.T @ fbox
Fz = fg[2::6].sum()
# resultant x location from My about origin: sum over grids of (Fz*x - My_y)
My = 0.0
for gid, gi in grid_index.items():
    g = bulk.grids[gid]
    My += -fg[6 * gi + 2] * g.x + fg[6 * gi + 4]
x_eff = -My / Fz
print(f"box k={j}: bound-vortex x = {0.5*(b0.bound_a[0]+b0.bound_b[0]):.4f}, "
      f"colloc x = {b0.colloc[0]:.4f}, structural resultant x = {x_eff:.4f}")

# ---------------------------------------------------------------------------
# Trim solves
# ---------------------------------------------------------------------------
print("\n=== HA144A trim (NASTRAN ref: SC1 ANGLEA=0.169191, ELEV=0.492457;"
      " SC2 ANGLEA=0.001373, ELEV=0.019325) ===")
for sub in cc.subcases:
    try:
        res = run_sol144_trim(bulk, sub, aero)
        print(f"\nSubcase {sub.subcase_id} q={res.q}: trim_vars =",
              {k: round(v, 6) for k, v in res.trim_vars.items()})
        print(f"  total CL = {res.total_cl:.5f}  total CM = {res.total_cm:.5f}")
        wt = 8000.0 / 32.174  # slug weight equivalent; expected CL*q*S = 8000 lb
        print(f"  lift = CL*q*S = {res.total_cl * res.q * bulk.aeros.sref:.1f} lb (expect ~8000 lb up)")
        rd = res.rigid_derivs
        print("  rigid derivs CZ/CMY:",
              {k: (round(v['CZ'], 4), round(v['CMY'], 4)) for k, v in rd.items()})
    except Exception as e:
        import traceback
        traceback.print_exc()
        break
