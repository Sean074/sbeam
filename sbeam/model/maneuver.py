"""sbeam's transient maneuver-loads card set (Phase G0): MANVR, MANTRIM, MANTIME, MANCMD, MANPRNT.

These cards drive the DLM-free quasi-steady transient maneuver-loads solver
(`sbeam/solver/maneuver_qs.py`).  They are sbeam-only cards.  Until #87 they borrowed
ZAERO's MLOADS/MLD* names with a different layout and meaning (ZAERO's drive an
aeroservoelastic state-space model, ZAERO 9.2 UM PDF p.383-400); those names are now
refused.  The implementation is restricted to Phase G0 increment 1:

  * Level 1 quasi-steady aerodynamics (steady VLM evaluated at the instantaneous
    rigid-body rates / attitude — no DLM, no lag/apparent-mass states), and
  * open-loop control (prescribed pilot-command time histories; no closed-loop
    control law).

Card orchestration::

    MANVR  ──references──▶ MANTRIM (steady-state initial condition = a TRIM sid)
        │                   MANTIME (integration window t0/tend/dt/tout)
        │                   MANCMD (pilot command label → TABLED1 time history)
        └─────────────────▶ MANPRNT (ASCII time-history output request)

``TABLED1`` is the general tabular (time → value) function the commands point to.
"""
import math

from dataclasses import dataclass, field
import numpy as np


@dataclass
class Tabled1:
    """Tabular function y(x) with linear interpolation (NASTRAN TABLED1).

    For pilot-command time histories ``x`` is time and ``y`` is the commanded
    value (e.g. a control-surface deflection or a load-factor target).

    Outside the table the value is **extrapolated linearly from the two end
    points**, as MSC does: "interpolation within the table and extrapolation
    outside the table using the two starting or end points" (MSC Nastran 2024.1
    QRG PDF p.2896-2897, remark 6).  To hold a value, end the table with two
    points of equal y.  Until #70 sbeam held the end value instead.
    """
    tid:   int
    xs:    list[float] = field(default_factory=list)   # abscissae (time)
    ys:    list[float] = field(default_factory=list)   # ordinates (command)
    xaxis: str = "LINEAR"                         # the parser refuses LOG (#70)
    yaxis: str = "LINEAR"

    def end_slopes(self) -> tuple[float, float]:
        """Slopes of the first and last segments, which carry on outside the table."""
        xs, ys = self.xs, self.ys
        if len(xs) < 2:
            return 0.0, 0.0
        return ((ys[1] - ys[0]) / (xs[1] - xs[0]), (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]))

    def evaluate(self, x: float) -> float:
        """Linear interpolation inside the table, linear extrapolation outside it."""
        xs = self.xs
        if not xs:
            return 0.0
        first, last = self.end_slopes()
        if x <= xs[0]:
            return self.ys[0] + first * (x - xs[0])
        if x >= xs[-1]:
            return self.ys[-1] + last * (x - xs[-1])
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
    """MANTRIM — steady-state initial condition: a static TRIM sid and the freestream density.

    ``rho`` exists solely to map the TRIM's dynamic pressure to a true airspeed
    ``V = sqrt(2q/rho)`` for the free-flight solver's rigid-rate aerodynamics, in the
    deck's own consistent units (charter §7).  ``0.0`` means "not supplied".  Until #87
    it was an ``RHOREF`` pseudo-label on the TRIM card, which MSC's TRIM does not have.
    """
    sid:      int
    trim_sid: int
    rho:      float = 0.0

    def velocity(self, q: float) -> float:
        """True airspeed V = sqrt(2q/rho) at dynamic pressure ``q``.

        Raises:
            ValueError if RHO was not given — the transient maneuver rate terms
            (Step 61 ``build_dj_rigidrate``) are undefined without a physical velocity.
        """
        if self.rho <= 0.0:
            raise ValueError(
                f"MANTRIM {self.sid}: a freestream velocity is required but RHO (field 4) "
                "is blank; give the freestream density in the deck's own consistent "
                "units so V = sqrt(2q/rho) can be formed")
        return float(math.sqrt(2.0 * q / self.rho))


@dataclass
class Mloads:
    """Top-level transient maneuver-loads driver (references the sub-cards).

    ``nmodes``/``method``/``zeta`` configure the free-free modal basis (Step 61)
    and select the solver (Step 62): ``method`` selects the EIGRL used for the
    basis eigensolve (0 ⇒ an internal all-modes default; -1 ⇒ the same internal
    default AND the modal solver — the all-defaults-modal sentinel), ``nmodes``
    is the number of retained **elastic** modes (rigid modes are always all
    retained; 0 ⇒ all elastic), and ``zeta`` is the uniform elastic modal
    damping ratio.  Any of the three nonzero selects the Step 62 modal transient
    solver (``selects_modal``); an all-zeros card runs the legacy direct l-set
    solver (``maneuver_qs``), kept permanently as the regression anchor.
    """
    sid:        int
    mldtrim:    int            # MANTRIM sid (initial condition)
    mldtime:    int            # MANTIME sid (integration window)
    mldcomd:    int = 0        # MANCMD sid (0 ⇒ no commands; hold trim)
    mldprnt:    int = 0        # MANPRNT sid (0 ⇒ no ASCII print)
    nmodes:     int = 0        # retained ELASTIC modes (0 ⇒ all available)
    method:     int = 0        # EIGRL sid for the basis solve (0 ⇒ internal
                               # default; -1 ⇒ internal default + modal solver)
    zeta:       float = 0.0    # uniform elastic modal damping ratio

    @property
    def selects_modal(self) -> bool:
        """True when this card requests the Step 62 modal transient solver."""
        return bool(self.nmodes or self.method or self.zeta)
