"""Hand-computed latency verification for the Clockwork service model.

Every term of the end-to-end latency of a hand-picked plan is recomputed
from first principles (positions, chord lengths, the speed of light,
payload sizes, profile values) and compared with the independent evaluator,
in BOTH source modes: the satellite-captured image (default) and the
ground-originated request. The return leg goes through an explicit egress
satellite whose plane is reserved, symmetric with the ingress. Forwarding
is pipelined: serialization once per transfer. No solver is involved.
"""

import math

import numpy as np
import pytest

from lab.provider import build_provider
from lab.service import (AOI, EGRESS, evaluate, load_chain,
                                load_demands, load_io, load_profiles)
from substrate import visibility as VIS

VIENNA = (48.2082, 16.3738)
GATE_T = 4860.0
C_KM_PER_MS = 2.998e5 / 1e3       # speed of light, km per millisecond


@pytest.fixture(scope="module")
def setting():
    inst = build_provider("mvp-gate", VIENNA, t=GATE_T, seed=0)
    comps, edges = load_chain()
    profiles = load_profiles()
    demands = load_demands()
    return inst, comps, edges, profiles, demands


def _ecef(inst, sat):
    shell = inst.shells[sat[0]]
    return VIS.sat_ecef_km(shell.walker, sat[1], sat[2], inst.t)


def _hand_plan(inst):
    """Detector and classifier colocated on a visible cpu ingress satellite
    (demand 0.75 <= 1), llm on an adjacent same-plane GPU satellite, the
    result downlinked from the ingress satellite again (visible, plane
    already reserved)."""
    for s0 in inst.sat_access:
        if inst.sat_hw[s0] != "cpu":
            continue
        n_slots = inst.shells[s0[0]].walker.sats_per_plane
        for ds in (-1, 1):
            sg = (s0[0], s0[1], (s0[2] + ds) % n_slots)
            if inst.sat_hw.get(sg, "cpu") != "cpu":
                return s0, sg
    raise AssertionError("no visible cpu satellite with a GPU neighbor")


def test_access_is_slant_range_over_c(setting):
    inst, *_ = setting
    gnd = VIS.ground_point_ecef_km(*VIENNA)
    for sat, access_ms in inst.sat_access.items():
        slant_km = float(np.linalg.norm(_ecef(inst, sat) - gnd))
        assert access_ms == pytest.approx(slant_km / C_KM_PER_MS, rel=1e-6)


def test_chain_ends_at_egress(setting):
    inst, comps, edges, *_ = setting
    assert edges[-1][1] == EGRESS
    assert [u for u, _, _ in edges] == [AOI] + comps


@pytest.mark.parametrize("source", ["satellite", "ground"])
def test_end_to_end_latency_by_hand(setting, source):
    inst, comps, edges, profiles, demands = setting
    io = dict(load_io(), source=source)
    s0, sg = _hand_plan(inst)
    placement = {AOI: (s0, None), "detector": (s0, "cpu"),
                 "classifier": (s0, "cpu"), "llm": (sg, inst.sat_hw[sg]),
                 EGRESS: (s0, None)}
    assert demands["detector"] + demands["classifier"] <= 1.0 + 1e-9

    gnd = VIS.ground_point_ecef_km(*VIENNA)
    access0 = float(np.linalg.norm(_ecef(inst, s0) - gnd)) / C_KM_PER_MS
    uplink_ser = 8.0 * 8e6 / (2.5e9) * 1e3            # 25.6 ms exactly
    hop_km = float(np.linalg.norm(_ecef(inst, s0) - _ecef(inst, sg)))
    hop_ms = hop_km / C_KM_PER_MS                     # adjacent: direct chord
    isl_ser = 0.04 * 8e6 / (100e9) * 1e3              # classifier -> llm
    down_ser = io["sink_mb"] * 8e6 / (1.0e9) * 1e3    # 0.08 ms
    execs = (profiles[("detector", "cpu")] + profiles[("classifier", "cpu")]
             + profiles[("llm", inst.sat_hw[sg])])
    # aoi->detector: nothing (satellite) or access + uplink ser (ground);
    # detector->classifier colocated: nothing; classifier->llm: one chord
    # plus ISL serialization; llm->egress: the same chord back plus the
    # downlink serialization; egress access from s0.
    if source == "ground":
        exp_access = access0 + access0
        exp_network = uplink_ser + hop_ms + isl_ser + hop_ms + down_ser
    else:
        exp_access = access0
        exp_network = hop_ms + isl_ser + hop_ms + down_ser
    expected = exp_access + exp_network + execs

    cost, lat, comp_ms, net_ms, acc_ms = evaluate(
        inst, comps, edges, profiles, placement, io)
    assert lat == pytest.approx(expected, abs=1e-6)
    assert acc_ms == pytest.approx(exp_access, abs=1e-6)
    assert comp_ms == pytest.approx(execs, abs=1e-6)
    assert net_ms == pytest.approx(exp_network, abs=1e-6)
    # Cost by hand: one plane, the cpu satellite billed once for two
    # components, the GPU neighbor; the egress adds no cost in-plane.
    assert cost == pytest.approx(
        inst.plane_cost + inst.hw_cost["cpu"]
        + inst.hw_cost[inst.sat_hw[sg]], abs=1e-9)
    assert math.isfinite(lat)


def test_egress_in_new_plane_costs_a_plane(setting):
    inst, comps, edges, profiles, demands = setting
    s0, sg = _hand_plan(inst)
    other = [s for s in inst.sat_access if (s[0], s[1]) != (s0[0], s0[1])]
    if not other:
        pytest.skip("only one visible plane at this instant")
    base = {AOI: (s0, None), "detector": (s0, "cpu"),
            "classifier": (s0, "cpu"), "llm": (sg, inst.sat_hw[sg])}
    c_in = evaluate(inst, comps, edges, profiles, {**base, EGRESS: (s0, None)})[0]
    c_out = evaluate(inst, comps, edges, profiles, {**base, EGRESS: (other[0], None)})[0]
    assert c_out == pytest.approx(c_in + inst.plane_cost, abs=1e-9)


def test_ground_mode_is_never_faster(setting):
    inst, comps, edges, profiles, demands = setting
    s0, sg = _hand_plan(inst)
    placement = {AOI: (s0, None), "detector": (s0, "cpu"),
                 "classifier": (s0, "cpu"), "llm": (sg, inst.sat_hw[sg]),
                 EGRESS: (s0, None)}
    sat = evaluate(inst, comps, edges, profiles, placement,
                   dict(load_io(), source="satellite"))[1]
    gnd = evaluate(inst, comps, edges, profiles, placement,
                   dict(load_io(), source="ground"))[1]
    assert gnd > sat
