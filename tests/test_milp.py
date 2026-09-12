"""MILP == enumeration: the two exact planners were implemented independently
(binary program with a latency decomposition vs brute-force evaluation), so
agreement on accuracy AND cost across instances and SLOs validates both — the
core cross-implementation check for contribution C3's exact half."""

import pytest

from lab.enumeration import enumerate_records, best_feasible
from lab.instances import build_instance
from lab.milp import plan_milp
from lab.workflow import load_workflow

SLACK = 3.0


@pytest.mark.parametrize("con,p,seed", [
    ("ctrl-star", 0.01, 0), ("ctrl-star", 0.002, 1), ("starlink-s1", 0.05, 2),
])
def test_milp_matches_enumeration(con, p, seed):
    wf = load_workflow("wildfire")
    inst = build_instance(con, "mid_latitude", p, seed)
    records = enumerate_records(wf, inst, 3)
    for slo_s in (0.6, 0.85, 1.0, 2.0):
        oracle = best_feasible(records, slo_s * 1e3, SLACK)
        m = plan_milp(wf, inst, slo_s * 1e3)
        if oracle is None:
            assert m is None
            continue
        assert m is not None, f"MILP found nothing at {slo_s}s"
        assert abs(m.accuracy - oracle["accuracy"]) < 1e-9, slo_s
        assert abs(m.cost - oracle["cost"]) < 1e-9, slo_s


def test_milp_respects_budget():
    wf = load_workflow("wildfire")
    inst = build_instance("ctrl-star", "mid_latitude", 0.01, 0)
    records = enumerate_records(wf, inst, 3)
    oracle = best_feasible(records, 2.0e3, SLACK, budget=20.0)
    m = plan_milp(wf, inst, 2.0e3, budget=20.0)
    assert m is not None and m.cost <= 20.0
    assert abs(m.accuracy - oracle["accuracy"]) < 1e-9
