# E0 — worked example (go/no-go, FIRST)

**Hypothesis:** HC2 (achievable workflow accuracy is placement-dependent under a
fixed SLO). E0 is **THE go/no-go for the whole paper**. FAIL kills or reframes it.

## Instance (brief Section 7)

- Constellation ref-star, sparse-strong fleet (2% H100-class, rest iX10).
- Wildfire pipeline: ingest (150 MB tile), screen (5 GFLOPs, 10 MB out, recall
  0.98), detect (YOLOv8n..x placeholder ladder, ~500 crops per tile), spread
  (2 GFLOPs, 1 MB out), alert (10 KB).
- Two placements at the same SLO: **A** packs every component on iX10 nodes
  adjacent to the sensor; **B** detours detect k hops to the nearest H100. k is
  measured from the substrate (`graph.nearest_capable`), not assumed.

## Definition of done

One figure (two placement diagrams plus a latency-budget bar decomposed into
hops, transmission, compute, with achieved accuracy annotated) and a PASS/FAIL
verdict. **PASS if the accuracy gap is at least several mAP at equal SLO without
contrived numbers.** Only the SLO is chosen; FLOPs, mAP, device throughputs, and
k are cited or measured. The SLO calibration is disclosed in constants.yaml and
RESULTS.md, and the result is shown across a range of SLOs.

## Run

    just run e0_worked_example      # writes results/e0_worked_example/<ts>/
    just figures e0_worked_example  # writes figures/e0_worked_example.{pdf,png}
