"""E4 dynamics (EQ4): validity windows are minutes, planning is seconds.

Per instance: COLD planning time (constellation graph build + multi-start
heuristic, cache cleared first) vs the plan's validity window (the chosen
sensor's dwell over the AoI, Earth rotation applied). Also the dwell
distribution over every satellite in the slice (the operator's sensor choice
set) and slice churn over one orbital period.

Run via `just run e4_dynamics`.
"""

import time

import pandas as pd

from lab import constants as C
from lab import instances as I
from lab.harness import Run
from lab.heuristic import plan_greedy
from lab.workflow import load_workflow
from substrate import dynamics as D
from substrate.slices import AOIS
from substrate.walker import Walker


def main() -> None:
    run = Run.start("e4_dynamics")
    cfg = run.config
    wf = load_workflow(cfg["workflow"])
    p = C.to_float(cfg["capable_fraction"])
    slo_ms = C.to_float(cfg["slo_s"]) * 1e3
    dwell_dt = C.to_float(cfg["dwell_dt_s"])

    wrows, crows = [], []
    for spec in cfg["instances"]:
        con, aoi_name = spec["constellation"], spec["aoi"]
        w = Walker.from_constellation(con)
        aoi = AOIS[aoi_name]

        for seed in cfg["fleet_seeds"]:
            I._GRAPH_CACHE.clear()  # cold planning time, honestly
            t0 = time.perf_counter()
            inst = I.build_instance(con, aoi_name, p, int(seed))
            if not inst.covered:
                wrows.append({"constellation": con, "aoi": aoi_name,
                              "seed": int(seed), "covered": False})
                continue
            h = plan_greedy(wf, inst, slo_ms, k_candidates=int(cfg["candidates_k"]))
            plan_s = time.perf_counter() - t0

            sensor_win = D.dwell_window_s(w, inst.sensor, aoi, dt=dwell_dt)
            wrows.append({
                "constellation": con, "aoi": aoi_name, "seed": int(seed),
                "covered": True, "plan_s": plan_s,
                "plan_feasible": h.plan is not None and h.plan.feasible,
                "heuristic_evals": h.evals,
                "sensor_window_s": sensor_win,
                "window_over_plan": (sensor_win / plan_s) if sensor_win else None,
            })

        # Dwell distribution over the whole slice + churn (seed-independent).
        wins = [D.dwell_window_s(w, n, aoi, dt=dwell_dt)
                for n in D.slice_at(w, aoi, 0.0)]
        wins = [x for x in wins if x is not None]
        for t, size, entered, left in D.slice_churn(
                w, aoi, 0.0, C.to_float(cfg["churn_horizon_s"]),
                C.to_float(cfg["churn_dt_s"])):
            crows.append({"constellation": con, "aoi": aoi_name, "t_s": t,
                          "slice_size": size, "entered": entered, "left": left})
        if wins:
            s = pd.Series(wins)
            print(f"[e4] {con}/{aoi_name}: slice {len(wins)} sats, dwell "
                  f"median {s.median():.0f}s IQR [{s.quantile(.25):.0f},"
                  f"{s.quantile(.75):.0f}]s")
        run.save_json(f"dwell_{con}_{aoi_name}.json", {"dwell_s": wins})

    run.save_dataframe("windows.csv", pd.DataFrame(wrows))
    run.save_dataframe("churn.csv", pd.DataFrame(crows))
    wdf = pd.DataFrame([r for r in wrows if r.get("covered")])
    if len(wdf):
        print(f"[e4] planning {wdf.plan_s.median():.2f}s median, sensor window "
              f"{wdf.sensor_window_s.median():.0f}s median, ratio "
              f"{wdf.window_over_plan.median():.0f}x")


if __name__ == "__main__":
    main()
