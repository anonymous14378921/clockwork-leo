"""Bounded integration check for the adapted HyperDrive baseline."""
from dataclasses import asdict
import hashlib
import shutil

import pandas as pd

from lab.cycle import epochs
from lab.harness import Run
from lab.hyperdrive import UPSTREAM_COMMIT, plan_hyperdrive
from lab.provider import build_provider
from lab.provision_baselines import greedy_compose
from lab.provision_label import solve_label


def main():
    run = Run.start("pQ_hyperdrive_adapter")
    cfg = run.config
    # Archive the actual dirty-tree implementation and all numerical inputs.
    paths = [*run.root.glob("src/**/*.py"),
             *run.root.glob("constants/*.yaml"),
             *run.root.glob("configs/providers/*.yaml"),
             *run.root.glob("workflows/*.yaml"),
             *run.root.glob("data/profiles/*.csv"),
             *run.root.glob("tests/fixtures/hyperdrive_upstream/*"),
             run.root / "experiments/pQ_hyperdrive_adapter/run.py"]
    hashes = {}
    for path in paths:
        relative = path.relative_to(run.root)
        target = run.path("source", str(relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    import geopy
    import geographiclib
    run.save_json("implementation.json", {
        "upstream_commit": UPSTREAM_COMMIT, "sha256": hashes,
        "geopy": geopy.__version__, "geographiclib": geographiclib.__version__,
        "scope": "integration check, one hardware assignment, not paper results",
    })
    rows, traces = [], []
    for seed in cfg["fleet_seeds"]:
        for snapshot, t in enumerate(epochs(cfg)):
            inst = build_provider(cfg["provider"],
                                  (float(cfg["aoi"]["lat"]), float(cfg["aoi"]["lon"])),
                                  t=float(t), seed=seed, plane_routes=False)
            for slo in cfg["slos_ms"]:
                plans = {"castor": solve_label(inst, slo),
                         "greedy_compose": greedy_compose(inst, slo)}
                complete = {}
                for mode in cfg["candidate_modes"]:
                    method = "hyperdrive_" + mode
                    result = plan_hyperdrive(
                        inst, slo, candidate_mode=mode,
                        vicinity_radius_km=cfg["vicinity_radius_km"],
                        vicinity_count=cfg["vicinity_count"])
                    plans[method] = result.plan
                    complete[method] = result.best_complete
                    traces.append({"seed": seed, "snapshot": snapshot, "time_s": t,
                                   "slo_ms": slo, "method": method,
                                   "result": asdict(result)})
                for method, plan in plans.items():
                    attempted = complete.get(method)
                    rows.append({
                        "seed": seed, "snapshot": snapshot, "time_s": t,
                        "slo_ms": slo, "method": method, "feasible": plan is not None,
                        "cost": plan.cost if plan else None,
                        "latency_ms": plan.latency_ms if plan else None,
                        "n_planes": len(plan.activated) if plan else None,
                        "best_complete_latency_ms": attempted.latency_ms if attempted else None,
                    })
                print(f"[pQ] seed {seed} snapshot {snapshot} SLO {slo} complete", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("comparison.csv", df)
    run.save_json("decisions.json", traces)
    summaries = []
    for (slo, method), group in df.groupby(["slo_ms", "method"]):
        reference = df[(df.slo_ms == slo) & (df.method == "castor")]
        paired = group.merge(reference, on=["seed", "snapshot"], suffixes=("", "_castor"))
        shared = paired[paired.feasible & paired.feasible_castor]
        summaries.append({
            "slo_ms": int(slo), "method": method, "instances": len(group),
            "feasible": int(group.feasible.sum()),
            "shared_feasible_with_castor": len(shared),
            "mean_cost_on_shared": float(shared.cost.mean()) if len(shared) else None,
            "castor_mean_cost_on_shared": float(shared.cost_castor.mean()) if len(shared) else None,
        })
    run.save_json("summary.json", summaries)
    print(df.groupby(["slo_ms", "method"]).feasible.agg(["sum", "count"]).to_string())


if __name__ == "__main__":
    main()
