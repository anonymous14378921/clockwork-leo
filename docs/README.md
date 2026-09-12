# Clockwork companion documentation

This directory contains the companion documentation for the Clockwork paper. It provides details on the system model, algorithms, experiments, and reproducibility that go beyond the paper's page limit.

## Contents

### Reference

- [System model](system-model.md) — full standalone reference for the Clockwork model: orbital substrate, service model, provisioning state, feasibility, cost, and cyclic schedule formulation
- [Castor](castor.md) — per-snapshot provisioning algorithm, layered Pareto label search, and complexity analysis
- [Pollux](pollux.md) — cyclic schedule construction algorithm, dynamic programming formulation, and complexity analysis

### Experiments

- [Experiment index](experiments/) — all experiments with descriptions, configurations, and results
- [Paper artifact conventions](paper-artifact.md) — reproduction conventions and provenance
- [Temporal resolution validation](temporal-resolution.md) — schedule replay methodology on finer time grids

### Baselines

- [HyperDrive baseline adaptation](hyperdrive-baseline.md) — step-by-step adaptation of the HyperDrive placement policy, fidelity checks, and interpretation guidelines

### Reproducibility

- [Reproducibility guide](reproducibility.md) — installation, running experiments, understanding outputs
