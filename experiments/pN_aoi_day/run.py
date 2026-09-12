"""Experiment N: one day of the service seen from the region (Section II).

Writes day.csv (per instant: planes and satellites in view, cheapest
feasible cost, the number of in-view planes that can host the workflow
alone, day-two identity of the visible set on both providers) and intervals.csv (contiguous visibility runs per satellite
and per plane, in seconds). Run via `just run pN_aoi_day`.
"""

import pandas as pd

from lab import constants as C
from lab.cycle import cycle_s, grid
from lab.harness import Run
from lab.provider import build_provider
from lab.provision_label import solve_label


def runs(times, member):
    """Contiguous runs of True on the cyclic grid: (start_s, duration_s)."""
    n = len(times)
    step = cycle_s() / n
    out, start = [], None
    for k in range(n):
        if member[k] and start is None:
            start = k
        if not member[k] and start is not None:
            out.append((start, k))
            start = None
    if start is not None:
        if out and out[0][0] == 0:            # wrap around the cycle
            _, e0 = out.pop(0)
            out.append((start, n + e0))
        else:
            out.append((start, n))
    return [(s * step, (e - s) * step) for s, e in out]


def main() -> None:
    run = Run.start("pN_aoi_day")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    slo = C.to_float(cfg["slo_ms"])
    n = int(cfg["n_steps"])
    seed = int(cfg["seed"])
    times = grid(n)
    T = cycle_s()

    rows, vis_day1 = [], []
    for k, t in enumerate(times):
        inst = build_provider(cfg["provider"], aoi, t=float(t), seed=seed)
        vis = frozenset(inst.sat_access)
        vis_day1.append(vis)
        fresh = solve_label(inst, slo) if vis else None
        # planes in view that can host the whole workflow on their own
        vis_planes = sorted({(s[0], s[1]) for s in vis})
        alone = [solve_label(inst, slo, restrict_planes=[p]) for p in vis_planes]
        alone_costs = [pl.cost for pl in alone if pl is not None]
        inst2 = build_provider(cfg["provider"], aoi, t=float(t + T), seed=seed)
        d1 = build_provider(cfg["drift_provider"], aoi, t=float(t), seed=seed)
        d2 = build_provider(cfg["drift_provider"], aoi, t=float(t + T),
                            seed=seed)
        rows.append({
            "t_s": t, "n_visible": len(vis),
            "n_visible_planes": len({(s[0], s[1]) for s in vis}),
            "opt_cost": fresh.cost if fresh else None,
            "opt_planes": len(fresh.activated) if fresh else None,
            "n_planes_alone": len(alone_costs),
            "single_feasible": bool(alone_costs),
            "single_cost": min(alone_costs) if alone_costs else None,
            "day2_identical": vis == frozenset(inst2.sat_access),
            "day2_identical_nearrepeat":
                frozenset(d1.sat_access) == frozenset(d2.sat_access),
        })
        if k % (n // 8) == 0:
            print(f"[pN] instant {k}/{n}", flush=True)
    df = pd.DataFrame(rows)
    run.save_dataframe("day.csv", df)

    sats = sorted({s for v in vis_day1 for s in v})
    planes = sorted({(s[0], s[1]) for s in sats})
    irows = []
    for s in sats:
        for start, dur in runs(times, [s in v for v in vis_day1]):
            irows.append({"kind": "satellite", "shell": s[0], "plane": s[1],
                          "slot": s[2], "start_s": start, "duration_s": dur})
    for p in planes:
        member = [any((s[0], s[1]) == p for s in v) for v in vis_day1]
        for start, dur in runs(times, member):
            irows.append({"kind": "plane", "shell": p[0], "plane": p[1],
                          "slot": -1, "start_s": start, "duration_s": dur})
    idf = pd.DataFrame(irows)
    run.save_dataframe("intervals.csv", idf)

    changes = int((df.opt_cost.fillna(-1).diff().fillna(0) != 0).sum())
    print(f"[pN] visible satellites: min {df.n_visible.min()} median "
          f"{df.n_visible.median():.0f} max {df.n_visible.max()} | "
          f"unserviceable {(df.opt_cost.isna()).mean():.3f} | "
          f"single-plane feasible {df.single_feasible.mean():.3f} | "
          f"opt cost changes {changes} | day-two identical "
          f"{df.day2_identical.mean():.3f} (near-repeat "
          f"{df.day2_identical_nearrepeat.mean():.3f})")
    for kind in ("satellite", "plane"):
        d = idf[idf.kind == kind].duration_s / 60.0
        print(f"[pN] {kind} pass (min): median {d.median():.1f} "
              f"p10 {d.quantile(.1):.1f} p90 {d.quantile(.9):.1f} n {len(d)}")


if __name__ == "__main__":
    main()
