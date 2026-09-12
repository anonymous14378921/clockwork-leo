"""Latency-first baseline: the exact search with the latency objective.

Feasible exactly when ACE is (same candidates, same SLO), never slower
than ACE's plan, never cheaper than ACE's plan.
"""

import pytest

from lab.provider import build_provider
from lab.provision_baselines import latency_first
from lab.provision_label import solve_label

VIENNA = (48.2082, 16.3738)


@pytest.mark.parametrize("provider,t,slo", [
    ("mvp-gate", 4860.0, 250.0), ("mvp-gate", 4860.0, 1000.0),
    ("mvp-main", 1080.0, 300.0), ("mvp-main", 1080.0, 1000.0)])
def test_latency_first_vs_ace(provider, t, slo):
    inst = build_provider(provider, VIENNA, t=t, seed=0)
    ace = solve_label(inst, slo)
    lf = latency_first(inst, slo)
    assert (ace is None) == (lf is None)
    if ace is None:
        return
    assert lf.latency_ms <= ace.latency_ms + 1e-6
    assert lf.cost >= ace.cost - 1e-6
    assert lf.latency_ms <= slo + 1e-6


def test_latency_first_is_latency_optimal_on_gate():
    """Brute force over the candidate pool: no plan is faster."""
    from lab.provision_milp import (AOI, EGRESS, candidate_sats, evaluate,
                                    load_chain, load_demands, load_io,
                                    load_profiles)
    import itertools
    inst = build_provider("mvp-gate", VIENNA, t=4860.0, seed=0)
    comps, edges = load_chain()
    profiles, demand, io = load_profiles(), load_demands(), load_io()
    ingress, cands = candidate_sats(inst)
    best = None
    opts = [[(s, inst.sat_hw[s]) for s in cands
             if (v, inst.sat_hw[s]) in profiles] for v in comps]
    for si in ingress:
        for combo in itertools.product(*opts):
            loads = {}
            for v, (s, h) in zip(comps, combo):
                loads[s] = loads.get(s, 0.0) + demand[v]
            if any(l > 1.0 + 1e-9 for l in loads.values()):
                continue
            for so in ingress:
                placement = {AOI: (si, None), EGRESS: (so, None)}
                for v, (s, h) in zip(comps, combo):
                    placement[v] = (s, h)
                _, lat, _, _, _ = evaluate(inst, comps, edges, profiles,
                                           placement, io)
                if best is None or lat < best:
                    best = lat
    lf = latency_first(inst, 1000.0)
    assert lf.latency_ms == pytest.approx(best, abs=1e-6)
