"""Experiment E v3: replanning policies under orbital dynamics.

Per epoch: rebuild substrate, solve the fresh optimum (label search), and
advance each policy's incumbent. Every policy may perform ingress HANDOVER
within its activated planes (control-plane event); policies differ only in
WHEN they adopt a fresh plan: event-driven (only when the incumbent is
infeasible after handover), periodic (every Delta), always-fresh (whenever
the optimum changes). A REPROVISION is counted when the adopted plan
changes the compute placement OR grows the activated plane set; an ingress
change within the already-activated planes is a handover. Temporal cost is
a RESERVATION RATE: an incumbent's plan cost is charged per hour for as
long as it stays reserved (served or not) and integrated over the 24 h
window into reserved unit-hours. The horizon is one cycle (a sidereal day)
sampled on n_steps instants. Run via `just run pE_time`.
"""

import pandas as pd

from lab import constants as C
from lab.cycle import cycle_s, grid
from lab.harness import Run
from lab.provider import build_provider
from lab.castor import solve_label as solve
from lab.service import (AOI, EGRESS, evaluate, load_chain,
                                load_profiles)

IO = (AOI, EGRESS)      # virtual nodes: no compute, free handover


def provision_key(placement):
    """(compute placement, activated plane set): the tenant-visible state."""
    comp = tuple(sorted((v, p[0]) for v, p in placement.items()
                        if v not in IO))
    planes = frozenset((p[0][0], p[0][1]) for p in placement.values())
    return comp, planes


def is_reprovision(old_placement, new_placement) -> bool:
    ck_old, pl_old = provision_key(old_placement)
    ck_new, pl_new = provision_key(new_placement)
    return ck_new != ck_old or not pl_new <= pl_old


def plan_rate(inst, placement) -> float:
    """Reservation rate of a plan in cost units (its static plan cost)."""
    planes = {(placement[v][0][0], placement[v][0][1]) for v in placement}
    sats = {placement[v][0] for v in placement if v not in IO}
    return (len(planes) * inst.plane_cost
            + sum(inst.hw_cost[inst.sat_hw[s]] for s in sats))


def handover_eval(inst, comps, edges, profiles, placement, slo_ms):
    """Best ingress and egress re-selection within the plan's activated
    planes (both are free handovers, symmetric)."""
    active = {(placement[v][0][0], placement[v][0][1]) for v in placement}
    vis = inst.visible_in(active)
    best = None
    for s_in in vis:
        for s_out in vis:
            trial = dict(placement)
            trial[AOI] = (s_in, None)
            trial[EGRESS] = (s_out, None)
            cost, lat, _, _, _ = evaluate(inst, comps, edges, profiles, trial)
            if best is None or lat < best[1]:
                best = (cost, lat, trial)
    if best is None:
        return None
    cost, lat, trial = best
    return (cost, lat, trial) if lat <= slo_ms else None


def main() -> None:
    run = Run.start("pE_time")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    slo_ms = C.to_float(cfg["slo_ms"])
    n_steps = int(cfg["n_steps"])
    times = grid(n_steps)
    step = cycle_s() / n_steps
    comps, edges = load_chain()
    profiles = load_profiles()
    policies = (["event", "fresh"]
                + [f"periodic_{p}" for p in cfg["periodic_s"]])

    rows = []
    for seed in cfg["fleet_seeds"]:
        inc = {p: None for p in policies}     # placement dict per policy
        for k, t in enumerate(times):
            inst = build_provider(cfg["provider"], aoi, t=float(t),
                                  seed=int(seed))
            nvis = sum(pv.visible for pv in inst.planes.values())
            fresh = solve(inst, slo_ms) if nvis else None
            fresh_pl = ({a.component: (a.sat, a.hardware)
                         for a in fresh.assignments} if fresh else None)

            for pol in policies:
                state = (handover_eval(inst, comps, edges, profiles,
                                       inc[pol], slo_ms)
                         if inc[pol] is not None else None)
                if state is not None:     # track the handed-over ingress so
                    inc[pol] = dict(state[2])   # released planes stop billing
                adopt = False
                if pol == "event":
                    adopt = state is None
                elif pol == "fresh":
                    adopt = fresh_pl is not None and (
                        inc[pol] is None or state is None
                        or provision_key(inc[pol]) != provision_key(fresh_pl))
                else:
                    period = int(pol.split("_")[1])
                    adopt = (k % max(1, round(period / step)) == 0)
                switch = False
                if adopt and fresh_pl is not None:
                    if inc[pol] is not None:
                        switch = is_reprovision(inc[pol], fresh_pl)
                    inc[pol] = dict(fresh_pl)
                    state = (fresh.cost, fresh.latency_ms, fresh_pl)
                rate = plan_rate(inst, inc[pol]) if inc[pol] else 0.0
                rows.append({
                    "t_s": t, "seed": int(seed), "policy": pol,
                    "n_visible": nvis,
                    "served": state is not None,
                    "cost": state[0] if state else None,
                    "opt_cost": fresh.cost if fresh else None,
                    "reprovision": switch,
                    "rate": rate,
                })
            if k % (n_steps // 4) == 0:
                print(f"[pE] seed {seed} t={t:.0f}", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("policies.csv", df)
    step_h = step / 3600.0
    summ = df.groupby("policy").agg(
        served=("served", "mean"),
        reprovisions_per_day=("reprovision",
                              lambda s: s.sum() / df.seed.nunique()),
        reserved_unit_hours=("rate",
                             lambda s: s.sum() * step_h / df.seed.nunique()),
        mean_rate=("rate", "mean")).round(3)
    print(summ.to_string())


if __name__ == "__main__":
    main()
