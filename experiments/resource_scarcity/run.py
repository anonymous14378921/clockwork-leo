"""Experiment L: accelerator scarcity sweep (hub planes in the Star shell).

For each hub count, the Star shell is rebuilt from hub and base plane
profiles (seeded plane and slot shuffles as everywhere), the Delta keeps
its mvp-main fleet, and every method is solved on evenly spaced cycle
epochs. Infeasible outcomes are rows. Run via `just run resource_scarcity`.
"""

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_baselines import POLICIES
from lab.castor import solve_label


def main() -> None:
    run = Run.start("resource_scarcity")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    slo_ms = C.to_float(cfg["slo_ms"])
    rows = []
    for hubs in cfg["star_hubs"]:
        hubs = int(hubs)
        profiles = {"star_1": {
            "hub": {"count": hubs, "hw": dict(cfg["hub_profile"])},
            "base": {"count": 12 - hubs, "hw": dict(cfg["base_profile"])}}}
        if hubs == 0:
            profiles["star_1"] = {"base": {"count": 12,
                                           "hw": dict(cfg["base_profile"])}}
        for t0 in epochs(cfg):
            for seed in cfg["fleet_seeds"]:
                inst = build_provider(cfg["provider"], aoi, t=float(t0),
                                      seed=int(seed), plane_profiles=profiles)
                n_gl = sum(h == "gpu_large" for h in inst.sat_hw.values())
                plans = {"castor": solve_label(inst, slo_ms)}
                for name, fn in POLICIES.items():
                    plans[name] = fn(inst, slo_ms)
                for method, plan in plans.items():
                    rows.append({"star_hubs": hubs, "n_gpu_large": n_gl,
                                 "method": method, "seed": int(seed),
                                 "epoch_s": float(t0),
                                 "feasible": plan is not None,
                                 "cost": plan.cost if plan else None,
                                 "n_planes": (len(plan.activated)
                                              if plan else None)})
        print(f"[pL] hubs {hubs} done", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("scarcity.csv", df)
    print(df.groupby(["star_hubs", "method"]).feasible.mean().unstack()
          .round(2).to_string())


if __name__ == "__main__":
    main()
