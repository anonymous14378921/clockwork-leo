"""Cross-check for the layered label search: Brute Force == Label on
gate-scale instances (cost equality; latency must meet the SLO). The two
implementations share only the evaluator, so agreement guards the
dominance rules against silent pruning of optima.
"""

import time

import pytest

from lab.provider import build_provider
from lab.castor import solve_brute, solve_label

VIENNA = (48.2082, 16.3738)
GATE_T = 4860.0


@pytest.fixture(scope="module")
def gate():
    return build_provider("mvp-gate", VIENNA, t=GATE_T, seed=0)


@pytest.mark.parametrize("slo", [250.0, 500.0, 1000.0])
def test_label_vs_brute_on_gate(gate, slo):
    label = solve_label(gate, slo)
    brute = solve_brute(gate, slo)
    assert (label is None) == (brute is None)
    if label is None:
        return
    assert abs(label.cost - brute[0]) < 1e-6
    assert label.latency_ms <= slo + 1e-6


def test_label_consistent_on_main(gate):
    inst = build_provider("mvp-main", VIENNA, t=1080.0, seed=0)
    for slo in (200.0, 300.0, 500.0):
        label = solve_label(inst, slo)
        if label is not None:
            assert label.latency_ms <= slo + 1e-6


def test_label_is_fast(gate):
    inst = build_provider("mvp-main", VIENNA, t=1080.0, seed=0)
    inst.sat_dist(next(iter(inst.sat_access)), next(iter(inst.sat_hw)))
    t0 = time.perf_counter()
    solve_label(inst, 300.0)
    dt = time.perf_counter() - t0
    assert dt < 2.0
