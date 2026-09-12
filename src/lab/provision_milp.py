"""Min-cost provisioning MILP, satellite-level model (2026-09-01).

Roles are separated per the model decision: PLANES are the provisioning
domain the tenant sees (activation variables y_p, activation cost), while
placement and routing are SATELLITE-level. Each satellite carries one
hardware class, so the placement variable is x_{v,s} with hardware implied,
linked by x_{v,s} <= y_{plane(s)}. Ingress is the actual visible satellite
(a_s over visible satellites) and latency uses true satellite-pair shortest
paths. Satellites have normalized capacity SAT_CAPACITY and components have
fractional demands (workflow yaml), so components may colocate; billing is
per USED satellite (w_s binaries) plus per activated plane. Service model
(Clockwork, 2026-09-01): the workflow's `source` decides whether the image
is captured on the ingress satellite (no uplink) or uplinked from the AoI;
the result returns to the ground through a visible EGRESS satellite whose
plane is reserved, symmetric with the ingress (b_v binaries). Forwarding is
pipelined: serialization once per transfer, propagation per route.
Colocated components pay no hop.

Candidate restriction keeps the program CBC-sized: all visible satellites,
every non-cpu satellite, and the k nearest cpu satellites to each visible
and each GPU satellite. Cross-shell pairs are infinite (portfolio, not
spanning). Every returned plan is re-scored by the independent evaluator
with a loud assert.

Baselines call this same solver restricted to single planes, so every
method shares one set of arithmetic.
"""

import csv
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import pulp
import yaml

from lab import constants as C
from lab.harness.runner import repo_root
from lab.provider import INF_MS, PlaneId, ProviderInstance, SatId

AOI = "aoi"
EGRESS = "egress"      # virtual sink: the visible satellite that downlinks
K_NEAR_CPU = 2
SAT_CAPACITY = 1.0     # normalized capacity of every satellite


@dataclass
class Assignment:
    component: str
    sat: Optional[SatId]        # None never occurs for real components
    hardware: Optional[str]     # None for the aoi virtual node
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
    """Service model of the workflow: `source` ("satellite": the image is
    captured on the ingress satellite; "ground": the request uplinks from
    the AoI) and `sink_mb` (result payload downlinked to the ground)."""
    with (repo_root() / "workflows" / f"{name}.yaml").open() as f:
        spec = yaml.safe_load(f)
    source = spec.get("source", "satellite")
    if source not in ("satellite", "ground"):
        raise ValueError(f"unknown workflow source mode {source!r}")
    return {"source": source,
            "sink_mb": C.to_float(spec["sink"]["payload_mb"])}


def ingress_ms(inst: ProviderInstance, io: dict, s: SatId) -> float:
    """Latency charged before the first component: the AoI access
    propagation for a ground-originated request, nothing when the image is
    captured on the ingress satellite itself."""
    if io["source"] == "ground":
        return inst.sat_access.get(s, INF_MS)
    return 0.0 if s in inst.sat_access else INF_MS


def edge_ms(inst: ProviderInstance, io: dict, u: str, v: str, su: SatId,
            sv: SatId, mb: float) -> float:
    """Propagation plus serialization of one chain edge (u, v) placed on
    satellites (su, sv). Forwarding is pipelined over uncongested links:
    serialization is paid once per transfer, propagation accumulates over
    the route. The first edge of a ground-originated request serializes at
    the uplink rate; the last edge (to the downlinking satellite)
    serializes at the downlink rate and pays no ISL hop when colocated;
    other edges pay nothing when colocated. INF when the endpoints have no
    path."""
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
    """Ground-link propagation of the return leg from satellite s, which
    must be AoI-visible (INF otherwise)."""
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
        # K nearest cpu satellites in the same shell (by latency) AND K
        # nearest in the same plane: the latter avoids a plane activation,
        # which the latency ranking alone cannot see (lossy without it,
        # found by pA on the Clockwork model 2026-09-01; pI verifies).
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

    Billing is per USED satellite (single-tenant reservation: a satellite
    is reserved whole, capacity limits how many components fit on it) plus
    per activated plane. Latency is one request end to end: the ingress
    term of the service model (nothing for a satellite-captured image, AoI
    access for a ground-originated request), the chain edges (ISL hop plus
    serialization, zero when colocated, uplink serialization on the first
    edge of a ground request), the component executions, and the return
    leg from the last component's satellite to the nearest AoI-visible
    satellite and down. `access` collects the ground-link propagation
    terms, `network` the ISL propagation and every serialization."""
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


def solve(inst: ProviderInstance, slo_ms: float,
          workflow: str = "mvp_fixed", profile_name: str = "workflow_mvp",
          restrict_planes: Optional[Iterable[PlaneId]] = None,
          full_candidates: bool = False,
          profiles: Optional[Dict[Tuple[str, str], float]] = None,
          io: Optional[dict] = None
          ) -> Optional[ProvisionPlan]:
    comps, edges = load_chain(workflow)
    if profiles is None:
        profiles = load_profiles(profile_name)
    demand = load_demands(workflow)
    io = io or load_io(workflow)
    ingress, cands = candidate_sats(inst, restrict_planes, full_candidates)
    if not ingress:
        return None

    prob = pulp.LpProblem("ace_provision_sat", pulp.LpMinimize)
    planes_touched = sorted({(s[0], s[1]) for s in cands}
                            | {(s[0], s[1]) for s in ingress})
    y = {p: pulp.LpVariable(f"y_{i}", cat="Binary")
         for i, p in enumerate(planes_touched)}
    x = {(v, s): pulp.LpVariable(f"x_{v}_{i}", cat="Binary")
         for v in comps for i, s in enumerate(cands)
         if (v, inst.sat_hw[s]) in profiles}
    a = {s: pulp.LpVariable(f"a_{i}", cat="Binary")
         for i, s in enumerate(ingress)}
    b = {s: pulp.LpVariable(f"b_{i}", cat="Binary")   # downlinking satellite
         for i, s in enumerate(ingress)}
    w = {s: pulp.LpVariable(f"w_{i}", cat="Binary")   # satellite is billed
         for i, s in enumerate(cands)}

    for v in comps:
        prob += pulp.lpSum(var for (vv, _), var in x.items() if vv == v) == 1
    prob += pulp.lpSum(a.values()) == 1
    prob += pulp.lpSum(b.values()) == 1
    for (v, s), var in x.items():
        prob += var <= y[(s[0], s[1])]
        prob += var <= w[s]
    for s, var in a.items():
        prob += var <= y[(s[0], s[1])]
    for s, var in b.items():                # the egress plane is reserved too
        prob += var <= y[(s[0], s[1])]
    for s in cands:                       # normalized capacity per satellite
        prob += pulp.lpSum(demand[vv] * var
                           for (vv, ss), var in x.items()
                           if ss == s) <= SAT_CAPACITY

    def on(v: str, s: SatId):
        if v == AOI:
            return a.get(s, 0)
        if v == EGRESS:
            return b.get(s, 0)
        return x.get((v, s), 0)

    # Execution, the ingress term (linear in a), egress access plus downlink
    # serialization (linear in b); edge propagation via z.
    sink_ser = _trans_ms(io["sink_mb"], inst.downlink_gbps)
    lat = pulp.lpSum(var * profiles[(v, inst.sat_hw[s])]
                     for (v, s), var in x.items())
    lat = lat + pulp.lpSum(var * ingress_ms(inst, io, s)
                           for s, var in a.items())
    lat = lat + pulp.lpSum(var * (egress_access_ms(inst, s) + sink_ser)
                           for s, var in b.items())
    for ei, (u, v, mb) in enumerate(edges):
        tails = ingress if u == AOI else cands
        heads = ingress if v == EGRESS else cands
        for i, su in enumerate(tails):
            if u != AOI and (u, su) not in x:
                continue
            for j, sv in enumerate(heads):
                if v != EGRESS and (v, sv) not in x:
                    continue
                coeff = edge_ms(inst, io, u, v, su, sv, mb)
                if v == EGRESS and coeff < INF_MS:
                    coeff -= sink_ser     # already linear in b
                if coeff >= INF_MS:
                    prob += on(u, su) + on(v, sv) <= 1
                    continue
                if coeff == 0.0:
                    continue              # colocated: no hop, no serialization
                zz = pulp.LpVariable(f"z_{ei}_{i}_{j}", cat="Binary")
                prob += zz >= on(u, su) + on(v, sv) - 1
                lat = lat + zz * coeff
    prob += lat <= slo_ms

    prob += (pulp.lpSum(y[p] * inst.plane_cost for p in planes_touched)
             + pulp.lpSum(var * inst.hw_cost[inst.sat_hw[s]]
                          for s, var in w.items()))
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[prob.status] != "Optimal":
        return None

    placement: Dict[str, Tuple[SatId, Optional[str]]] = {}
    for s, var in a.items():
        if var.value() > 0.5:
            placement[AOI] = (s, None)
    for (v, s), var in x.items():
        if var.value() > 0.5:
            placement[v] = (s, inst.sat_hw[s])
    for s, var in b.items():
        if var.value() > 0.5:
            placement[EGRESS] = (s, None)
    cost, latency, compute, network, access = evaluate(
        inst, comps, edges, profiles, placement, io)
    assert latency <= slo_ms + 1e-6, "re-scored plan violates the SLO"
    loads: Dict[SatId, float] = {}
    for v in comps:
        loads[placement[v][0]] = loads.get(placement[v][0], 0.0) + demand[v]
    assert all(l <= SAT_CAPACITY + 1e-9 for l in loads.values()), \
        "plan violates satellite capacity"

    return ProvisionPlan(
        assignments=[Assignment(v, placement[v][0], placement[v][1],
                                profiles.get((v, placement[v][1]), 0.0)
                                if placement[v][1] else 0.0)
                     for v in [AOI] + comps + [EGRESS]],
        activated=sorted({(placement[v][0][0], placement[v][0][1])
                          for v in placement}),
        cost=cost, latency_ms=latency, compute_ms=compute,
        network_ms=network, access_ms=access, feasible=True)
