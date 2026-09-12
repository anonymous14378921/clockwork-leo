# E1 — substrate characterization (SQ1)

**Hypotheses:** HA2 (Star vs Delta induce materially different path-cost
structures: seam tax vs latitude cap), HA3 (the AoI determines the feasible
substrate slice), HB2 (capable satellites are sparse and reaching them costs
hops). E1 is the **go/no-go for the topology-class framing** (HA2).

## Definition of done (brief Sections 4, 5)

- Graph metrics for Star and Delta: mean and p95 hop count, diameter, seam
  stretch (extra hops a seam-straddling pair pays vs its physical proximity).
- AoI slices for Europe, Arctic, equatorial: slice size and induced-subgraph
  connectivity per topology (Delta cannot cover above its inclination).
- Nearest-capable and ring-compression under capable fraction
  p in {0.01, 0.05, 0.2, 1.0}: distribution of hops to the nearest capable node.
- Every figure reproducible from `just run e1_substrate` then
  `just figures e1_substrate`. Verdict recorded in RESULTS.md.

## Status

Not started. Substrate package (`substrate.walker/graph/slices`) is in place and
the E0 detour uses `graph.nearest_capable`, so the machinery E1 needs exists.
