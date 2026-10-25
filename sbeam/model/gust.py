"""Gust load-factor case card (FAR/CS 23.341).

Design note: ``docs/30_future/designs/gust_pratt_23341.md`` (issue #1).

``GUSTLF`` is a **provenance card**.  Only ``trimid``, ``n`` and ``g`` affect the
solution — the referenced TRIM supplies the flight condition and every prescribed
label except ``URDD3``, which this card supplies as ``-n*g``.  Every other field
is *recorded* by the generating tool and echoed to the f06, never entering an
equation.

That split is deliberate.  The 23.341 gust calculation is dimensional (``U_de``
is 50 ft/s, the schedule is keyed to altitude in feet) while conventions charter
§7 forbids unit-converting fields anywhere in sbeam, and the solver has no
atmosphere model.  So the dimensional half lives in
``sbeam_tools/cases/gust.py`` and the solver receives only the dimensionless
load factor.  sbeam does **not** compute, and cannot verify, the gust
derivation — the f06 block says so in the listing itself.
"""

from dataclasses import dataclass
from typing import Optional


# ``K_g = 0.88 mu / (5.3 + mu)`` is strictly increasing in ``mu`` and tends to
# 0.88, so a recorded value outside this open interval cannot have come from the
# regulation's formula.  It is the one piece of the derivation the parser can
# falsify without owning the arithmetic.
KG_MAX = 0.88


@dataclass
class Gustlf:
    """One quasi-static gust load case applied to a referenced TRIM.

    Attributes:
        sid: Set ID; referenced by case control ``GUSTLF = sid``.
        trimid: TRIM SID supplying Q, MACH and every prescribed label but URDD3.
        n: Gust load factor.  **Used** — the solver prescribes ``URDD3 = -n*g``.
            Negative for a down-gust that overcomes 1 g.
        g: Gravitational acceleration in model units.  **Used**.
        ude: Derived gust velocity ``U_de`` (EAS).  Recorded only.
        veas: Equivalent airspeed at the condition.  Recorded only.
        kg: Gust alleviation factor ``K_g``.  Recorded only.
        mu: Mass ratio ``mu``.  Recorded only.
        a: Airplane normal-force curve slope per radian.  Recorded only.
        asrc: Which derivative set ``a`` came from — ``RIGID`` or ``RESTRAINED``.
        alt: Altitude of the condition, or ``None`` when not recorded.
            Recorded only.

    The optional provenance fields use ``0.0`` to mean "not recorded", which is
    unambiguous for all of them but one: a zero gust velocity, airspeed,
    alleviation factor, mass ratio or lift slope is physically meaningless, so
    zero cannot be a real reading.  **Altitude is the exception** — sea level is
    a real and common condition — so ``alt`` is ``Optional`` and ``None`` is its
    absence.
    """

    sid: int
    trimid: int
    n: float
    g: float
    ude: float = 0.0
    veas: float = 0.0
    kg: float = 0.0
    mu: float = 0.0
    a: float = 0.0
    asrc: str = "RIGID"
    alt: Optional[float] = None

    @property
    def urdd3(self) -> float:
        """The prescribed vertical acceleration, ``-n*g`` (charter §5).

        Authored in the RCSID frame, which presumes a z-DOWN (stability-axes)
        RCSID — see ``sbeam.model.maneuver_presets.load_factor_to_urdd3``, which
        owns this sign, and the RCSID orientation guard in ``sol144``.
        """
        from .maneuver_presets import load_factor_to_urdd3

        return load_factor_to_urdd3(self.n, self.g)

    @property
    def sense(self) -> str:
        """``UP-GUST`` when ``n > 1``, else ``DOWN-GUST`` — a label, not physics."""
        return "UP-GUST" if self.n > 1.0 else "DOWN-GUST"
