"""HyperDrive placement policy adapted to Clockwork's snapshot model.

Upstream: polaris-slo-cloud/hyper-drive, revision recorded below, Apache-2.0.
Network rounding/normalization, averaged scores, stable ties, and vicinity
selection follow that implementation. This module changes the infrastructure,
resource schema, endpoint handling, and final SLO evaluation. It is NOT the
complete HyperDrive platform. See docs/hyperdrive-baseline.md and the pinned
upstream sources and license in tests/fixtures/hyperdrive_upstream/.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from lab.provider import INF_MS, ProviderInstance, SatId
from lab.service import (
    AOI, EGRESS, SAT_CAPACITY, Assignment, ProvisionPlan, candidate_sats,
    evaluate, load_chain, load_demands, load_io, load_profiles,
)
from substrate.dynamics import omega_earth

UPSTREAM_COMMIT = "94d753a4da15339268423e4141a2c086974ac507"
# Upstream scheduler/config_helper.py and HeatOptPlugin's nonbinding case.
VICINITY_RADIUS_KM = 2000.0
VICINITY_COUNT = 60
THERMAL_SCORE = 100


def network_scores(incoming_latencies: Sequence[Sequence[float]]) -> list[int]:
    """Upstream NetworkQosPlugin.score + normalize_scores, including rounding."""
    if not incoming_latencies:
        return []
    raw = [int(round(max([0.0, *values]), 0)) for values in incoming_latencies]
    lowest, highest = min(raw), max(raw)
    span = float(highest - lowest) or 1.0
    return [math.floor(((highest - value) / span) * 100) for value in raw]


def rank_candidates(candidates: Sequence[SatId], latencies: Sequence[float]):
    """Stable descending upstream scores, with the same constant heat score.

    Retaining int((network + heat)/2) matters. It can merge adjacent network
    scores into ties, so dropping the heat plugin is not equivalent.
    """
    if len(candidates) != len(latencies):
        raise ValueError("candidate and latency lengths differ")
    if any(not math.isfinite(d) or d < 0 or d >= INF_MS for d in latencies):
        raise ValueError("ranking requires reachable, finite latencies")
    scores = network_scores([[d] for d in latencies])
    ranked = [(sat, int((score + THERMAL_SCORE) / 2))
              for sat, score in zip(candidates, scores)]
    return sorted(ranked, key=lambda item: item[1], reverse=True)


def resources_fit(available: Mapping[str, float], required: Mapping[str, float]):
    """ResourcesFitPlugin's resource comparison, with Clockwork resource keys."""
    for key, quantity in required.items():
        available_quantity = available.get(key)
        if available_quantity is None or available_quantity < quantity:
            return False
    return True


def select_vicinity(candidates, locations, predecessor, radius_km, count):
    """Upstream's first count nodes inside a WGS84 surface radius, not k-nearest.

    Altitude is deliberately ignored as in SelectNodesInVicinityPlugin.
    Candidate order is preserved and capacity is checked only afterwards.
    """
    from geopy.distance import geodesic

    if not math.isfinite(radius_km) or radius_km < 0 or count < 0:
        raise ValueError("vicinity radius and count must be nonnegative")
    selected = []
    for sat in candidates:
        if len(selected) == count:
            break
        if geodesic(locations[predecessor], locations[sat]).km <= radius_km:
            selected.append(sat)
    return selected


def _locations(inst):
    rotation_deg = math.degrees(omega_earth() * inst.t)
    locations = {}
    for sat in inst.sat_hw:
        lat, lon = inst.shells[sat[0]].walker.subpoint(sat[1], sat[2], inst.t)
        locations[sat] = (lat, (lon - rotation_deg + 180) % 360 - 180)
    return locations


@dataclass
class Attempt:
    ingress: SatId
    status: str
    decisions: list[dict] = field(default_factory=list)
    plan: ProvisionPlan | None = None


@dataclass
class HyperDriveResult:
    """Keep complete SLO failures and partial attempts visible for auditing."""
    plan: ProvisionPlan | None
    attempts: list[Attempt]

    @property
    def best_complete(self):
        plans = [a.plan for a in self.attempts if a.plan is not None]
        return min(plans, key=lambda p: p.latency_ms) if plans else None


def plan_hyperdrive(
    inst: ProviderInstance, slo_ms: float, *, candidate_mode: str = "matched",
    vicinity_radius_km: float = VICINITY_RADIUS_KM,
    vicinity_count: int = VICINITY_COUNT,
    workflow: str = "mvp_fixed", profile_name: str = "workflow_mvp",
    profiles=None, io=None,
) -> HyperDriveResult:
    """Sequential placement for every visible ingress, then best return path.

    matched uses Castor's candidates. vicinity uses upstream's 2000 km / 60
    selector on the full satellite catalog. Both use sorted satellite IDs.
    Each incoming propagation limit equals the whole workflow SLO, a necessary
    but insufficient condition. No deadline partition, cost score, execution
    score, backtracking, or remaining-work bound is inserted into the policy.
    """
    if candidate_mode not in {"matched", "vicinity"}:
        raise ValueError(f"unknown candidate mode {candidate_mode!r}")
    if not math.isfinite(slo_ms) or slo_ms < 0:
        raise ValueError("SLO must be finite and nonnegative")
    if (not math.isfinite(vicinity_radius_km) or vicinity_radius_km < 0
            or not isinstance(vicinity_count, int) or vicinity_count < 0):
        raise ValueError("invalid vicinity radius or count")
    comps, edges = load_chain(workflow)
    if not comps:
        raise ValueError("a compound AI workflow must have components")
    profiles = load_profiles(profile_name) if profiles is None else profiles
    demand = load_demands(workflow)
    io = load_io(workflow) if io is None else io
    ingress, candidates = candidate_sats(inst, full=candidate_mode == "vicinity")
    locations = _locations(inst) if candidate_mode == "vicinity" else None
    attempts = []
    for source in ingress:
        attempt = Attempt(source, "no_eligible_candidate")
        attempts.append(attempt)
        placement = {AOI: (source, None)}
        usage = {}
        predecessor = source
        for comp in comps:
            selected = candidates if candidate_mode == "matched" else select_vicinity(
                candidates, locations, predecessor, vicinity_radius_km, vicinity_count)
            eligible, latencies = [], []
            for sat in selected:
                latency = profiles.get((comp, inst.sat_hw[sat]), math.inf)
                available = {"capacity": SAT_CAPACITY - usage.get(sat, 0.0),
                             "compatible": float(math.isfinite(latency))}
                if not resources_fit(available, {"capacity": demand[comp],
                                                 "compatible": 1.0}):
                    continue
                propagation = inst.sat_dist(predecessor, sat)
                # INF_MS is our orchestrator's unreachable sentinel, upstream uses -1.
                if (not math.isfinite(propagation) or propagation < 0
                        or propagation >= INF_MS or propagation > slo_ms):
                    continue
                eligible.append(sat)
                latencies.append(propagation)
            ranked = rank_candidates(eligible, latencies)
            attempt.decisions.append({
                "component": comp, "predecessor": predecessor,
                "candidates": list(selected), "eligible": eligible,
                "propagation_ms": latencies, "ranked": ranked,
                "chosen": ranked[0][0] if ranked else None,
            })
            if not ranked:
                break
            sat = ranked[0][0]
            placement[comp] = (sat, inst.sat_hw[sat])
            usage[sat] = usage.get(sat, 0.0) + demand[comp]
            predecessor = sat
        else:
            # Clockwork's output endpoint is selected after function placement.
            # Constant final serialization means propagation + access is sufficient.
            sinks = [s for s in ingress if inst.sat_dist(predecessor, s) < INF_MS]
            if not sinks:
                attempt.status = "no_egress"
                continue
            sink = min(sinks, key=lambda s: inst.sat_dist(predecessor, s)
                       + inst.sat_access[s])
            placement[EGRESS] = (sink, None)
            cost, latency, compute, network, access = evaluate(
                inst, comps, edges, profiles, placement, io)
            feasible = latency <= slo_ms
            attempt.plan = ProvisionPlan(
                assignments=[Assignment(v, placement[v][0], placement[v][1],
                                        profiles[(v, placement[v][1])] if v in comps else 0.0)
                             for v in [AOI, *comps, EGRESS]],
                activated=sorted({s[:2] for s, _ in placement.values()}),
                cost=cost, latency_ms=latency, compute_ms=compute,
                network_ms=network, access_ms=access, feasible=feasible,
            )
            attempt.status = "feasible" if feasible else "end_to_end_slo_failure"
    feasible = [a.plan for a in attempts if a.plan is not None and a.plan.feasible]
    # This is an endpoint wrapper, not a cost-aware repair of component decisions.
    best = min(feasible, key=lambda p: p.latency_ms) if feasible else None
    return HyperDriveResult(best, attempts)


def solve_hyperdrive(inst, slo_ms, **kwargs):
    """Provisioning-baseline interface. Use plan_hyperdrive for decision traces."""
    return plan_hyperdrive(inst, slo_ms, **kwargs).plan
