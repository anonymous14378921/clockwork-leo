"""E0 worked example: the go/no-go for the whole paper. Run via `just run e0_worked_example`.

Measures the detour hop count k from the substrate (sparse-strong fleet: 2% of
ref-star nodes are H100, seeded), then evaluates the two placements with lab.e0
and writes the verdict plus the latency-budget decomposition and the SLO sweep.
"""

import random

import pandas as pd

from lab import constants as C
from lab import e0 as E0
from lab.harness import Run
from substrate import graph as G
from substrate import slices
from substrate.walker import Walker


def measure_k(seed: int):
    """Nearest-H100 detour from a mid-latitude sensor: returns (k_hops, ms, meta)."""
    k = C.load_constants()
    e0c = k["e0"]
    w = Walker.from_constellation(e0c["constellation"])
    g = G.build_graph(w)

    frac = C.to_float(k["fleet_mixes"][e0c["fleet"]]["strong_fraction"])
    nodes = sorted(g.nodes())
    rng = random.Random(seed)
    n_strong = max(1, round(frac * len(nodes)))
    capable = set(rng.sample(nodes, n_strong))

    # Sensor: a mid-latitude node that is not itself an H100.
    aoi = slices.MID_LATITUDE
    candidates = [n for n in sorted(slices.slice_nodes(w, aoi)) if n not in capable]
    if not candidates:
        candidates = [n for n in nodes if n not in capable]
    sensor = candidates[0]

    node, hops, ms = G.nearest_capable(g, sensor, capable)
    meta = {
        "n_nodes": len(nodes), "n_strong": n_strong, "strong_fraction": frac,
        "sensor": list(sensor), "nearest_h100": list(node),
        "detour_ms_measured": ms, "t_hop_intra_ms": w.intra_plane_hop_ms(),
    }
    return hops, w.intra_plane_hop_ms(), meta


def main() -> None:
    run = Run.start("e0_worked_example")
    seed = int(run.config.get("seed", 0))

    k, t_hop_ms, meta = measure_k(seed)
    print(f"[e0] detour k = {k} hops to nearest H100 "
          f"(measured {meta['detour_ms_measured']:.1f} ms), T_hop = {t_hop_ms:.2f} ms")

    res = E0.run_e0(k, t_hop_ms)

    # Full result as JSON (verdict + provenance of the decision).
    run.save_json("e0.json", {
        "verdict": res.verdict,
        "k_hops": res.k_hops,
        "t_hop_ms": res.t_hop_ms,
        "slo_ms": res.slo_ms,
        "gap_map": res.gap_map,
        "workflow_gap_map": res.workflow_gap_map,
        "placement_A": {"variant": res.chosen_a.variant.name, "map": res.chosen_a.map,
                        "compute_ms": res.chosen_a.compute_ms,
                        "propagation_ms": res.chosen_a.propagation_ms,
                        "transmission_ms": res.chosen_a.transmission_ms,
                        "total_ms": res.chosen_a.total_ms},
        "placement_B": {"variant": res.chosen_b.variant.name, "map": res.chosen_b.map,
                        "compute_ms": res.chosen_b.compute_ms,
                        "propagation_ms": res.chosen_b.propagation_ms,
                        "transmission_ms": res.chosen_b.transmission_ms,
                        "total_ms": res.chosen_b.total_ms},
        "geometry": meta,
    })

    # Latency-budget decomposition, tidy long form (for the figure).
    rows = []
    for pe, label in ((res.chosen_a, "A: packed (iX10)"), (res.chosen_b, "B: detour (H100)")):
        rows += [
            {"placement": label, "variant": pe.variant.name, "map": pe.map,
             "component": "compute", "ms": pe.compute_ms},
            {"placement": label, "variant": pe.variant.name, "map": pe.map,
             "component": "hops", "ms": pe.propagation_ms},
            {"placement": label, "variant": pe.variant.name, "map": pe.map,
             "component": "transmission", "ms": pe.transmission_ms},
        ]
    run.save_dataframe("decomposition.csv", pd.DataFrame(rows))
    run.save_dataframe("slo_sweep.csv", pd.DataFrame(res.sweep))

    print(f"[e0] A -> {res.chosen_a.variant.name} ({res.chosen_a.map:.1f} mAP, "
          f"{res.chosen_a.total_ms:.0f} ms) | "
          f"B -> {res.chosen_b.variant.name} ({res.chosen_b.map:.1f} mAP, "
          f"{res.chosen_b.total_ms:.0f} ms)")
    print(f"[e0] accuracy gap = {res.gap_map:.1f} mAP at SLO {res.slo_ms:.0f} ms "
          f"-> VERDICT: {res.verdict}")


if __name__ == "__main__":
    main()
