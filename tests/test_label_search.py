"""Triple check for the layered label search: Brute Force == MILP == Label
on gate-scale instances (cost equality; latency of the returned plan must
meet the SLO in all three). The three implementations share only the
evaluator, so agreement guards the dominance rules (plane-superset and
component-wise residual capacity) against silent pruning of optima.
"""

import time

import pytest

from lab.provider import build_provider
from lab.provision_label import solve_brute, solve_label
from lab.provision_milp import solve

VIENNA = (48.2082, 16.3738)
GATE_T = 4860.0


@pytest.fixture(scope="module")
def gate():
    return build_provider("mvp-gate", VIENNA, t=GATE_T, seed=0)


@pytest.mark.parametrize("slo", [250.0, 500.0, 1000.0])
def test_triple_equality_on_gate(gate, slo):
    milp = solve(gate, slo)
    label = solve_label(gate, slo)
    brute = solve_brute(gate, slo)
    assert (milp is None) == (label is None) == (brute is None)
    if milp is None:
        return
    assert abs(label.cost - milp.cost) < 1e-6
    assert abs(brute[0] - milp.cost) < 1e-6
    assert label.latency_ms <= slo + 1e-6
    assert milp.latency_ms <= slo + 1e-6


def test_label_matches_milp_on_main(gate):
    inst = build_provider("mvp-main", VIENNA, t=1080.0, seed=0)
    for slo in (200.0, 300.0, 500.0):
        milp = solve(inst, slo)
        label = solve_label(inst, slo)
        assert (milp is None) == (label is None), slo
        if milp is not None:
            assert abs(label.cost - milp.cost) < 1e-6, slo


def test_label_is_fast(gate):
    inst = build_provider("mvp-main", VIENNA, t=1080.0, seed=0)
    inst.sat_dist(next(iter(inst.sat_access)), next(iter(inst.sat_hw)))
    t0 = time.perf_counter()
    solve_label(inst, 300.0)
    dt = time.perf_counter() - t0
    assert dt < 2.0    # generous bound; measured numbers reported by pA
