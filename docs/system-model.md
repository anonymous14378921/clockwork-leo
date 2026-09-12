# System model

This document provides a standalone reference for the Clockwork system model. A reader can understand and reimplement the full model from this document alone without requiring the paper.

> This page is under active development. Sections marked with *[TBD]* will be expanded.

## 1. Orbital substrate

### 1.1 Walker constellations

Clockwork models two Walker constellation topologies at repeat-ground-track altitudes.

- **Star** (Walker Star, Type I): 12 planes x 16 satellites, 561 km altitude, 87 degree inclination. Cylinder topology with a counter-rotating seam between the first and last plane.
- **Delta** (Walker Delta, Type II): 12 planes x 16 satellites, 888 km altitude, 53 degree inclination. Torus topology with no seam, coverage capped at the inclination latitude.

*[TBD: Walker position equations, ISL graph construction, repeat-ground-track justification]*

### 1.2 Planning cycle

The planning cycle is one sidereal day (86,164 s). At repeat-ground-track altitudes, the constellation returns to the same geometry after this period, making the provisioning problem periodic. Star completes 15 revolutions and Delta completes 14 revolutions per sidereal day.

*[TBD: epoch grid, snapshot sequence, temporal resolution]*

### 1.3 Area of interest and visibility

*[TBD: AoI definition, elevation mask, satellite visibility, access latency]*

## 2. Service model

### 2.1 Compound AI workflows

A workflow is a directed acyclic graph (DAG) of components: detectors, classifiers, and language models. Each component has a variant ladder trading accuracy for compute.

*[TBD: workflow DAG definition, variant ladder structure, execution profiles]*

### 2.2 Source and capture modes

*[TBD: ground-originated vs satellite-captured, ingress/egress selection]*

## 3. Provisioning state

A provisioning state specifies the shell, the set of active planes, and the placement of each workflow component on a satellite.

*[TBD: formal definition, feasibility conditions, cost model]*

## 4. Cyclic schedule formulation

The Clockwork problem is to find a sequence of provisioning states over the planning cycle that minimizes total provisioning and reprovisioning cost while meeting the latency SLO at every snapshot where service is feasible.

*[TBD: objective function, switching cost, permitted transitions]*

## 5. Constants and parameters

All physical and model constants are defined in `constants/constants.yaml` with provenance tags (paper, spec, estimate, derived). No number is hardcoded elsewhere in the codebase. See the file for the complete list with units and sources.
