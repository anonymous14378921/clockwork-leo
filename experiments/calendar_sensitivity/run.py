"""Sensitivity of the calendar planner to temporal resolution and pool slack.

Each resolution cell rebuilds the candidate pool and latency table, plans the
calendar, and replays it at 1-second resolution to measure inter-snapshot
attainment loss. Run via `just run calendar_sensitivity`.
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


def _replay_at_1s(cfg, cal, states, n_planning, comps, edges, profiles, io):
    """Replay a Pollux calendar at 1-second resolution, return attainment."""
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    seed = int(cfg["fleet_seed"])
    total = cycle_s()
    planning_step = total / n_planning
    served = 0
    total_samples = 0

    for interval in range(n_planning):
        state_idx = cal.assignment[interval]
        if state_idx < 0:
            start = interval * planning_step
            n_seconds = int(planning_step)
            total_samples += n_seconds
            continue
        state = states[state_idx]
        start = interval * planning_step
        n_seconds = int(planning_step)
        for k in range(n_seconds):
            t = start + k
            if t >= total:
                break
            total_samples += 1
            inst = build_provider(cfg["provider"], aoi, t=t, seed=seed,
                                  plane_routes=False)
            visible = inst.visible_in(state.planes)
            if not visible:
                continue
            result = CAL.serve(inst, state, comps, edges, profiles, io)
            if result is not None and result[1] <= C.to_float(cfg["slo_ms"]):
                served += 1

    return served / total_samples if total_samples > 0 else 0.0


def one_cell(args):
    cfg, kind, slack, n, do_replay = args
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

    replay_attainment = None
    t_replay = 0.0
    if do_replay:
        print(f"  [{kind} n={n}] replaying at 1s...", flush=True)
        t0 = time.perf_counter()
        replay_attainment = _replay_at_1s(cfg, cal, states, n, comps, edges,
                                          profiles, io)
        t_replay = time.perf_counter() - t0
        print(f"  [{kind} n={n}] replay done: {replay_attainment:.4f} "
              f"({t_replay:.0f}s)", flush=True)

    print(f"[sens] {kind} slack={slack} n={n}: {len(states)} states, "
          f"{cal.switches} switches, {cal.unit_hours:.1f} unit-h, "
          f"served={cal.served:.4f}, "
          f"pool {t_pool:.0f}s table {t_table:.0f}s dp {t_dp:.1f}s"
          + (f" replay {t_replay:.0f}s" if do_replay else ""),
          flush=True)

    row = {"kind": kind, "slack": slack, "n_steps": n,
           "step_s": cycle_s() / n, "n_states": len(states),
           "switches": cal.switches, "unit_hours": cal.unit_hours,
           "served": cal.served, "objective": cal.objective,
           "lower_bound": cal.lower_bound,
           "gap_to_bound": cal.objective - cal.lower_bound,
           "t_pool_s": t_pool, "t_table_s": t_table, "t_dp_s": t_dp}
    if do_replay:
        row["replay_1s_attainment"] = replay_attainment
        row["attainment_drop_pp"] = 100.0 * (cal.served - replay_attainment)
        row["t_replay_s"] = t_replay
    return row


def main() -> None:
    run = Run.start("calendar_sensitivity")
    cfg = run.config
    do_replay = cfg.get("replay_1s", False)
    cells = [(cfg, "slack", C.to_float(s), int(cfg["n_steps_slack"]), False)
             for s in cfg["slacks"]]
    cells += [(cfg, "resolution", C.to_float(cfg["slack_steps"]), int(n),
               do_replay)
              for n in cfg["n_steps_list"]]
    with Pool(int(cfg["workers"])) as pool:
        rows = pool.map(one_cell, cells)
    df = pd.DataFrame(rows)
    run.save_dataframe("sensitivity.csv", df)
    print(df.to_string())


if __name__ == "__main__":
    main()
