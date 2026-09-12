"""Service model infrastructure: shared types, plan evaluation, and instance helpers.

Provisioning state types, the independent plan evaluator, candidate satellite
selection, and workflow/profile loading. Every planner and baseline imports
from here so that plan arithmetic is defined in one place.
"""

import csv
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import yaml

from lab import constants as C
from lab.harness.runner import repo_root
from lab.provider import INF_MS, PlaneId, ProviderInstance, SatId

AOI = "aoi"
EGRESS = "egress"
K_NEAR_CPU = 2
SAT_CAPACITY = 1.0


@dataclass
class Assignment:
    component: str
    sat: Optional[SatId]
    hardware: Optional[str]
    exec_ms: float

    @property
    def plane(self) -> PlaneId:
        return (self.sat[0], self.sat[1])


@dataclass
class ProvisionPlan:
    assignments: List[Assignment]
    activated: List[PlaneId]
    cost: float
    latency_ms: float
    compute_ms: float
    network_ms: float
    access_ms: float
    feasible: bool


def load_chain(name: str = "mvp_fixed"):
    with (repo_root() / "workflows" / f"{name}.yaml").open() as f:
        spec = yaml.safe_load(f)
    comps = list(spec["components"])
    edges = []
    prev = AOI
    for comp in comps:
        key = f"{prev}_{comp}"
        edges.append((prev, comp, C.to_float(spec["edges"][key]["payload_mb"])))
        prev = comp
    edges.append((prev, EGRESS, C.to_float(spec["sink"]["payload_mb"])))
    return comps, edges


def load_demands(name: str = "mvp_fixed") -> Dict[str, float]:
    """Per-component resource demand as a fraction of SAT_CAPACITY."""
    with (repo_root() / "workflows" / f"{name}.yaml").open() as f:
        spec = yaml.safe_load(f)
    return {k: C.to_float(v) for k, v in spec["demands"].items()}


def load_io(name: str = "mvp_fixed") -> Dict[str, object]:
    """Service model of the workflow: source mode and sink payload."""
    with (repo_root() / "workflows" / f"{name}.yaml").open() as f:
        spec = yaml.safe_load(f)
    source = spec.get("source", "satellite")
    if source not in ("satellite", "ground"):
        raise ValueError(f"unknown workflow source mode {source!r}")
    return {"source": source,
            "sink_mb": C.to_float(spec["sink"]["payload_mb"])}


def ingress_ms(inst: ProviderInstance, io: dict, s: SatId) -> float:
    """Latency before the first component: AoI access propagation for a
    ground-originated request, zero when the image is captured on the
    ingress satellite itself."""
    if io["source"] == "ground":
        return inst.sat_access.get(s, INF_MS)
    return 0.0 if s in inst.sat_access else INF_MS


def edge_ms(inst: ProviderInstance, io: dict, u: str, v: str, su: SatId,
            sv: SatId, mb: float) -> float:
    """Propagation plus serialization of one chain edge. Forwarding is
    pipelined: serialization once per transfer, propagation over the route.
    Zero when colocated."""
    if u == AOI and io["source"] == "ground":
        return inst.sat_dist(su, sv) + _trans_ms(mb, inst.uplink_gbps)
    if v == EGRESS:
        d = 0.0 if su == sv else inst.sat_dist(su, sv)
        return INF_MS if d >= INF_MS else d + _trans_ms(mb, inst.downlink_gbps)
    if su == sv:
        return 0.0
    d = inst.sat_dist(su, sv)
    return INF_MS if d >= INF_MS else d + _trans_ms(mb, inst.isl_gbps)


def egress_access_ms(inst: ProviderInstance, s: SatId) -> float:
    """Ground-link propagation from the egress satellite."""
    return inst.sat_access.get(s, INF_MS)


def load_profiles(name: str = "workflow_mvp") -> Dict[Tuple[str, str], float]:
    out: Dict[Tuple[str, str], float] = {}
    with (repo_root() / "data" / "profiles" / f"{name}.csv").open() as f:
        for row in csv.DictReader(f):
            out[(row["component"], row["hardware"])] = float(row["latency_ms"])
    return out


def _trans_ms(payload_mb: float, isl_gbps: float) -> float:
    return payload_mb * 8e6 / (isl_gbps * 1e9) * 1e3


def candidate_sats(inst: ProviderInstance,
                   restrict_planes: Optional[Iterable[PlaneId]] = None,
                   full: bool = False
                   ) -> Tuple[List[SatId], List[SatId]]:
    """(ingress candidates, compute candidates), optionally within planes.
    full=True disables the restriction: every satellite is a candidate."""
    keep = set(restrict_planes) if restrict_planes is not None else None

    def ok(s: SatId) -> bool:
        return keep is None or (s[0], s[1]) in keep

    ingress = [s for s in inst.sat_access if ok(s)]
    if full:
        return sorted(set(ingress)), sorted(s for s in inst.sat_hw if ok(s))
    compute = [s for s, h in inst.sat_hw.items() if h != "cpu" and ok(s)]
    seeds = ingress + compute
    cpus = [s for s, h in inst.sat_hw.items() if h == "cpu" and ok(s)]
    near_cpu: List[SatId] = []
    for seed in seeds:
        ranked = sorted((s for s in cpus if s[0] == seed[0]),
                        key=lambda s: inst.sat_dist(seed, s))
        near_cpu += ranked[:K_NEAR_CPU]
        same_plane = sorted((s for s in cpus if s[:2] == seed[:2]),
                            key=lambda s: inst.sat_dist(seed, s))
        near_cpu += same_plane[:K_NEAR_CPU]
    compute_all = sorted(set(compute + near_cpu + ingress))
    return sorted(set(ingress)), compute_all


def evaluate(inst: ProviderInstance, comps: List[str], edges, profiles,
             placement: Dict[str, Tuple[SatId, Optional[str]]],
             io: Optional[dict] = None
             ) -> Tuple[float, float, float, float, float]:
    """Independent re-score: (cost, latency, compute, network, access).

    Billing is per used satellite (reserved whole, capacity limits colocation)
    plus per activated plane. Latency is one request end to end."""
    io = io or load_io()
    used_planes = {(placement[v][0][0], placement[v][0][1]) for v in placement}
    used_sats = {placement[v][0] for v in comps}
    cost = len(used_planes) * inst.plane_cost + sum(
        inst.hw_cost[inst.sat_hw[s]] for s in used_sats)
    compute = sum(profiles[(v, placement[v][1])] for v in comps)
    network = 0.0
    access = ingress_ms(inst, io, placement[AOI][0]) \
        + egress_access_ms(inst, placement[EGRESS][0])
    for u, v, mb in edges:
        network += edge_ms(inst, io, u, v, placement[u][0],
                           placement[v][0], mb)
    return cost, compute + network + access, compute, network, access
