"""The run harness: config loading, provenance capture, results-dir creation.

Every experiment starts a run through this package and gets provenance for
free. See lab.harness.runner.Run.
"""

from .config import load_config
from .provenance import capture_provenance, hardware_manifest
from .runner import Run, latest_run, repo_root

__all__ = [
    "Run",
    "load_config",
    "capture_provenance",
    "hardware_manifest",
    "latest_run",
    "repo_root",
]
