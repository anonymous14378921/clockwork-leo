"""Experiment M: pool slack and temporal resolution of the calendar planner.

Each cell rebuilds the candidate pool and the latency table (the expensive
passes) and plans the calendar at a fixed switching cost; cells run in
parallel. Reported per cell: pool size, reprovisions, unit-hours, served
fraction, gap to the linear lower bound, and the three planning times.
Run via `just run pM_calendar_sensitivity`.
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


def one_cell(args):
    cfg, kind, slack, n = args
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    slo = C.to_float(cfg["slo_ms"])
    lam = C.to_float(cfg["switch_cost"])
    seed = int(cfg["fleet_seed"])
    times = grid(n)
    step_h = cycle_s() / n / 3600.0
    comps, edges = load_chain()
    profiles = load_profiles()
    io = load_io()
    build = lambda t: build_provider(cfg["provider"], aoi, t=t, seed=seed)
    t0 = time.perf_counter()
    states = CAL.collect_candidates(build, times, slo, slack)
    t_pool = time.perf_counter() - t0
    t0 = time.perf_counter()
    table, rates = CAL.latency_table(build, times, states, comps, edges,
                                     profiles, io)
    t_table = time.perf_counter() - t0
    t0 = time.perf_counter()
    cal = CAL.plan_calendar(states, table, rates, step_h, lam, slo)
    t_dp = time.perf_counter() - t0
    print(f"[pM] {kind} slack {slack} n {n}: {len(states)} states, "
          f"{cal.switches} switches, {cal.unit_hours:.1f} unit-h, "
          f"pool {t_pool:.0f}s table {t_table:.0f}s dp {t_dp:.1f}s",
          flush=True)
    return {"kind": kind, "slack": slack, "n_steps": n,
            "step_s": cycle_s() / n, "n_states": len(states),
            "switches": cal.switches, "unit_hours": cal.unit_hours,
            "served": cal.served, "objective": cal.objective,
            "lower_bound": cal.lower_bound,
            "gap_to_bound": cal.objective - cal.lower_bound,
            "t_pool_s": t_pool, "t_table_s": t_table, "t_dp_s": t_dp}


def main() -> None:
    run = Run.start("pM_calendar_sensitivity")
    cfg = run.config
    cells = [(cfg, "slack", C.to_float(s), int(cfg["n_steps_slack"]))
             for s in cfg["slacks"]]
    cells += [(cfg, "resolution", C.to_float(cfg["slack_steps"]), int(n))
              for n in cfg["n_steps_list"]]
    with Pool(int(cfg["workers"])) as pool:
        rows = pool.map(one_cell, cells)
    df = pd.DataFrame(rows)
    run.save_dataframe("sensitivity.csv", df)
    print(df.to_string())


if __name__ == "__main__":
    main()
