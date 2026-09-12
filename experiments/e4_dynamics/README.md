# E4 — dynamics measurement (SQ4)

**Hypothesis:** HD1 (AoI slices live minutes, placements are temporary).
Measurement only, feeds one motivation figure and the validity-horizon semantics.

## Definition of done (brief Sections 3, 4)

- Slice lifetime distribution: how long an AoI slice's covering set stays stable
  as the constellation advances (time-expanded `substrate.walker`, non-zero t).
- Churn distribution: rate at which satellites enter/leave a slice.
- Placement validity horizons derived from slice lifetimes.
- One motivation figure, reproducible from one entry point. RESULTS.md carries
  the median slice lifetime in minutes.

## Status

Not started. `substrate.walker.position(t)` already advances by mean motion, so
the time-expanded views E4 needs are supported.
