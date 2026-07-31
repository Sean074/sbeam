"""ZAERO-style transient maneuver-loads card set (Phase G0).

These cards drive the DLM-free quasi-steady transient maneuver-loads solver
(`sbeam/solver/maneuver_qs.py`).  They adopt ZAERO's ``MLOADS`` vocabulary so a
deck author familiar with ZAERO transient maneuver analysis recognises the
inputs, but the implementation is restricted to Phase G0 increment 1:

  * Level 1 quasi-steady aerodynamics (steady VLM evaluated at the instantaneous
    rigid-body rates / attitude — no DLM, no lag/apparent-mass states), and
  * open-loop control (prescribed pilot-command time histories; no closed-loop
    control law).

Card orchestration::

    MLOADS  ──references──▶ MLDTRIM (steady-state initial condition = a TRIM sid)
        │                   MLDTIME (integration window t0/tend/dt/tout)
        │                   MLDCOMD (pilot command label → TABLED1 time history)
        └─────────────────▶ MLDPRNT (ASCII time-history output request)

``TABLED1`` is the general tabular (time → value) function the commands point to.
"""

from dataclasses import dataclass, field
import numpy as np


@dataclass
class Tabled1:
    """Tabular function y(x) with linear interpolation (NASTRAN/ZAERO TABLED1).

    For pilot-command time histories ``x`` is time and ``y`` is the commanded
    value (e.g. a control-surface deflection or a load-factor target).  Values
    are held constant (clamped) outside the tabulated range — appropriate for a
    pilot input that ramps to a steady deflection and then holds.
    """
    tid:   int
    xs:    list[float] = field(default_factory=list)   # abscissae (time)
    ys:    list[float] = field(default_factory=list)   # ordinates (command)
    xaxis: str = "LINEAR"                         # LINEAR or LOG (only LINEAR honoured)
    yaxis: str = "LINEAR"

    def evaluate(self, x: float) -> float:
        """Linear interpolation with constant (held) extrapolation at the ends."""
        xs = self.xs
        if not xs:
            return 0.0
        if x <= xs[0]:
            return self.ys[0]
        if x >= xs[-1]:
            return self.ys[-1]
        # xs are assumed monotonically increasing (validated at parse time)
        return float(np.interp(x, xs, self.ys))


@dataclass
class Mldtime:
    """Time-integration window for a transient maneuver run."""
    sid:  int
    t0:   float            # start time
    tend: float            # end time
    dt:   float            # integration time step
    tout: float = 0.0      # output sampling interval (0 ⇒ every step, = dt)


@dataclass
class Mldcomd:
    """Pilot/control command time histories.

    ``commands`` pairs a trim-variable label (AESTAT or AESURF label, e.g.
    ``ELEV`` or ``ANGLEA``) with the TABLED1 sid giving its commanded value
    versus time.  Labels not commanded here remain at their initial-trim value.
    """
    sid:      int
    commands: list[tuple[str, int]] = field(default_factory=list)   # [(label, tabid)]


@dataclass
class Mldprnt:
    """ASCII time-history output request.

    ``items`` is an optional list of quantity keywords to print (e.g. ``STATE``,
    ``CONTROL``, ``LOADS``); empty means print all available time histories.
    """
    sid:   int
    items: list[str] = field(default_factory=list)


@dataclass
class Mldtrim:
    """Steady-state initial condition — references a static TRIM sid (Step 53)."""
    sid:      int
    trim_sid: int


@dataclass
class Mloads:
    """Top-level transient maneuver-loads driver (references the sub-cards).

    ``nmodes``/``method``/``zeta`` configure the free-free modal basis (Step 61):
    ``method`` selects the EIGRL used for the basis eigensolve (0 ⇒ an internal
    all-modes default), ``nmodes`` is the number of retained **elastic** modes
    (rigid modes are always all retained; 0 ⇒ all elastic), and ``zeta`` is the
    uniform elastic modal damping ratio.  The Step 61 basis/operator layer is
    built and validated standalone; the modal transient solver that consumes it
    lands with Step 62, so the legacy quasi-steady solver still ignores all three.
    """
    sid:        int
    mldtrim:    int            # MLDTRIM sid (initial condition)
    mldtime:    int            # MLDTIME sid (integration window)
    mldcomd:    int = 0        # MLDCOMD sid (0 ⇒ no commands; hold trim)
    mldprnt:    int = 0        # MLDPRNT sid (0 ⇒ no ASCII print)
    nmodes:     int = 0        # retained ELASTIC modes (0 ⇒ all available)
    method:     int = 0        # EIGRL sid for the basis solve (0 ⇒ internal default)
    zeta:       float = 0.0    # uniform elastic modal damping ratio
