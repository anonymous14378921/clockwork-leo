"""Experiment K: the Clockwork calendar vs reactive policies over one cycle.

Per fleet seed (in parallel): pass 1 collects the candidate state pool and
the per-instant optimum; pass 2 tabulates every state's best latency at
every instant on the repeat-track shells; pass 3 does the same on the
near-repeat shells for the drift replay. Then, in memory: the calendar DP
per switching cost, the reactive policies per staging time, and the
day-two study (reuse vs recompute) on both providers. Run via `just run calendar_scheduling`.
"""

import time
from multiprocessing import Pool

import pandas as pd

from lab import pollux as CAL
from lab import constants as C
from lab.cycle import cycle_s, grid
from lab.harness import Run
from lab.provider import build_provider
from lab.service import load_chain, load_io, load_profiles


def one_seed(args):
    cfg, seed = args
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    slo = C.to_float(cfg["slo_ms"])
    n = int(cfg["n_steps"])
    times = grid(n)
    step_h = cycle_s() / n / 3600.0
    comps, edges = load_chain()
    profiles = load_profiles()
    io = load_io()
    log = lambda msg: print(f"[pK seed {seed}] {msg}", flush=True)
    build = lambda t: build_provider(cfg["provider"], aoi, t=t, seed=seed)
    def build_for(name):
        return lambda t: build_provider(name, aoi, t=t, seed=seed)

    t0 = time.perf_counter()
    states = CAL.collect_candidates(build, times, slo,
                                    C.to_float(cfg["cost_slack"]), log)
    t_pool = time.perf_counter() - t0
    log(f"candidate pool: {len(states)} states in {t_pool:.0f} s")
    t0 = time.perf_counter()
    table, rates = CAL.latency_table(build, times, states, comps, edges,
                                     profiles, io, log)
    t_table = time.perf_counter() - t0
    optimum = []
    for k in range(n):
        feas = [i for i in range(len(states)) if CAL.feasible(table, k, i, slo)]
        optimum.append(min(feas, key=lambda i: rates[i]) if feas else -1)

    rows, policy_rows, drift_rows = [], [], []
    for lam in cfg["switch_costs"]:
        t0 = time.perf_counter()
        cal = CAL.plan_calendar(states, table, rates, step_h,
                                C.to_float(lam), slo)
        t_dp = time.perf_counter() - t0
        rows.append({"seed": seed, "switch_cost": C.to_float(lam),
                     "switches": cal.switches, "unit_hours": cal.unit_hours,
                     "served": cal.served, "n_states": len(states),
                     "segments": len(cal.segments()),
                     "objective": cal.objective,
                     "lower_bound": cal.lower_bound,
                     "gap_to_bound": cal.objective - cal.lower_bound,
                     "t_pool_s": t_pool, "t_table_s": t_table,
                     "t_dp_s": t_dp, "t_total_s": t_pool + t_table + t_dp})
    lam0 = C.to_float(cfg["drift_switch_cost"])     # the default penalty
    # Every policy is simulated over two cycles, the second reported.
    # Two staging regimes per policy: "dark" (the reprovision comes up
    # after staging_s, unserved meanwhile) and "prestaged" (the incoming
    # state is reserved staging_s early, both states paid: the overlap).
    # The calendar is always prestaged (its boundaries are known).
    cal0 = CAL.plan_calendar(states, table, rates, step_h, lam0, slo)
    rolling = {}
    for h_min in cfg.get("horizons_min", []):
        steps = max(1, int(round(C.to_float(h_min) * 60.0 / (cycle_s() / n))))
        t0 = time.perf_counter()
        rolling[h_min] = CAL.simulate_rolling(states, table, rates, step_h,
                                              lam0, slo, steps)
        log(f"rolling horizon {h_min} min: {rolling[h_min].switches} "
            f"switches, {rolling[h_min].unit_hours:.1f} unit-hours "
            f"in {time.perf_counter() - t0:.0f} s")
    for st_s in cfg["staging_s"]:
        steps = int(round(C.to_float(st_s) / (cycle_s() / n)))
        for pol in ("event", "fresh"):
            r_dark = CAL.simulate_reactive(states, table, rates, optimum,
                                           step_h, slo, pol, steps, lam0)
            r_pre = CAL.simulate_reactive(states, table, rates, optimum,
                                          step_h, slo, pol, 0, lam0)
            overlap = CAL.overlap_unit_hours(r_pre, rates, C.to_float(st_s))
            policy_rows.append({"seed": seed, "policy": pol,
                                "staging_s": C.to_float(st_s),
                                "switches": r_dark.switches,
                                "unit_hours": r_dark.unit_hours,
                                "served": r_dark.served})
            policy_rows.append({"seed": seed, "policy": f"{pol}_prestaged",
                                "staging_s": C.to_float(st_s),
                                "switches": r_pre.switches,
                                "unit_hours": r_pre.unit_hours + overlap,
                                "overlap_unit_hours": overlap,
                                "served": r_pre.served})
        for h_min, r in rolling.items():
            overlap = CAL.overlap_unit_hours(r, rates, C.to_float(st_s))
            policy_rows.append({"seed": seed, "policy": f"rolling_{h_min}",
                                "staging_s": C.to_float(st_s),
                                "switches": r.switches,
                                "unit_hours": r.unit_hours + overlap,
                                "overlap_unit_hours": overlap,
                                "served": r.served})
        overlap = CAL.overlap_unit_hours(cal0, rates, C.to_float(st_s))
        policy_rows.append({"seed": seed, "policy": "calendar",
                            "staging_s": C.to_float(st_s),
                            "switches": cal0.switches,
                            "unit_hours": cal0.unit_hours + overlap,
                            "overlap_unit_hours": overlap,
                            "served": cal0.served})
    # Day two. Does the plan survive the next cycle? On the repeat-track
    # shells day two IS day one (control). On the near-repeat shells it is
    # not: reusing day one's plan drifts, while planning day two from its
    # own geometry (from the state day one ended in) does not. The daily
    # planner is the linear DP; the periodic calendar is also replayed on
    # day two of the repeat shells as the identity check.
    times_d2 = [t + cycle_s() for t in times]
    lam_d = C.to_float(cfg["drift_switch_cost"])
    studies = [("repeat", build, states, table, rates)]
    for name in cfg["drift_providers"]:
        studies.append((name, build_for(name), None, None, None))
    for label, bld, pool_d1, table_d1, rates_d1 in studies:
        if pool_d1 is None:
            pool_d1 = CAL.collect_candidates(bld, times, slo,
                                             C.to_float(cfg["cost_slack"]))
            table_d1, rates_d1 = CAL.latency_table(bld, times, pool_d1, comps,
                                                   edges, profiles, io)
        cal_d1 = CAL.plan_day(pool_d1, table_d1, rates_d1, step_h, lam_d, slo)
        # reuse: day one's plan executed open-loop on day two
        table_d1_on_d2, _ = CAL.latency_table(bld, times_d2, pool_d1, comps,
                                              edges, profiles, io)
        reused = CAL.replay(table_d1_on_d2, cal_d1, slo)
        # recompute: day two planned from day two, starting where day
        # one ended (that state is added to day two's pool if missing)
        pool_d2 = CAL.collect_candidates(bld, times_d2, slo,
                                         C.to_float(cfg["cost_slack"]))
        last = cal_d1.assignment[-1]
        start = None
        if last >= 0:
            end_state = pool_d1[last]
            if end_state not in pool_d2:
                pool_d2 = pool_d2 + [end_state]
            start = pool_d2.index(end_state)
        table_d2, rates_d2 = CAL.latency_table(bld, times_d2, pool_d2, comps,
                                               edges, profiles, io)
        ceiling = sum(any(CAL.feasible(table_d2, k, i, slo)
                          for i in range(len(pool_d2)))
                      for k in range(n)) / n
        cal_d2 = CAL.plan_day(pool_d2, table_d2, rates_d2, step_h, lam_d,
                              slo, start=start)
        row = {"seed": seed, "provider": label,
               "served_d1": cal_d1.served, "switches_d1": cal_d1.switches,
               "unit_hours_d1": cal_d1.unit_hours,
               "served_ceiling_d2": ceiling,
               "served_reused_d2": sum(reused) / n,
               "served_recomputed_d2": cal_d2.served,
               "switches_recomputed_d2": cal_d2.switches,
               "unit_hours_recomputed_d2": cal_d2.unit_hours,
               "pool_d1": len(pool_d1), "pool_d2": len(pool_d2)}
        if label == "repeat":
            # identity check: the periodic calendar replayed on day two
            row["served_periodic_d2"] = sum(CAL.replay(table_d1_on_d2, cal0,
                                                       slo)) / n
        log(f"day two on {label}: ceiling {ceiling:.3f}, reused "
            f"{row['served_reused_d2']:.3f}, recomputed {cal_d2.served:.3f}")
        drift_rows.append(row)
    log("done")
    return rows, policy_rows, drift_rows


def main() -> None:
    run = Run.start("calendar_scheduling")
    cfg = run.config
    with Pool(int(cfg["workers"])) as pool:
        parts = pool.map(one_seed, [(cfg, int(s)) for s in cfg["fleet_seeds"]])
    rows = [r for p in parts for r in p[0]]
    policy_rows = [r for p in parts for r in p[1]]
    drift_rows = [r for p in parts for r in p[2]]
    run.save_dataframe("calendar.csv", pd.DataFrame(rows))
    run.save_dataframe("policies.csv", pd.DataFrame(policy_rows))
    run.save_dataframe("drift.csv", pd.DataFrame(drift_rows))
    df = pd.DataFrame(rows)
    print(df.groupby("switch_cost")[["switches", "unit_hours", "served",
                                     "gap_to_bound"]].mean().round(3)
          .to_string())
    print("timings (s): pool %.0f table %.0f dp %.1f total %.0f" % tuple(
        df[["t_pool_s", "t_table_s", "t_dp_s", "t_total_s"]].mean()))
    print(pd.DataFrame(policy_rows).groupby(["policy", "staging_s"])
          [["switches", "unit_hours", "served"]].mean().round(3).to_string())
    print(pd.DataFrame(drift_rows).groupby("provider")
          [["served_d1", "served_ceiling_d2", "served_reused_d2",
            "served_recomputed_d2", "switches_d1", "switches_recomputed_d2"]]
          .mean().round(3).to_string())


if __name__ == "__main__":
    main()
