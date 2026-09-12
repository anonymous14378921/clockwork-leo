"""Experiment G: is satellite-level modeling necessary? (ablation)

For each satellite-level Castor plan, compute the plane-pooled abstraction's
latency prediction for the SAME logical plan (components mapped to their
planes, anchor-based plane-pair routes, one intra-plane hop between
co-plane components, best-visible access for the ingress plane) and compare
it with the true satellite-level latency. Feasibility flips (pooled says
feasible, reality says not, or vice versa) are counted per SLO.
Run via `just run pG_pooling_ablation`.
"""

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider
from lab.castor import solve_label
from lab.service import (AOI, EGRESS, _trans_ms, load_chain, load_io,
                                load_profiles)


def pooled_latency(inst, comps, edges, profiles, placement, io) -> float:
    """What the plane-pooled model would predict for this plan: plane-pair
    anchor routes for every edge (one intra-plane hop when both endpoints
    share a plane, so colocation is inexpressible), the plane's best access
    for a ground-originated ingress, and a plane-level return leg (cheapest
    visible plane by route plus access)."""
    lat = 0.0
    for u, v, mb in edges:
        pu = (placement[u][0][0], placement[u][0][1])
        pv_ = (placement[v][0][0], placement[v][0][1])
        prop = inst.route_ms.get((pu, pv_), 1e9)
        if u == AOI and io["source"] == "ground":
            lat += prop + _trans_ms(mb, inst.uplink_gbps) \
                + inst.planes[pu].access_ms
        elif v == EGRESS:
            lat += prop + _trans_ms(mb, inst.downlink_gbps) \
                + inst.planes[pv_].access_ms
        else:
            lat += prop + _trans_ms(mb, inst.isl_gbps)
    lat += sum(profiles[(v, placement[v][1])] for v in comps)
    return lat


def main() -> None:
    run = Run.start("pG_pooling_ablation")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    comps, edges = load_chain()
    profiles = load_profiles()
    io = load_io()

    rows = []
    for t0 in epochs(cfg):
        for seed in cfg["fleet_seeds"]:
            inst = build_provider(cfg["provider"], aoi, t=float(t0),
                                  seed=int(seed))
            if not any(pv.visible for pv in inst.planes.values()):
                continue
            for slo in cfg["slos_ms"]:
                slo_ms = C.to_float(slo)
                plan = solve_label(inst, slo_ms)
                if plan is None:
                    continue
                placement = {a.component: (a.sat, a.hardware)
                             for a in plan.assignments}
                pooled = pooled_latency(inst, comps, edges, profiles,
                                        placement, io)
                rows.append({
                    "epoch_s": float(t0), "seed": int(seed), "slo_ms": slo_ms,
                    "actual_ms": plan.latency_ms, "pooled_ms": pooled,
                    "error_ms": plan.latency_ms - pooled,
                    "pooled_feasible": pooled <= slo_ms,
                    "flip": (pooled <= slo_ms) != (plan.latency_ms <= slo_ms),
                })
        print(f"[pG] epoch {t0} done", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("ablation.csv", df)
    print(f"[pG] plans: {len(df)} | pooled underestimates by median "
          f"{df.error_ms.median():.1f} ms (p90 {df.error_ms.quantile(0.9):.1f})"
          f" | feasibility flips: {int(df.flip.sum())}")


if __name__ == "__main__":
    main()
