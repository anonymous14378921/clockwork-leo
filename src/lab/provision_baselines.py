"""Provisioning baselines sharing the satellite-level evaluation model.

The single-plane policies use the same solver restricted to selected planes:

- nearest: the plane containing the highest-elevation visible satellite.
- max_compute: the visible plane with the largest capacity score.
- cheapest_single: best over all visible planes (restricted solve each).

Greedy Compose places components sequentially by incremental cost.
Latency First is the exact latency-objective ablation. The adapted HyperDrive
policy preserves upstream network scoring. These three permit multiple planes.
"""

from typing import Optional

from lab.provider import PlaneId, ProviderInstance
from lab.castor import solve_label as solve
from lab.service import ProvisionPlan
from lab.hyperdrive import solve_hyperdrive


def _visible_planes(inst: ProviderInstance):
    return [p for p, pv in inst.planes.items() if pv.visible]


def nearest(inst: ProviderInstance, slo_ms: float,
            **kw) -> Optional[ProvisionPlan]:
    vis = _visible_planes(inst)
    if not vis:
        return None
    pid = max(vis, key=lambda p: inst.planes[p].best_elevation)
    return solve(inst, slo_ms, restrict_planes=[pid], **kw)


def max_compute(inst: ProviderInstance, slo_ms: float,
                **kw) -> Optional[ProvisionPlan]:
    vis = _visible_planes(inst)
    if not vis:
        return None

    def score(p: PlaneId) -> float:
        return sum(n * inst.hw_cost[h]
                   for h, n in inst.planes[p].hw_counts.items())

    pid = max(vis, key=score)
    return solve(inst, slo_ms, restrict_planes=[pid], **kw)


def cheapest_single(inst: ProviderInstance, slo_ms: float,
                    **kw) -> Optional[ProvisionPlan]:
    best: Optional[ProvisionPlan] = None
    for pid in _visible_planes(inst):
        plan = solve(inst, slo_ms, restrict_planes=[pid], **kw)
        if plan is not None and (best is None or plan.cost < best.cost):
            best = plan
    return best


def greedy_compose(inst: ProviderInstance, slo_ms: float,
                   **kw) -> Optional[ProvisionPlan]:
    """Multi-plane greedy: cheapest feasible ingress, then per component the
    cheapest reachable compatible satellite that keeps the SLO reachable
    (min-remaining-execution lookahead), activating planes as needed. Can
    compose planes but does not optimize globally."""
    from lab.service import (AOI, EGRESS, SAT_CAPACITY, candidate_sats,
                         edge_ms, egress_access_ms, evaluate,
                         ingress_ms, load_chain, load_demands,
                         load_io, load_profiles)
    comps, edges = load_chain(kw.get("workflow", "mvp_fixed"))
    profiles = kw.get("profiles") or load_profiles(
        kw.get("profile_name", "workflow_mvp"))
    demand = load_demands(kw.get("workflow", "mvp_fixed"))
    io = kw.get("io") or load_io(kw.get("workflow", "mvp_fixed"))
    ingress, cands = candidate_sats(inst)
    if not ingress:
        return None
    payload = {(u, v): mb for u, v, mb in edges}
    min_rem = []
    for i in range(len(comps)):
        rem = 0.0
        for v in comps[i:]:
            execs = [profiles[(v, inst.sat_hw[s2])] for s2 in cands
                     if (v, inst.sat_hw[s2]) in profiles]
            if not execs:
                return None
            rem += min(execs)
        min_rem.append(rem)
    min_rem.append(0.0)

    best_plan = None
    for si in sorted(ingress, key=lambda s2: inst.sat_access[s2])[:3]:
        lat = ingress_ms(inst, io, si)
        planes = {(si[0], si[1])}
        usage = {}
        placement = {AOI: (si, None)}
        cur, ok = si, True
        for idx, v in enumerate(comps + [EGRESS]):
            u = AOI if idx == 0 else comps[idx - 1]
            mb = payload[(u, v)]
            options = []
            for s2 in (ingress if v == EGRESS else cands):
                h = inst.sat_hw[s2]
                if v != EGRESS and (v, h) not in profiles:
                    continue
                load = usage.get(s2, 0.0)
                if v != EGRESS and load + demand[v] > SAT_CAPACITY + 1e-9:
                    continue
                hop = edge_ms(inst, io, u, v, cur, s2, mb)
                if hop >= 1e9:
                    continue
                if v == EGRESS:
                    nl = lat + hop + egress_access_ms(inst, s2)
                    rem = 0.0
                else:
                    nl = lat + hop + profiles[(v, h)]
                    rem = min_rem[idx + 1]
                if nl + rem > slo_ms:
                    continue
                p = (s2[0], s2[1])
                if v == EGRESS:
                    dc = 0 if p in planes else inst.plane_cost
                else:
                    dc = (0.0 if load > 1e-9 else inst.hw_cost[h]) + (
                        0 if p in planes else inst.plane_cost)
                options.append((dc, nl, s2, h, p))
            if not options:
                ok = False
                break
            dc, nl, s2, h, p = min(options)
            lat, cur = nl, s2
            planes.add(p)
            if v == EGRESS:
                placement[v] = (s2, None)
            else:
                usage[s2] = usage.get(s2, 0.0) + demand[v]
                placement[v] = (s2, h)
        if not ok:
            continue
        cost, l2, comp_ms, net_ms, acc_ms = evaluate(inst, comps, edges,
                                                     profiles, placement, io)
        if l2 <= slo_ms and (best_plan is None or cost < best_plan.cost):
            from lab.service import Assignment
            best_plan = ProvisionPlan(
                assignments=[Assignment(v, placement[v][0], placement[v][1],
                                        profiles.get((v, placement[v][1]),
                                                     0.0)
                                        if placement[v][1] else 0.0)
                             for v in [AOI] + comps + [EGRESS]],
                activated=sorted({(placement[v][0][0], placement[v][0][1])
                                  for v in placement}),
                cost=cost, latency_ms=l2, compute_ms=comp_ms,
                network_ms=net_ms, access_ms=acc_ms, feasible=True)
    return best_plan


def latency_first(inst: ProviderInstance, slo_ms: float,
                  **kw) -> Optional[ProvisionPlan]:
    """Latency-first placement (an exact latency objective ablation):
    minimize end-to-end latency, cost-blind, free to compose planes. The
    same exact search with the latency objective, so it is feasible
    exactly when Castor is; it shows what ignoring cost costs."""
    return solve(inst, slo_ms, objective="latency", **kw)


POLICIES = {"nearest": nearest, "max_compute": max_compute,
            "cheapest_single": cheapest_single,
            "greedy_compose": greedy_compose,
            "latency_first": latency_first,
            "hyperdrive": solve_hyperdrive}
