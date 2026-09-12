"""Walker constellation geometry: positions, hop distances, and ISL links.

Two topology classes (brief Section 1):
  star  — RAAN spread over pi (a cylinder with a seam; full latitude coverage).
  delta — RAAN spread over 2 pi (a torus; coverage capped at inclination).

Everything is driven by constants.yaml through lab.constants, so no orbital
number is hardcoded here. Positions are Earth-centered inertial (ECI) km for a
circular orbit; a single snapshot (t=0) is enough for the static graph metrics
E0 and E1 need, and the time argument advances the argument of latitude by the
mean motion for the time-expanded views E4 will use.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from lab import constants as C

Node = Tuple[int, int]  # (plane index p, slot index s)


def _c_km_s() -> float:
    return C.to_float(C.val(C.load_constants()["physical"]["c_m_s"])) / 1e3


def _mu() -> float:
    return C.to_float(C.val(C.load_constants()["physical"]["mu_earth_m3_s2"]))


def _earth_radius_km() -> float:
    return C.to_float(C.val(C.load_constants()["physical"]["earth_radius_km"]))


def hop_ms(dist_km: float) -> float:
    """Propagation time in ms for a straight-line ISL of length dist_km."""
    return dist_km / _c_km_s() * 1e3


@dataclass(frozen=True)
class Walker:
    name: str
    topology: str            # "star" or "delta"
    altitude_km: float
    inclination_deg: float
    n_planes: int            # Nx
    sats_per_plane: int      # Ny
    phasing_f: int           # F (0 if unspecified)

    # --- construction --------------------------------------------------------
    @classmethod
    def from_constellation(cls, name: str) -> "Walker":
        c = C.constellation(name)
        return cls(
            name=name,
            topology=c.topology,
            altitude_km=c.altitude_km,
            inclination_deg=c.inclination_deg,
            n_planes=c.n_planes,
            sats_per_plane=c.sats_per_plane,
            phasing_f=0 if c.phasing_f is None else c.phasing_f,
        )

    @property
    def a_km(self) -> float:
        """Orbital radius = Earth radius + altitude."""
        return _earth_radius_km() + self.altitude_km

    @property
    def raan_span(self) -> float:
        """RAAN spread: pi for a star (seam), 2 pi for a delta (torus)."""
        return math.pi if self.topology == "star" else 2.0 * math.pi

    # --- analytic hop distances (the sanity-test targets) --------------------
    def intra_plane_hop_km(self) -> float:
        """Chord between adjacent satellites in one plane: d = 2 a sin(pi/Ny)."""
        return 2.0 * self.a_km * math.sin(math.pi / self.sats_per_plane)

    def intra_plane_hop_ms(self) -> float:
        return hop_ms(self.intra_plane_hop_km())

    def inter_plane_equator_hop_km(self) -> float:
        """Node separation between adjacent planes at the equator:
        d = 2 a sin(dOmega/2), dOmega = pi/Nx (star) or 2 pi/Nx (delta)."""
        d_omega = self.raan_span / self.n_planes
        return 2.0 * self.a_km * math.sin(d_omega / 2.0)

    def inter_plane_equator_hop_ms(self) -> float:
        return hop_ms(self.inter_plane_equator_hop_km())

    # --- positions -----------------------------------------------------------
    def mean_motion(self) -> float:
        """Orbital angular rate n = sqrt(mu / a^3), rad/s."""
        a_m = self.a_km * 1e3
        return math.sqrt(_mu() / a_m**3)

    def _u0(self, p: int, s: int) -> float:
        """Argument of latitude of satellite (p, s) at t=0, with phasing F."""
        return (2.0 * math.pi * s / self.sats_per_plane
                + 2.0 * math.pi * self.phasing_f * p
                / (self.n_planes * self.sats_per_plane))

    def _raan(self, p: int) -> float:
        return self.raan_span * p / self.n_planes

    def position(self, p: int, s: int, t: float = 0.0) -> np.ndarray:
        """ECI position (km) of satellite (p, s) at time t seconds."""
        a = self.a_km
        inc = math.radians(self.inclination_deg)
        omega = self._raan(p)
        u = self._u0(p, s) + self.mean_motion() * t
        cu, su = math.cos(u), math.sin(u)
        co, so = math.cos(omega), math.sin(omega)
        ci = math.cos(inc)
        x = a * (cu * co - su * ci * so)
        y = a * (cu * so + su * ci * co)
        z = a * (su * math.sin(inc))
        return np.array([x, y, z])

    def positions(self, t: float = 0.0) -> Dict[Node, np.ndarray]:
        return {
            (p, s): self.position(p, s, t)
            for p in range(self.n_planes)
            for s in range(self.sats_per_plane)
        }

    def subpoint(self, p: int, s: int, t: float = 0.0) -> Tuple[float, float]:
        """Sub-satellite latitude, longitude in degrees (ECI, no Earth spin).

        Static-snapshot simplification: Earth rotation (GMST) is not applied, so
        longitudes are inertial. Relative AoI geometry is what E1 measures, so
        this is adequate; note it where absolute ground tracks would matter.
        """
        x, y, z = self.position(p, s, t)
        r = math.sqrt(x * x + y * y + z * z)
        lat = math.degrees(math.asin(z / r))
        lon = math.degrees(math.atan2(y, x))
        return lat, lon

    # --- ISL links (+Grid) ---------------------------------------------------
    def links(self, t: float = 0.0, polar_cap_deg: Optional[float] = None
              ) -> List[Tuple[Node, Node, str]]:
        """+Grid ISLs: one intra-plane ring plus same-index inter-plane links.

        star  drops the seam (no wrap between plane Nx-1 and plane 0), because
              those planes counter-rotate. delta wraps (torus, no seam).
        polar_cap_deg, if set, drops inter-plane links whose either endpoint is
        poleward of the cap (the polar link-drop of a real star constellation).
        """
        Nx, Ny = self.n_planes, self.sats_per_plane
        edges: List[Tuple[Node, Node, str]] = []

        # Intra-plane ring: (p, s) -- (p, s+1 mod Ny).
        for p in range(Nx):
            for s in range(Ny):
                edges.append(((p, s), (p, (s + 1) % Ny), "intra"))

        # Inter-plane: (p, s) -- (p_next, s).
        for p in range(Nx):
            p_next = (p + 1) % Nx
            if self.topology == "star" and p_next == 0:
                continue  # seam: no wrap for a star
            for s in range(Ny):
                if polar_cap_deg is not None:
                    lat_a, _ = self.subpoint(p, s, t)
                    lat_b, _ = self.subpoint(p_next, s, t)
                    if abs(lat_a) > polar_cap_deg or abs(lat_b) > polar_cap_deg:
                        continue  # polar link-drop
                edges.append(((p, s), (p_next, s), "inter"))
        return edges
