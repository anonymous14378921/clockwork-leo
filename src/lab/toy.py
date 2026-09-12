"""A toy 'system under test'.

Stands in for whatever you are actually studying. Here: two convergence curves
with different time constants, so the demo figure has a series to compare and
an `ours=` to highlight. Replace this module with your real system; the harness
and figure pipeline stay the same.
"""

import math
from typing import Dict, List


def convergence_curve(n_steps: int, tau: float, noise: float, seed: int) -> List[float]:
    """y = 1 - exp(-t/tau) with a little reproducible noise."""
    rng = _Lcg(seed)
    out = []
    for t in range(n_steps):
        base = 1.0 - math.exp(-t / tau)
        out.append(base + noise * (rng.next() - 0.5))
    return out


class _Lcg:
    """Tiny seedable RNG so the toy has zero numpy dependency for its core."""

    def __init__(self, seed: int):
        self.state = (seed * 2654435761 + 12345) & 0xFFFFFFFF

    def next(self) -> float:
        self.state = (1103515245 * self.state + 12345) & 0x7FFFFFFF
        return self.state / 0x7FFFFFFF


def run_toy(config: Dict) -> Dict[str, List[float]]:
    """Produce one curve per named series. Returns {series_name: values}."""
    n_steps = int(config["n_steps"])
    noise = float(config.get("noise", 0.0))
    seed = int(config.get("seed", 0))
    curves = {}
    for i, (label, tau) in enumerate(config["series"].items()):
        curves[label] = convergence_curve(n_steps, float(tau), noise, seed + i)
    return curves
