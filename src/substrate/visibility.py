"""Point-AoI visibility: elevation, slant range, access latency (MVP pivot).

The AoI is an Earth-fixed point (lat, lon). A satellite is visible when its
elevation above the point's local horizon meets a minimum elevation angle.
Positions come from the walker in ECI; the ground frame subtracts Earth
rotation (omega_E t), consistent with substrate.dynamics.
"""

import math
from typing import Optional, Tuple

import numpy as np

from lab import constants as C
from .dynamics import omega_earth
from .walker import Node, Walker


def ground_point_ecef_km(lat_deg: float, lon_deg: float) -> np.ndarray:
    r = C.to_float(C.val(C.load_constants()["physical"]["earth_radius_km"]))
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    return r * np.array([math.cos(la) * math.cos(lo),
                         math.cos(la) * math.sin(lo),
                         math.sin(la)])


def sat_ecef_km(w: Walker, p: int, s: int, t: float) -> np.ndarray:
    """ECI position rotated into the Earth-fixed frame at time t."""
    x, y, z = w.position(p, s, t)
    th = omega_earth() * t
    ct, st = math.cos(th), math.sin(th)
    return np.array([x * ct + y * st, -x * st + y * ct, z])


def elevation_deg(sat_ecef: np.ndarray, gnd_ecef: np.ndarray) -> float:
    """Elevation of the satellite above the ground point's local horizon."""
    d = sat_ecef - gnd_ecef
    up = gnd_ecef / np.linalg.norm(gnd_ecef)
    return math.degrees(math.asin(float(np.dot(d, up) / np.linalg.norm(d))))


def access(w: Walker, node: Node, lat_deg: float, lon_deg: float, t: float,
           min_elevation_deg: float) -> Optional[Tuple[float, float, float]]:
    """(elevation_deg, slant_range_km, access_latency_ms) if visible, else None."""
    gnd = ground_point_ecef_km(lat_deg, lon_deg)
    sat = sat_ecef_km(w, node[0], node[1], t)
    el = elevation_deg(sat, gnd)
    if el < min_elevation_deg:
        return None
    slant = float(np.linalg.norm(sat - gnd))
    c_km_s = C.to_float(C.val(C.load_constants()["physical"]["c_m_s"])) / 1e3
    return el, slant, slant / c_km_s * 1e3
