"""Standard maneuver-case presets for SOL 144 balanced-maneuver trim (Step 53).

These are *authoring* conveniences: they translate a familiar maneuver
description (a load factor, a steady rate) into the prescribed ``AESTAT`` trim
values a ``TRIM`` card carries.  The solver itself consumes only the resulting
prescribed values — no new card is introduced.

Gravity is folded into the load factor (NASTRAN convention): for a symmetric
pull-up the prescribed vertical acceleration is ``URDD3 = -n_z * g`` in the
RCSID frame (z-down), so the inertia-relief load ``-M*a`` carries the full
``n_z * W`` weight reaction and no separate ``GRAV`` term is added in trim.

Recipes (prescribe these labels on the TRIM card; leave the rest free; one free
label per SUPORT DOF for a determined trim — ``docs/10_standard/05c_sol144_maneuver.md``
"Lateral trim cases", ``sample/val_lateral_aileron_rudder.bdf``):

  * Symmetric pull-up / push-over (SUPORT 35):  URDD3 = load_factor_to_urdd3(n_z, g),
    URDD5 = 0, and PITCH = (n_z − 1)·g·c_ref/(2V²) — the steady pitch rate of the
    pull-up as a reduced rate (0 only for level flight; a push-over at n_z < 1 has
    a negative rate).  Free: ANGLEA + elevator AESURF (balance lift & pitch).
    The flagship ``TRIM 2`` carries this value.
  * Steady roll (SUPORT 4):  ROLL = pb/2V (reduced rate, positive = starboard
    wing down), URDD4 = 0.  Free: aileron AESURF (one label — the CID1/CID2
    pair).  Roll damping comes from the antisymmetric VLM (build_djx ROLL column).
  * Steady sideslip (SUPORT 6):  SIDES = beta (positive = wind from port, −β
    textbook), YAW = 0.  Free: rudder AESURF.
  * Both together (SUPORT 46, the validation deck): prescribe ROLL or SIDES plus
    the other lateral labels, free AIL and RUD.
"""


def load_factor_to_urdd3(n_z: float, g: float) -> float:
    """Vertical URDD3 acceleration (RCSID z-down) for a load factor ``n_z``.

    Returns ``-n_z * g``.  A 1 g level condition is ``load_factor_to_urdd3(1, g)
    = -g``; a 2.5 g pull-up is ``-2.5 g``; a push-over uses ``n_z < 1`` (or a
    negative load factor for an outside maneuver).

    Args:
        n_z: maneuver load factor (1.0 = level flight).
        g:   gravitational acceleration in the model's unit system.

    Returns:
        The prescribed URDD3 value for the TRIM card.
    """
    return -n_z * g
