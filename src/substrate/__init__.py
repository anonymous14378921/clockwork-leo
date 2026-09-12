"""Orbital substrate compiler.

Turns constellation parameters into satellite positions, a hardware-annotated
ISL graph, and AoI slices.

    from substrate.walker import Walker
    from substrate import graph, slices
    w = Walker.from_constellation("ref-star")
    g = graph.build_graph(w)
"""

from .walker import Walker

__all__ = ["Walker"]
