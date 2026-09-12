# Pollux time-series illustration

The experiment now also exports Rolling Horizon schedules with 5, 15 and
60 minutes of lookahead. The compact pK figure uses all six methods with
one shared method legend and full axis borders, as requested by the author.
Its solid and hatched bar portions denote provisioning and reprovisioning
costs. Line patterns distinguish methods, with no separate encoding legend.

Run `just run pollux_timeline`, then `just figures pollux_timeline`.
Set `POLLUX_TIMELINE_RUN` to an absolute result directory to regenerate a
specific run. The figure JSON records that directory and the displayed state
ID mapping. No LaTeX is modified.

The full sidereal day is planned before plotting its first two hours. Seed 0
and the window [0, 7200) seconds were fixed before examining the schedules.
This uses the actual pK experiment AoI of 48.21 N, 16.37 E, not the 40 N, 0 E
currently written in the draft. SLO is 300 ms, lambda is 5, margin is 5, and
the full cycle contains 1440 snapshots. This is one illustrative assignment,
not an aggregate result.

Labels q_i in blocks identify provisioning states consistently across methods.
Colors identify methods and match the cost curves. State identity is encoded
only by the label, not by color. White blocks indicate released resources.
Short blocks omit the label for
legibility. Gray bands indicate snapshots with no feasible candidate and
do not imply that held resources provide service. Black triangles mark
charged reprovisionings. Pure plane releases change the state without a
triangle. Latency is checked only at snapshot times.

Cumulative cost integrates provisioning rates and adds lambda at charged
transitions. The event at time zero includes the final-to-first transition
of the returned cyclic schedule. Each full-cycle reconstructed cost and
transition count is asserted equal to the planner's own total. The final
plotted interval is clipped to two hours. No staging overlap is added.

## First run

Source `results/pollux_timeline/20260908-100759`. Input source and data
copies accompany the run because the working tree was dirty.

| Method | Two-hour scheduling cost | Charged reprovisionings |
|---|---:|---:|
| Pollux | 63.20 | 4 |
| Reactive | 163.27 | 26 |
| Per-Snapshot Minimum | 193.27 | 32 |

The most visible behavior is retention through short unserviceable gaps.
Baselines release resources during those gaps and incur a charge on return.
Do not describe the trace solely as avoiding transitions to cheaper states.

Proposed caption, not applied to the paper

Provisioning states and cumulative scheduling cost during the first two
hours of hardware assignment 0, with a 300 ms SLO and lambda = 5. Labels q_i
identify states across methods, colors identify methods, triangles mark charged reprovisionings,
and gray bands indicate no feasible candidate. Pollux retains resources
through short service gaps to avoid subsequent reprovisioning. Costs
include the cycle-boundary transition at time zero.
