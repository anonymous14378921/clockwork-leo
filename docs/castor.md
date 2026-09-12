# Castor: per-snapshot provisioning

Castor is the per-snapshot provisioning algorithm. Given a constellation snapshot, a compound AI workflow, and a latency SLO, Castor finds the minimum-cost provisioning state that satisfies the SLO.

> This page is under active development. Sections marked with *[TBD]* will be expanded.

## Algorithm overview

Castor searches a layered placement graph whose paths jointly determine ingress, component placement, egress, and the planes that must be activated. It uses:

- **Candidate reduction**: topology-aware filtering of satellites based on visibility and hardware compatibility
- **Pareto label dominance**: pruning dominated partial plans during the layered search
- **Latency lower bound**: early termination of paths that cannot meet the SLO
- **Cost lower bound**: early termination of paths that cannot improve the current best

The search returns one minimum-cost feasible state and, optionally, alternatives within a specified cost-rate margin for use by Pollux.

## Implementation

The primary implementation is in `src/lab/castor.py` (layered Pareto label search).

Additional implementations:
- `src/lab/service.py` — shared types, plan evaluator, instance helpers
- `src/lab/provision_baselines.py` — baseline policies (single-plane, greedy, latency-first, HyperDrive adapter)

## Complexity analysis

*[TBD: time complexity, space complexity, empirical scaling]*

## Baselines

*[TBD: greedy_compose, single-plane restriction, latency_first, HyperDrive adapter]*
