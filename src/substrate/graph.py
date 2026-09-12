"""Build a hardware-annotated ISL graph per snapshot and query it.

A networkx.Graph whose nodes are (plane, slot) tuples carrying ECI position and
sub-satellite lat/lon, and whose edges carry chord length (km) and propagation
weight (ms). Path costs are reported in ms and, by the caller, in hop-equivalents.
"""

import math
from typing import Optional, Tuple

import networkx as nx
import numpy as np

from .walker import Node, Walker, hop_ms


def build_graph(w: Walker, t: float = 0.0,
                polar_cap_deg: Optional[float] = None) -> nx.Graph:
    """Snapshot ISL graph. Edge weight is propagation time in ms (chord/c)."""
    g = nx.Graph()
    pos = w.positions(t)
    for node, xyz in pos.items():
        lat, lon = w.subpoint(node[0], node[1], t)
        g.add_node(node, eci_km=xyz, lat=lat, lon=lon)
    for a, b, kind in w.links(t, polar_cap_deg=polar_cap_deg):
        dist_km = float(np.linalg.norm(pos[a] - pos[b]))
        g.add_edge(a, b, dist_km=dist_km, weight_ms=hop_ms(dist_km), kind=kind)
    return g


def shortest_path_hops(g: nx.Graph, a: Node, b: Node) -> int:
    """Number of ISL hops on the unweighted shortest path."""
    return nx.shortest_path_length(g, a, b)


def shortest_path_ms(g: nx.Graph, a: Node, b: Node) -> float:
    """Propagation-time-minimizing path cost in ms."""
    return nx.shortest_path_length(g, a, b, weight="weight_ms")


def closest_cross_seam_pair(w: Walker, g: nx.Graph) -> Tuple[Node, Node, float]:
    """The physically nearest (plane 0, plane Nx-1) pair: it straddles the seam.

    Returns (node_in_plane_0, node_in_last_plane, distance_km). For a star these
    planes counter-rotate and are unlinked, so this pair exposes the seam tax.
    """
    last = w.n_planes - 1
    pos = w.positions()
    best: Optional[Tuple[Node, Node, float]] = None
    for s0 in range(w.sats_per_plane):
        p0 = pos[(0, s0)]
        for s1 in range(w.sats_per_plane):
            d = float(np.linalg.norm(p0 - pos[(last, s1)]))
            if best is None or d < best[2]:
                best = ((0, s0), (last, s1), d)
    assert best is not None
    return best


def nearest_capable(g: nx.Graph, source: Node, capable: set) -> Tuple[Node, int, float]:
    """Nearest node in `capable` to `source`: (node, hops, ms).

    Used by E0 to measure the k-hop detour to the nearest strong (H100) satellite,
    and by E1's nearest-capable experiment.
    """
    if source in capable:
        return source, 0, 0.0
    hop_len = nx.single_source_shortest_path_length(g, source)
    ms_len = nx.single_source_dijkstra_path_length(g, source, weight="weight_ms")
    best: Optional[Tuple[Node, int, float]] = None
    for node in capable:
        if node not in hop_len:
            continue
        cand = (node, hop_len[node], ms_len[node])
        if best is None or cand[1] < best[1]:
            best = cand
    if best is None:
        raise ValueError("no capable node reachable from source")
    return best
