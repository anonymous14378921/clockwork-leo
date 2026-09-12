"""Replay fixed one-minute schedules between their planning snapshots."""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import shutil
from pathlib import Path

import pandas as pd

from lab import pollux as cal
from lab.cycle import cycle_s
from lab.harness import Run
from lab.provider import build_provider
from lab.service import load_chain, load_io, load_profiles


_CTX = {}


def _state(raw):
    return cal.State(
        tuple((component, tuple(sat), hardware)
              for component, sat, hardware in raw["compute"]),
        frozenset(tuple(plane) for plane in raw["planes"]),
    )


def _init_worker(context):
    global _CTX
    _CTX = context


def _evaluate_time(item):
    sample_index, interval, t, duration_s = item
    ctx = _CTX
    inst = build_provider(ctx["provider"], ctx["aoi"], t=t,
                          seed=ctx["seed"], plane_routes=False)
    out = []
    cache = {}
    for method, assignment in ctx["assignments"].items():
        state_id = assignment[interval]
        if state_id < 0:
            category, latency = "released", None
        else:
            if state_id not in cache:
                state = ctx["states"][state_id]
                visible = inst.visible_in(state.planes)
                if not visible:
                    cache[state_id] = ("no_access", None)
                else:
                    result = cal.serve(inst, state, ctx["components"],
                                       ctx["edges"], ctx["profiles"],
                                       ctx["io"])
                    if result is None:
                        cache[state_id] = ("no_route", None)
                    elif result[1] <= ctx["slo_ms"]:
                        cache[state_id] = ("served", result[1])
                    else:
                        cache[state_id] = ("latency", result[1])
            category, latency = cache[state_id]
        out.append((method, sample_index, interval, t, duration_s,
                    state_id, category, latency))
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _samples(step_s, planning_steps):
    total = cycle_s()
    planning_step = total / planning_steps
    samples = []
    sample_index = 0
    for interval in range(planning_steps):
        start = interval * planning_step
        end = (interval + 1) * planning_step
        offset = 0.0
        while start + offset < end:
            t = start + offset
            duration = min(step_s, end - t)
            samples.append((sample_index, interval, t, duration))
            sample_index += 1
            offset += step_s
    return samples


def _summarize(rows, timeline, resolution_s):
    frame = pd.DataFrame(rows, columns=[
        "method", "sample", "interval", "time_s", "duration_s",
        "state", "category", "latency_ms"])
    start_feasible = {
        (row.method, int(row.snapshot)): pd.notna(row.latency_ms)
        for row in timeline.itertuples()
    }
    frame["start_feasible"] = [
        start_feasible[(method, int(interval))]
        for method, interval in zip(frame.method, frame.interval)]
    frame["missed_failure"] = frame.start_feasible & (frame.category != "served")

    interval_rows = (frame.groupby(
        ["method", "interval", "start_feasible", "category"], as_index=False)
        .agg(duration_s=("duration_s", "sum"),
             samples=("sample", "count"),
             max_latency_ms=("latency_ms", "max")))

    summary = {}
    total_s = cycle_s()
    for method, group in frame.groupby("method"):
        durations = group.groupby("category").duration_s.sum().to_dict()
        latency_failures = group[group.category == "latency"].latency_ms
        missed = group[group.missed_failure]
        longest = 0.0
        for _, interval_group in missed.groupby("interval"):
            ordered = interval_group.sort_values("sample")
            run = 0.0
            previous = None
            for row in ordered.itertuples():
                if previous is None or row.sample == previous + 1:
                    run += row.duration_s
                else:
                    longest = max(longest, run)
                    run = row.duration_s
                previous = row.sample
            longest = max(longest, run)
        planning = timeline[timeline.method == method]
        planning_attainment = planning.latency_ms.notna().mean()
        fine_attainment = durations.get("served", 0.0) / total_s
        start_feasible_s = group[group.start_feasible].duration_s.sum()
        missed_s = missed.duration_s.sum()
        summary[method] = {
            "planning_grid_attainment": planning_attainment,
            "fine_replay_attainment": fine_attainment,
            "attainment_change_percentage_points":
                100.0 * (fine_attainment - planning_attainment),
            "served_s": durations.get("served", 0.0),
            "released_s": durations.get("released", 0.0),
            "no_access_s": durations.get("no_access", 0.0),
            "no_route_s": durations.get("no_route", 0.0),
            "latency_failure_s": durations.get("latency", 0.0),
            "missed_failure_s_within_start_feasible_intervals": missed_s,
            "start_feasible_interval_time_s": start_feasible_s,
            "missed_failure_fraction_within_start_feasible_intervals":
                missed_s / start_feasible_s if start_feasible_s else None,
            "longest_observed_missed_failure_run_s": longest,
            "mean_latency_exceedance_ms": (
                float((latency_failures - _CTX["slo_ms"]).mean())
                if len(latency_failures) else None),
            "max_latency_exceedance_ms": (
                float((latency_failures - _CTX["slo_ms"]).max())
                if len(latency_failures) else None),
        }
    return frame, interval_rows, summary


def main():
    run = Run.start("pP_temporal_validation")
    cfg = run.config
    source = run.root / cfg["source_run"]
    required = [source / name for name in
                ("timeline.csv", "states.json", "summary.json", "config.yaml")]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    source_copy = run.path("source")
    source_copy.mkdir()
    for path in required:
        shutil.copy2(path, source_copy / path.name)

    timeline = pd.read_csv(source / "timeline.csv")
    with (source / "states.json").open() as handle:
        states = [_state(raw) for raw in json.load(handle)]
    assignments = {
        method: list(group.sort_values("snapshot").state.astype(int))
        for method, group in timeline.groupby("method")
    }
    expected = set(range(int(cfg["planning_steps"])))
    for method, group in timeline.groupby("method"):
        if set(group.snapshot.astype(int)) != expected:
            raise ValueError(f"incomplete source schedule for {method}")

    components, edges = load_chain()
    context = {
        "provider": cfg["provider"],
        "aoi": (float(cfg["aoi"]["lat"]), float(cfg["aoi"]["lon"])),
        "seed": int(cfg["seed"]),
        "slo_ms": float(cfg["slo_ms"]),
        "planning_steps": int(cfg["planning_steps"]),
        "planning_step_s": cycle_s() / int(cfg["planning_steps"]),
        "states": states,
        "assignments": assignments,
        "components": components,
        "edges": edges,
        "profiles": load_profiles(),
        "io": load_io(),
    }
    metadata = {
        "source_run": str(source.relative_to(run.root)),
        "source_files_sha256": {path.name: _sha256(path) for path in required},
        "cycle_s": cycle_s(),
        "planning_step_s": context["planning_step_s"],
        "methods": sorted(assignments),
    }
    run.save_json("source_metadata.json", metadata)

    all_summaries = {}
    workers = int(cfg.get("workers", 1))
    for resolution_s in cfg["replay_steps_s"]:
        resolution_s = float(resolution_s)
        samples = _samples(resolution_s, context["planning_steps"])
        print(f"[replay] {resolution_s:g}s grid, {len(samples)} samples, "
              f"{workers} workers", flush=True)
        with mp.Pool(workers, initializer=_init_worker,
                     initargs=(context,)) as pool:
            nested = pool.map(_evaluate_time, samples, chunksize=20)
        rows = [row for sample_rows in nested for row in sample_rows]
        _init_worker(context)
        _, interval_rows, summary = _summarize(
            rows, timeline, resolution_s)
        label = f"{resolution_s:g}".replace(".", "p")
        run.save_dataframe(f"intervals_{label}s.csv", interval_rows)
        run.save_json(f"summary_{label}s.json", summary)
        all_summaries[f"{resolution_s:g}s"] = summary
        print(json.dumps(summary, indent=2), flush=True)
    run.save_json("summary.json", all_summaries)


if __name__ == "__main__":
    main()
