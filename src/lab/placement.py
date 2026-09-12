"""The general plan evaluator: score one (configuration, placement) pair.

The atom of the evaluation. Every downstream module (baselines, exhaustive
enumeration, heuristic) calls evaluate_plan() so that all
algorithms are judged by the identical arithmetic. A plan is a cascade
configuration c = (detector, verifier, threshold) plus an assignment of every
workflow component to a substrate node.

Latency model per root-to-sink path: sum of component execution (measured
per-device profiles via lab.profiles, roofline fallback) plus per-edge
propagation (hops * T_hop) and transmission (bytes / ISL rate). The
detect->verify edge and the verifier's compute scale with the forward fraction
phi(detector, threshold). verifier=none contracts the verify stage out of the
DAG. Paths through a slack-class component (the vlm report branch) are checked
against slo * slack_factor; all other paths against slo (per-path SLOs).

Cost: sum of provisioning prices over DISTINCT nodes hosting components
(relays route traffic but are not provisioned). Accuracy: measured cascade grid
via lab.configurations, with the source flag propagated so placeholder-derived
results are unmistakable.

Geometry-free: the caller supplies hops(u, v) (from substrate.graph shortest
paths in experiments, or a synthetic metric in tests) and device_of(node).
"""

from dataclasses import dataclass
from typing import Callable, Dict, Hashable, List, Tuple

from lab import configurations as CFG
from lab import constants as C
from lab import profiles as P
from lab.workflow import Workflow

Node = Hashable


@dataclass(frozen=True)
class PlanEval:
    config: CFG.Config
    accuracy: float
    accuracy_source: str          # configurations.MEASURED_GRID or PLACEHOLDER
    forward_fraction: float
    phi_source: str
    component_compute_ms: Dict[str, float]
    detect_source: str            # profiles.MEASURED or ROOFLINE (detector stage)
    path_latency_ms: Dict[str, float]   # "a->b->c" -> ms
    tight_latency_ms: float       # max latency over tight (non-slack) paths
    slack_latency_ms: float       # max latency over slack paths (0 if none)
    cost: float
    slo_feasible: bool
    budget_feasible: bool

    @property
    def feasible(self) -> bool:
        return self.slo_feasible and self.budget_feasible


def evaluate_plan(
    wf: Workflow,
    cfg: CFG.Config,
    assignment: Dict[str, Node],
    device_of: Callable[[Node], str],
    hops: Callable[[Node, Node], int],
    t_hop_ms: float,
    isl_gbps: float,
    slo_ms: float,
    budget: float = float("inf"),
) -> PlanEval:
    cas = wf.cascade
    ladder = {v.name: v for v in P.load_ladder(cas.ladder)}
    phi, phi_src = CFG.forward_fraction(cfg, cas)
    acc, acc_src = CFG.accuracy(cfg, cas)

    drop = None if cfg.has_verifier else cas.verify_stage
    edges = wf.contracted_edges(drop)
    active = {c for e in edges for c in e}

    detect_src = P.ROOFLINE
    comp_ms: Dict[str, float] = {}
    for cid in active:
        comp = wf.components[cid]
        dev_name = device_of(assignment[cid])
        dev = C.device(dev_name)
        if comp.kind == "io":
            comp_ms[cid] = 0.0
        elif comp.kind == "fixed":
            comp_ms[cid] = P.roofline_ms(comp.flops, dev)
        elif comp.role == "cascade-detector":
            ms, detect_src = P.batch_ms(ladder[cfg.detector], dev_name, dev,
                                        comp.crops_per_tile)
            comp_ms[cid] = ms
        elif comp.role == "cascade-verifier":
            crops = wf.components[cas.detect_stage].crops_per_tile
            per_img, _ = P.exec_ms_per_image(ladder[cfg.verifier], dev_name, dev)
            comp_ms[cid] = phi * crops * per_img
        else:
            raise ValueError(f"ml component {cid} without a cascade role")

    def edge_bytes(u: str) -> float:
        b = wf.components[u].out_bytes
        if u == cas.detect_stage and cfg.has_verifier:
            return phi * b  # only forwarded crops travel to the verifier
        return b

    def edge_ms(u: str, v: str) -> float:
        h = hops(assignment[u], assignment[v])
        trans = edge_bytes(u) * 8.0 / (isl_gbps * 1e9) * 1e3
        return h * t_hop_ms + trans

    path_ms: Dict[str, float] = {}
    tight = 0.0
    slackmax = 0.0
    slo_ok = True
    for path in wf.paths(edges):
        lat = sum(comp_ms[c] for c in path)
        lat += sum(edge_ms(u, v) for u, v in zip(path, path[1:]))
        path_ms["->".join(path)] = lat
        slack = any(wf.components[c].path_class == "slack" for c in path)
        limit = slo_ms * (wf.slo_slack_factor if slack else 1.0)
        if lat > limit:
            slo_ok = False
        if slack:
            slackmax = max(slackmax, lat)
        else:
            tight = max(tight, lat)

    used = {assignment[c] for c in active}
    cost = sum(C.price(device_of(n)) for n in used)

    return PlanEval(
        config=cfg, accuracy=acc, accuracy_source=acc_src,
        forward_fraction=phi, phi_source=phi_src,
        component_compute_ms=comp_ms, detect_source=detect_src,
        path_latency_ms=path_ms, tight_latency_ms=tight,
        slack_latency_ms=slackmax, cost=cost,
        slo_feasible=slo_ok, budget_feasible=cost <= budget,
    )
