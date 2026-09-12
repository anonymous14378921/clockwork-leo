"""Screening bound: must upper-bound the oracle on every instance and SLO
(the certificate property), and must certify the heuristic wherever the
heuristic actually reaches the bound."""

import pytest

from lab.enumeration import enumerate_records, best_feasible
from lab.heuristic import plan_greedy
from lab.instances import build_instance
from lab.screening import accuracy_upper_bound, certifies
from lab.workflow import load_workflow

SLACK = 3.0


@pytest.mark.parametrize("con,p,seed", [
    ("ctrl-star", 0.002, 0), ("ref-star", 0.01, 1), ("starlink-s1", 0.05, 2),
])
def test_bound_dominates_oracle(con, p, seed):
    wf = load_workflow("wildfire")
    inst = build_instance(con, "mid_latitude", p, seed)
    real = enumerate_records(wf, inst, 3)
    zero = enumerate_records(wf, inst, 3, zero_propagation=True)
    for slo_s in (0.6, 0.85, 1.0, 2.0, 4.0):
        bound = accuracy_upper_bound(wf, inst, slo_s * 1e3, zero_records=zero)
        oracle = best_feasible(real, slo_s * 1e3, SLACK)
        if oracle is None:
            continue  # bound may still exist (relaxation is weaker)
        assert bound is not None
        assert bound >= oracle["accuracy"] - 1e-9, slo_s


def test_certificate_fires_at_relaxed_slo():
    # At a relaxed SLO propagation is immaterial, the bound is tight, and the
    # heuristic's plan should be CERTIFIED optimal without any exact solve.
    wf = load_workflow("wildfire")
    inst = build_instance("ref-star", "mid_latitude", 0.05, 0)
    bound = accuracy_upper_bound(wf, inst, 4.0e3)
    h = plan_greedy(wf, inst, 4.0e3)
    assert certifies(bound, h.plan.accuracy)
