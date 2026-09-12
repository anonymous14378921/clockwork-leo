"""Load compound-AI workflow DAG specs from workflows/*.yaml.

A workflow is a DAG of components (io / fixed / ml) with one embedded detection
cascade: a cascade-detector stage and a cascade-verifier stage
whose configuration space lives in lab.configurations. verifier=none contracts
the verify stage out of the DAG (its edges are rerouted around it), so the
single-detector workflow is the degenerate special case.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import yaml

from lab import constants as C
from lab.harness.runner import repo_root


@dataclass(frozen=True)
class Component:
    id: str
    kind: str                    # io | fixed | ml
    role: Optional[str]          # cascade-detector | cascade-verifier | None
    flops: float                 # fixed components only (0 otherwise)
    out_bytes: float
    crops_per_tile: int          # cascade-detector only (0 otherwise)
    path_class: str              # "tight" (default) or "slack"


@dataclass(frozen=True)
class CascadeSpec:
    detect_stage: str
    verify_stage: str
    detectors: Tuple[str, ...]
    verifiers: Tuple[str, ...]   # includes "none"
    thresholds: Tuple[float, ...]
    ladder: str


@dataclass(frozen=True)
class Workflow:
    name: str
    components: Dict[str, Component]
    edges: Tuple[Tuple[str, str], ...]
    cascade: CascadeSpec
    slo_slack_factor: float

    def contracted_edges(self, drop: Optional[str]) -> Tuple[Tuple[str, str], ...]:
        """Edges with component `drop` contracted out (predecessors rewired to
        successors). Used when verifier=none. Returns edges unchanged if drop
        is None."""
        if drop is None:
            return self.edges
        preds = [u for u, v in self.edges if v == drop]
        succs = [v for u, v in self.edges if u == drop]
        kept = [(u, v) for u, v in self.edges if drop not in (u, v)]
        kept += [(u, v) for u in preds for v in succs]
        return tuple(kept)

    def paths(self, edges: Tuple[Tuple[str, str], ...]) -> List[List[str]]:
        """All root-to-sink paths of the (possibly contracted) DAG."""
        targets = {u for u, _ in edges}
        sources = {v for _, v in edges}
        roots = sorted(targets - sources)
        sinks = sorted(sources - targets)
        out: Dict[str, List[str]] = {}
        for u, v in edges:
            out.setdefault(u, []).append(v)
        result: List[List[str]] = []

        def walk(node: str, acc: List[str]) -> None:
            if node in sinks:
                result.append(acc)  # acc already ends with node
                return
            for nxt in sorted(out.get(node, [])):
                walk(nxt, acc + [nxt])

        for r in roots:
            walk(r, [r])
        return result


def load_workflow(name: str) -> Workflow:
    path = repo_root() / "workflows" / f"{name}.yaml"
    with path.open("r") as f:
        spec = yaml.safe_load(f)
    comps = {}
    for c in spec["components"]:
        comps[c["id"]] = Component(
            id=c["id"],
            kind=c["kind"],
            role=c.get("role"),
            flops=C.to_float(c.get("flops", 0.0)),
            out_bytes=C.to_float(c.get("out_bytes", 0.0)),
            crops_per_tile=int(c.get("crops_per_tile", 0)),
            path_class=c.get("path_class", "tight"),
        )
    cas = spec["cascade"]
    cascade = CascadeSpec(
        detect_stage=cas["detect_stage"],
        verify_stage=cas["verify_stage"],
        detectors=tuple(cas["detectors"]),
        verifiers=tuple(str(v) for v in cas["verifiers"]),
        thresholds=tuple(C.to_float(t) for t in cas["thresholds"]),
        ladder=cas["ladder"],
    )
    return Workflow(
        name=spec["name"],
        components=comps,
        edges=tuple((u, v) for u, v in spec["edges"]),
        cascade=cascade,
        slo_slack_factor=C.to_float(spec.get("slo_slack_factor", 1.0)),
    )
