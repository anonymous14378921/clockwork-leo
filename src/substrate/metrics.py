"""Substrate graph metrics for E1 (and reused by E2/E3).

Path-cost distributions, the seam/wrap-pair hop distribution (the seam tax),
coverage by latitude band across snapshots (the latitude cap), and the
nearest-capable hop sweep (capable-node sparsity). All CPU, pure geometry.

Sampling: pairwise path-cost distributions are estimated from a fixed, seeded set
of source nodes rather than all pairs, which is enough for mean and p95 and keeps
the 1000-to-1600-node graphs fast. Diameter is computed exactly (the graphs are
connected).
"""

import math
import random
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Sequence, Tuple

import networkx as nx
import numpy as np

from .graph import build_graph, nearest_capable
from .walker import Node, Walker


@dataclass(frozen=True)
class Summary:
    mean: float
    p50: float
    p95: float
    maximum: float
    n: int


def summarize(vals: Sequence[float]) -> Summary:
    a = np.asarray(list(vals), dtype=float)
    if a.size == 0:
        return Summary(math.nan, math.nan, math.nan, math.nan, 0)
    return Summary(
        mean=float(a.mean()),
        p50=float(np.percentile(a, 50)),
        p95=float(np.percentile(a, 95)),
        maximum=float(a.max()),
        n=int(a.size),
    )


# --- path-cost distribution --------------------------------------------------
def _sample_sources(g: nx.Graph, k: int, seed: int) -> List[Node]:
    nodes = sorted(g.nodes())
    if k >= len(nodes):
        return nodes
    return random.Random(seed).sample(nodes, k)


def pathcost_hops(g: nx.Graph, k_sources: int = 60, seed: int = 0) -> List[int]:
    """Shortest-path hop counts from k sampled sources to all other nodes."""
    out: List[int] = []
    for s in _sample_sources(g, k_sources, seed):
        d = nx.single_source_shortest_path_length(g, s)
        out.extend(v for t, v in d.items() if t != s)
    return out


def pathcost_ms(g: nx.Graph, k_sources: int = 60, seed: int = 0) -> List[float]:
    """Propagation-minimizing path costs (ms) from k sampled sources."""
    out: List[float] = []
    for s in _sample_sources(g, k_sources, seed):
        d = nx.single_source_dijkstra_path_length(g, s, weight="weight_ms")
        out.extend(v for t, v in d.items() if t != s)
    return out


def diameter_hops(g: nx.Graph) -> Optional[int]:
    """Exact unweighted diameter, or None if the graph is disconnected."""
    if not nx.is_connected(g):
        return None
    return nx.diameter(g)


# --- seam / wrap-pair hop distribution (the seam tax) ------------------------
def seam_pair_hops(w: Walker, g: nx.Graph) -> List[int]:
    """Graph hop distance between physically-nearest first/last-plane pairs.

    For each satellite in plane 0, find the physically closest satellite in plane
    Nx-1 and return their shortest-path hop count. For a Star these planes
    straddle the seam (counter-rotating, unlinked), so the values are large (the
    seam tax). For a Delta they wrap on the torus, so the values are ~1.
    """
    last = w.n_planes - 1
    pos = w.positions()
    out: List[int] = []
    for s0 in range(w.sats_per_plane):
        p0 = pos[(0, s0)]
        nearest = min(range(w.sats_per_plane),
                      key=lambda s1: float(np.linalg.norm(p0 - pos[(last, s1)])))
        out.append(nx.shortest_path_length(g, (0, s0), (last, nearest)))
    return out


# --- coverage by latitude band across snapshots (the latitude cap) -----------
# Bands as (name, min_abs_lat, max_abs_lat) in degrees.
LAT_BANDS: Tuple[Tuple[str, float, float], ...] = (
    ("equatorial", 0.0, 10.0),
    ("mid", 30.0, 60.0),
    ("arctic", 66.5, 90.0),
)


def _orbital_period_s(w: Walker) -> float:
    return 2.0 * math.pi / w.mean_motion()


def coverage_by_band(w: Walker, n_snapshots: int = 12) -> Dict[str, float]:
    """Mean number of satellites in each latitude band, averaged over one period.

    Latitude coverage is exact under the static-snapshot model (Earth rotation
    does not change latitudes), so a Delta at inclination i has zero satellites
    above |lat| = i. Averaging over snapshots smooths the per-instant count.
    """
    period = _orbital_period_s(w)
    counts: Dict[str, List[int]] = {name: [] for name, _, _ in LAT_BANDS}
    for i in range(n_snapshots):
        t = period * i / n_snapshots
        per_band = {name: 0 for name, _, _ in LAT_BANDS}
        for p in range(w.n_planes):
            for s in range(w.sats_per_plane):
                lat, _ = w.subpoint(p, s, t)
                al = abs(lat)
                for name, lo, hi in LAT_BANDS:
                    if lo <= al <= hi:
                        per_band[name] += 1
        for name in per_band:
            counts[name].append(per_band[name])
    return {name: float(np.mean(v)) for name, v in counts.items()}


# --- nearest-capable sweep (capable-node sparsity) ---------------------------
def nearest_capable_sweep(w: Walker, g: nx.Graph, fractions: Sequence[float],
                          seed: int = 0, k_sources: int = 60) -> Dict[float, Summary]:
    """For each capable fraction p, the hop distance from sampled sources to the
    nearest capable node. As p shrinks the distances grow (ring compression)."""
    nodes = sorted(g.nodes())
    rng = random.Random(seed)
    sources = _sample_sources(g, k_sources, seed + 1)
    out: Dict[float, Summary] = {}
    for p in fractions:
        n_cap = max(1, round(p * len(nodes)))
        capable = set(rng.sample(nodes, n_cap))
        hops = []
        for src in sources:
            _, h, _ = nearest_capable(g, src, capable)
            hops.append(h)
        out[p] = summarize(hops)
    return out


def summary_row(s: Summary) -> Dict[str, float]:
    return asdict(s)
