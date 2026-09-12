"""Cascade configuration space: accuracy and forward fractions per configuration.

A configuration is c = (detector, verifier, threshold) for the detection
cascade. Workflow accuracy is the MEASURED end-to-end mAP of the cascade
under c.

Data source resolution, in order:
  1. ladders/cascade_grid_measured.yaml, if present: the measured grid. Entries
     keyed "<detector>|<verifier>|<threshold>", each {accuracy, forward_fraction}.
     Source reported as MEASURED_GRID.
  2. Otherwise a PLACEHOLDER analytic grid derived from the single-model ladder
     (documented below), source reported as PLACEHOLDER. Every result produced
     from it carries that flag; nothing placeholder-derived may reach the paper.

Placeholder grid (prov: estimate, replaced by the measured grid):
  - accuracy(det, none, t)  = mAP(det)
  - accuracy(det, ver, t)   = mAP(det) + max(0, mAP(ver) - mAP(det)) * (t / t_max) * 0.8
      (a higher threshold forwards more low-confidence crops, recovering up to
       80% of the detector-to-verifier gap at the largest threshold)
  - phi(det, t) = min(1, t * conf_factor(det)) with conf_factor n=1.4, s=1.0,
      m=0.7 (weaker detectors are less confident, so they forward more)
Shapes are qualitative stand-ins so the machinery is testable end to end; the
numbers carry no evidentiary weight.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import yaml

from lab import constants as C
from lab import profiles as P
from lab.harness.runner import repo_root
from lab.workflow import CascadeSpec

MEASURED_GRID = "measured-grid"
PLACEHOLDER = "placeholder-estimate"

_GRID_FILE = "cascade_grid_measured.yaml"

_CONF_FACTOR = {"YOLOv8n": 1.4, "YOLOv8s": 1.0, "YOLOv8m": 0.7}
_GAP_RECOVERY = 0.8


@dataclass(frozen=True)
class Config:
    detector: str
    verifier: str        # "none" for no verifier
    threshold: float

    @property
    def has_verifier(self) -> bool:
        return self.verifier != "none"

    def key(self) -> str:
        return f"{self.detector}|{self.verifier}|{self.threshold:g}"


def config_space(cascade: CascadeSpec) -> List[Config]:
    """Every (detector, verifier, threshold); verifier=none collapses the
    threshold axis (no forwarding decision exists), canonicalized to t=0."""
    out: List[Config] = []
    for d in cascade.detectors:
        out.append(Config(d, "none", 0.0))
        for v in cascade.verifiers:
            if v == "none":
                continue
            for t in cascade.thresholds:
                out.append(Config(d, v, t))
    return out


@lru_cache(maxsize=1)
def _load_measured_grid() -> Optional[Dict[str, Dict[str, float]]]:
    path = repo_root() / "ladders" / _GRID_FILE
    if not path.exists():
        return None
    with path.open("r") as f:
        raw = yaml.safe_load(f)
    return {k: {kk: C.to_float(vv) for kk, vv in rec.items()}
            for k, rec in raw["grid"].items()}


def _ladder_map(cascade: CascadeSpec) -> Dict[str, float]:
    return {v.name: v.map for v in P.load_ladder(cascade.ladder)}


def accuracy(cfg: Config, cascade: CascadeSpec) -> Tuple[float, str]:
    """Measured end-to-end cascade accuracy under cfg, with its source flag."""
    grid = _load_measured_grid()
    if grid is not None and cfg.key() in grid:
        return grid[cfg.key()]["accuracy"], MEASURED_GRID
    maps = _ladder_map(cascade)
    base = maps[cfg.detector]
    if not cfg.has_verifier:
        return base, PLACEHOLDER
    t_max = max(cascade.thresholds)
    gain = max(0.0, maps[cfg.verifier] - base)
    return base + gain * (cfg.threshold / t_max) * _GAP_RECOVERY, PLACEHOLDER


def forward_fraction(cfg: Config, cascade: CascadeSpec) -> Tuple[float, str]:
    """Fraction of crops the detector forwards to the verifier under cfg."""
    if not cfg.has_verifier:
        return 0.0, MEASURED_GRID  # exactly zero by construction, no data needed
    grid = _load_measured_grid()
    if grid is not None and cfg.key() in grid:
        return grid[cfg.key()]["forward_fraction"], MEASURED_GRID
    phi = min(1.0, cfg.threshold * _CONF_FACTOR.get(cfg.detector, 1.0))
    return phi, PLACEHOLDER
