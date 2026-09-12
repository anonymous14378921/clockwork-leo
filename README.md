# Clockwork

**Scheduling Compound AI Workflows in Space Data Centers**

Clockwork is a planning framework for provisioning compound AI workflows on LEO satellite constellations under end-to-end latency SLOs. It uses predicted orbital geometry to plan provisioning decisions across constellation snapshots, jointly optimizing plane activation, component placement, and reprovisioning cost over time.

Clockwork relies on two algorithms:

- **Castor** constructs candidate provisioning states for individual constellation snapshots by searching a layered graph using label dominance and latency/cost bounds.
- **Pollux** connects Castor's candidate states across time using dynamic programming, exploiting the repeating orbital cycle to minimize total scheduling cost while preserving SLO attainment.

## Quickstart

```bash
pip install -e .                  # install the package
just test                         # run the test suite (66 tests)
just run pA_slo_sweep             # run an experiment
```

Requires Python >= 3.9 and [just](https://github.com/casey/just). CPU only, no GPU needed.

## Repository layout

```
src/lab/              system model, planners, and run harness
src/substrate/        orbital mechanics (Walker positions, ISL graph, visibility)
experiments/<name>/   one config.yaml + one run.py per experiment
results/<name>/<ts>/  created by each run: config copy, commit hash, hardware manifest
tests/                66 tests covering substrate, planners, and baselines
constants/            single source of truth for all physical and model constants
configs/              provider fleet specifications
workflows/            compound AI workflow DAG definitions
ladders/              measured component execution profiles
docs/                 companion documentation (system model, algorithms, experiments)
```

## Documentation

See [docs/](docs/) for the full companion documentation, including:

- [System model](docs/system-model.md) reference
- [Castor](docs/castor.md) algorithm and complexity analysis
- [Pollux](docs/pollux.md) algorithm and complexity analysis
- [Experiment index](docs/experiments/)
- [Reproducibility guide](docs/reproducibility.md)
- [HyperDrive baseline adaptation](docs/hyperdrive-baseline.md)

## Running experiments

Every experiment is invoked through the justfile:

```bash
just run <experiment>     # e.g., just run pK_calendar
```

Each run writes its configuration, source revision, and hardware manifest into `results/<experiment>/<timestamp>/` for full provenance. See the [reproducibility guide](docs/reproducibility.md) for details.

## License

MIT
