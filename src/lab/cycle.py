"""The planning cycle: one sidereal day, and epoch grids over it.

Shells sit at repeat-ground-track altitudes, so the AoI-relative geometry
repeats exactly every cycle. Experiments sample the cycle on an evenly
spaced grid chosen before any outcome is seen.
"""

from typing import List

from lab import constants as C


def cycle_s() -> float:
    """Length of the planning cycle in seconds (one sidereal day)."""
    return C.to_float(C.val(C.load_constants()["cycle"]["sidereal_day_s"]))


def epochs(cfg: dict, key: str = "n_epochs", literal: str = "epochs_s"
           ) -> List[float]:
    """Evenly spaced epochs over one cycle from cfg[key], else cfg[literal]."""
    if key in cfg:
        n = int(cfg[key])
        return [k * cycle_s() / n for k in range(n)]
    return [C.to_float(t) for t in cfg[literal]]


def grid(n_steps: int) -> List[float]:
    """Dense time grid over one cycle (for the temporal experiments)."""
    return [k * cycle_s() / n_steps for k in range(n_steps)]


def repeat_track_altitude_km(revs_per_sidereal_day: int) -> float:
    """Altitude at which a circular two-body orbit completes exactly
    `revs_per_sidereal_day` revolutions per sidereal day (constants.yaml
    mu, Earth radius, sidereal day): a = (mu (T/R)^2 / 4 pi^2)^(1/3)."""
    import math
    consts = C.load_constants()
    mu = C.to_float(C.val(consts["physical"]["mu_earth_m3_s2"]))
    r_e = C.to_float(C.val(consts["physical"]["earth_radius_km"]))
    period = cycle_s() / revs_per_sidereal_day
    a_m = (mu * period ** 2 / (4.0 * math.pi ** 2)) ** (1.0 / 3.0)
    return a_m / 1e3 - r_e
