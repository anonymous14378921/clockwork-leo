"""substrate — the Walker-topology substrate compiler for Ace.

Importable across experiments (not experiment-local): it turns constellation
parameters into satellite positions, a hardware-annotated ISL graph, and AoI
slices. Placed under src/ so the template's package discovery exports it as the
top-level import ``substrate`` on the editable install.

    from substrate.walker import Walker
    from substrate import graph, slices
    w = Walker.from_constellation("ref-star")
    g = graph.build_graph(w)
"""

from .walker import Walker

__all__ = ["Walker"]
