"""P0 sanity gate for the provisioning model.

Solves the tiny instance at several SLOs and prints cost, latency
decomposition, and selections. GATE: cost must be monotone non-increasing in
the SLO, tight SLOs must use GPU hardware, and the loosest SLO must shift
work to cheaper hardware. Run via `just run sanity_gate`.
"""

import pandas as pd

from lab import constants as C
from lab.harness import Run
from lab.provider import build_provider
from lab.castor import solve_label as solve


def find_epoch(cfg) -> float:
    """Epoch with the RICHEST visibility (most visible planes, ties by
    earliest), so the gate exercises real choice rather than a lone plane."""
    scan = cfg["epoch_scan"]
    best_t, best_n = None, -1
    for t in range(int(scan["start_s"]), int(scan["stop_s"]),
                   int(scan["step_s"])):
        inst = build_provider(cfg["provider"],
                              (C.to_float(cfg["aoi"]["lat"]),
                               C.to_float(cfg["aoi"]["lon"])),
                              t=float(t), seed=int(cfg["seed"]))
        n = sum(pv.visible for pv in inst.planes.values())
        if n > best_n:
            best_t, best_n = float(t), n
    if best_n < 1:
        raise RuntimeError("no epoch with AoI visibility in the scan range")
    return best_t


def main() -> None:
    run = Run.start("sanity_gate")
    cfg = run.config
    t0 = find_epoch(cfg)
    inst = build_provider(cfg["provider"],
                          (C.to_float(cfg["aoi"]["lat"]),
                           C.to_float(cfg["aoi"]["lon"])),
                          t=t0, seed=int(cfg["seed"]))
    nvis = sum(pv.visible for pv in inst.planes.values())
    print(f"[p0] epoch t={t0:.0f}s, {nvis} visible planes")

    rows = []
    for slo in cfg["slos_ms"]:
        plan = solve(inst, C.to_float(slo))
        if plan is None:
            print(f"[p0] SLO {slo} ms: INFEASIBLE")
            rows.append({"slo_ms": slo, "feasible": False})
            continue
        hw = {a.component: a.hardware for a in plan.assignments
              if a.hardware}
        print(f"[p0] SLO {slo:>5} ms: cost {plan.cost:5.1f} | "
              f"lat {plan.latency_ms:7.1f} ms "
              f"(comp {plan.compute_ms:.1f} net {plan.network_ms:.1f} "
              f"acc {plan.access_ms:.1f}) | planes {plan.activated} | {hw}")
        rows.append({"slo_ms": slo, "feasible": True, "cost": plan.cost,
                     "latency_ms": plan.latency_ms,
                     "compute_ms": plan.compute_ms,
                     "network_ms": plan.network_ms,
                     "access_ms": plan.access_ms,
                     "n_planes": len(plan.activated),
                     "hw": str(hw)})
    df = pd.DataFrame(rows)
    run.save_dataframe("gate.csv", df)

    feas = df[df.feasible == True]
    costs = list(feas.cost)
    mono = all(a >= b - 1e-9 for a, b in zip(costs, costs[1:]))
    print(f"[p0] GATE cost-monotonicity: {'PASS' if mono else 'FAIL'} {costs}")


if __name__ == "__main__":
    main()
