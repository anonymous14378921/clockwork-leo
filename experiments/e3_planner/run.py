"""E3 planner comparison (EQ3): oracle vs structure-blind baselines.

Per instance the restricted plan space is enumerated twice, on the real
substrate and on the seamless zero-propagation substrate the Atlas-like
baseline believes in. Every method then selects from the SAME real records
(atlas_like selects in its believed world, is scored in the real one), so
differences are pure selection policy. Oracle runtime (enumeration wall time)
is recorded per instance for the runtime-vs-validity-window story.

Run via `just run e3_planner`.
"""

import time

import pandas as pd

from lab import baselines as BL
from lab import constants as C
from lab.enumeration import enumerate_records, best_feasible
from lab.harness import Run
from lab.heuristic import plan_greedy
from lab.instances import build_instance
from lab.milp import plan_milp
from lab.workflow import load_workflow


def _heuristic_record(h) -> dict:
    """Normalize a HeuristicResult into the record shape the rows use."""
    if h.plan is None:
        return None
    ev = h.plan
    return {"accuracy": ev.accuracy, "acc_source": ev.accuracy_source,
            "cost": ev.cost, "tight_ms": ev.tight_latency_ms,
            "slack_ms": ev.slack_latency_ms,
            "detector": ev.config.detector, "verifier": ev.config.verifier,
            "threshold": ev.config.threshold,
            "heuristic_evals": h.evals, "n_moves": len(h.steps)}


def main() -> None:
    run = Run.start("e3_planner")
    cfg = run.config
    wf = load_workflow(cfg["workflow"])
    slack = wf.slo_slack_factor
    k = int(cfg["candidates_k"])
    budget = C.to_float(cfg["budget"])

    rows = []
    for con in cfg["constellations"]:
        for seed in cfg["fleet_seeds"]:
            for p in cfg["capable_fractions"]:
                inst = build_instance(con, cfg["aoi"], C.to_float(p), int(seed))
                t0 = time.perf_counter()
                real = enumerate_records(wf, inst, k)
                oracle_s = time.perf_counter() - t0
                zero = enumerate_records(wf, inst, k, zero_propagation=True)
                base = {"constellation": con, "topology": inst.topology,
                        "p": C.to_float(p), "seed": int(seed),
                        "oracle_enum_s": oracle_s}
                for slo_s in cfg["slos_s"]:
                    slo_ms = C.to_float(slo_s) * 1e3
                    oracle = best_feasible(real, slo_ms, slack, budget)
                    t1 = time.perf_counter()
                    heur = plan_greedy(wf, inst, slo_ms, budget, k)
                    heur_s = time.perf_counter() - t1
                    hrec = _heuristic_record(heur)
                    if hrec is not None:
                        hrec["heuristic_s"] = heur_s
                    chosen = {
                        "oracle": oracle,
                        "heuristic": hrec,
                        "latency_first": BL.latency_first(real, slo_ms, slack, budget),
                        "atlas_like": BL.atlas_like(real, zero, slo_ms, slack, budget),
                        "accuracy_greedy": BL.accuracy_greedy(real, slo_ms, slack),
                    }
                    if C.to_float(slo_s) in [C.to_float(x) for x in
                                             cfg.get("milp_slos_s", [])]:
                        t2 = time.perf_counter()
                        mev = plan_milp(wf, inst, slo_ms, budget, k)
                        milp_s = time.perf_counter() - t2
                        if mev is not None:
                            chosen["milp"] = {
                                "accuracy": mev.accuracy,
                                "acc_source": mev.accuracy_source,
                                "cost": mev.cost,
                                "tight_ms": mev.tight_latency_ms,
                                "slack_ms": mev.slack_latency_ms,
                                "detector": mev.config.detector,
                                "verifier": mev.config.verifier,
                                "threshold": mev.config.threshold,
                                "milp_s": milp_s,
                            }
                    for d in range(int(cfg["random_draws"])):
                        chosen[f"random_{d}"] = BL.random_feasible(
                            real, slo_ms, slack, budget, seed=1000 * int(seed) + d)
                    for method, rec in chosen.items():
                        row = dict(base, slo_s=C.to_float(slo_s), method=method)
                        if rec is None:
                            row.update({"selected": False})
                        else:
                            feas = rec.get("slo_feasible",
                                           rec["tight_ms"] <= slo_ms
                                           and rec["slack_ms"] <= slo_ms * slack)
                            row.update({
                                "selected": True,
                                "accuracy": rec["accuracy"],
                                "acc_source": rec["acc_source"],
                                "cost": rec["cost"],
                                "tight_ms": rec["tight_ms"],
                                "slo_feasible": bool(feas),
                                "detector": rec["detector"],
                                "verifier": rec["verifier"],
                                "threshold": rec["threshold"],
                                "gap_vs_oracle": (oracle["accuracy"] - rec["accuracy"]
                                                  if oracle and feas else None),
                            })
                            for opt in ("milp_s", "heuristic_s",
                                        "heuristic_evals", "n_moves"):
                                if opt in rec:
                                    row[opt] = rec[opt]
                        rows.append(row)
                print(f"[e3] {con} p={p} seed={seed}: enum {oracle_s:.2f}s")

    df = pd.DataFrame(rows)
    run.save_dataframe("planner.csv", df)
    src = set(df.get("acc_source", pd.Series(dtype=str)).dropna().unique())
    if src != {"measured-grid"}:
        print("[e3] WARNING: placeholder accuracy grid; structural results only.")
    print(f"[e3] rows: {len(df)}")


if __name__ == "__main__":
    main()
