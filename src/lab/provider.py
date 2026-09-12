"""Provider model for the min-cost provisioning MVP (pivot 2026-08-31).

A provider owns several shells; every satellite carries one hardware class,
assigned from seeded per-shell fractions; every orbital plane is a
PROVISIONING DOMAIN (the availability-zone analog of the orbital tier) with
aggregated per-class capacity and an activation cost. Planes, not individual
satellites, are what the optimizer activates; satellites inside supply the
hardware units and the network anchors.

Plane-pair latency (agreed correction to the MVP plan): each plane gets an
anchor satellite, the best AoI-visible member where the plane is visible,
otherwise the member nearest by propagation time to the shell's best visible
satellite. Pair latency is the shortest-path propagation time between
anchors; the diagonal charges one intra-plane hop (components in one plane
generally sit on different satellites); cross-shell pairs are infinite (no
inter-shell links, portfolio not spanning).
"""

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import networkx as nx
import yaml

from lab import constants as C
from lab.harness.runner import repo_root
from substrate import graph as G
from substrate import visibility as VIS
from substrate.walker import Node, Walker

PlaneId = Tuple[str, int]           # (shell_id, plane_index)
INF_MS = 1e9


@dataclass
class Shell:
    id: str
    walker: Walker
    hw_of: Dict[Node, str]          # satellite -> hardware class


@dataclass
class PlaneView:
    pid: PlaneId
    members: List[Node]
    hw_counts: Dict[str, int]
    visible: bool
    access_ms: float                # slant-range latency of best visible member
    best_elevation: float
    anchor: Node


SatId = Tuple[str, int, int]        # (shell_id, plane, slot)


@dataclass
class ProviderInstance:
    name: str
    shells: Dict[str, Shell]
    planes: Dict[PlaneId, PlaneView]
    route_ms: Dict[Tuple[PlaneId, PlaneId], float]
    hw_cost: Dict[str, float]
    plane_cost: float
    isl_gbps: float
    uplink_gbps: float
    downlink_gbps: float
    t: float
    aoi: Tuple[float, float]
    graphs: Dict[str, "nx.Graph"] = field(default_factory=dict)
    net: Optional["nx.Graph"] = None      # unified multi-shell G(t) over SatId
    sat_hw: Dict[SatId, str] = field(default_factory=dict)
    sat_access: Dict[SatId, float] = field(default_factory=dict)
    _sat_dist_cache: Dict[SatId, Dict] = field(default_factory=dict)

    def plane_of(self, s: SatId) -> PlaneId:
        return (s[0], s[1])

    def visible_in(self, planes) -> List[SatId]:
        """AoI-visible satellites whose plane is in `planes` (the ingress
        and egress candidates of a state with that reserved plane set)."""
        return [s for s in self.sat_access if (s[0], s[1]) in planes]

    def sat_dist(self, a: SatId, b: SatId) -> float:
        """Satellite-pair propagation ms on the unified G(t). No special
        cases: cross-shell pairs are reachable exactly when G(t) contains a
        path (inter-shell edge class empty in the MVP config -> INF)."""
        if a == b:
            return 0.0
        if a not in self._sat_dist_cache:
            self._sat_dist_cache[a] = nx.single_source_dijkstra_path_length(
                self.net, a, weight="weight_ms")
        return self._sat_dist_cache[a].get(b, INF_MS)


def _load_spec() -> dict:
    with (repo_root() / "configs" / "providers" / "mvp.yaml").open() as f:
        return yaml.safe_load(f)


def _assign_hw_planes(w: Walker, plane_profiles: dict,
                      seed: int) -> Dict[Node, str]:
    """Plane-structured fleets: each plane gets a profile (hub/edge/base) via
    a seeded shuffle over plane indices; per-satellite classes fill the
    profile's counts, padded with cpu."""
    labels: List[str] = []
    for name, spec in plane_profiles.items():
        labels += [name] * int(spec["count"])
    while len(labels) < w.n_planes:
        labels.append(labels[-1])
    labels = labels[:w.n_planes]
    rng = random.Random(seed)
    rng.shuffle(labels)
    hw_of: Dict[Node, str] = {}
    for p, lab in enumerate(labels):
        classes: List[str] = []
        for cls, cnt in plane_profiles[lab]["hw"].items():
            classes += [cls] * int(cnt)
        while len(classes) < w.sats_per_plane:
            classes.append("cpu")
        classes = classes[:w.sats_per_plane]
        rng.shuffle(classes)     # slot positions are part of the seed
        for s in range(w.sats_per_plane):
            hw_of[(p, s)] = classes[s]
    return hw_of


def _assign_hw(w: Walker, fractions: Dict[str, float], seed: int) -> Dict[Node, str]:
    nodes = [(p, s) for p in range(w.n_planes) for s in range(w.sats_per_plane)]
    n = len(nodes)
    pool: List[str] = []
    for cls, fr in fractions.items():
        pool += [cls] * round(C.to_float(fr) * n)
    while len(pool) < n:
        pool.append(max(fractions, key=lambda k: C.to_float(fractions[k])))
    pool = pool[:n]
    random.Random(seed).shuffle(pool)
    return dict(zip(nodes, pool))


def build_provider(name: str, aoi: Tuple[float, float], t: float = 0.0,
                   seed: int = 0,
                   plane_profiles: Optional[Dict[str, dict]] = None,
                   plane_routes: bool = True
                   ) -> ProviderInstance:
    """Build the provider `name` at instant t with fleet seed `seed`.
    `plane_profiles`, if given, maps shell id -> plane_profiles block and
    replaces that shell's fleet composition (the scarcity sweep).
    `plane_routes=False` skips the legacy plane-anchor distance table when a
    caller uses only satellite-level routing, as fine-resolution replay does.
    """
    spec = _load_spec()
    pspec = spec["providers"][name]
    if plane_profiles:
        pspec = {**pspec, "shells": [
            {**sh, "plane_profiles": plane_profiles[sh["id"]]}
            if sh["id"] in plane_profiles else sh
            for sh in pspec["shells"]]}
    min_el = C.to_float(spec["min_elevation_deg"])
    hw_cost = {k: C.to_float(v) for k, v in spec["costs"]["hardware"].items()}
    plane_cost = C.to_float(spec["costs"]["plane_activation"])
    consts = C.load_constants()
    isl_gbps = C.to_float(C.val(
        consts["constellations"]["ref-star"]["isl_rate_gbps"]))
    uplink_gbps = C.to_float(C.val(consts["links"]["ground_uplink_gbps"]))
    downlink_gbps = C.to_float(C.val(consts["links"]["ground_downlink_gbps"]))

    shells: Dict[str, Shell] = {}
    planes: Dict[PlaneId, PlaneView] = {}
    route: Dict[Tuple[PlaneId, PlaneId], float] = {}
    graphs: Dict[str, object] = {}
    sat_hw: Dict[SatId, str] = {}
    sat_access: Dict[SatId, float] = {}

    for si, sh in enumerate(pspec["shells"]):
        if "revs_per_sidereal_day" in sh:
            # Repeat ground track: the exact altitude for an integer number
            # of revolutions per sidereal day (Clockwork cycle).
            from lab.cycle import repeat_track_altitude_km
            alt = repeat_track_altitude_km(int(sh["revs_per_sidereal_day"]))
        else:
            alt = C.to_float(sh["altitude_km"])
        w = Walker(name=sh["id"],
                   topology="star" if sh["type"] == "walker_star" else "delta",
                   altitude_km=alt,
                   inclination_deg=C.to_float(sh["inclination_deg"]),
                   n_planes=int(sh["planes"]),
                   sats_per_plane=int(sh["sats_per_plane"]),
                   phasing_f=int(sh.get("phasing_f", 1)))
        if "plane_profiles" in sh:
            hw = _assign_hw_planes(w, sh["plane_profiles"], seed * 100 + si)
        else:
            hw = _assign_hw(w, sh["hw_fractions"], seed * 100 + si)
        shells[sh["id"]] = Shell(sh["id"], w, hw)
        g = G.build_graph(w, t)
        graphs[sh["id"]] = g
        for node, cls in hw.items():
            sat_hw[(sh["id"], node[0], node[1])] = cls

        # Best visible satellite of the whole shell (reference for anchors).
        best_shell: Optional[Tuple[Node, float, float]] = None
        vis_by_plane: Dict[int, Tuple[Node, float, float]] = {}
        for node in g.nodes():
            acc = VIS.access(w, node, aoi[0], aoi[1], t, min_el)
            if acc is None:
                continue
            el, _, ms = acc
            sat_access[(sh["id"], node[0], node[1])] = ms
            cur = vis_by_plane.get(node[0])
            if cur is None or el > cur[1]:
                vis_by_plane[node[0]] = (node, el, ms)
            if best_shell is None or el > best_shell[1]:
                best_shell = (node, el, ms)

        dist_from_ref: Dict[Node, float] = {}
        if plane_routes and best_shell is not None:
            dist_from_ref = nx.single_source_dijkstra_path_length(
                g, best_shell[0], weight="weight_ms")

        anchors: Dict[int, Node] = {}
        for p in range(w.n_planes):
            members = [(p, s) for s in range(w.sats_per_plane)]
            counts: Dict[str, int] = {}
            for m in members:
                counts[hw[m]] = counts.get(hw[m], 0) + 1
            if p in vis_by_plane:
                node, el, ms = vis_by_plane[p]
                pv = PlaneView((sh["id"], p), members, counts, True, ms, el, node)
            else:
                if dist_from_ref:
                    anchor = min(members, key=lambda m: dist_from_ref.get(m, INF_MS))
                else:
                    anchor = members[0]
                pv = PlaneView((sh["id"], p), members, counts, False,
                               INF_MS, -90.0, anchor)
            planes[pv.pid] = pv
            anchors[p] = pv.anchor

        # Plane-pair propagation within the shell (anchor shortest paths).
        if plane_routes:
            for p in range(w.n_planes):
                lengths = nx.single_source_dijkstra_path_length(
                    g, anchors[p], weight="weight_ms")
                for q in range(w.n_planes):
                    if p == q:
                        route[((sh["id"], p), (sh["id"], q))] = w.intra_plane_hop_ms()
                    else:
                        route[((sh["id"], p), (sh["id"], q))] = lengths.get(
                            anchors[q], INF_MS)

    # Cross-shell pairs are infinite: no inter-shell links (portfolio only).
    if plane_routes:
        for a in planes:
            for b in planes:
                if a[0] != b[0]:
                    route[(a, b)] = INF_MS

    net = nx.Graph()
    for sid, g in graphs.items():
        for node in g.nodes():
            net.add_node((sid, node[0], node[1]))
        for u, v, data in g.edges(data=True):
            net.add_edge((sid, u[0], u[1]), (sid, v[0], v[1]),
                         weight_ms=data["weight_ms"], cls="intra_shell")
    # Optional link classes (inter-shell, ground) from the spec; empty lists
    # by default, so the MVP substrate has no cross-shell paths.
    for extra in spec.get("extra_links", []):
        net.add_edge(tuple(extra["a"]), tuple(extra["b"]),
                     weight_ms=C.to_float(extra["ms"]),
                     cls=extra.get("cls", "inter_shell"))

    return ProviderInstance(name, shells, planes, route, hw_cost, plane_cost,
                            isl_gbps, uplink_gbps, downlink_gbps, t, aoi,
                            graphs=graphs, net=net, sat_hw=sat_hw,
                            sat_access=sat_access)


def richest_epoch(name: str, aoi: Tuple[float, float], start_s: float = 0,
                  stop_s: float = 7200, step_s: float = 60,
                  seed: int = 0) -> float:
    """Epoch with the most AoI-visible planes (ties earliest). Visibility is
    seed-independent, so one scan serves every fleet seed."""
    best_t, best_n = None, -1
    t = start_s
    while t < stop_s:
        inst = build_provider(name, aoi, t=float(t), seed=seed)
        n = sum(pv.visible for pv in inst.planes.values())
        if n > best_n:
            best_t, best_n = float(t), n
        t += step_s
    if best_n < 1:
        raise RuntimeError("no epoch with AoI visibility in the scan range")
    return best_t


def restrict_shells(inst: ProviderInstance, shell_ids) -> ProviderInstance:
    """Portfolio view: the same provider limited to a subset of shells."""
    keep = set(shell_ids)
    planes = {p: v for p, v in inst.planes.items() if p[0] in keep}
    route = {k: v for k, v in inst.route_ms.items()
             if k[0][0] in keep and k[1][0] in keep}
    return ProviderInstance(inst.name, {k: v for k, v in inst.shells.items()
                                        if k in keep},
                            planes, route, inst.hw_cost, inst.plane_cost,
                            inst.isl_gbps, inst.uplink_gbps,
                            inst.downlink_gbps, inst.t, inst.aoi,
                            graphs={k: v for k, v in inst.graphs.items()
                                    if k in keep},
                            net=inst.net.subgraph(
                                [n for n in inst.net.nodes()
                                 if n[0] in keep]).copy(),
                            sat_hw={k: v for k, v in inst.sat_hw.items()
                                    if k[0] in keep},
                            sat_access={k: v for k, v in inst.sat_access.items()
                                        if k[0] in keep})
