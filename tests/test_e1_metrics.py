"""E1 metric sanity tests: the seam tax and the latitude cap must show up.

These lock the two structural signatures on the
controlled pair (identical except RAAN span).
"""

from substrate import graph as G
from substrate import metrics as M
from substrate.walker import Walker


def test_delta_wraps_star_pays_seam_on_controlled_pair():
    ws = Walker.from_constellation("ctrl-star")
    wd = Walker.from_constellation("ctrl-delta")
    gs, gd = G.build_graph(ws), G.build_graph(wd)

    star_seam = M.summarize(M.seam_pair_hops(ws, gs))
    delta_wrap = M.summarize(M.seam_pair_hops(wd, gd))

    # Delta's first/last planes are torus neighbours: a couple of hops at most.
    assert delta_wrap.p95 <= 3
    # Star's straddle the seam: many planes to route around.
    assert star_seam.p95 >= ws.n_planes // 2
    # And the tax is a large ratio, not a rounding difference.
    assert star_seam.p95 >= 5 * max(delta_wrap.p95, 1)


def test_latitude_cap_on_inclination_60():
    # Both controlled constellations are inclination 60, so neither reaches the
    # Arctic band (>= 66.5 deg), but both populate the mid band.
    for name in ("ctrl-star", "ctrl-delta"):
        cov = M.coverage_by_band(Walker.from_constellation(name), n_snapshots=6)
        assert cov["arctic"] == 0.0
        assert cov["mid"] > 0.0


def test_nearest_capable_zero_when_all_capable():
    w = Walker.from_constellation("ctrl-delta")
    g = G.build_graph(w)
    sweep = M.nearest_capable_sweep(w, g, fractions=[1.0], k_sources=10)
    assert sweep[1.0].maximum == 0.0
