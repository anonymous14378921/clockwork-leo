"""Exhaustive enumeration over the restricted candidate set: the oracle.

For one instance, evaluate EVERY (configuration, placement) in the restricted
space and keep the full record list. Restriction (justified in prose, certified
by the screening bound): components upstream of the detector are pinned to the
sensor (the 150 MB tile must collapse before it travels), the detector and
verifier each choose among {sensor} + the k nearest capable nodes, and the
lightweight tail (spread/classify/alert/vlm) co-locates with the last cascade
stage. Records are evaluated once with SLO and budget unconstrained; feasibility
at any (SLO, budget) is re-derived by filtering, so one enumeration serves every
sweep point (EQ1 spread, EQ2 frontier, EQ3 oracle).
"""

from typing import Dict, List, Optional

from lab import configurations as CFG
from lab import placement as PL
from lab.instances import Instance
from lab.workflow import Workflow


def candidate_nodes(inst: Instance, k: int) -> List:
    return [inst.sensor] + [n for n, _ in inst.nearest_capable_nodes(k)]


def _upstream_of(wf: Workflow, target: str) -> set:
    rev: Dict[str, List[str]] = {}
    for u, v in wf.edges:
        rev.setdefault(v, []).append(u)
    seen, stack = set(), [target]
    while stack:
        for u in rev.get(stack.pop(), []):
            if u not in seen:
                seen.add(u)
                stack.append(u)
    return seen


def enumerate_records(wf: Workflow, inst: Instance, k_candidates: int = 3,
                      zero_propagation: bool = False) -> List[Dict]:
    """zero_propagation=True evaluates plans on a fictional seamless zero-hop
    substrate (identical hardware): the world the Atlas-like baseline believes
    in. Records keep the real detour fields so plans can be re-identified."""
    cas = wf.cascade
    cands = candidate_nodes(inst, k_candidates)
    upstream = _upstream_of(wf, cas.detect_stage)
    dist = (lambda a, b: 0.0) if zero_propagation else inst.dist_ms
    records: List[Dict] = []

    for cfg in CFG.config_space(cas):
        verify_opts = cands if cfg.has_verifier else [None]
        for det_node in cands:
            for ver_node in verify_opts:
                tail = ver_node if cfg.has_verifier else det_node
                assign = {}
                for cid in wf.components:
                    if cid in upstream:
                        assign[cid] = inst.sensor
                    elif cid == cas.detect_stage:
                        assign[cid] = det_node
                    elif cid == cas.verify_stage:
                        assign[cid] = ver_node if cfg.has_verifier else det_node
                    else:
                        assign[cid] = tail
                ev = PL.evaluate_plan(
                    wf, cfg, assign, inst.device_of, dist,
                    t_hop_ms=1.0,  # dist already returns ms
                    isl_gbps=inst.isl_gbps, slo_ms=float("inf"))
                records.append({
                    "detector": cfg.detector, "verifier": cfg.verifier,
                    "threshold": cfg.threshold, "phi": ev.forward_fraction,
                    "detect_node": str(det_node), "verify_node": str(ver_node),
                    "accuracy": ev.accuracy, "acc_source": ev.accuracy_source,
                    "tight_ms": ev.tight_latency_ms,
                    "slack_ms": ev.slack_latency_ms, "cost": ev.cost,
                    "detect_device": inst.device_of(det_node),
                    "verify_device": (inst.device_of(ver_node)
                                      if cfg.has_verifier else "none"),
                    "detect_detour_ms": inst.dist_ms(inst.sensor, det_node),
                    "verify_detour_ms": (inst.dist_ms(det_node, ver_node)
                                         if cfg.has_verifier else 0.0),
                    "packed": det_node == inst.sensor and
                              (not cfg.has_verifier or ver_node == inst.sensor),
                })
    return records


def best_feasible(records: List[Dict], slo_ms: float, slack_factor: float,
                  budget: float = float("inf"),
                  packed_only: bool = False) -> Optional[Dict]:
    """Accuracy-maximal record meeting per-path SLOs and budget; ties broken by
    lower cost, then lower latency. packed_only restricts to zero-detour plans
    (the topology-blind reference point for the spread)."""
    ok = [r for r in records
          if r["tight_ms"] <= slo_ms
          and r["slack_ms"] <= slo_ms * slack_factor
          and r["cost"] <= budget
          and (r["packed"] or not packed_only)]
    if not ok:
        return None
    return min(ok, key=lambda r: (-r["accuracy"], r["cost"], r["tight_ms"]))
