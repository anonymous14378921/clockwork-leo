"""Heuristic sanity: never beats the oracle (same evaluator, same space),
always finds a plan when the oracle does (anchor-existence: if any plan is
feasible, the smallest-detector no-verifier plan at the same detect node is
feasible too, since it strictly reduces compute, phi, and cost), and its plan
is genuinely feasible.
"""

from lab import constants as C
from lab.enumeration import enumerate_records, best_feasible
from lab.heuristic import plan_greedy
from lab.instances import build_instance
from lab.workflow import load_workflow

SLACK = 3.0


def _setup():
    wf = load_workflow("wildfire")
    inst = build_instance("ctrl-star", "mid_latitude", 0.01, seed=0)
    records = enumerate_records(wf, inst, 3)
    return wf, inst, records


def test_heuristic_never_beats_oracle_and_stays_feasible():
    wf, inst, records = _setup()
    for slo_s in (0.6, 0.85, 1.0, 2.0, 4.0):
        oracle = best_feasible(records, slo_s * 1e3, SLACK)
        h = plan_greedy(wf, inst, slo_s * 1e3)
        if oracle is None:
            continue
        assert h.plan is not None, f"anchor must exist at {slo_s}s"
        assert h.plan.feasible
        assert h.plan.accuracy <= oracle["accuracy"] + 1e-9


def test_heuristic_reaches_oracle_on_relaxed_slo():
    # At a relaxed SLO the greedy walk should reach the configuration ceiling.
    wf, inst, records = _setup()
    oracle = best_feasible(records, 4.0e3, SLACK)
    h = plan_greedy(wf, inst, 4.0e3)
    assert abs(h.plan.accuracy - oracle["accuracy"]) < 1e-9


def test_heuristic_respects_budget():
    wf, inst, _ = _setup()
    h = plan_greedy(wf, inst, 2.0e3, budget=C.price("iX10") * 6)
    assert h.plan is not None
    assert h.plan.cost <= C.price("iX10") * 6
