# Pollux time-series illustration

The experiment exports Pollux, Reactive, Per-Snapshot Minimum, and Rolling
Horizon schedules (5, 15, 60 minutes of lookahead). The compact figure uses
all six methods with one shared method legend and full axis borders. Solid
and hatched bar portions denote provisioning and reprovisioning costs.

Run `just run pollux_timeline`, then generate figures from the results.

The full sidereal day is planned before plotting its first two hours. Seed 0
and the window [0, 7200) seconds were fixed before examining the schedules.
SLO is 300 ms, lambda is 5, margin is 5, and the full cycle contains 1440
snapshots. This is one illustrative assignment, not an aggregate result.

Labels q_i in blocks identify provisioning states consistently across methods.
Colors identify methods and match the cost curves. State identity is encoded
only by the label, not by color. White blocks indicate released resources.
Short blocks omit the label for legibility. Gray bands indicate snapshots with
no feasible candidate and do not imply that held resources provide service.
Black triangles mark charged reprovisionings. Pure plane releases change the
state without a triangle. Latency is checked only at snapshot times.

Cumulative cost integrates provisioning rates and adds lambda at charged
transitions. The event at time zero includes the final-to-first transition
of the returned cyclic schedule. Each full-cycle reconstructed cost and
transition count is asserted equal to the planner's own total. The final
plotted interval is clipped to two hours. No staging overlap is added.
