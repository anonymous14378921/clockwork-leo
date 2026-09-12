"""Pivot MVP sanity: visibility geometry and the provisioning MILP gate.

The gate assertions mirror the master setup's go/no-go: cost is monotone
non-increasing in the SLO, tight SLOs buy GPU hardware, and the incompatible
(llm, cpu) pair never appears.
"""

import math

from lab.provider import build_provider
from lab.provision_milp import solve
from substrate import visibility as VIS
from substrate.walker import Walker

VIENNA = (48.2082, 16.3738)
GATE_T = 4860.0   # richest-visibility epoch of the gate scan (seed 0)


def test_elevation_geometry():
    gnd = VIS.ground_point_ecef_km(0.0, 0.0)
    # A satellite directly overhead has elevation ~90 degrees.
    import numpy as np
    overhead = gnd * (1 + 550.0 / 6371.0)
    assert VIS.elevation_deg(overhead, gnd) > 89.0
    # A satellite over the antipode is far below the horizon.
    assert VIS.elevation_deg(-overhead, gnd) < 0.0


def test_gate_monotone_and_compatible():
    inst = build_provider("mvp-gate", VIENNA, t=GATE_T, seed=0)
    costs = []
    for slo in (250.0, 500.0, 1000.0):
        plan = solve(inst, slo)
        assert plan is not None, f"gate instance infeasible at {slo} ms"
        assert plan.latency_ms <= slo + 1e-6
        hw = {a.component: a.hardware for a in plan.assignments if a.hardware}
        assert hw["llm"] != "cpu"          # compatibility respected
        costs.append(plan.cost)
    assert costs[0] >= costs[1] >= costs[2]   # relaxing SLO never costs more
    # Tight SLO must run the llm on the large accelerator (900 ms on the
    # small one, measured 2026-09-03); loose may use the small one.
    tight = solve(inst, 250.0)
    hw = {a.component: a.hardware for a in tight.assignments if a.hardware}
    assert hw["llm"] == "gpu_large"


def test_cross_shell_never_spans():
    inst = build_provider("mvp-gate", VIENNA, t=GATE_T, seed=0)
    plan = solve(inst, 1000.0)
    shells = {p[0] for p in plan.activated}
    assert len(shells) == 1   # portfolio, not spanning
