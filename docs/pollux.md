# Pollux: cyclic schedule construction

Pollux is the cycle-wide scheduling algorithm. Given Castor's candidate provisioning states at each snapshot, Pollux connects them into a minimum-cost schedule over the full planning cycle using dynamic programming.

> This page is under active development. Sections marked with *[TBD]* will be expanded.

## Algorithm overview

Pollux operates over two consecutive copies of the snapshot sequence to handle the cyclic boundary condition. At each snapshot, it evaluates which candidate states remain feasible (accounting for changing visibility and propagation latency over time) and uses dynamic programming to select the cost-minimizing sequence of states, including switching costs for state transitions.

Key properties:
- **Cyclic optimality**: the DP over two copies ensures the schedule wraps around the sidereal day
- **Pre-staging**: new states can be prepared during unserviceable intervals, eliminating switching gaps
- **Switching cost trade-off**: a single parameter controls the cost of reprovisioning, trading schedule stability against local optimality

## Implementation

The primary implementation is in `src/lab/pollux.py`, which includes:
- The Pollux DP solver
- Reactive baselines (event-driven reprovisioning with and without pre-staging)
- A brute-force oracle for validation on small instances

## Complexity analysis

*[TBD: time complexity, space complexity, relationship to number of snapshots and candidate states]*

## Reactive baselines

*[TBD: reactive event-driven, reactive with pre-staging, fresh-optimum tracking]*
