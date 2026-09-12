# HyperDrive baseline adaptation

The implemented method is **HyperDrive adapted to Clockwork's snapshot model**.
Its function placement policy follows the pinned upstream implementation under
nonbinding thermal conditions. It is not a reproduction of the complete
HyperDrive platform or its published experimental setting.

The reference is Pusztai, Marcelino, and Nastic, *HyperDrive, Scheduling Serverless
Functions in the Edge-Cloud-Space 3D Continuum*, SEC 2024.
Paper https://arxiv.org/abs/2410.16026
Code https://github.com/polaris-slo-cloud/hyper-drive
Pinned revision `94d753a4da15339268423e4141a2c086974ac507`.

## Step by step

1. Use the same orbital snapshot, compound AI workflow, hardware assignment,
   capacity shares, and execution profiles as Clockwork. Compute runs on
   satellites only. This replaces HyperDrive's edge, cloud, and satellite
   infrastructure with the infrastructure under study.
2. Try every visible ingress as the fixed input source. Upstream supports
   scheduling after a forced initial placement. Enumerating the possible
   sources is our wrapper, because Clockwork chooses ingress. Every attempt
   starts with an empty resource usage map. No random initial-task placement
   from upstream is needed because the input source is already fixed.
3. Select candidate satellites for the next component. The `matched` mode uses
   exactly Castor's candidate set. This replaces HyperDrive's geographic
   candidate selector and isolates placement choices on a shared search space.
   The `vicinity` mode preserves the original selector's satellite behavior.
   It takes the first 60 satellites within 2000 km of the predecessor's ground
   subpoint, in catalog order. These are the defaults in upstream
   `config_helper.py`. It uses WGS84 geodesic distance through geopy, ignores
   altitude, and applies the cap before resource filtering. It does not choose
   the nearest 60 satellites. We use sorted satellite IDs as the catalog order
   in both modes. This order is deterministic and can affect tied choices.
   Earth rotation is applied when deriving subpoints from our orbital model.
4. Filter candidates by hardware compatibility and remaining capacity. We map
   these into two requested resources, a compatibility flag and normalized
   capacity. The comparison of requested and available quantities matches
   `ResourcesFitPlugin`. Compatibility requires a finite execution profile.
   This replaces CPU architecture, memory, and GPU resource descriptions with
   Clockwork's resource schema. Execution time is not a ranking criterion.
5. Filter incoming network propagation latency against the full workflow SLO.
   Each chain edge receives the same limit delta. Since all latency terms in
   our model are nonnegative, this is necessary for complete feasibility but
   does not ensure it. There is no arbitrary division of the deadline among
   components and no remaining-work bound. Our unreachable-path sentinel is
   mapped to rejection, corresponding to upstream's `-1` sentinel.
   This SLO mapping is an adaptation. HyperDrive receives explicit incoming
   network constraints, which our service request does not provide.
6. Score and commit a component using the upstream decisions. The network
   scorer takes the maximum incoming propagation latency, rounds it to whole
   milliseconds using Python rounding, and normalizes it to an integer score
   between 0 and 100. All-equal raw values receive network score zero, exactly
   as upstream does. Thermal scores are fixed at 100, representing nonbinding
   thermal conditions. The scheduler averages the two scores and truncates
   to an integer. Stable descending sorting retains catalog order on ties.
   Both rounding stages are preserved. We do not add compute latency, resource
   cost, payload serialization, or lookahead to this ranking.
7. Reserve the selected component's capacity and advance through the chain.
   No concurrent scheduler competes for the resources in this experiment, so
   the highest ranked eligible node commits successfully. This is the
   conflict-free case of upstream's multi-commit procedure. There is no
   backtracking if a later component cannot be placed.
8. After all component placements are fixed, choose the visible egress with
   minimum final ISL propagation plus ground propagation. Final downlink
   serialization is constant across egress choices. This endpoint selection
   belongs to our service model and is an adapter operation.
9. Evaluate the full plan using the common Clockwork evaluator. This adds
   component execution, payload serialization, ISL propagation, and access
   latency, and charges each used satellite and active plane according to
   the same model as the other methods. The complete plan must meet the SLO.
   No infeasible plan is repaired or reported as served. Among ingress
   attempts, return the feasible complete plan with lowest full latency.
   Resource costs never choose or break ties between plans.

## What the fidelity checks establish

`just test-hyperdrive` compares the adapter with unmodified source files retained
in `tests/fixtures/hyperdrive_upstream/`, including their license and SHA256
manifest. Tests execute the original plugin class bodies and scheduler methods
with lightweight data and orchestrator interfaces.

Checks cover original network scoring on fractional milliseconds and multiple
incoming sources, original scheduler averaging and tie order over 100 seeded
candidate lists, resource comparison, and original geographic selection with
radius, ordering, and candidate cap. A complete mapped component sequence is
also checked against upstream filtering, scoring, and multi-commit decisions.
Adapter tests check capacity reservation, endpoint attempts, disconnection,
unsupported hardware, full SLO rejection, cost independence, and zero visibility.

These establish decision equivalence for the mapped inputs and assumptions.
They do not establish equivalent results in HyperDrive's original deployment.
The thermal model, multi-scheduler conflicts, edge and cloud placement, and
explicit per-link SLO specification are outside this comparison.

## Interpreting a comparison

Use the name **HyperDrive adapted** and identify the candidate mode. The registry
key `hyperdrive` uses `matched`. `latency_first` remains an exact latency-objective
ablation and is not HyperDrive.

First compare complete workflow SLO attainment. Compare costs and latency on
the shared feasible instances and report how many instances that includes.
The returned `HyperDriveResult` also records complete infeasible plans and
partial placement attempts so that failure causes remain auditable.

Lower provisioning cost alone is not evidence that Castor improves HyperDrive's
own objective. HyperDrive does not optimize our provisioning charges. Likewise,
a missed complete SLO can result from the distinction between its incoming
network constraints and our complete workflow deadline. Describe the comparison
as the behavior of its adapted placement policy under our service contract.
Do not describe it as a reproduction that disproves the original paper's SLO
results. Adding deadline lookahead or an execution-aware score would constitute
a further algorithm variant and must be named separately.

## Reproduction and bounded integration run

Install the project dependencies, then run `just test-hyperdrive` and
`just run pQ_hyperdrive_adapter`. The fidelity tests use Python 3.12 or newer.
An isolated geopy installation can be made with `just hyperdrive-deps`.
For the current workstation the commands are

```sh
PATH=/opt/anaconda3/bin:$PATH PYTHONPATH=src:/tmp/clockwork-hyperdrive-deps just test-hyperdrive
PATH=/opt/anaconda3/bin:$PATH PYTHONPATH=src:/tmp/clockwork-hyperdrive-deps just run pQ_hyperdrive_adapter
```

The integration run uses seed 0 and four equally spaced snapshots, with 300 ms
and 1000 ms SLOs. Configuration is fixed before execution. It is a small
implementation check, not the full paper evaluation or a seed robustness study.
`comparison.csv` reports outcomes. `decisions.json` preserves every candidate,
eligible candidate, incoming propagation latency, score, chosen satellite,
and ingress attempt. `summary.json` reports costs only on shared feasible
instances. Numerical inputs, source files, and upstream fixtures are archived
under the run's `source/` with hashes in `implementation.json`, in addition to
the normal run provenance. No paper text or figures are changed by the run.

The first run is `results/pQ_hyperdrive_adapter/20260909-101025/`.
At 300 ms, Castor serves three of four snapshots and each HyperDrive mode serves
one. At 1000 ms, Castor serves four and each HyperDrive mode still serves one.
Both modes give the same best complete latencies in this small sample. In the
three failures, the best complete attempt chooses CPU execution for detector
and classifier and the small accelerator for the LLM. Execution alone totals
1008.8 ms. Network-only ranking does not account for this execution cost.
The outcome demonstrates why the SLO adaptation must be explicit. It is not
evidence against HyperDrive's original network-SLO claims. The evaluation
journal records the full preliminary results and validation status.
