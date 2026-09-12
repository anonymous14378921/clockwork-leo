"""Baseline planners (EQ3). All consume the SAME enumeration records that feed
the oracle, so every method is judged by the identical evaluator arithmetic
(lab.placement) and differs only in its selection rule:

- latency_first (HyperDrive-like): SLO- and budget-aware but accuracy-blind;
  among feasible plans, minimize end-to-end latency. Qualitative
  reimplementation of the latency-first policy family; adaptation disclosed.
- atlas_like (topology-blind): the strongest accuracy-aware baseline we can
  construct. Picks the accuracy-optimal (configuration, placement) believing
  in a seamless zero-propagation substrate (the Atlas/Compass world), then is
  evaluated on the real constellation, where it may lose feasibility.
- random_feasible: seeded uniform draw among feasible plans; the sanity floor.
- accuracy_greedy: maximum-accuracy plan ignoring SLO and budget entirely;
  shows what accuracy-blindness in the OTHER direction costs (infeasibility).

Each returns the chosen REAL record (with its real latency/feasibility fields)
or None when the rule selects nothing. plan_key() identifies a plan across the
real and zero-propagation record sets.
"""

import random
from typing import Dict, List, Optional

from lab.enumeration import best_feasible


def plan_key(r: Dict) -> tuple:
    return (r["detector"], r["verifier"], r["threshold"],
            r["detect_node"], r["verify_node"])


def _feasible(records: List[Dict], slo_ms: float, slack_factor: float,
              budget: float) -> List[Dict]:
    return [r for r in records
            if r["tight_ms"] <= slo_ms
            and r["slack_ms"] <= slo_ms * slack_factor
            and r["cost"] <= budget]


def latency_first(records: List[Dict], slo_ms: float, slack_factor: float,
                  budget: float = float("inf")) -> Optional[Dict]:
    ok = _feasible(records, slo_ms, slack_factor, budget)
    return min(ok, key=lambda r: (r["tight_ms"], r["cost"])) if ok else None


def atlas_like(records_real: List[Dict], records_zero: List[Dict],
               slo_ms: float, slack_factor: float,
               budget: float = float("inf")) -> Optional[Dict]:
    believed = best_feasible(records_zero, slo_ms, slack_factor, budget)
    if believed is None:
        return None
    key = plan_key(believed)
    by_key = {plan_key(r): r for r in records_real}
    real = by_key[key]
    # Real feasibility under the same SLO the baseline believed it met.
    real = dict(real)
    real["slo_feasible"] = (real["tight_ms"] <= slo_ms
                            and real["slack_ms"] <= slo_ms * slack_factor)
    return real


def random_feasible(records: List[Dict], slo_ms: float, slack_factor: float,
                    budget: float = float("inf"),
                    seed: int = 0) -> Optional[Dict]:
    ok = _feasible(records, slo_ms, slack_factor, budget)
    return random.Random(seed).choice(ok) if ok else None


def accuracy_greedy(records: List[Dict], slo_ms: float,
                    slack_factor: float) -> Dict:
    best = min(records, key=lambda r: (-r["accuracy"], r["cost"], r["tight_ms"]))
    best = dict(best)
    best["slo_feasible"] = (best["tight_ms"] <= slo_ms
                            and best["slack_ms"] <= slo_ms * slack_factor)
    return best
