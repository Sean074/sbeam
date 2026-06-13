"""Standard maneuver-case presets for SOL 144 balanced-maneuver trim (Step 53).

These are *authoring* conveniences: they translate a familiar maneuver
description (a load factor, a steady rate) into the prescribed ``AESTAT`` trim
values a ``TRIM`` card carries.  The solver itself consumes only the resulting
prescribed values — no new card is introduced.

Gravity is folded into the load factor (NASTRAN convention): for a symmetric
pull-up the prescribed vertical acceleration is ``URDD3 = -n_z * g`` in the
RCSID frame (z-down), so the inertia-relief load ``-M*a`` carries the full
``n_z * W`` weight reaction and no separate ``GRAV`` term is added in trim.

Recipes (prescribe these labels on the TRIM card; leave the rest free):

  * Symmetric pull-up / push-over:  URDD3 = load_factor_to_urdd3(n_z, g),
    PITCH = 0.  Free: ANGLEA + elevator AESURF (balance lift & pitch).
  * Steady roll:  ROLL = p (nondimensional roll rate), URDD4 = 0 (steady).
    Free: aileron AESURF.  Roll damping comes from the antisymmetric VLM
    (build_djx ROLL column).
  * Steady sideslip:  SIDES = beta, YAW = 0.  Free: rudder AESURF.
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
