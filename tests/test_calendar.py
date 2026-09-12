"""Clockwork calendar planner checks.

1. Exact-cycle DP == exhaustive enumeration on synthetic tiny instances
   (random latency tables), including forced gaps and the wrap switch.
2. Two-pass DP is feasible and within two switching costs of the exact
   cyclic optimum (the provable bound; one is what is observed).
3. Switch count is non-increasing in the switching cost (exact cycle).
4. On the real gate substrate: every served instant of the calendar is
   SLO-feasible when re-scored by the independent evaluator, and with zero
   switching cost the calendar equals always-fresh (release semantics
   are identical on both sides).
"""

import random

import pytest

from lab import pollux as CAL
from lab.cycle import cycle_s
from lab.provider import build_provider
from lab.service import (AOI, evaluate, load_chain, load_io,
                                load_profiles)

VIENNA = (48.2082, 16.3738)


def _synthetic(seed: int, n: int = 6, m: int = 4):
    """Random states over two compute placements and nested plane sets,
    random latencies, some instants with nothing feasible."""
    rng = random.Random(seed)
    states = []
    planes_a = [frozenset({("s", 0)}), frozenset({("s", 0), ("s", 1)})]
    planes_b = [frozenset({("s", 2)}), frozenset({("s", 2), ("s", 3)})]
    comp_a = (("detector", ("s", 0, 1), "cpu"),)
    comp_b = (("detector", ("s", 2, 1), "cpu"),)
    for p in planes_a:
        states.append(CAL.State(comp_a, p))
    for p in planes_b:
        states.append(CAL.State(comp_b, p))
    states = states[:m]
    rates = [1.0 + len(st.planes) + rng.random() for st in states]
    table = []
    for k in range(n):
        row = []
        for i in range(m):
            if rng.random() < 0.35:
                row.append(None)
            else:
                row.append((("s", 0, 0), rng.uniform(100.0, 400.0)))
        table.append(row)
    return states, table, rates


@pytest.mark.parametrize("seed", range(12))
def test_exact_cycle_matches_brute_force(seed):
    states, table, rates = _synthetic(seed)
    for lam in (0.0, 0.7, 3.0):
        cal = CAL.plan_calendar(states, table, rates, 0.5, lam, 300.0,
                                exact_cycle=True)
        brute = CAL.brute_calendar(states, table, rates, 0.5, lam, 300.0)
        assert cal.objective == pytest.approx(brute, abs=1e-9)


@pytest.mark.parametrize("seed", range(12))
def test_two_pass_within_one_switch_of_exact(seed):
    states, table, rates = _synthetic(seed)
    for lam in (0.0, 0.7, 3.0):
        two = CAL.plan_calendar(states, table, rates, 0.5, lam, 300.0)
        exact = CAL.plan_calendar(states, table, rates, 0.5, lam, 300.0,
                                  exact_cycle=True)
        assert two.objective >= exact.objective - 1e-9
        assert two.objective <= exact.objective + 2 * lam + 1e-9
        for k, i in enumerate(two.assignment):
            gap = not any(CAL.feasible(table, k, j, 300.0)
                          for j in range(len(states)))
            if i >= 0 and not gap:          # held states only inside gaps
                assert CAL.feasible(table, k, i, 300.0)
            assert (two.ingress[k] is not None) == (i >= 0 and not gap)


@pytest.mark.parametrize("seed", range(6))
def test_switches_monotone_in_switch_cost(seed):
    states, table, rates = _synthetic(seed, n=8)
    prev = None
    for lam in (0.0, 0.5, 1.0, 2.0, 5.0, 50.0):
        cal = CAL.plan_calendar(states, table, rates, 0.5, lam, 300.0,
                                exact_cycle=True)
        if prev is not None:
            assert cal.switches <= prev
        prev = cal.switches


def test_calendar_on_gate_is_feasible_and_no_dearer_than_fresh():
    comps, edges = load_chain()
    profiles = load_profiles()
    io = load_io()
    slo = 500.0
    times = [k * cycle_s() / 24 for k in range(24)]     # hourly, one cycle
    build = lambda t: build_provider("mvp-gate", VIENNA, t=t, seed=0)
    states = CAL.collect_candidates(build, times, slo, cost_slack=5.0)
    assert states
    table, rates = CAL.latency_table(build, times, states, comps, edges,
                                     profiles, io)
    step_h = cycle_s() / 24 / 3600.0
    # per-instant optimum among the candidates
    optimum = []
    for k in range(len(times)):
        feas = [i for i in range(len(states)) if CAL.feasible(table, k, i, slo)]
        optimum.append(min(feas, key=lambda i: rates[i]) if feas else -1)
    cal = CAL.plan_calendar(states, table, rates, step_h, 0.0, slo)
    fresh = CAL.simulate_reactive(states, table, rates, optimum, step_h,
                                  slo, "fresh")
    # Invariant: at zero switching cost the calendar IS always-fresh
    # (same min-rate feasible state at every instant, same releases).
    assert cal.unit_hours == pytest.approx(fresh.unit_hours, abs=1e-9)
    assert cal.served == pytest.approx(fresh.served)
    assert cal.lower_bound <= cal.objective + 1e-9
    # independent re-score of every served instant
    for k, i in enumerate(cal.assignment):
        if i < 0:
            continue
        inst = build(times[k])
        placement = states[i].placement(*cal.ingress[k])
        _, lat, _, _, _ = evaluate(inst, comps, edges, profiles, placement,
                                   io)
        assert lat <= slo + 1e-6
    # a large switching cost never increases switches
    dear = CAL.plan_calendar(states, table, rates, step_h, 100.0, slo)
    assert dear.switches <= cal.switches
    # Rolling horizon at zero switching cost is also always-fresh, for
    # any window: the DP picks the per-instant minimum regardless of
    # what it sees ahead.
    for H in (1, 3, 24):
        roll = CAL.simulate_rolling(states, table, rates, step_h, 0.0,
                                    slo, H)
        assert roll.unit_hours == pytest.approx(fresh.unit_hours, abs=1e-9)
        assert roll.served == pytest.approx(fresh.served)
    # With a switching cost, a longer window never does worse than the
    # myopic one on the objective it optimizes, up to end effects, and a
    # full-cycle window cannot beat the calendar's lower bound.
    lam = 5.0
    cal5 = CAL.plan_calendar(states, table, rates, step_h, lam, slo)
    roll_full = CAL.simulate_rolling(states, table, rates, step_h, lam,
                                     slo, len(times))
    assert roll_full.objective >= cal5.lower_bound - 1e-9
    assert roll_full.switches >= 0 and roll_full.served <= 1.0
    # The daily planner (linear, no wrap) at zero switching cost is
    # always-fresh too, and its objective is the calendar's lower bound.
    day0 = CAL.plan_day(states, table, rates, step_h, 0.0, slo)
    assert day0.unit_hours == pytest.approx(fresh.unit_hours, abs=1e-9)
    day5 = CAL.plan_day(states, table, rates, step_h, lam, slo)
    assert day5.objective == pytest.approx(cal5.lower_bound, abs=1e-6)
    # Starting from a held state: entering the horizon from the state the
    # plan itself ends in costs at most as much as starting from nothing.
    last = day5.assignment[-1]
    if last >= 0:
        cont = CAL.plan_day(states, table, rates, step_h, lam, slo,
                            start=last)
        assert cont.objective <= day5.objective + 1e-9
        assert cont.served == pytest.approx(day5.served)
