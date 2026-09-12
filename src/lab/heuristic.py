"""The greedy carrier-upgrade heuristic (algorithm Step 4a-4c, contribution C3).

Multi-start greedy: anchor the cheapest plan (smallest detector, no verifier)
at every candidate node where it is feasible, climb from each anchor by
repeatedly taking the best feasible upgrade move, and keep the best final
plan. Moves (informed by the EQ1 mechanisms):

  detector+   upgrade the detector one ladder rung in place
  verifier+   add the smallest verifier / upgrade it one rung
  threshold+  raise the forwarding threshold one tick (buys accuracy with phi)
  move-detect relocate the detector to another candidate node
  move-verify relocate the verifier to another candidate node

Selection rule: the feasible move with the largest accuracy gain, ties broken
by smaller cost increase then smaller latency. Lateral relocations (zero
accuracy gain but lower latency or cost) are taken only when no improving move
exists AND they strictly reduce tight latency or cost (they can unlock the next
upgrade). Terminates: accuracy strictly increases on upgrade moves and lateral
moves strictly reduce (latency, cost), both bounded.

Every candidate move is scored by the SAME evaluator as the oracle and the
baselines (lab.placement via the same record arithmetic), so EQ3's
heuristic-vs-oracle gap is pure search quality.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from lab import configurations as CFG
from lab import placement as PL
from lab import profiles as P
from lab.enumeration import candidate_nodes, _upstream_of
from lab.instances import Instance
from lab.workflow import Workflow


@dataclass
class HeuristicResult:
    plan: Optional[PL.PlanEval]
    detect_node: Optional[object]
    verify_node: Optional[object]
    evals: int          # evaluator calls consumed (the runtime currency)
    steps: List[str]    # move log, for the mechanism narrative
    # Accepted-state trajectory of the WINNING anchor's climb, for figures:
    # (move label, tight latency ms, delivered accuracy) per accepted state.
    trace: List[Tuple[str, float, float]] = None


def _evaluate(wf, inst, cfg, det_node, ver_node, upstream, slo_ms, budget):
    cas = wf.cascade
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
    return PL.evaluate_plan(wf, cfg, assign, inst.device_of, inst.dist_ms,
                            t_hop_ms=1.0, isl_gbps=inst.isl_gbps,
                            slo_ms=slo_ms, budget=budget)


def plan_greedy(wf: Workflow, inst: Instance, slo_ms: float,
                budget: float = float("inf"),
                k_candidates: int = 3) -> HeuristicResult:
    cas = wf.cascade
    ladder = [v.name for v in P.load_ladder(cas.ladder)]
    detectors = list(cas.detectors)
    verifiers = [v for v in cas.verifiers if v != "none"]
    thresholds = sorted(cas.thresholds)
    cands = candidate_nodes(inst, k_candidates)
    upstream = _upstream_of(wf, cas.detect_stage)
    evals = 0
    steps: List[str] = []

    def score(cfg, dn, vn):
        nonlocal evals
        evals += 1
        return _evaluate(wf, inst, cfg, dn, vn, upstream, slo_ms, budget)

    # 4a: MULTI-START anchors — the smallest-detector no-verifier plan at EVERY
    # candidate node where it is feasible. Single-start greedy has a systematic
    # trap: reaching "detector moved to the strong node, then upgraded" requires
    # a latency-increasing lateral move it never takes (observed 4.4-6.7 mAP
    # loss in the 0.85-1 s band). Climbing from each anchor and keeping the best
    # final plan removes the trap at linear extra cost in |candidates|.
    anchors = []
    for dn in cands:
        cfg = CFG.Config(detectors[0], "none", 0.0)
        ev = score(cfg, dn, None)
        if ev.feasible:
            anchors.append((cfg, dn, None, ev))
    if not anchors:
        return HeuristicResult(None, None, None, evals, steps + ["no anchor"])

    # Dual-policy multi-start: the eager policy offers every verifier variant
    # when adding one (closes the zero-gain wall at relaxed SLOs), the
    # conservative policy offers only the smallest (climbs the ladder rung by
    # rung, better under tight SLOs). Climbs cost milliseconds, so we run both
    # from every anchor and keep the best final plan.
    best_final = None
    for policy_vers in (verifiers, verifiers[:1]):
        for anchor in anchors:
            steps.append(f"anchor detector={detectors[0]} @ {anchor[1]}")
            trace = [("anchor", anchor[3].tight_latency_ms, anchor[3].accuracy)]
            final = _climb(anchor, score, cands, detectors, verifiers,
                           thresholds, steps, trace, add_vers=policy_vers)
            key = (-final[3].accuracy, final[3].cost,
                   final[3].tight_latency_ms)
            if best_final is None or key < best_final[0]:
                best_final = (key, final, trace)

    cfg, dn, vn, ev = best_final[1]
    return HeuristicResult(ev, dn, vn, evals, steps, trace=best_final[2])


def _climb(state, score, cands, detectors, verifiers, thresholds, steps,
           trace=None, add_vers=None):
    if add_vers is None:
        add_vers = verifiers
    # 4b/4c: greedy upgrades with lateral fallback. The visited set prevents
    # lateral-move cycles (latency-vs-cost oscillation); the iteration cap is a
    # backstop only.
    visited = {(state[0].key(), state[1], state[2])}
    for _ in range(200):
        cfg, dn, vn, cur = state
        moves: List[Tuple[str, CFG.Config, object, object]] = []
        di = detectors.index(cfg.detector)
        if di + 1 < len(detectors):
            moves.append(("detector+", CFG.Config(detectors[di + 1], cfg.verifier,
                                                  cfg.threshold), dn, vn))
        if not cfg.has_verifier:
            for ver in add_vers:
                for node in cands:
                    moves.append((f"verifier+ {ver}@{node}",
                                  CFG.Config(cfg.detector, ver,
                                             thresholds[0]), dn, node))
        else:
            vi = verifiers.index(cfg.verifier)
            if vi + 1 < len(verifiers):
                moves.append(("verifier+", CFG.Config(cfg.detector,
                                                      verifiers[vi + 1],
                                                      cfg.threshold), dn, vn))
            ti = thresholds.index(cfg.threshold)
            if ti + 1 < len(thresholds):
                moves.append(("threshold+", CFG.Config(cfg.detector, cfg.verifier,
                                                       thresholds[ti + 1]), dn, vn))
        for node in cands:
            if node != dn:
                moves.append((f"move-detect@{node}", cfg, node, vn))
            if cfg.has_verifier and node != vn:
                moves.append((f"move-verify@{node}", cfg, dn, node))

        best_up, best_lat = None, None
        for name, mcfg, mdn, mvn in moves:
            if (mcfg.key(), mdn, mvn) in visited:
                continue
            ev = score(mcfg, mdn, mvn)
            if not ev.feasible:
                continue
            cand = (name, mcfg, mdn, mvn, ev)
            if ev.accuracy > cur.accuracy + 1e-12:
                key = (-ev.accuracy, ev.cost - cur.cost, ev.tight_latency_ms)
                if best_up is None or key < best_up[0]:
                    best_up = (key, cand)
            elif (ev.accuracy >= cur.accuracy - 1e-12
                  and (ev.tight_latency_ms < cur.tight_latency_ms - 1e-9
                       or ev.cost < cur.cost - 1e-12)):
                key = (ev.tight_latency_ms, ev.cost)
                if best_lat is None or key < best_lat[0]:
                    best_lat = (key, cand)

        chosen = best_up or best_lat
        if chosen is None:
            break
        name, mcfg, mdn, mvn, ev = chosen[1]
        steps.append(name)
        if trace is not None:
            trace.append((name, ev.tight_latency_ms, ev.accuracy))
        visited.add((mcfg.key(), mdn, mvn))
        state = (mcfg, mdn, mvn, ev)

    return state
