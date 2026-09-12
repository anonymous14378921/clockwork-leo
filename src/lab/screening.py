"""Shell screening bound (algorithm Step 3): a cheap, certified upper bound on
the accuracy any plan can achieve in a shell.

Construction: evaluate the restricted plan space on the zero-propagation clone
of the substrate (hops free, same hardware). Every real plan's latency is >=
its zero-propagation latency and its cost is unchanged, so the best
zero-propagation-feasible accuracy upper-bounds the real optimum (proof is two
lines; tested against the oracle on the full instance grid).

Uses: (1) shell pruning during planning — a shell whose bound does not beat the
incumbent solution is skipped without solving it; (2) a per-instance optimality
CERTIFICATE at scales where enumeration is out of reach — if the heuristic's
plan meets the bound, it is provably optimal on the restricted space.
"""

from typing import List, Optional

from lab.enumeration import enumerate_records, best_feasible
from lab.instances import Instance
from lab.workflow import Workflow


def accuracy_upper_bound(wf: Workflow, inst: Instance, slo_ms: float,
                         budget: float = float("inf"),
                         k_candidates: int = 3,
                         zero_records: Optional[List[dict]] = None
                         ) -> Optional[float]:
    """Upper bound on achievable accuracy in this instance's shell, or None if
    even the zero-propagation relaxation is infeasible (a coverage-style
    certificate of infeasibility for the real problem too)."""
    if zero_records is None:
        zero_records = enumerate_records(wf, inst, k_candidates,
                                         zero_propagation=True)
    best = best_feasible(zero_records, slo_ms, wf.slo_slack_factor, budget)
    return best["accuracy"] if best else None


def certifies(bound: Optional[float], achieved: Optional[float],
              tol: float = 1e-9) -> bool:
    """True when an achieved plan meets the bound, i.e. it is provably optimal
    on the restricted space without any exact solve."""
    return (bound is not None and achieved is not None
            and achieved >= bound - tol)
