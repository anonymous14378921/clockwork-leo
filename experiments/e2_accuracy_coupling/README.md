# E2 — accuracy coupling (SQ2)

**Hypotheses:** HC1 (variant ladders are steep: order-of-magnitude compute for a
few accuracy points), HC2 (achievable workflow accuracy is placement-dependent
under a fixed SLO), HC3 (latency-optimal and accuracy-optimal placements differ
structurally). This is the paper's identity result at scale; E0 is its worked
example.

## Definition of done (brief Sections 4, 6)

- E2a: compile variant ladders **with citations** (fire detector family, VLM size
  ladder), no GPU. Replaces the placeholder `ladders/yolo_coco.yaml`.
- E2b: enumerate placements and variant configurations for the wildfire and
  maritime DAGs over the E1 graphs; Pareto frontiers (accuracy vs latency) per
  strategy per topology; decompose the placement-induced accuracy spread into
  hop-budget vs node-cap mechanisms.
- Figures reproducible from one entry point. RESULTS.md carries the spread
  numbers and the HC1/HC2/HC3 verdicts.

## Status

Not started. Depends on E1 graphs and the E0 latency/accuracy model
(`lab.e0`), which generalizes to the full enumeration.
