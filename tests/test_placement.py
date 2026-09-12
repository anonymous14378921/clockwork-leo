"""General plan evaluator tests.

The load-bearing check is the E0 cross-implementation equivalence: lab.e0 and
lab.placement were written independently, so agreement on E0's two hand-built
placements validates both (the anti-fabrication redundancy pattern). Then
structural invariants of the cascade machinery.

Accuracy note: evaluate_plan uses cascade-grid semantics (config-level accuracy,
GPU-measured), while lab.e0 applies the per-device quantized mAP. The E0
equivalence therefore asserts LATENCY and cost equality; the device-aware
accuracy delta (Hailo 43.9 vs float 44.9 for YOLOv8s) is a disclosed
sensitivity, not a bug.
"""

import math

from lab import configurations as CFG
from lab import e0 as E0
from lab import placement as PL
from lab.workflow import Workflow, Component, CascadeSpec, load_workflow


def _e0_workflow() -> Workflow:
    """The E0 pipeline expressed as a v2 workflow (verify contracts away)."""
    comps = {
        "ingest": Component("ingest", "io", None, 0.0, 150.0e6, 0, "tight"),
        "screen": Component("screen", "fixed", None, 5.0e9, 10.0e6, 0, "tight"),
        "detect": Component("detect", "ml", "cascade-detector", 0.0, 5.0e5, 500, "tight"),
        "verify": Component("verify", "ml", "cascade-verifier", 0.0, 5.0e5, 0, "tight"),
        "spread": Component("spread", "fixed", None, 2.0e9, 1.0e6, 0, "tight"),
        "alert": Component("alert", "io", None, 0.0, 10.0e3, 0, "tight"),
    }
    edges = (("ingest", "screen"), ("screen", "detect"), ("detect", "verify"),
             ("verify", "spread"), ("spread", "alert"))
    cas = CascadeSpec("detect", "verify", ("YOLOv8n", "YOLOv8s", "YOLOv8m"),
                      ("YOLOv8m", "YOLOv8l", "YOLOv8x", "none"),
                      (0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5), "yolo_coco")
    return Workflow("e0-equiv", comps, edges, cas, 1.0)


T_HOP = 4.525527873388185
K = 7


def _plan(wf, detector, strong_detect):
    """Assignment + metrics mirroring E0's A (packed) or B (detour)."""
    assign = {"ingest": "n0", "screen": "n1", "detect": "nD",
              "verify": "nD", "spread": "n2", "alert": "n3"}
    hop_table = {
        ("n0", "n1"): 1, ("n1", "nD"): 1 if not strong_detect else K,
        ("nD", "n2"): 1 if not strong_detect else K, ("n2", "n3"): 1,
    }

    def hops(u, v):
        return 0 if u == v else hop_table[(u, v)]

    def device_of(n):
        return "H100" if (n == "nD" and strong_detect) else "iX10"

    cfg = CFG.Config(detector, "none", 0.0)
    return PL.evaluate_plan(wf, cfg, assign, device_of, hops, T_HOP,
                            isl_gbps=100.0, slo_ms=2000.0)


def test_e0_cross_implementation_equivalence_placement_a():
    # E0 placement A (packed on iX10, YOLOv8s): totals must agree exactly.
    wf = _e0_workflow()
    e0cfg = E0.load_e0_config()
    ladder = {v.name: v for v in E0.load_ladder("yolo_coco")}
    ref = E0.evaluate(e0cfg, "A", ladder["YOLOv8s"], k=K, t_hop_ms=T_HOP)
    got = _plan(wf, "YOLOv8s", strong_detect=False)
    assert math.isclose(sum(got.component_compute_ms.values()),
                        ref.compute_ms, rel_tol=1e-9)
    assert math.isclose(got.tight_latency_ms, ref.total_ms, rel_tol=1e-9)


def test_e0_cross_implementation_equivalence_placement_b():
    # E0 placement B (detect detoured k hops to the H100, YOLOv8m as a probe).
    wf = _e0_workflow()
    e0cfg = E0.load_e0_config()
    ladder = {v.name: v for v in E0.load_ladder("yolo_coco")}
    ref = E0.evaluate(e0cfg, "B", ladder["YOLOv8m"], k=K, t_hop_ms=T_HOP)
    got = _plan(wf, "YOLOv8m", strong_detect=True)
    assert math.isclose(got.tight_latency_ms, ref.total_ms, rel_tol=1e-9)


def test_cost_counts_distinct_provisioned_nodes():
    wf = _e0_workflow()
    a = _plan(wf, "YOLOv8s", strong_detect=False)
    b = _plan(wf, "YOLOv8s", strong_detect=True)
    assert a.cost == 5 * 4.0            # five distinct iX10 nodes (verify co-located, contracted)
    assert b.cost == 4 * 4.0 + 50.0     # four iX10 + one H100
    assert not PL.evaluate_plan(wf, CFG.Config("YOLOv8s", "none", 0.0),
                                {"ingest": "n0", "screen": "n1", "detect": "nD",
                                 "verify": "nD", "spread": "n2", "alert": "n3"},
                                lambda n: "H100" if n == "nD" else "iX10",
                                lambda u, v: 0 if u == v else K,
                                T_HOP, 100.0, 1e9, budget=50.0).budget_feasible


def test_verifier_none_contracts_stage():
    wf = _e0_workflow()
    got = _plan(wf, "YOLOv8s", strong_detect=False)
    assert "verify" not in got.component_compute_ms
    assert got.forward_fraction == 0.0


def test_placeholder_grid_monotone_and_flagged():
    wf = load_workflow("wildfire")
    cas = wf.cascade
    accs, phis = [], []
    for t in cas.thresholds:
        cfg = CFG.Config("YOLOv8n", "YOLOv8x", t)
        a, a_src = CFG.accuracy(cfg, cas)
        p, p_src = CFG.forward_fraction(cfg, cas)
        assert a_src == CFG.PLACEHOLDER and p_src == CFG.PLACEHOLDER
        accs.append(a)
        phis.append(p)
    assert accs == sorted(accs)   # more forwarding never hurts (placeholder shape)
    assert phis == sorted(phis)


def test_wildfire_config_space_size():
    wf = load_workflow("wildfire")
    space = CFG.config_space(wf.cascade)
    # 3 detectors x (1 none + 3 verifiers x 7 thresholds) = 66
    assert len(space) == 66


def test_slack_path_gets_slack_slo():
    # The vlm report path may exceed the tight SLO by up to slack_factor.
    wf = load_workflow("wildfire")
    nodes = {c: "n" for c in wf.components}   # everything co-located
    got = PL.evaluate_plan(wf, CFG.Config("YOLOv8n", "none", 0.0), nodes,
                           lambda n: "H100", lambda u, v: 0, T_HOP, 100.0,
                           slo_ms=600.0)
    vlm_paths = [k for k in got.path_latency_ms if "vlm" in k]
    assert vlm_paths
    # vlm roofline on H100: 4e12/(989e12*0.7) s ~ 5.8 ms, well within slack.
    assert got.slo_feasible


def test_farther_verifier_costs_more_latency():
    wf = load_workflow("wildfire")
    cfg = CFG.Config("YOLOv8n", "YOLOv8x", 0.3)
    assign = {c: "near" for c in wf.components}

    def make(dist):
        a = dict(assign)
        a["verify"] = "far"
        return PL.evaluate_plan(
            wf, cfg, a, lambda n: "H100" if n == "far" else "iX10",
            lambda u, v: 0 if u == v else dist, T_HOP, 100.0, 1e9)

    assert make(12).tight_latency_ms > make(2).tight_latency_ms
