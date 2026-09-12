# E3 — planner (SQ3)

**Contribution / hypothesis:** C3 (the planner: exact MILP oracle plus a
topology-aware scalable heuristic, emitting plans with validity horizons).

## Definition of done (brief Sections 2, 4)

- MILP oracle on small instances: exact accuracy-maximal SLO-feasible placement
  and variant configuration.
- Topology-aware heuristic compared against the MILP (optimality gap) and against
  baselines: latency-only, accuracy-only, topology-unaware, random.
- Plans emit a validity horizon (from E4 slice lifetimes).
- Figures reproducible from one entry point. RESULTS.md carries the optimality
  gap and the win over baselines.

## Status

Not started. Depends on the E2 formulation and the substrate graphs.
