"""Substrate characterization: Star vs Delta topology-class metrics.

For each constellation (controlled pair plus the four real ones) build the ISL
graph and measure path-cost distribution, seam/wrap-pair hop distance (the seam
tax), coverage by latitude band (the latitude cap), and the nearest-capable hop
sweep (capable-node sparsity). The verdict:
  seam:  the controlled Star seam-pair p95 must dwarf the controlled Delta wrap
         p95 (pure topology-class effect, inclination held equal), and
  cap:   a real Delta must have zero Arctic coverage while a real Star has some.
PASS requires both. Run via `just run e1_substrate`.
"""

import pandas as pd

from lab.harness import Run
from substrate import graph as G
from substrate import metrics as M
from substrate.walker import Walker


def main() -> None:
    run = Run.start("e1_substrate")
    cfg = run.config
    seed = int(cfg.get("seed", 0))
    k_sources = int(cfg.get("k_sources", 60))
    n_snapshots = int(cfg.get("n_snapshots", 12))
    fractions = [float(p) for p in cfg["capable_fractions"]]

    metric_rows = []
    sweep_rows = []
    seam_by_con = {}
    cov_by_con = {}

    for name in cfg["constellations"]:
        w = Walker.from_constellation(name)
        g = G.build_graph(w)

        hops = M.summarize(M.pathcost_hops(g, k_sources=k_sources, seed=seed))
        ms = M.summarize(M.pathcost_ms(g, k_sources=k_sources, seed=seed))
        seam = M.summarize(M.seam_pair_hops(w, g))
        cov = M.coverage_by_band(w, n_snapshots=n_snapshots)
        diam = M.diameter_hops(g)
        seam_by_con[name] = seam
        cov_by_con[name] = cov

        metric_rows.append({
            "constellation": name, "topology": w.topology,
            "n_nodes": g.number_of_nodes(), "n_edges": g.number_of_edges(),
            "hops_mean": hops.mean, "hops_p95": hops.p95, "diameter": diam,
            "ms_mean": ms.mean, "ms_p95": ms.p95,
            "seam_p50": seam.p50, "seam_p95": seam.p95, "seam_max": seam.maximum,
            "cov_equatorial": cov["equatorial"], "cov_mid": cov["mid"],
            "cov_arctic": cov["arctic"],
        })
        print(f"[e1] {name:12s} {w.topology:5s} hops p95={hops.p95:.0f} "
              f"diam={diam} seam p95={seam.p95:.0f} arctic={cov['arctic']:.1f}")

        sweep = M.nearest_capable_sweep(w, g, fractions, seed=seed, k_sources=k_sources)
        for p, s in sweep.items():
            sweep_rows.append({"constellation": name, "topology": w.topology,
                               "p": p, "mean_hops": s.mean, "p95_hops": s.p95})

    run.save_dataframe("metrics.csv", pd.DataFrame(metric_rows))
    run.save_dataframe("capable_sweep.csv", pd.DataFrame(sweep_rows))

    # --- verdict -------------------------------------------------------------
    sp = cfg["seam_pair"]
    cp = cfg["cap_pair"]
    star_seam_p95 = seam_by_con[sp["star"]].p95
    delta_wrap_p95 = seam_by_con[sp["delta"]].p95
    seam_ratio = star_seam_p95 / max(delta_wrap_p95, 1.0)
    seam_pass = seam_ratio >= 5.0

    delta_arctic = cov_by_con[cp["delta"]]["arctic"]
    star_arctic = cov_by_con[cp["star"]]["arctic"]
    cap_pass = (delta_arctic == 0.0) and (star_arctic > 0.0)

    verdict = "PASS" if (seam_pass and cap_pass) else "FAIL"

    run.save_json("e1.json", {
        "verdict": verdict,
        "seam": {"star": sp["star"], "delta": sp["delta"],
                 "star_seam_p95_hops": star_seam_p95,
                 "delta_wrap_p95_hops": delta_wrap_p95,
                 "ratio": seam_ratio, "pass": seam_pass},
        "cap": {"star": cp["star"], "delta": cp["delta"],
                "star_arctic_sats": star_arctic, "delta_arctic_sats": delta_arctic,
                "pass": cap_pass},
    })

    print(f"[e1] seam tax ratio (Star/Delta p95) = {seam_ratio:.1f}x "
          f"[{'ok' if seam_pass else 'no'}]")
    print(f"[e1] Arctic coverage: {cp['star']}={star_arctic:.1f} sats, "
          f"{cp['delta']}={delta_arctic:.1f} sats [{'ok' if cap_pass else 'no'}]")
    print(f"[e1] VERDICT: {verdict}")


if __name__ == "__main__":
    main()
