# justfile — the single entry point for running anything in this repo.
# `just` with no arguments lists every runnable target.

# Show all targets with their descriptions (default).
list:
    @just --list --unsorted

# Run the full test suite.
test:
    python -m pytest tests/ -q

# Check the HyperDrive adapter against pinned upstream decisions.
test-hyperdrive:
    python -m pytest tests/test_hyperdrive.py -q

# Optional isolated dependencies for the upstream vicinity selector.
hyperdrive-deps target="/tmp/clockwork-hyperdrive-deps":
    python -m pip install --target {{target}} geopy==2.4.1

# Run an experiment: writes results/<exp>/<timestamp>/ with full provenance.
run exp:
    python experiments/{{exp}}/run.py

# Install this repo (editable).
install:
    pip install -e .
