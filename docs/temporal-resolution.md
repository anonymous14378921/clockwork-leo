# Temporal resolution and schedule replay

## Question

Clockwork's scheduling experiments make decisions at 1,440 equally spaced
snapshots over a sidereal day, approximately 59.84 seconds apart. This check
asks whether a provisioning state selected at a planning snapshot remains
feasible between that snapshot and the next decision. It also tests whether
five-second replay is stable when refined to one second.

This is a replay check. It does not give any method additional opportunities
to change its provisioning state.

## Method

The source schedules are pinned at
`results/pO_pollux_timeline/20260908-210755`. They contain Pollux, Reactive,
Per-Snapshot Minimum, and Rolling Horizon with 5, 15, and 60 minutes of
lookahead for hardware seed 0. The source uses the main provider, the Vienna
AoI at 48.21 N and 16.37 E, a 300 ms SLO, a state-pool margin of 5, and a
reprovisioning cost of 5.

For every original schedule interval, the replay keeps the selected component
placement and active planes fixed. At each finer sample it recomputes orbital
positions, AoI visibility, ISL propagation latency, and the lowest-latency
visible ingress and egress pair within the active planes. Samples are split at
the exact original schedule boundaries. Results distinguish four reasons for
not serving a request.

* `released` means the schedule selected the empty state.
* `no_access` means the scheduled state has no visible satellite in its active
  planes.
* `no_route` means access exists but the evaluator finds no ISL route.
* `latency` means a route exists but its end-to-end latency exceeds 300 ms.

The missed-failure metric considers only intervals where the scheduled state
was feasible at the interval's planning snapshot. Durations between samples
are estimates under the sampled replay. They do not prove continuous behavior.

## Results

The validated run is
`results/pP_temporal_validation/20260908-234414`. It copies the source schedule
files into the result directory and records their SHA-256 hashes in
`source_metadata.json`.

| Method | Planning grid attainment | 5 s replay | 1 s replay | Change at 1 s |
|---|---:|---:|---:|---:|
| Pollux | 84.03% | 81.52% | 81.37% | -2.66 pp |
| RH60 | 84.03% | 81.43% | 81.28% | -2.75 pp |
| RH15 | 84.03% | 80.73% | 80.52% | -3.50 pp |
| RH5 | 84.03% | 80.42% | 80.18% | -3.85 pp |
| Reactive | 84.03% | 74.94% | 74.33% | -9.70 pp |
| Per-Snapshot Minimum | 84.03% | 75.03% | 74.36% | -9.66 pp |

Five-second and one-second replay give similar conclusions. Refining Pollux's
replay changes attainment by 0.15 percentage points. The one-second replay
finds no route failures. Pollux spends about 533 seconds above the latency SLO.
Across the complete cycle it spends about 13,782 seconds without visible
access in the scheduled active planes, including intervals already
unserviceable at their planning snapshots. Within intervals whose starting
snapshot is feasible, Pollux fails for an estimated 5,883 seconds, or 8.13% of
their duration. Most newly detected failures arise from access loss within an
interval rather than a latency crossing.

## Interpretation

The one-minute grid provides a common set of decision times for comparing the
methods on the planning grid. This replay does not support claiming that the
grid preserves feasibility between decisions. Pollux is less sensitive than
Reactive and Per-Snapshot Minimum in this hardware assignment, but its sampled
attainment still falls by 2.66 percentage points.

These results cover one hardware assignment. Planning at 30, 60, and 120
second intervals has also been evaluated for this assignment by the existing
planning-resolution experiment.

| Decision interval | Candidate states | Planning-grid attainment | Pollux cost | Reprovisions |
|---|---:|---:|---:|---:|
| 119.67 s | 6,471 | 84.58% | 760.02 | 46 |
| 59.84 s | 6,707 | 84.03% | 828.51 | 57 |
| 29.92 s | 6,931 | 84.03% | 860.54 | 63 |

These results come from
`results/pM_calendar_sensitivity/20260904-141446`. Refinement does not change
the candidate-pool attainment between the 60 and 30 second grids, but it does
increase the number of observed reprovisionings and total scheduling cost.
The result therefore does not show cost convergence at one minute. Each row
rebuilds Castor's candidate pool, so the experiment combines temporal
resolution with a changing pool. A controlled common-pool comparison and
multi-seed replication remain open checks.

## Reproduction

Run:

```text
just run pP_temporal_validation
```

The configuration pins the source run and replay resolutions. The result
contains one summary JSON file per resolution and an interval-level CSV that
preserves the failure categories without storing every individual sample.
