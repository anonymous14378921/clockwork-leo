"""Exact MILP planner (contribution C3's exact half, PuLP + CBC).

Structure: configurations are enumerated in descending accuracy order (the
config space is small and finite, Compass-style); for each configuration one
small binary program places the detector and verifier over the candidate set,
minimizing provisioning cost subject to the per-path SLO and the budget. The
first accuracy level with a feasible placement is optimal by construction
(accuracy depends only on the configuration), and within that level the MILP
returns the cheapest placement, matching the oracle's tie-breaking.

Variables per configuration: d_n (detector at node n), v_m (verifier at m),
w_nm = d_n AND v_m (standard linearization, needed because the detect->verify
edge cost depends on the node PAIR), u_n (node provisioned). All latency
coefficients are computed by the same profile arithmetic as lab.placement, and
the returned plan is RE-SCORED through lab.placement.evaluate_plan, so the
MILP cannot disagree with the evaluator without failing loudly (asserted).

Scaling role: on the k=3 candidate set enumeration is already exact and this
solver is its cross-check (tested equal); on wide candidate sets (every
capable node plus the slice) enumeration is quadratic in candidates while the
MILP stays one CBC solve per accuracy level.
"""

from typing import Dict, List, Optional, Tuple

import pulp

from lab import configurations as CFG
from lab import constants as C
from lab import placement as PL
from lab import profiles as P
from lab.enumeration import candidate_nodes, _upstream_of
from lab.heuristic import _evaluate
from lab.instances import Instance
from lab.workflow import Workflow


def _latency_pieces(wf: Workflow, inst: Instance, cfg: CFG.Config,
                    cands: List) -> Tuple[Dict, Dict, Dict, float, float]:
    """Decompose tight-path latency: base (placement-independent) + L1[dn]
    (detector terms) + L2[vn] (verifier compute) + L3[(dn,vn)] (pair edge).
    Computed from the same profiles/constants as the evaluator."""
    cas = wf.cascade
    ladder = {v.name: v for v in P.load_ladder(cas.ladder)}
    phi, _ = CFG.forward_fraction(cfg, cas)
    det_comp = wf.components[cas.detect_stage]
    sensor = inst.sensor

    def trans(nbytes):
        return nbytes * 8.0 / (inst.isl_gbps * 1e9) * 1e3

    # Base: upstream fixed compute at the sensor + upstream edges + tail
    # compute/edges that do not depend on dn/vn (tail co-located with the last
    # cascade stage). We fold everything placement-independent into base by
    # evaluating one reference plan and subtracting its variable parts, which
    # keeps this decomposition honest against the evaluator (asserted below).
    L1, L2, L3 = {}, {}, {}
    for dn in cands:
        dev = C.device(inst.device_of(dn))
        det_ms, _ = P.batch_ms(ladder[cfg.detector], inst.device_of(dn), dev,
                               det_comp.crops_per_tile)
        L1[dn] = det_ms + inst.dist_ms(sensor, dn)  # compute + screen->detect hop
        if cfg.has_verifier:
            for vn in cands:
                L3[(dn, vn)] = (phi * trans(det_comp.out_bytes)
                                + inst.dist_ms(dn, vn))
    if cfg.has_verifier:
        for vn in cands:
            dev = C.device(inst.device_of(vn))
            per_img, _ = P.exec_ms_per_image(ladder[cfg.verifier],
                                             inst.device_of(vn), dev)
            L2[vn] = phi * det_comp.crops_per_tile * per_img
    # Placement-independent remainder from a reference evaluation.
    ref_dn, ref_vn = cands[0], (cands[0] if cfg.has_verifier else None)
    upstream = _upstream_of(wf, cas.detect_stage)
    ref = _evaluate(wf, inst, cfg, ref_dn, ref_vn, upstream, float("inf"),
                    float("inf"))
    var = L1[ref_dn] + (L2[ref_vn] + L3[(ref_dn, ref_vn)]
                        if cfg.has_verifier else 0.0)
    base = ref.tight_latency_ms - var
    slack_base = ref.slack_latency_ms - var if ref.slack_latency_ms else 0.0
    return L1, L2, L3, base, slack_base


def plan_milp(wf: Workflow, inst: Instance, slo_ms: float,
              budget: float = float("inf"),
              k_candidates: int = 3) -> Optional[PL.PlanEval]:
    cas = wf.cascade
    cands = candidate_nodes(inst, k_candidates)
    upstream = _upstream_of(wf, cas.detect_stage)
    slack_limit = slo_ms * wf.slo_slack_factor

    configs = CFG.config_space(cas)
    configs.sort(key=lambda c: (-CFG.accuracy(c, cas)[0]))

    best: Optional[Tuple[float, float, PL.PlanEval]] = None
    for cfg in configs:
        acc = CFG.accuracy(cfg, cas)[0]
        if best is not None and acc < best[0] - 1e-12:
            break  # strictly worse accuracy than an already-feasible level
        L1, L2, L3, base, slack_base = _latency_pieces(wf, inst, cfg, cands)

        prob = pulp.LpProblem("ace_place", pulp.LpMinimize)
        d = {n: pulp.LpVariable(f"d_{i}", cat="Binary")
             for i, n in enumerate(cands)}
        prob += pulp.lpSum(d.values()) == 1
        u = {n: pulp.LpVariable(f"u_{i}", cat="Binary")
             for i, n in enumerate(cands)}
        lat = base + pulp.lpSum(d[n] * L1[n] for n in cands)
        if cfg.has_verifier:
            v = {n: pulp.LpVariable(f"v_{i}", cat="Binary")
                 for i, n in enumerate(cands)}
            w = {(n, m): pulp.LpVariable(f"w_{i}_{j}", cat="Binary")
                 for i, n in enumerate(cands) for j, m in enumerate(cands)}
            prob += pulp.lpSum(v.values()) == 1
            for n in cands:
                for m in cands:
                    prob += w[(n, m)] >= d[n] + v[m] - 1
                    prob += w[(n, m)] <= d[n]
                    prob += w[(n, m)] <= v[m]
            lat = (lat + pulp.lpSum(v[m] * L2[m] for m in cands)
                   + pulp.lpSum(w[(n, m)] * L3[(n, m)]
                                for n in cands for m in cands))
            for m in cands:
                prob += u[m] >= v[m]
        prob += lat <= slo_ms
        if slack_base:
            prob += lat + (slack_base - base) <= slack_limit
        for n in cands:
            prob += u[n] >= d[n]
        sensor_price = C.price(inst.device_of(inst.sensor))
        cost = sensor_price + pulp.lpSum(
            u[n] * C.price(inst.device_of(n)) for n in cands if n != inst.sensor)
        # The sensor is always provisioned; a cascade stage placed ON the
        # sensor adds no new node, handled by excluding it from the sum.
        if budget != float("inf"):
            prob += cost <= budget
        prob += cost
        prob.solve(pulp.PULP_CBC_CMD(msg=0))
        if pulp.LpStatus[prob.status] != "Optimal":
            continue

        dn = next(n for n in cands if d[n].value() > 0.5)
        vn = (next(n for n in cands if v[n].value() > 0.5)
              if cfg.has_verifier else None)
        ev = _evaluate(wf, inst, cfg, dn, vn, upstream, slo_ms, budget)
        assert ev.feasible, "MILP-feasible plan must re-score feasible"
        if best is None or (ev.accuracy, -ev.cost) > (best[0], -best[1]):
            best = (ev.accuracy, ev.cost, ev)
    return best[2] if best else None
