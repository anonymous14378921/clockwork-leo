"""Build evaluation instances: substrate graph + fleet + AoI-derived roles.

An instance fixes everything the planner takes as given: a constellation
snapshot graph, a seeded fleet (per-node device classes drawn from a named mix
in constants.yaml, sparse-strong by default or the graded mix), an AoI with its
slice, the sensor node (a base-class slice node, deterministic under the seed),
and ms-weighted shortest-path distances. The planner's decisions
(configuration, placement) happen on top of this.

The coverage filter (algorithm Step 1) lives here: an AoI a constellation
cannot see yields covered=False (e.g. any Delta shell vs the Arctic), which
experiments record as the coverage-cap outcome rather than an error.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

from lab import constants as C
from substrate import graph as G
from substrate import slices
from substrate.walker import Node, Walker


@dataclass
class Instance:
    constellation: str
    topology: str                 # star | delta
    aoi: str
    p: float                      # strong fraction (sparse-strong) or -1 (mix-defined)
    seed: int
    mix: str
    covered: bool
    graph: Optional[nx.Graph]
    sensor: Optional[Node]
    device_map: Dict[Node, str]   # node -> device class
    strong_classes: Tuple[str, ...]
    t_hop_ms: float               # canonical intra-plane hop (hop-equivalents)
    isl_gbps: float
    _dist_cache: Dict[Node, Dict[Node, float]] = field(default_factory=dict)

    @property
    def capable(self) -> Set[Node]:
        return {n for n, d in self.device_map.items() if d in self.strong_classes}

    def device_of(self, n: Node) -> str:
        return self.device_map[n]

    def dist_ms(self, a: Node, b: Node) -> float:
        """Propagation ms on the cheapest path; Dijkstra cached per source."""
        if a == b:
            return 0.0
        if a not in self._dist_cache:
            self._dist_cache[a] = nx.single_source_dijkstra_path_length(
                self.graph, a, weight="weight_ms")
        return self._dist_cache[a][b]

    def nearest_capable_nodes(self, k: int) -> List[Tuple[Node, float]]:
        """Up to k nearest nodes of EACH strong class to the sensor, merged and
        sorted by distance (so a graded fleet offers both the near mid-tier and
        the far top-tier as candidates). The sensor is never included."""
        if self.sensor not in self._dist_cache:
            self._dist_cache[self.sensor] = nx.single_source_dijkstra_path_length(
                self.graph, self.sensor, weight="weight_ms")
        d = self._dist_cache[self.sensor]
        merged: List[Tuple[Node, float]] = []
        for cls in self.strong_classes:
            members = [n for n, dev in self.device_map.items()
                       if dev == cls and n in d and n != self.sensor]
            members.sort(key=lambda n: d[n])
            merged += [(n, d[n]) for n in members[:k]]
        return sorted(merged, key=lambda t: t[1])


_GRAPH_CACHE: Dict[str, Tuple[Walker, nx.Graph]] = {}


def _walker_graph(constellation: str) -> Tuple[Walker, nx.Graph]:
    if constellation not in _GRAPH_CACHE:
        w = Walker.from_constellation(constellation)
        _GRAPH_CACHE[constellation] = (w, G.build_graph(w))
    return _GRAPH_CACHE[constellation]


def _mix_spec(mix: str, p_override: Optional[float]) -> Tuple[Dict[str, float], Tuple[str, ...], str]:
    """(fractions, strong_classes, base_class) for a named fleet mix. For
    sparse-strong, p_override replaces the mix's strong fraction (the p axis of
    the instance grid)."""
    spec = C.load_constants()["fleet_mixes"][mix]
    if "fractions" in spec:
        fr = {k: C.to_float(v) for k, v in spec["fractions"].items()}
        return fr, tuple(spec["strong_classes"]), spec["base"]
    strong = spec["strong_device"]
    rest = spec["rest_device"]
    p = C.to_float(spec["strong_fraction"]) if p_override is None else p_override
    return {strong: p, rest: 1.0 - p}, (strong,), rest


def _assign_fleet(nodes: List[Node], fractions: Dict[str, float],
                  seed: int) -> Dict[Node, str]:
    order = list(nodes)
    random.Random(seed).shuffle(order)
    out: Dict[Node, str] = {}
    i = 0
    classes = list(fractions.items())
    for j, (cls, fr) in enumerate(classes):
        n = max(1, round(fr * len(order))) if fr > 0 else 0
        chunk = order[i:] if j == len(classes) - 1 else order[i:i + n]
        for node in chunk:
            out[node] = cls
        i += len(chunk)
    return out


def build_instance(constellation: str, aoi_name: str, p: Optional[float],
                   seed: int, mix: str = "sparse-strong") -> Instance:
    w, g = _walker_graph(constellation)
    con = C.constellation(constellation)

    nodes = sorted(g.nodes())
    fractions, strong_classes, base = _mix_spec(mix, p)
    device_map = _assign_fleet(nodes, fractions, seed)

    aoi = slices.AOIS[aoi_name]
    in_slice = sorted(slices.slice_nodes(w, aoi))
    covered = len(in_slice) > 0
    base_slice = [n for n in in_slice if device_map[n] == base]
    sensor = (base_slice[0] if base_slice else (in_slice[0] if in_slice else None))

    return Instance(
        constellation=constellation, topology=con.topology, aoi=aoi_name,
        p=(p if p is not None else -1.0), seed=seed, mix=mix, covered=covered,
        graph=g if covered else None, sensor=sensor, device_map=device_map,
        strong_classes=strong_classes,
        t_hop_ms=w.intra_plane_hop_ms(), isl_gbps=con.isl_rate_gbps,
    )
