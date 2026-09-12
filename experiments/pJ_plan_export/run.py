"""Experiment J: example plan export and the multi-plane diagnosis.

Part 1: for each SLO on the example instance (the first cycle epoch at
which Castor is feasible at the tightest SLO, a rule fixed before looking at
outcomes), export the Castor plan in full (ingress, compute planes, stage
placements, inter-satellite and inter-plane edges, the return leg, latency
decomposition, cost decomposition).

Part 2: for the tight SLO across all seeds and epochs, explain every
multi-plane Castor plan by checking each visible plane in isolation with an
exact minimum-latency dynamic program: no single visible plane can host
the chain at all (hardware absence), one can but not within the SLO
(latency), or one could and Castor composed planes because it was cheaper
(single_plane_feasible). Run via `just run pJ_plan_export`.
"""

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import INF_MS, build_provider
from lab.castor import solve_label
from lab.service import (AOI, EGRESS, SAT_CAPACITY, _trans_ms, edge_ms,
                                egress_access_ms, ingress_ms, load_chain,
                                load_demands, load_io, load_profiles)


def min_latency_single_plane(inst, pid, comps, edges, profiles, demand, io):
    """Exact minimum end-to-end latency using only satellites of plane pid
    (dynamic program over stages; capacity respected; cost ignored)."""
    members = [s for s in inst.sat_hw if (s[0], s[1]) == pid]
    ingress = [s for s in members if s in inst.sat_access]
    if not ingress:
        return None
    payload = {(u, v): mb for u, v, mb in edges}
    states = {(s, tuple()): ingress_ms(inst, io, s) for s in ingress}
    for idx, v in enumerate(comps + [EGRESS]):
        u = AOI if idx == 0 else comps[idx - 1]
        mb = payload[(u, v)]
        nxt = {}
        for (cur, usage), lat in states.items():
            load = dict(usage)
            for s in (ingress if v == EGRESS else members):
                h = inst.sat_hw[s]
                if v != EGRESS and (v, h) not in profiles:
                    continue
                if v != EGRESS and load.get(s, 0.0) + demand[v] > SAT_CAPACITY + 1e-9:
                    continue
                hop = edge_ms(inst, io, u, v, cur, s, mb)
                if hop >= INF_MS:
                    continue
                if v == EGRESS:
                    nl = lat + hop + egress_access_ms(inst, s)
                    nu = dict(load)
                else:
                    nl = lat + hop + profiles[(v, h)]
                    nu = dict(load)
                    nu[s] = nu.get(s, 0.0) + demand[v]
                key = (s, tuple(sorted(nu.items())))
                if key not in nxt or nl < nxt[key]:
                    nxt[key] = nl
        states = nxt
        if not states:
            return None
    return min(states.values())


def export_plan(inst, plan, comps, edges, profiles, io):
    placement = {a.component: (a.sat, a.hardware) for a in plan.assignments}
    stages = []
    for a in plan.assignments:
        stages.append({
            "component": a.component, "sat": list(a.sat),
            "plane": list(a.plane), "hardware": a.hardware,
            "exec_ms": a.exec_ms})
    sat_edges, plane_edges = [], []
    for u, v, mb in edges:
        su, sv = placement[u][0], placement[v][0]
        first = u == AOI
        prop = inst.sat_dist(su, sv) if (su != sv or first) else 0.0
        ser = edge_ms(inst, io, u, v, su, sv, mb) - prop
        sat_edges.append({"from": u, "to": v, "sat_from": list(su),
                          "sat_to": list(sv), "payload_mb": mb,
                          "prop_ms": prop, "ser_ms": ser})
        pu, pv_ = (su[0], su[1]), (sv[0], sv[1])
        if pu != pv_:
            plane_edges.append({"from": list(pu), "to": list(pv_)})
    s_out = placement[EGRESS][0]
    used_sats = sorted({tuple(placement[v][0]) for v in comps})
    return {
        "slo_ms": None,        # filled by caller
        "source": io["source"],
        "ingress": {"sat": list(placement[AOI][0]),
                    "plane": list(placement[AOI][0][:2]),
                    "ingress_ms": ingress_ms(inst, io, placement[AOI][0])},
        "egress": {"sat": list(s_out), "plane": list(s_out[:2]),
                   "access_ms": egress_access_ms(inst, s_out),
                   "ser_ms": _trans_ms(io["sink_mb"], inst.downlink_gbps)},
        "activated_planes": [list(p) for p in plan.activated],
        "stages": stages,
        "sat_edges": sat_edges,
        "plane_edges": plane_edges,
        "latency": {"total_ms": plan.latency_ms,
                    "access_ms": plan.access_ms,
                    "network_ms": plan.network_ms,
                    "compute_ms": plan.compute_ms},
        "cost": {"total": plan.cost,
                 "planes": len(plan.activated) * inst.plane_cost,
                 "hardware": plan.cost - len(plan.activated)
                 * inst.plane_cost,
                 "billed_sats": [list(s) for s in used_sats]},
    }


def main() -> None:
    run = Run.start("pJ_plan_export")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    comps, edges = load_chain()
    profiles = load_profiles()
    demand = load_demands()
    io = load_io()
    slos = sorted(C.to_float(s) for s in cfg["slos_ms"])
    grid_epochs = epochs(cfg)

    # Part 1: example plans, instance = first epoch feasible at the tightest
    # SLO for the example seed (rule fixed before any outcome).
    ex_seed = int(cfg["example_seed"])
    inst, ex_t = None, None
    for t0 in grid_epochs:
        cand = build_provider(cfg["provider"], aoi, t=float(t0), seed=ex_seed)
        if solve_label(cand, slos[0]) is not None:
            inst, ex_t = cand, float(t0)
            break
    if inst is None:
        raise RuntimeError("no cycle epoch feasible at the tightest SLO")
    exports = []
    for slo_ms in slos:
        plan = solve_label(inst, slo_ms)
        if plan is None:
            exports.append({"slo_ms": slo_ms, "feasible": False})
            continue
        doc = export_plan(inst, plan, comps, edges, profiles, io)
        doc["slo_ms"] = slo_ms
        doc["feasible"] = True
        exports.append(doc)
        print(f"[pJ] SLO {slo_ms:.0f}: cost {plan.cost:.0f}, "
              f"lat {plan.latency_ms:.1f} ms (comp {plan.compute_ms:.1f} "
              f"net {plan.network_ms:.1f} acc {plan.access_ms:.1f}), "
              f"planes {len(plan.activated)}", flush=True)
    run.save_json("plans.json", {"example": {"epoch_s": ex_t,
                                             "seed": ex_seed},
                                 "plans": exports})

    # Part 2: why multiple planes at the tight SLO.
    dslo = C.to_float(cfg["diagnose_slo_ms"])
    rows = []
    for t0 in grid_epochs:
        for seed in cfg["diagnose_seeds"]:
            inst = build_provider(cfg["provider"], aoi, t=float(t0),
                                  seed=int(seed))
            vis = [p for p, pv in inst.planes.items() if pv.visible]
            if not vis:
                continue
            plan = solve_label(inst, dslo)
            if plan is None:
                continue
            lats = {p: min_latency_single_plane(inst, p, comps, edges,
                                                profiles, demand, io)
                    for p in vis}
            hosting = {p: l for p, l in lats.items() if l is not None}
            best = min(hosting.values()) if hosting else None
            if not hosting:
                reason = "hardware_absent"
            elif best > dslo:
                reason = "latency"
            else:
                reason = "single_plane_feasible"
            rows.append({
                "epoch_s": float(t0), "seed": int(seed),
                "n_planes": len(plan.activated), "cost": plan.cost,
                "n_visible": len(vis),
                "n_hosting_planes": len(hosting),
                "best_single_plane_ms": best,
                "gap_ms": (best - dslo) if best is not None else None,
                "reason": reason,
            })
        print(f"[pJ] diagnose epoch {t0:.0f} done", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("diagnosis.csv", df)
    multi = df[df.n_planes > 1]
    print(f"[pJ] SLO {dslo:.0f}: {len(multi)}/{len(df)} plans multi-plane | "
          f"reasons: {multi.reason.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
