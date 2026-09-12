"""Experiment F (VI-G): cost-vector sensitivity.

The qualitative claims under test: (1) at the tight SLO, composition stays
necessary (Castor feasible where single-plane is not) regardless of prices;
(2) cost ordering Castor <= greedy_compose <= cheapest_single holds; (3) the
frontier stays monotone in the SLO. Prices are overridden on the built
instance, so geometry and profiles are identical across regimes.
Run via `just run cost_sensitivity`.
"""

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_baselines import cheapest_single, greedy_compose
from lab.castor import solve_label


def main() -> None:
    run = Run.start("cost_sensitivity")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))

    rows = []
    for t0 in epochs(cfg):
        for seed in cfg["fleet_seeds"]:
            inst = build_provider(cfg["provider"], aoi, t=float(t0),
                                  seed=int(seed))
            for regime, hw in cfg["hw_regimes"].items():
                for pc in cfg["plane_costs"]:
                    inst.hw_cost = {k: C.to_float(v) for k, v in hw.items()}
                    inst.plane_cost = C.to_float(pc)
                    for slo in cfg["slos_ms"]:
                        slo_ms = C.to_float(slo)
                        plans = {"castor": solve_label(inst, slo_ms),
                                 "cheapest_single": cheapest_single(inst, slo_ms),
                                 "greedy_compose": greedy_compose(inst, slo_ms)}
                        for m, p in plans.items():
                            rows.append({
                                "regime": regime, "plane_cost": C.to_float(pc),
                                "slo_ms": slo_ms, "epoch_s": float(t0),
                                "seed": int(seed), "method": m,
                                "feasible": p is not None,
                                "cost": p.cost if p else None,
                                "n_planes": len(p.activated) if p else None})
        print(f"[pF] epoch {t0} done", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("sensitivity.csv", df)
    print(f"[pF] rows: {len(df)}")


if __name__ == "__main__":
    main()
