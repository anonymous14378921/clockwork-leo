# Clockwork

**Scheduling Compound AI Workflows in Space Data Centers**

Clockwork is a planning framework for provisioning compound AI workflows on LEO satellite constellations under end-to-end latency SLOs. It uses predicted orbital geometry to plan provisioning decisions across constellation snapshots, jointly optimizing plane activation, component placement, and reprovisioning cost over time.

Clockwork relies on two algorithms:

- **Castor** constructs candidate provisioning states for individual constellation snapshots by searching a layered graph using label dominance and latency/cost bounds.
- **Pollux** connects Castor's candidate states across time using dynamic programming, exploiting the repeating orbital cycle to minimize total scheduling cost while preserving SLO attainment.

## Quickstart

```bash
pip install -e .                  # install the package
just test                         # run the test suite
just run pA_slo_sweep             # run an experiment
```

Requires Python >= 3.9 and [just](https://github.com/casey/just). CPU only, no GPU needed.

## Repository layout

```
src/lab/
  service.py          shared types, plan evaluator, instance helpers
  castor.py           Castor: per-snapshot provisioning (label search)
  pollux.py           Pollux: cyclic schedule construction (DP)
  provision_baselines.py   baselines (single-plane, greedy, latency-first)
  hyperdrive.py       HyperDrive adapted baseline
  provider.py         provider fleet model
  workflow.py          workflow DAG loading
  profiles.py         execution profile loading
  cycle.py            planning cycle and epoch grids
  constants.py        constants loader
  harness/            run harness (provenance capture)

src/substrate/
  walker.py           Walker constellation positions and ISL links
  graph.py            snapshot ISL graph (networkx)
  visibility.py       elevation, slant range, access latency
  dynamics.py         Earth rotation, ground subpoint, dwell windows
  slices.py           AoI slice extraction

experiments/<name>/   one config.yaml + one run.py per experiment
results/<name>/<ts>/  created by each run: config, commit hash, hardware manifest
tests/                test suite covering substrate, planners, and baselines
constants/            single source of truth for all physical and model constants
configs/              provider fleet specifications
workflows/            compound AI workflow DAG definitions
ladders/              measured component execution profiles
```

## Documentation

See the **[Wiki](../../wiki)** for full companion documentation:

- [System Model](../../wiki/System-Model) — orbital mechanics, provisioning formulation, evaluation configuration
- [Castor](../../wiki/Castor) — per-snapshot provisioning algorithm and complexity analysis
- [Pollux](../../wiki/Pollux) — cyclic scheduling algorithm and complexity analysis
- [Experiments](../../wiki/Experiments) — all experiments with descriptions and paper references
- [Reproducibility](../../wiki/Reproducibility) — installation, running experiments, output structure
- [HyperDrive Baseline](../../wiki/HyperDrive-Baseline) — adapted baseline with fidelity checks

## Running experiments

Every experiment is invoked through the justfile:

```bash
just run <experiment>     # e.g., just run pK_calendar
```

Each run writes its configuration, source revision, and hardware manifest into `results/<experiment>/<timestamp>/` for full provenance.

## License

MIT
