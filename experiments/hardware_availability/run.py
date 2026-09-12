"""Experiment D (H3): does heterogeneity make joint provisioning necessary?

Three fleets, all methods. Expected: baselines tie Castor on the homogeneous
fleet (negative control we predict), and their cost premium or
infeasibility grows with heterogeneity. Run via `just run hardware_availability`.
"""

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_baselines import POLICIES
from lab.castor import solve_label as solve


def main() -> None:
    run = Run.start("hardware_availability")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    slo_ms = C.to_float(cfg["slo_ms"])

    rows = []
    for fleet, provider in cfg["fleets"].items():
      for t0 in epochs(cfg):
        for seed in cfg["fleet_seeds"]:
            inst = build_provider(provider, aoi, t=float(t0), seed=int(seed))
            plans = {"castor": solve(inst, slo_ms)}
            for name, fn in POLICIES.items():
                plans[name] = fn(inst, slo_ms)
            castor_cost = plans["castor"].cost if plans["castor"] else None
            for method, plan in plans.items():
                row = {"fleet": fleet, "method": method, "seed": int(seed),
                       "epoch_s": float(t0),
                       "feasible": plan is not None}
                if plan is not None:
                    row["cost"] = plan.cost
                    row["n_planes"] = len(plan.activated)
                    if castor_cost and method != "castor":
                        row["premium_pct"] = 100.0 * (plan.cost - castor_cost) / castor_cost
                rows.append(row)          # infeasible outcomes are rows too
        print(f"[pD] {fleet} done", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("heterogeneity.csv", df)
    print(f"[pD] rows: {len(df)}")


if __name__ == "__main__":
    main()
