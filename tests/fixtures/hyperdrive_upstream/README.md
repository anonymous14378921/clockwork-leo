# Pinned HyperDrive reference sources

Repository https://github.com/polaris-slo-cloud/hyper-drive

Commit `94d753a4da15339268423e4141a2c086974ac507`

Authors Thomas Pusztai, Cynthia Marcelino, and Stefan Nastic.
Paper https://arxiv.org/abs/2410.16026

These files are unmodified copies, preserved under the upstream Apache 2.0
license in `LICENSE`. There was no upstream NOTICE file at this revision.
`manifest.json` records their SHA256 hashes. Files other than `scheduler.py`,
`config_helper.py`, and `LICENSE` originate in `scheduler/plugins/`.

The tests execute original class bodies with lightweight interface substitutes
for imports. They do not replace scoring, normalization, filtering, candidate
selection, or commit method bodies. The original generic method syntax requires
Python 3.12 or newer for these fidelity tests, as does upstream HyperDrive.

The production adapter is separately implemented in `src/lab/hyperdrive.py`.
It changes the infrastructure interfaces and explicitly documents its assumptions
in `docs/hyperdrive-baseline.md`. These reference files are test fixtures, not an
installed HyperDrive platform or a reproduction of its published experiments.
