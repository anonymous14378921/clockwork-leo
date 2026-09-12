"""Substrate sanity tests (brief item 4). Test-first: these are the spec.

Two families of checks:
  1. Geometry: the walker must reproduce the four hand-verified intra-plane hop
     times, and the four inter-plane equatorial hop times, each within 1 percent
     of the canonical values in constants.yaml.
  2. Topology: the Walker-Star seam must be visible as a path-length blow-up. A
     pair of satellites that straddle the seam (physically adjacent, in the first
     and last planes) must have no direct link and must route the long way round.

CPU only, no GPU, no network.
"""

import math

import pytest

from lab import constants as C
from substrate import graph as G
from substrate.walker import Walker

TOL = 0.01  # 1 percent, per brief item 4
ALL = ["ref-star", "starlink-s1", "kuiper-s1", "oneweb"]


def _verified(kind, name):
    node = C.load_constants()["verified_hops"][kind][name]
    return C.to_float(C.val(node))


@pytest.mark.parametrize("name", ALL)
def test_intra_plane_hop_matches_verified(name):
    w = Walker.from_constellation(name)
    got = w.intra_plane_hop_ms()
    want = _verified("intra_plane_ms", name)
    assert math.isclose(got, want, rel_tol=TOL), f"{name}: intra {got:.3f} vs {want:.3f} ms"


@pytest.mark.parametrize("name", ALL)
def test_inter_plane_equator_hop_matches_verified(name):
    w = Walker.from_constellation(name)
    got = w.inter_plane_equator_hop_ms()
    want = _verified("inter_plane_equator_ms", name)
    assert math.isclose(got, want, rel_tol=TOL), f"{name}: inter {got:.3f} vs {want:.3f} ms"


def test_invariant_a_over_c_ms_per_rad():
    # Brief Section 5: a/c is 23.1 to 25.3 ms/rad across all four constellations.
    for name in ALL:
        w = Walker.from_constellation(name)
        ms_per_rad = w.a_km / (C.to_float(C.val(C.load_constants()["physical"]["c_m_s"])) / 1e3) * 1e3
        assert 23.0 <= ms_per_rad <= 25.4, f"{name}: a/c = {ms_per_rad:.2f} ms/rad"


def test_star_seam_costs_the_long_way():
    # The seam sits between the first and last planes of a Walker-Star. A pair of
    # satellites straddling it is physically close (about one inter-plane hop) but
    # has no ISL, so the shortest path must wrap around the cylinder.
    w = Walker.from_constellation("ref-star")
    g = G.build_graph(w)
    a, b, phys_km = G.closest_cross_seam_pair(w, g)

    assert not g.has_edge(a, b), "seam pair must not be directly linked"

    inter_hop_km = w.inter_plane_equator_hop_km()
    assert phys_km < 3.0 * inter_hop_km, (
        f"seam pair should be physically near (got {phys_km:.0f} km "
        f"vs inter-hop {inter_hop_km:.0f} km)"
    )

    hops = G.shortest_path_hops(g, a, b)
    assert hops >= w.n_planes // 2, (
        f"seam detour should span many planes, got {hops} hops "
        f"(Nx={w.n_planes})"
    )


def test_delta_has_no_seam():
    # A Walker-Delta wraps as a torus: every plane links to its neighbour mod Nx,
    # so first and last planes ARE directly connected (no seam tax).
    w = Walker.from_constellation("starlink-s1")
    g = G.build_graph(w)
    last = w.n_planes - 1
    linked = any(
        g.has_edge((0, s), (last, s2))
        for s in range(w.sats_per_plane)
        for s2 in range(w.sats_per_plane)
    )
    assert linked, "delta torus must link the wrap-around planes"
