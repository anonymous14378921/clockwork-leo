# HyperDrive integration check

Run `just run hyperdrive_comparison` from the experiment repository.
The default workload comprises eight instance and SLO combinations on one
hardware assignment. It compares Castor, Greedy Compose, and two HyperDrive
candidate modes. It does not run Pollux or the complete evaluation sweep.

The adaptation specification and reproduction commands are in
`docs/hyperdrive-baseline.md`. The default registered baseline uses matched
Castor candidates. The vicinity variant preserves upstream geographic
selection. Both preserve upstream network scoring and stable tie order under
nonbinding thermal conditions.

Every run archives decision traces, complete failed attempts, numerical inputs,
and implementation sources. Costs are compared on shared feasible instances.
