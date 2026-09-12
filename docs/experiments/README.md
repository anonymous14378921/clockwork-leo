# Experiment index

All experiments are run via `just run <name>`. Each experiment has a `config.yaml` specifying its parameters and a `run.py` entry point. Results are written to `results/<name>/<timestamp>/` with full provenance.

## Paper experiments

These experiments directly support the results presented in the paper.

| Experiment | Description | Paper section |
|------------|-------------|---------------|
| `pA_slo_sweep` | SLO sweep: feasibility and provisioning cost vs latency deadline | Section VI-B |
| `pBC_aoi_portfolio` | AoI portfolio: geography effects on Star/Delta shell coverage | Section VI-B |
| `pD_heterogeneity` | Hardware sensitivity: uniform vs plane-structured fleet composition | Section VI-D |
| `pK_calendar` | Calendar scheduling: switching cost sweep, pre-staging, and drift | Section VI-C |
| `pQ_hyperdrive_adapter` | HyperDrive baseline: bounded comparison with adapted placement policy | Section VI-B |

## Supplementary experiments

These experiments provide additional evidence and sensitivity analyses beyond the paper.

| Experiment | Description |
|------------|-------------|
| `pE_time` | Planning time characterization over one cycle |
| `pF_cost_sensitivity` | Provisioning cost parameter sensitivity (nine regimes) |
| `pG_pooling_ablation` | Plane-pooled vs satellite-level resource accounting |
| `pH_profile_sensitivity` | Execution profile perturbation (+/- 20% noise, 20 draws) |
| `pI_candidate_ablation` | Candidate set restriction: lossless pruning verification |
| `pJ_plan_export` | Multi-plane plan inspection and diagnostics |
| `pL_scarcity` | Resource scarcity: Star hub planes 0 to 12 |
| `pM_calendar_sensitivity` | Calendar planner sensitivity: pool slack and temporal resolution |
| `pN_aoi_day` | AoI characterization over one sidereal day |
| `pO_pollux_timeline` | Two-hour illustrative trace of Pollux scheduling decisions |
| `pP_temporal_validation` | Fixed-schedule replay on finer time grids |

## Validation experiments

| Experiment | Description |
|------------|-------------|
| `p0_sanity_gate` | Quick correctness gate for the provisioning model |
| `toy` | Harness smoke test |

## Pre-pivot experiments

These experiments were developed during an earlier research phase and test hypotheses from the original problem formulation. They are included for completeness but are not referenced in the current paper.

| Experiment | Description |
|------------|-------------|
| `e0_worked_example` | Accuracy is placement-dependent at equal SLO |
| `e1_substrate` | Star vs Delta topology-class metrics |
| `e2_accuracy_coupling` | Variant ladders, Pareto frontiers, accuracy spread |
| `e3_planner` | MILP oracle and heuristic vs baselines |
| `e4_dynamics` | Slice lifetime and churn, validity horizons |
