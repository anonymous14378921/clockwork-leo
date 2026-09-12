# E2 Results

**Status: MACHINERY VALIDATED, mechanisms visible; accuracy numbers are
placeholder-grid (acc_source=placeholder-estimate) and MUST NOT reach the
paper.** Rerun unchanged once ladders/cascade_grid_measured.yaml lands.

Run 20260825-111137 (wildfire, 4 constellations x 2 AoIs x p in
{0.002, 0.01, 0.05, 0.2} x 10 SLOs x 3 fleet seeds; 1020 plans enumerated per
instance; 600 covered rows + 33 frontier rows).

## Mechanism findings (structural, robust to the grid swap)

1. **Node-cap + spread (EQ1):** spread (best minus packed at equal SLO) is 0
   below 0.65 s (nothing detour-reachable helps), peaks 12.9 mAP at 1 s, and
   decays to 1.9 mAP at 8 s. The planner walks the configuration space as the
   SLO relaxes: (n, none)@sensor -> (s, none)@H100 detour at 0.7 s ->
   (s, l, tau 0.1-0.15) at 0.85 s -> (m, x, tau 0.5) at 2 s+.
2. **Hop budget eats the threshold (config shift, EQ1):** at the 0.85 s SLO the
   chosen threshold falls monotonically with the instance's detour to the
   nearest strong node (tau 0.25 near zero detour, 0.15 at 8-53 ms, 0.10 at
   70-80 ms): the detour's propagation cost is paid by verifying a smaller
   fraction, costing accuracy. This is the orbital x compound coupling the
   formulation claims.
3. **Density buys accuracy:** at p=0.002, starlink-s1 (1584 sats, 19 ms median
   detour) reaches 44.9 at the 0.65 s SLO where the sparser shells sit at 37.3.
4. **Coverage cap:** every arctic x delta instance is covered=False (recorded,
   not errored); arctic is served only by ref-star.
5. **Frontier (EQ2), graded mix (rerun 20260825 with fleet_mixes.graded):**
   two steps, 37.3-45.75 mAP at cost 4 (iX10) -> 53.16 at cost 12 (Orin),
   across SLOs 0.85-2 s. The H100 tier is DOMINATED at every tested SLO
   because the Orin entry is the roofline fallback (275 TOPS optimistic,
   within 3.6x of the H100). Whether the frontier's third step exists is
   decided by the AGX Orin measurement -> that measurement is on the EQ2
   critical path, not a stretch goal.
6. Star-vs-Delta class MEDIANS do not differ in the mid-latitude band,
   consistent with E1 (classes differ by structure, seam and coverage, not by
   average path cost). Seam-adjacent AoI instances are the open lever for a
   class-level flip-map panel.

Figure: figures/e2_accuracy_coupling.{pdf,png} (spread vs SLO, threshold vs
detour, frontier).
