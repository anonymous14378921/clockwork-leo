"""Experiments B+C v2: geographic and shell-level provisioning.

Latitude sweep (primary) + named AoIs (examples), fixed shared epoch set,
medians over epochs x seeds. Run via `just run pBC_aoi_portfolio`.
"""

import pandas as pd

from lab import constants as C
from lab.cycle import epochs
from lab.harness import Run
from lab.provider import build_provider, restrict_shells
from lab.castor import solve_label as solve


def main() -> None:
    run = Run.start("pBC_aoi_portfolio")
    cfg = run.config
    slo_ms = C.to_float(cfg["slo_ms"])
    aois = ([{"name": f"lat{int(l)}", "lat": float(l),
              "lon": C.to_float(cfg["sweep_lon"]), "kind": "sweep"}
             for l in cfg["latitudes"]]
            + [dict(a, kind="named") for a in cfg["named_aois"]])

    rows = []
    for aoi_spec in aois:
        aoi = (C.to_float(aoi_spec["lat"]), C.to_float(aoi_spec["lon"]))
        for t0 in epochs(cfg):
            for seed in cfg["fleet_seeds"]:
                inst_full = build_provider(cfg["provider"], aoi,
                                           t=float(t0), seed=int(seed))
                for pname, shell_ids in cfg["portfolios"].items():
                    inst = restrict_shells(inst_full, shell_ids)
                    plan = solve(inst, slo_ms) if inst.planes else None
                    row = {"aoi": aoi_spec["name"], "kind": aoi_spec["kind"],
                           "lat": aoi[0], "portfolio": pname,
                           "epoch_s": float(t0), "seed": int(seed),
                           "feasible": plan is not None}
                    if plan is not None:
                        row.update({"cost": plan.cost,
                                    "latency_ms": plan.latency_ms,
                                    "n_planes": len(plan.activated),
                                    "shells": ",".join(sorted(
                                        {p[0] for p in plan.activated}))})
                    rows.append(row)
        print(f"[pBC] {aoi_spec['name']} done", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("aoi_portfolio.csv", df)
    print(f"[pBC] rows: {len(df)}")


if __name__ == "__main__":
    main()
