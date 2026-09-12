"""Experiment H: execution-profile perturbation sensitivity.

Draw seeded multiplicative noise on every (component, hardware) execution
latency and re-run Castor and the strongest baselines with the perturbed
profiles. Reported per draw: feasibility, cost, and whether Castor stays at
most as expensive as GreedyCompose. Run via `just run profile_sensitivity`.
"""

import random

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_baselines import POLICIES
from lab.castor import solve_label
from lab.service import load_profiles


def perturbed(base, eps: float, draw: int):
    rng = random.Random(draw)
    return {k: v * rng.uniform(1.0 - eps, 1.0 + eps)
            for k, v in base.items()}


def main() -> None:
    run = Run.start("profile_sensitivity")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    eps = C.to_float(cfg["perturbation_eps"])
    base = load_profiles()

    rows = []
    for t0 in epochs(cfg):
        for seed in cfg["fleet_seeds"]:
            inst = build_provider(cfg["provider"], aoi, t=float(t0),
                                  seed=int(seed))
            for draw in range(int(cfg["n_draws"])):
                prof = perturbed(base, eps, draw)
                for slo in cfg["slos_ms"]:
                    slo_ms = C.to_float(slo)
                    plans = {"castor": solve_label(inst, slo_ms, profiles=prof)}
                    for name in cfg["methods"]:
                        if name != "castor":
                            plans[name] = POLICIES[name](inst, slo_ms,
                                                         profiles=prof)
                    for method, plan in plans.items():
                        rows.append({
                            "draw": draw, "epoch_s": float(t0),
                            "seed": int(seed), "slo_ms": slo_ms,
                            "method": method,
                            "feasible": plan is not None,
                            "cost": plan.cost if plan else None,
                            "n_planes": (len(plan.activated)
                                         if plan else None),
                        })
        print(f"[pH] epoch {t0} done", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("sensitivity.csv", df)

    # Claim survival per draw: Castor feasibility, and castor <= greedy_compose
    # cost wherever both are feasible.
    wide = df.pivot_table(index=["draw", "epoch_s", "seed", "slo_ms"],
                          columns="method", values="cost")
    both = wide.dropna(subset=["castor", "greedy_compose"])
    viol = int((both["castor"] > both["greedy_compose"] + 1e-9).sum())
    castor = df[df.method == "castor"]
    print(f"[pH] draws: {cfg['n_draws']} | castor feasibility "
          f"{castor.feasible.mean():.3f} | castor<=greedy in "
          f"{len(both) - viol}/{len(both)} matched cases")


if __name__ == "__main__":
    main()
