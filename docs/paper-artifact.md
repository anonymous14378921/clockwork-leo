# Clockwork paper artifact

This directory is the versioned companion documentation for the Clockwork
paper. It holds details that support reproduction and interpretation but do
not fit in the paper. The paper remains the authoritative statement of the
model and claims.

## Validation

* [Temporal resolution and schedule replay](temporal-resolution.md)

## Reproduction convention

Every experiment is invoked through `just run <experiment>`. The harness
stores its configuration, source revision, working-tree status, and hardware
manifest under `results/<experiment>/<timestamp>/`. Documentation names a
specific result directory for every reported number. A dirty-tree warning
means that the recorded commit alone is insufficient, so a supporting run
must also preserve or hash the exact inputs it consumed.

