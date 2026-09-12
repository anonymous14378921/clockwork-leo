"""Layered Pareto label search: the primary provisioning algorithm.

Dynamic programming over the chain workflow's layered placement graph
(with dominance corrections).
A label is one nondominated partial plan,

    sigma = (stage, current satellite, cost C, latency L,
             activated planes P_U, per-satellite resource usage U),

extended stage by stage from every feasible ingress. Labels are bucketed by
(stage, current satellite); within a bucket, sigma1 dominates sigma2 iff

    C1 <= C2,  L1 <= L2,  P_U1 SUPERSET-OR-EQUAL P_U2,
    U1 <= U2 component-wise (residual-capacity dominance),

with at least one strict inequality. The plane-superset direction is
required because already-paid activations are future discounts; the
component-wise usage comparison (not set inclusion) is required because two
labels can load the same satellite to different depths. Exact for chains
given these rules; verified against the independent MILP and a brute-force
oracle in tests (triple check).

Capacity model (2026-09-01): satellites have normalized capacity
SAT_CAPACITY, components have fractional demands, colocation is allowed,
and billing is per USED satellite plus per activated plane, so placing a
second component on an already-billed satellite adds no hardware cost.
Service model (Clockwork, 2026-09-01): the workflow's source mode decides
the ingress term (satellite-captured image or ground uplink), colocated
consecutive components pay no hop, and the last stage adds the return leg
to the ground (egress), which depends only on the last satellite and so
preserves the bucket dominance.

Every returned plan is re-scored through provision_milp.evaluate with a
loud assert, the house anti-fabrication pattern.
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

from lab.provider import INF_MS, PlaneId, ProviderInstance, SatId
from lab.provision_milp import (AOI, EGRESS, SAT_CAPACITY, Assignment,
                                ProvisionPlan, candidate_sats, edge_ms,
                                egress_access_ms, evaluate, ingress_ms,
                                load_chain, load_demands, load_io,
                                load_profiles)

EPS = 1e-9


@dataclass
class Label:
    sat: SatId
    hw: str
    cost: float
    lat: float
    planes: FrozenSet[PlaneId]
    usage: Dict[SatId, float]
    parent: Optional["Label"]
    component: str


def _dominates(a: Label, b: Label) -> bool:
    if a.cost > b.cost + EPS or a.lat > b.lat + EPS:
        return False
    if not a.planes.issuperset(b.planes):
        return False
    for s, u in a.usage.items():
        if u > b.usage.get(s, 0.0) + EPS:
            return False
    strict = (a.cost < b.cost - EPS or a.lat < b.lat - EPS
              or a.planes != b.planes or a.usage != b.usage)
    return strict or (a.cost <= b.cost and a.lat <= b.lat)


def _insert(bucket: List[Label], lab: Label) -> None:
    for other in bucket:
        if _dominates(other, lab):
            return
    bucket[:] = [o for o in bucket if not _dominates(lab, o)]
    bucket.append(lab)


def _remaining_lb(inst, usage: Dict[SatId, float], comps, demand, profiles,
                  min_hw, idx: int) -> float:
    """Colocation-aware lower bound on the cost still to pay after stage
    idx-1. For each remaining component: zero if it could ride free on an
    already-billed satellite (compatible class, enough residual), else at
    least the cheapest compatible hardware. Later components may share ONE
    new satellite, so the sound aggregate is the max, not the sum."""
    lb = 0.0
    for k in range(idx, len(comps)):
        v = comps[k]
        free = any((v, inst.sat_hw[s]) in profiles
                   and u + demand[v] <= SAT_CAPACITY + EPS
                   for s, u in usage.items())
        if not free:
            lb = max(lb, min_hw[k])
    return lb


def solve_label(inst: ProviderInstance, slo_ms: float,
                workflow: str = "mvp_fixed",
                profile_name: str = "workflow_mvp",
                restrict_planes: Optional[Iterable[PlaneId]] = None,
                full_candidates: bool = False,
                profiles: Optional[Dict[Tuple[str, str], float]] = None,
                io: Optional[dict] = None,
                keep_all: bool = False, cost_slack: float = 0.0,
                objective: str = "cost"
                ):
    """Min-cost SLO-feasible plan, or None. With keep_all=True, return the
    LIST of every nondominated final plan whose cost is within cost_slack
    of the greedy incumbent (the candidate pool of the calendar planner);
    the branch-and-bound bound is relaxed by the same slack so those plans
    survive the search. objective="latency" turns the same search into the
    LATENCY-FIRST policy (cost-blind, may compose planes): the incumbent is
    a fastest-first greedy dive and labels slower than it are pruned, which
    is sound because latency only grows along the chain."""
    if objective not in ("cost", "latency"):
        raise ValueError(objective)
    comps, edges = load_chain(workflow)
    if profiles is None:
        profiles = load_profiles(profile_name)
    demand = load_demands(workflow)
    io = io or load_io(workflow)
    ingress, cands = candidate_sats(inst, restrict_planes, full_candidates)
    if not ingress:
        return None
    payload = {(u, v): mb for u, v, mb in edges}

    # Cheapest compatible hardware per component (used inside the
    # colocation-aware remaining-cost bound) and a greedy incumbent for
    # branch-and-bound pruning: labels that cannot beat the incumbent are
    # discarded. Sound (the bound is a true lower bound), and it prevents
    # label proliferation at loose SLOs, where latency prunes nothing.
    min_hw = []
    for v in comps:
        costs = [inst.hw_cost[inst.sat_hw[s]] for s in cands
                 if (v, inst.sat_hw[s]) in profiles]
        if not costs:
            return None
        min_hw.append(min(costs))
    incumbent = _greedy_dive(inst, slo_ms, comps, payload, demand, profiles,
                             ingress, cands, io, objective)
    if objective == "latency":
        ub = float("inf")                 # no cost pruning
        lat_ub = incumbent[0] if incumbent else slo_ms
    else:
        ub = incumbent[0] + cost_slack if incumbent else float("inf")
        lat_ub = slo_ms
    # Latency lookahead: the cheapest possible remaining execution plus the
    # nearest possible egress access. Sound, prunes at every SLO.
    min_exec = [min((profiles[(v, inst.sat_hw[s])] for s in cands
                     if (v, inst.sat_hw[s]) in profiles), default=INF_MS)
                for v in comps]
    min_egress = min(egress_access_ms(inst, s) for s in ingress)
    rem_lat = [sum(min_exec[k:]) + min_egress for k in range(len(comps) + 1)]

    # Stage 0: ingress pseudo-labels (sensing consumes no compute unit).
    buckets: Dict[SatId, List[Label]] = {}
    for si in ingress:
        p = (si[0], si[1])
        lab = Label(si, "", inst.plane_cost, ingress_ms(inst, io, si),
                    frozenset([p]), {}, None, AOI)
        _insert(buckets.setdefault(si, []), lab)

    for idx, v in enumerate(comps):
        u = AOI if idx == 0 else comps[idx - 1]
        mb = payload[(u, v)]
        nxt: Dict[SatId, List[Label]] = {}
        for bucket in buckets.values():
            for lab in bucket:
                for s in cands:
                    h = inst.sat_hw[s]
                    if (v, h) not in profiles:
                        continue
                    used = lab.usage.get(s, 0.0)
                    if used + demand[v] > SAT_CAPACITY + EPS:
                        continue
                    hop = edge_ms(inst, io, u, v, lab.sat, s, mb)
                    if hop >= INF_MS:
                        continue
                    lat = lab.lat + hop + profiles[(v, h)]
                    if lat + rem_lat[idx + 1] > lat_ub + EPS:
                        continue
                    p = (s[0], s[1])
                    cost = lab.cost + (
                        0.0 if used > EPS else inst.hw_cost[h]) + (
                        0.0 if p in lab.planes else inst.plane_cost)
                    usage = dict(lab.usage)
                    usage[s] = used + demand[v]
                    if cost + _remaining_lb(inst, usage, comps, demand,
                                            profiles, min_hw,
                                            idx + 1) > ub + EPS:
                        continue          # cannot beat the incumbent
                    new = Label(s, h, cost, lat,
                                lab.planes | frozenset([p]), usage, lab, v)
                    _insert(nxt.setdefault(s, []), new)
        buckets = nxt
        if not buckets:
            return None

    # Egress stage: the result returns through a visible satellite whose
    # plane is reserved (free if already activated, else a plane fee),
    # symmetric with the ingress. Consumes no compute.
    mb = payload[(comps[-1], EGRESS)]
    nxt = {}
    for bucket in buckets.values():
        for lab in bucket:
            for v_out in ingress:
                hop = edge_ms(inst, io, comps[-1], EGRESS, lab.sat, v_out, mb)
                if hop >= INF_MS:
                    continue
                lat = lab.lat + hop + egress_access_ms(inst, v_out)
                if lat > lat_ub + EPS:
                    continue
                p = (v_out[0], v_out[1])
                cost = lab.cost + (0.0 if p in lab.planes else inst.plane_cost)
                if cost > ub + EPS:
                    continue
                _insert(nxt.setdefault(v_out, []),
                        Label(v_out, "", cost, lat, lab.planes | frozenset([p]),
                              lab.usage, lab, EGRESS))
    buckets = nxt
    if not buckets:
        return None

    finals = [lab for bucket in buckets.values() for lab in bucket]
    if keep_all:
        # The pool rule is relative to the OPTIMUM: every nondominated final
        # plan within cost_slack of the cheapest one (the incumbent only
        # bounds the search, and is relaxed by the same slack so these
        # plans survive).
        opt = min(lab.cost for lab in finals)
        return [_materialize(lab, inst, comps, edges, profiles, demand, io,
                             slo_ms) for lab in finals
                if lab.cost <= opt + cost_slack + EPS]
    best: Optional[Label] = None
    for lab in finals:
        if objective == "latency":
            better = best is None or lab.lat < best.lat - EPS or (
                abs(lab.lat - best.lat) < EPS and lab.cost < best.cost)
        else:
            better = best is None or lab.cost < best.cost - EPS or (
                abs(lab.cost - best.cost) < EPS and lab.lat < best.lat)
        if better:
            best = lab
    if best is None:
        return None
    return _materialize(best, inst, comps, edges, profiles, demand, io,
                        slo_ms)


def _materialize(best: Label, inst, comps, edges, profiles, demand, io,
                 slo_ms: float) -> ProvisionPlan:
    """Follow parent pointers and re-score through the independent
    evaluator with loud asserts (the anti-fabrication pattern)."""
    chain: List[Label] = []
    cur = best
    while cur is not None:
        chain.append(cur)
        cur = cur.parent
    chain.reverse()
    placement: Dict[str, Tuple[SatId, Optional[str]]] = {
        AOI: (chain[0].sat, None)}
    for lab in chain[1:]:
        placement[lab.component] = (lab.sat, lab.hw or None)
    cost, latency, compute, network, access = evaluate(
        inst, comps, edges, profiles, placement, io)
    assert abs(cost - best.cost) < 1e-6, "label cost disagrees with evaluator"
    assert abs(latency - best.lat) < 1e-6, "label latency disagrees with evaluator"
    assert latency <= slo_ms + 1e-6, "label plan violates the SLO"
    loads: Dict[SatId, float] = {}
    for v in comps:
        loads[placement[v][0]] = loads.get(placement[v][0], 0.0) + demand[v]
    assert all(l <= SAT_CAPACITY + EPS for l in loads.values()), \
        "label plan violates satellite capacity"

    return ProvisionPlan(
        assignments=[Assignment(v, placement[v][0], placement[v][1],
                                profiles.get((v, placement[v][1]), 0.0)
                                if placement[v][1] else 0.0)
                     for v in [AOI] + comps + [EGRESS]],
        activated=sorted({(placement[v][0][0], placement[v][0][1])
                          for v in placement}),
        cost=cost, latency_ms=latency, compute_ms=compute,
        network_ms=network, access_ms=access, feasible=True)


def _greedy_dive(inst, slo_ms, comps, payload, demand, profiles,
                 ingress, cands, io, objective: str = "cost"):
    """Greedy chain for the branch-and-bound incumbent: cheapest-first
    (objective cost, returns (cost, placement)) or fastest-first (objective
    latency, returns (latency, placement)). None if the dive fails."""
    best = None
    for si in sorted(ingress, key=lambda s: inst.sat_access[s])[:4]:
        cur, lat = si, ingress_ms(inst, io, si)
        cost = inst.plane_cost
        planes = {(si[0], si[1])}
        usage: Dict[SatId, float] = {}
        placement = {AOI: (si, None)}
        ok = True
        for idx, v in enumerate(comps + [EGRESS]):
            u = AOI if idx == 0 else comps[idx - 1]
            mb = payload[(u, v)]
            options = []
            for s in (ingress if v == EGRESS else cands):
                h = inst.sat_hw[s]
                if v != EGRESS and (v, h) not in profiles:
                    continue
                used = usage.get(s, 0.0)
                if v != EGRESS and used + demand[v] > SAT_CAPACITY + EPS:
                    continue
                hop = edge_ms(inst, io, u, v, cur, s, mb)
                if hop >= INF_MS:
                    continue
                if v == EGRESS:
                    nl = lat + hop + egress_access_ms(inst, s)
                else:
                    nl = lat + hop + profiles[(v, h)]
                if nl > slo_ms:
                    continue
                p = (s[0], s[1])
                if v == EGRESS:
                    dc = 0.0 if p in planes else inst.plane_cost
                else:
                    dc = (0.0 if used > 1e-9 else inst.hw_cost[h]) + (
                        0.0 if p in planes else inst.plane_cost)
                key = (nl, dc) if objective == "latency" else (dc, nl)
                options.append((key, s, h, p, dc, nl))
            if not options:
                ok = False
                break
            _, s, h, p, dc, nl = min(options)
            cost += dc
            lat = nl
            cur = s
            planes.add(p)
            if v == EGRESS:
                placement[v] = (s, None)
            else:
                usage[s] = usage.get(s, 0.0) + demand[v]
                placement[v] = (s, h)
        score = lat if objective == "latency" else cost
        if ok and (best is None or score < best[0]):
            best = (score, placement)
    return best


def solve_brute(inst: ProviderInstance, slo_ms: float,
                workflow: str = "mvp_fixed",
                profile_name: str = "workflow_mvp",
                io: Optional[dict] = None
                ) -> Optional[Tuple[float, float]]:
    """Brute-force oracle for tiny instances: (min cost, its latency).
    Independent of both the MILP and the label search (triple check)."""
    import itertools
    comps, edges = load_chain(workflow)
    profiles = load_profiles(profile_name)
    demand = load_demands(workflow)
    io = io or load_io(workflow)
    ingress, cands = candidate_sats(inst)
    best = None
    opts = [[(s, inst.sat_hw[s]) for s in cands
             if (v, inst.sat_hw[s]) in profiles] for v in comps]
    for si in ingress:
        for combo in itertools.product(*opts):
            loads: Dict[SatId, float] = {}
            for v, (s, h) in zip(comps, combo):
                loads[s] = loads.get(s, 0.0) + demand[v]
            if any(l > SAT_CAPACITY + EPS for l in loads.values()):
                continue
            for so in ingress:
                placement = {AOI: (si, None), EGRESS: (so, None)}
                for v, (s, h) in zip(comps, combo):
                    placement[v] = (s, h)
                cost, lat, _, _, _ = evaluate(inst, comps, edges, profiles,
                                              placement, io)
                if lat <= slo_ms and (best is None or cost < best[0]):
                    best = (cost, lat)
    return best
