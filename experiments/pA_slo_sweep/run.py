"""Experiment A: provisioning under latency SLOs.

Evenly spaced epochs over the cycle, 10 fleet seeds, Castor (label
search) vs single-plane baselines vs GreedyCompose.
Run via `just run pA_slo_sweep`.
"""

import time
from multiprocessing import Pool

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_baselines import POLICIES
from lab.castor import solve_label


def one_instance(args):
    """All methods at every SLO for one (epoch, fleet seed) instance."""
    cfg, t0, seed = args
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    inst = build_provider(cfg["provider"], aoi, t=float(t0), seed=int(seed))
    rows = []
    for slo in cfg["slos_ms"]:
        slo_ms = C.to_float(slo)
        t_s = time.perf_counter()
        plans = {"castor": solve_label(inst, slo_ms)}
        castor_s = time.perf_counter() - t_s
        for name, fn in POLICIES.items():
            plans[name] = fn(inst, slo_ms)
        for method, plan in plans.items():
            row = {"method": method, "slo_ms": slo_ms,
                   "seed": int(seed), "epoch_s": float(t0),
                   "feasible": plan is not None}
            if plan is not None:
                row.update({"cost": plan.cost,
                            "latency_ms": plan.latency_ms,
                            "n_planes": len(plan.activated)})
            if method == "castor":
                row["solve_s"] = castor_s
            rows.append(row)
    print(f"[pA] epoch {t0} seed {seed} done", flush=True)
    return rows


def main() -> None:
    run = Run.start("pA_slo_sweep")
    cfg = run.config
    jobs = [(cfg, t0, seed) for t0 in epochs(cfg) for seed in cfg["fleet_seeds"]]
    workers = int(cfg.get("workers", 1))
    if workers > 1:
        with Pool(workers) as pool:
            results = pool.map(one_instance, jobs, chunksize=1)
    else:
        results = [one_instance(j) for j in jobs]
    df = pd.DataFrame([r for rows in results for r in rows])
    run.save_dataframe("frontier.csv", df)
    print(f"[pA] rows: {len(df)}")


if __name__ == "__main__":
    main()
