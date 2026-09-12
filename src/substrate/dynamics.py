"""Substrate dynamics: Earth rotation, slice membership over time, validity
windows.

substrate.walker deliberately computes static-snapshot subpoints (no Earth
rotation). This module owns the time axis: the AoI is fixed to the rotating
Earth, so in the constellation's inertial frame its longitude drifts west at
omega_E, i.e. a satellite's GROUND longitude is its inertial subpoint longitude
minus omega_E * t.

The validity window of a plan starts as the sensor's dwell: the time until the
sensing satellite's subpoint leaves the AoI (empirically the binding event; the
+Grid neighbor structure is static in the rotating constellation frame, so hop
COUNTS between assigned nodes do not change, only link lengths breathe with
latitude). Window computation is a coarse forward scan refined by bisection;
the scan IS the simulation cross-check for the refined event time (tested).
"""

import math
from typing import List, Optional, Tuple

from lab import constants as C
from .slices import AoI
from .walker import Node, Walker


def omega_earth() -> float:
    return C.to_float(C.val(C.load_constants()["physical"]["omega_earth_rad_s"]))


def ground_subpoint(w: Walker, p: int, s: int, t: float) -> Tuple[float, float]:
    """(lat, lon) over the rotating Earth at time t seconds."""
    lat, lon_inertial = w.subpoint(p, s, t)
    lon = lon_inertial - math.degrees(omega_earth() * t)
    lon = (lon + 180.0) % 360.0 - 180.0
    return lat, lon


def in_aoi(w: Walker, node: Node, aoi: AoI, t: float) -> bool:
    lat, lon = ground_subpoint(w, node[0], node[1], t)
    return aoi.contains(lat, lon)


def dwell_window_s(w: Walker, node: Node, aoi: AoI, t0: float = 0.0,
                   dt: float = 5.0, horizon_s: float = 7200.0,
                   tol_s: float = 0.01) -> Optional[float]:
    """Seconds from t0 until `node`'s ground subpoint leaves the AoI.

    None if the node is not in the AoI at t0. Coarse forward scan at dt, then
    bisection to tol_s. dt must be smaller than any in-out-in excursion we care
    about; 5 s vs minutes-scale passes is safe and tested against a finer scan.
    """
    if not in_aoi(w, node, aoi, t0):
        return None
    t = t0
    while t - t0 < horizon_s:
        if not in_aoi(w, node, aoi, t + dt):
            lo, hi = t, t + dt
            while hi - lo > tol_s:
                mid = 0.5 * (lo + hi)
                if in_aoi(w, node, aoi, mid):
                    lo = mid
                else:
                    hi = mid
            return 0.5 * (lo + hi) - t0
        t += dt
    return horizon_s


def slice_at(w: Walker, aoi: AoI, t: float) -> List[Node]:
    """Slice membership over the rotating Earth at time t."""
    return [(p, s) for p in range(w.n_planes) for s in range(w.sats_per_plane)
            if in_aoi(w, (p, s), aoi, t)]


def slice_churn(w: Walker, aoi: AoI, t0: float, t1: float, dt: float
                ) -> List[Tuple[float, int, int, int]]:
    """(t, size, entered, left) per step: how fast the slice turns over."""
    prev = set(slice_at(w, aoi, t0))
    out = [(t0, len(prev), 0, 0)]
    t = t0 + dt
    while t <= t1:
        cur = set(slice_at(w, aoi, t))
        out.append((t, len(cur), len(cur - prev), len(prev - cur)))
        prev = cur
        t += dt
    return out
