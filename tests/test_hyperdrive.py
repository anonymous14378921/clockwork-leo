"""Policy parity against unmodified upstream sources and adapter semantics."""
import ast
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as NS
from typing import cast

import networkx as nx
import pytest

from lab.hyperdrive import (
    UPSTREAM_COMMIT, network_scores, plan_hyperdrive, rank_candidates,
    resources_fit, select_vicinity,
)
from lab.provider import ProviderInstance
from lab.provision_milp import load_demands

FIXTURES = Path(__file__).parent / "fixtures" / "hyperdrive_upstream"


@dataclass
class EligibleNode:
    node: object
    score: int = 0


class Plugin:
    def normalize_scores(self, task, nodes, ctx):
        pass


def upstream(filename):
    """Execute upstream class bodies unchanged with lightweight interface types.

    Imports are replaced to avoid importing StarryNet and the entire platform.
    This is test-only. The original source files and hashes are retained.
    """
    tree = ast.parse((FIXTURES / filename).read_text())
    tree.body = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)] + [
        node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    namespace = dict(math=math, dataclass=dataclass, EligibleNode=EligibleNode,
                     FilterPlugin=type("FilterPlugin", (), {}),
                     ScorePlugin=Plugin, SelectCandidateNodesPlugin=Plugin, CommitPlugin=Plugin,
                     Random=random.Random, cast=cast)
    if filename == "select_nodes_in_vicinity.py":
        from geopy import distance
        namespace.update(distance=distance, SatelliteNode=SatelliteNode,
                         TerrestrialNode=type("TerrestrialNode", (), {}),
                         Location=NS)
    exec(compile(ast.fix_missing_locations(tree), str(FIXTURES / filename), "exec"), namespace)
    return namespace


def network_context(latencies):
    def incoming(task):
        return [(NS(max_latency_msec=task.limit), i) for i in range(len(latencies[0]))]
    return NS(workflow=NS(all_incoming_slos=incoming),
              orchestrator=NS(get_latency=lambda source, node: latencies[node][source]))


def test_pinned_upstream_sources():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest["commit"] == UPSTREAM_COMMIT
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("latencies", [
    [[0.0], [0.49], [0.5], [0.51], [1.5], [2.5]],
    [[10.4], [10.1], [10.0]],
    [[5.0, 2.0], [0.0, 8.0], [4.0, 3.0]],
])
def test_network_scoring_matches_upstream(latencies):
    plugin = upstream("network_qos.py")["NetworkQosPlugin"]()
    ctx, task = network_context(latencies), NS(limit=100.0)
    nodes = [EligibleNode(i, plugin.score(i, task, ctx)) for i in range(len(latencies))]
    plugin.normalize_scores(task, nodes, ctx)
    assert network_scores(latencies) == [n.score for n in nodes]


def test_ranking_matches_actual_upstream_scheduler():
    network = upstream("network_qos.py")["NetworkQosPlugin"]()
    scheduler_type = upstream("scheduler.py")["Scheduler"]

    class ConstantHeat(Plugin):
        def score(self, node, task, ctx):
            return 100

    scheduler = object.__new__(scheduler_type)
    scheduler._Scheduler__score_plugins = [network, ConstantHeat()]
    rng = random.Random(20260909)
    for _ in range(100):
        latencies = [rng.uniform(0, 150) for _ in range(40)]
        ctx, task = network_context([[d] for d in latencies]), NS(limit=200.0)
        nodes = [EligibleNode(i) for i in range(len(latencies))]
        scheduler._Scheduler__score_nodes(task, ctx, nodes)
        assert rank_candidates(list(range(len(latencies))), latencies) == [
            (n.node, n.score) for n in nodes]


def test_rounding_and_score_averaging_ties_are_preserved():
    # Choosing minimum raw latency here would silently change HyperDrive.
    assert rank_candidates(["first", "closer"], [10.4, 10.1])[0][0] == "first"
    # Network scores 49 and 48 become the same averaged score 74.
    ranked = rank_candidates(["worse", "better", "min", "max"], [52, 51, 0, 100])
    assert ranked.index(("worse", 74)) < ranked.index(("better", 74))


@pytest.mark.parametrize("available,required", [
    ({"capacity": .5, "compatible": 1}, {"capacity": .5, "compatible": 1}),
    ({"capacity": .4999, "compatible": 1}, {"capacity": .5, "compatible": 1}),
    ({"capacity": 1, "compatible": 0}, {"capacity": .5, "compatible": 1}),
    ({"capacity": 1}, {"capacity": .5, "compatible": 1}),
])
def test_resource_mapping_matches_upstream(available, required):
    plugin = upstream("resources_fit.py")["ResourcesFitPlugin"]()
    task = NS(cpu_architectures=[], req_resources=required)
    node = NS(resources=available)
    assert resources_fit(available, required) == plugin.filter(node, task, None)


class SatelliteNode:
    def __init__(self, name, location):
        self.name, self.location = name, location


def test_vicinity_matches_upstream_order_radius_and_cap():
    nodes = [SatelliteNode("source", (48, 16, 500)),
             SatelliteNode("far", (48, 20, 500)),
             SatelliteNode("near", (48, 16.1, 900)),
             SatelliteNode("outside", (-48, -160, 500))]
    task, predecessor = object(), object()
    ctx = NS(workflow=NS(get_predecessors=lambda task: [predecessor],
                        scheduled_tasks={predecessor: nodes[0]}),
             orchestrator=NS(get_satellite_position=lambda node: node.location))
    cls = upstream("select_nodes_in_vicinity.py")["SelectNodesInVicinityPlugin"]
    selector = cls(500, 200, 2000, 0, 0, 2)
    all_nodes = NS(ground_stations=[], cloud_nodes=[], edge_nodes=[], satellites=nodes)
    expected = list(selector.select_candidates(task, all_nodes, ctx))
    locations = {node.name: node.location[:2] for node in nodes}
    assert select_vicinity(list(locations), locations, "source", 2000, 2) == expected
    assert expected == ["source", "far"]  # not the two nearest nodes


def tiny_instance():
    sats = [("shell", i, 0) for i in range(3)]
    graph = nx.Graph()
    graph.add_nodes_from(sats)
    graph.add_edge(sats[0], sats[1], weight_ms=1)
    graph.add_edge(sats[1], sats[2], weight_ms=2)
    inst = ProviderInstance("test", {}, {}, {}, {"cpu": 1, "gpu": 10}, 5,
                            100, 1, 1, 0, (48, 16), net=graph,
                            sat_hw={sats[0]: "cpu", sats[1]: "gpu", sats[2]: "gpu"},
                            sat_access={sats[0]: 1})
    profiles = {("detector", "cpu"): 2, ("classifier", "cpu"): 2,
                ("detector", "gpu"): 1, ("classifier", "gpu"): 1,
                ("llm", "gpu"): 10}
    return inst, profiles


def test_complete_plan_capacity_cost_and_postcheck():
    inst, profiles = tiny_instance()
    result = plan_hyperdrive(inst, 50, profiles=profiles)
    plan = result.plan
    assert plan is not None
    assert plan.compute_ms == 14
    assert plan.cost == 21  # two planes + CPU once + GPU once
    assert plan.activated == [("shell", 0), ("shell", 1)]
    usage = {}
    for a in plan.assignments[1:-1]:
        usage[a.sat] = usage.get(a.sat, 0) + load_demands()[a.component]
    assert max(usage.values()) <= 1
    # Same component choices despite a global deadline they cannot meet.
    failed = plan_hyperdrive(inst, 5, profiles=profiles)
    assert failed.plan is None
    assert failed.best_complete is not None
    assert not failed.best_complete.feasible
    assert failed.attempts[0].status == "end_to_end_slo_failure"
    assert [d["chosen"] for d in failed.attempts[0].decisions] == [
        d["chosen"] for d in result.attempts[0].decisions]


def test_no_cost_based_tie_break_or_placement_repair():
    inst, profiles = tiny_instance()
    original = plan_hyperdrive(inst, 50, profiles=profiles)
    inst.hw_cost = {"cpu": 1000, "gpu": 1}
    inst.plane_cost = 1000
    changed = plan_hyperdrive(inst, 50, profiles=profiles)
    assert [a.sat for a in original.plan.assignments] == [a.sat for a in changed.plan.assignments]


def test_no_access_incompatible_hardware_and_disconnected_shells():
    inst, profiles = tiny_instance()
    del profiles[("llm", "gpu")]
    assert plan_hyperdrive(inst, 50, profiles=profiles).best_complete is None
    profiles[("llm", "gpu")] = 10
    inst.net.remove_edge(("shell", 0, 0), ("shell", 1, 0))
    inst._sat_dist_cache.clear()
    assert plan_hyperdrive(inst, 50, profiles=profiles).best_complete is None
    inst.sat_access = {}
    assert plan_hyperdrive(inst, 50, profiles=profiles).attempts == []


def test_capacity_is_reserved_across_components_and_attempts_are_independent():
    inst, profiles = tiny_instance()
    # All components favor the source GPU. Detector + classifier leave no
    # room for the LLM, which must run elsewhere.
    inst.sat_hw[("shell", 0, 0)] = "gpu"
    inst.sat_access[("shell", 2, 0)] = 2
    result = plan_hyperdrive(inst, 50, profiles=profiles)
    assert len(result.attempts) == 2
    for attempt in result.attempts:
        assert attempt.status == "feasible"
        choices = [d["chosen"] for d in attempt.decisions]
        assert choices[0] == choices[1]
        assert choices[2] != choices[0]
    assert result.plan.latency_ms == min(a.plan.latency_ms for a in result.attempts)


def test_component_decisions_match_upstream_filter_score_commit_pipeline():
    """Run the original pipeline methods for the adapter's mapped inputs."""
    inst, profiles = tiny_instance()
    result = plan_hyperdrive(inst, 50, profiles=profiles)
    network = upstream("network_qos.py")["NetworkQosPlugin"]()
    resource = upstream("resources_fit.py")["ResourcesFitPlugin"]()
    commit = upstream("multi_commit.py")["MultiCommitPlugin"]()
    scheduler_type = upstream("scheduler.py")["Scheduler"]

    class ConstantHeat(Plugin):
        def score(self, node, task, ctx):
            return 100

    scheduler = object.__new__(scheduler_type)
    scheduler._Scheduler__filter_plugins = [resource, network]
    scheduler._Scheduler__score_plugins = [network, ConstantHeat()]
    usage = {}
    for decision in result.attempts[0].decisions:
        comp, predecessor = decision["component"], decision["predecessor"]
        nodes = {sat: NS(sat=sat, resources={
            "capacity": 1 - usage.get(sat, 0),
            "compatible": float(math.isfinite(profiles.get((comp, inst.sat_hw[sat]), math.inf))),
        }) for sat in decision["candidates"]}
        task = NS(cpu_architectures=[], req_resources={
            "capacity": load_demands()[comp], "compatible": 1})
        ctx = NS(workflow=NS(all_incoming_slos=lambda _: [(NS(max_latency_msec=50), predecessor)]),
                 orchestrator=NS(get_latency=lambda source, node: inst.sat_dist(source, node.sat),
                                 assign_task=lambda task, node: True))
        eligible = scheduler._Scheduler__filter_nodes(task, ctx, nodes, [])
        scheduler._Scheduler__score_nodes(task, ctx, eligible)
        chosen = commit.commit(task, eligible, ctx).node.sat
        assert chosen == decision["chosen"]
        assert [(e.node.sat, e.score) for e in eligible] == decision["ranked"]
        usage[chosen] = usage.get(chosen, 0) + load_demands()[comp]
