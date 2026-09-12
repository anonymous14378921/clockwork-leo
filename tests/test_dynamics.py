"""Dynamics sanity: Earth-rotation term, dwell-window semantics, and the
window == simulation cross-check (the bisection-refined event time must agree
with a much finer forward scan; two implementations of the same event)."""

import math

from substrate import dynamics as D
from substrate.slices import AOIS, AoI
from substrate.walker import Walker


def test_ground_longitude_drifts_west():
    w = Walker.from_constellation("ref-star")
    _, lon0 = D.ground_subpoint(w, 0, 0, 0.0)
    # After time T the ground longitude must have shifted by exactly
    # omega_E*T relative to the inertial subpoint drift.
    t = 600.0
    lat_i, lon_i = w.subpoint(0, 0, t)
    _, lon_g = D.ground_subpoint(w, 0, 0, t)
    want = (lon_i - math.degrees(D.omega_earth() * t) + 180.0) % 360.0 - 180.0
    assert abs(lon_g - want) < 1e-9


def test_dwell_window_boundary_semantics():
    w = Walker.from_constellation("ref-star")
    aoi = AOIS["mid_latitude"]
    node = next(n for n in D.slice_at(w, aoi, 0.0))
    win = D.dwell_window_s(w, node, aoi, dt=5.0)
    assert win is not None and win > 0
    # Just inside before the event, just outside after it.
    assert D.in_aoi(w, node, aoi, win - 0.5)
    assert not D.in_aoi(w, node, aoi, win + 0.5)


def test_window_matches_fine_simulation():
    # Cross-check: coarse-scan + bisection vs a 0.5 s brute-force scan.
    w = Walker.from_constellation("ref-star")
    aoi = AOIS["mid_latitude"]
    node = next(n for n in D.slice_at(w, aoi, 0.0))
    win = D.dwell_window_s(w, node, aoi, dt=5.0, tol_s=0.01)
    t = 0.0
    while D.in_aoi(w, node, aoi, t + 0.5):
        t += 0.5
    assert abs(win - t) <= 0.5 + 0.01


def test_outside_node_has_no_window():
    w = Walker.from_constellation("ref-star")
    arctic = AOIS["arctic"]
    node = next(n for n in D.slice_at(w, AOIS["equatorial"], 0.0))
    assert D.dwell_window_s(w, node, arctic) is None
