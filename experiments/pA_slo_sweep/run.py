"""Experiment A: provisioning under latency SLOs (VI-B).

Evenly spaced epochs over the cycle (no favorable-epoch sampling), 10 fleet seeds, ACE (label
search) vs single-plane baselines vs GreedyCompose. MILP equality is
spot-checked on a documented subset. Run via `just run pA_slo_sweep`.
"""

import time
from multiprocessing import Pool

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_baselines import POLICIES
from lab.provision_label import solve_label
from lab.provision_milp import solve as solve_milp


def one_instance(args):
    """All methods at every SLO for one (epoch, fleet seed) instance."""
    cfg, t0, seed = args
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    chk = cfg["milp_check"]
    check_epochs = {epochs(cfg)[int(i)] for i in chk["epoch_indices"]}
    inst = build_provider(cfg["provider"], aoi, t=float(t0), seed=int(seed))
    rows = []
    for slo in cfg["slos_ms"]:
        slo_ms = C.to_float(slo)
        t_s = time.perf_counter()
        plans = {"ace": solve_label(inst, slo_ms)}
        ace_s = time.perf_counter() - t_s
        if (t0 in check_epochs and seed in chk["seeds"]):
            t_s = time.perf_counter()
            milp = solve_milp(inst, slo_ms)
            milp_s = time.perf_counter() - t_s
            assert (milp is None) == (plans["ace"] is None)
            if milp is not None:
                assert abs(milp.cost - plans["ace"].cost) < 1e-6
        else:
            milp_s = None
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
            if method == "ace":
                row["solve_s"] = ace_s
                if milp_s is not None:
                    row["milp_s"] = milp_s
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
