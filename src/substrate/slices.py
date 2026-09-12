"""Area-of-interest (AoI) slices: which satellites currently cover a region.

An AoI is a latitude/longitude bounding box. A slice at time t is the set of
satellites whose sub-satellite point falls inside the box, and the ISL subgraph
they induce. A Delta constellation cannot cover latitudes above its inclination.
"""

from dataclasses import dataclass
from typing import Dict, List

import networkx as nx

from .graph import build_graph
from .walker import Node, Walker

# A few named AoIs (lat_min, lat_max, lon_min, lon_max) in degrees.
AOIS: Dict[str, "AoI"] = {}


@dataclass(frozen=True)
class AoI:
    name: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def contains(self, lat: float, lon: float) -> bool:
        return (self.lat_min <= lat <= self.lat_max
                and self.lon_min <= lon <= self.lon_max)


def _register(a: AoI) -> AoI:
    AOIS[a.name] = a
    return a


EUROPE = _register(AoI("europe", 36.0, 71.0, -25.0, 45.0))
ARCTIC = _register(AoI("arctic", 66.5, 90.0, -180.0, 180.0))
EQUATORIAL = _register(AoI("equatorial", -10.0, 10.0, -180.0, 180.0))
MID_LATITUDE = _register(AoI("mid_latitude", 30.0, 50.0, -20.0, 40.0))


def slice_nodes(w: Walker, aoi: AoI, t: float = 0.0) -> List[Node]:
    """Satellites whose sub-satellite point lies within the AoI at time t."""
    out = []
    for p in range(w.n_planes):
        for s in range(w.sats_per_plane):
            lat, lon = w.subpoint(p, s, t)
            if aoi.contains(lat, lon):
                out.append((p, s))
    return out


def slice_subgraph(w: Walker, aoi: AoI, t: float = 0.0) -> nx.Graph:
    """ISL subgraph induced by the satellites covering the AoI at time t."""
    g = build_graph(w, t)
    return g.subgraph(slice_nodes(w, aoi, t)).copy()
