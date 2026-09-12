"""E0 model sanity tests. Lock the latency arithmetic and the placement logic.

These do not touch geometry (k is passed in), so they are fast and deterministic.
Detect latency comes from measured per-device profiles
(lab.profiles); the roofline test below now exercises the fallback path.
"""

import math

from lab import constants as C
from lab import e0 as E0
from lab import profiles as P


def test_compute_roofline_matches_hand_value():
    # Fallback-path arithmetic: iX10 effective throughput = 26e12 * 0.7 =
    # 18.2e12 op/s. 500 crops of YOLOv8x (257.8 GFLOPs/img) is 1.289e14 FLOPs.
    ix10 = C.device("iX10")
    ladder = {v.name: v for v in E0.load_ladder("yolo_coco")}
    flops = ladder["YOLOv8x"].gflops_per_image * 1e9 * 500
    got = E0.compute_ms(flops, ix10)
    want = flops / (26e12 * 0.7) * 1e3
    assert math.isclose(got, want, rel_tol=1e-9)
    assert 7000 < got < 7200  # ~7.08 s ideal; the measured Hailo-8 time is ~20 s


def test_transmission_10mb_over_100gbps():
    # 10 MB over 100 Gbps = 10e6*8/100e9 s = 0.8 ms.
    assert math.isclose(E0.transmission_ms(10e6, 100.0), 0.8, rel_tol=1e-9)


def test_detect_uses_measured_profiles():
    # Both placements' detect stage must resolve to measured numbers, and the
    # weak-node compute must match the published Hailo-8 batch-1 throughput.
    cfg = E0.load_e0_config()
    ladder = {v.name: v for v in E0.load_ladder(cfg.ladder_name)}
    a = E0.evaluate(cfg, "A", ladder["YOLOv8m"], k=7, t_hop_ms=4.53)
    b = E0.evaluate(cfg, "B", ladder["YOLOv8m"], k=7, t_hop_ms=4.53)
    assert a.detect_source == P.MEASURED
    assert b.detect_source == P.MEASURED
    # 500 crops at 66.9 FPS = 7473.8 ms, plus sub-ms screen/spread roofline.
    assert math.isclose(a.compute_ms, 500 * 1e3 / 66.9, rel_tol=1e-3)


def test_delivered_accuracy_is_device_aware():
    # The packed placement runs detect on the Hailo-8 and delivers quantized mAP.
    cfg = E0.load_e0_config()
    ladder = {v.name: v for v in E0.load_ladder(cfg.ladder_name)}
    a = E0.evaluate(cfg, "A", ladder["YOLOv8s"], k=7, t_hop_ms=4.53)
    b = E0.evaluate(cfg, "B", ladder["YOLOv8s"], k=7, t_hop_ms=4.53)
    assert a.map == 43.9   # Hailo quantized
    assert b.map == 44.9   # GPU float


def test_detour_is_never_cheaper_in_hops_than_packed():
    # For any variant, placement B's propagation must be >= A's (it detours).
    cfg = E0.load_e0_config()
    ladder = E0.load_ladder(cfg.ladder_name)
    for v in ladder:
        a = E0.evaluate(cfg, "A", v, k=7, t_hop_ms=4.53)
        b = E0.evaluate(cfg, "B", v, k=7, t_hop_ms=4.53)
        assert b.propagation_ms >= a.propagation_ms


def test_verdict_pass_at_measured_geometry():
    # With the substrate-measured k=7 and canonical T_hop, E0 must PASS and the
    # packed placement must be strictly capped below the detour placement.
    res = E0.run_e0(k=7, t_hop_ms=4.525527873388185)
    assert res.verdict == "PASS"
    assert res.gap_map >= E0.SEVERAL_MAP
    assert res.chosen_b.map > res.chosen_a.map
