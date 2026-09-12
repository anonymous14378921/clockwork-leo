# Reproducibility guide

## Requirements

- **Python**: >= 3.9
- **OS**: Linux or macOS (tested on both)
- **Hardware**: CPU only, no GPU required for any experiment
- **Tools**: [just](https://github.com/casey/just) command runner

## Installation

```bash
git clone <this-repository>
cd clockwork-leo

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install the package and dependencies
just install
# or equivalently: pip install -e .
```

Dependencies (installed automatically):
- pyyaml >= 6
- numpy >= 1.24
- pandas >= 2
- networkx >= 3
- pulp >= 2.7 (CBC MILP solver)
- geopy == 2.4.1 (HyperDrive baseline's WGS84 vicinity selector)

For tests: `pip install pytest>=7`

## Verifying the installation

```bash
just test                 # runs 66 tests covering substrate, planners, baselines
just test-hyperdrive      # runs HyperDrive adapter fidelity checks separately
```

## Running experiments

Every experiment is invoked through the justfile:

```bash
just run <experiment>
```

For example:

```bash
just run toy                    # smoke test
just run pA_slo_sweep           # SLO sweep (paper Section VI-B)
just run pK_calendar            # calendar scheduling (paper Section VI-C)
just run pD_heterogeneity       # hardware sensitivity (paper Section VI-D)
```

### Output structure

Each run creates a timestamped directory under `results/<experiment>/<timestamp>/` containing:

| File | Contents |
|------|----------|
| `config.yaml` | Copy of the experiment configuration |
| `commit.txt` | Git commit hash at run time |
| `dirty.txt` | Whether the working tree had uncommitted changes |
| `hardware.json` | CPU model, core count, memory |
| `*.csv` / `*.json` | Experiment-specific raw results |

### Available experiments

See the [experiment index](experiments/) for the full list with descriptions.

## Constants and configuration

All physical and model constants are in `constants/constants.yaml`. Each value carries a provenance tag:

- **paper**: taken from a cited publication
- **spec**: from a hardware or system specification
- **estimate**: engineering estimate with documented rationale
- **derived**: computed from other tagged values

Provider fleet configurations are in `configs/providers/`. Workflow DAG specifications are in `workflows/`.

## Code layout

| Directory | Purpose |
|-----------|---------|
| `src/lab/` | System model, planners, baselines, run harness |
| `src/substrate/` | Orbital mechanics (Walker positions, ISL graph, visibility) |
| `experiments/` | One directory per experiment (config + run script) |
| `tests/` | Test suite |
| `constants/` | Physical and model constants |
| `configs/` | Provider fleet specifications |
| `workflows/` | Workflow DAG definitions |
| `ladders/` | Measured component execution profiles |
| `docs/` | Companion documentation |
