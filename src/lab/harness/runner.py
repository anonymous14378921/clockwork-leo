"""Run: the harness every experiment inherits.

`Run.start("toy")` loads experiments/toy/config.yaml, creates
results/toy/<timestamp>/, and writes provenance into it BEFORE the experiment
does anything. Experiments cannot opt out of provenance — that is the point.
"""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import load_config
from .provenance import capture_provenance

_ROOT_MARKERS = ("pyproject.toml", ".git")


def repo_root(start: Optional[Path] = None) -> Path:
    """Walk up to the repo root (the dir holding pyproject.toml / .git)."""
    here = Path(start or __file__).resolve()
    for parent in [here, *here.parents]:
        if any((parent / m).exists() for m in _ROOT_MARKERS):
            return parent
    raise RuntimeError("Could not locate repo root (no pyproject.toml/.git above).")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


@dataclass
class Run:
    """A single experiment run. Owns its results/<exp>/<ts>/ directory."""

    name: str
    dir: Path
    config: Dict[str, Any]
    root: Path
    started_at: str
    provenance: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def start(cls, name: str, root: Optional[Path] = None) -> "Run":
        root = Path(root) if root else repo_root()
        exp_dir = root / "experiments" / name
        config_path = exp_dir / "config.yaml"
        if not config_path.exists():
            raise FileNotFoundError(
                f"No config for experiment '{name}': expected {config_path}"
            )

        config = load_config(config_path)
        ts = _timestamp()
        run_dir = root / "results" / name / ts
        run_dir.mkdir(parents=True, exist_ok=False)

        # Provenance, written first and unconditionally.
        shutil.copy2(config_path, run_dir / "config.yaml")
        provenance = capture_provenance(root)
        provenance["experiment"] = name
        provenance["started_at"] = ts
        with (run_dir / "provenance.json").open("w") as f:
            json.dump(provenance, f, indent=2)

        run = cls(
            name=name, dir=run_dir, config=config, root=root,
            started_at=ts, provenance=provenance,
        )
        print(f"[harness] run '{name}' -> {run_dir}")
        if provenance.get("git_dirty"):
            print("[harness] WARNING: git tree is dirty; results are not reproducible.")
        return run

    def path(self, *parts: str) -> Path:
        """A path inside this run's results dir."""
        return self.dir.joinpath(*parts)

    def save_json(self, filename: str, obj: Any) -> Path:
        p = self.path(filename)
        with p.open("w") as f:
            json.dump(obj, f, indent=2)
        return p

    def save_dataframe(self, filename: str, df) -> Path:
        """Write a pandas DataFrame as CSV into the run dir."""
        p = self.path(filename)
        df.to_csv(p, index=False)
        return p


def latest_run(name: str, root: Optional[Path] = None) -> Path:
    """Most recent results/<name>/<ts>/ dir. Used by figure scripts."""
    root = Path(root) if root else repo_root()
    exp_results = root / "results" / name
    runs = sorted(p for p in exp_results.glob("*") if p.is_dir())
    if not runs:
        raise FileNotFoundError(f"No runs found under {exp_results}. Run `just run {name}` first.")
    return runs[-1]
