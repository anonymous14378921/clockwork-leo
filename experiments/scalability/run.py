"""Scalability: Castor planning time vs constellation size and workflow depth.

Measures single-snapshot Castor time across fleet sizes (32 to 10K satellites)
and workflow depths (2 to 6 components). Run via `just run scalability`.
"""

import time
import yaml
from pathlib import Path

import pandas as pd

from lab import castor
from lab import constants as C
from lab.cycle import repeat_track_altitude_km
from lab.harness import Run
from lab.provider import build_provider
from lab.service import load_chain, load_io, load_profiles


def _add_scalability_provider(planes, sats, name):
    """Register a temporary provider spec for the given constellation size."""
    spec_path = Path(__file__).resolve().parents[2] / "configs" / "providers" / "mvp.yaml"
    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    gpu_large_planes = max(1, planes // 6)
    gpu_small_planes = max(1, planes // 4)
    base_planes = planes - gpu_large_planes - gpu_small_planes

    gpu_large_per_plane = max(1, sats // 8)
    gpu_small_per_plane = max(1, sats // 4)

    spec["providers"][name] = {
        "shells": [{
            "id": "star_s",
            "type": "walker_star",
            "revs_per_sidereal_day": 15,
            "inclination_deg": 87.0,
            "planes": planes,
            "sats_per_plane": sats,
            "phasing_f": 1,
            "plane_profiles": {
                "hub": {
                    "count": gpu_large_planes,
                    "hw": {
                        "cpu": sats - gpu_small_per_plane - gpu_large_per_plane,
                        "gpu_small": gpu_small_per_plane,
                        "gpu_large": gpu_large_per_plane,
                    },
                },
                "edge": {
                    "count": gpu_small_planes,
                    "hw": {
                        "cpu": sats - gpu_small_per_plane,
                        "gpu_small": gpu_small_per_plane,
                    },
                },
                "base": {
                    "count": base_planes,
                    "hw": {"cpu": sats},
                },
            },
        }],
    }
    with open(spec_path, "w") as f:
        yaml.safe_dump(spec, f, default_flow_style=False, sort_keys=False)
    return name


def _run_castor_single(provider_name, aoi, slo, seed, slack):
    """Run Castor on a single snapshot at t=0, return timing and stats."""
    inst = build_provider(provider_name, aoi, t=0.0, seed=seed)
    total_sats = sum(
        sh.walker.n_planes * sh.walker.sats_per_plane
        for sh in inst.shells.values()
    )
    profiles = load_profiles()
    io = load_io()

    t0 = time.perf_counter()
    results = castor.solve_label(
        inst, slo, profiles=profiles, io=io,
        keep_all=True, cost_slack=slack,
    )
    elapsed = time.perf_counter() - t0

    if isinstance(results, list):
        n_plans = len(results)
        best_cost = min(r.cost_rate for r in results) if results else None
        best_lat = min(r.latency_ms for r in results) if results else None
    elif results is not None:
        n_plans = 1
        best_cost = results.cost_rate
        best_lat = results.latency_ms
    else:
        n_plans = 0
        best_cost = None
        best_lat = None

    return {
        "total_satellites": total_sats,
        "n_plans": n_plans,
        "best_cost": best_cost,
        "best_latency_ms": best_lat,
        "castor_time_s": elapsed,
    }


def main():
    run = Run.start("scalability")
    cfg = run.config
    aoi = (C.to_float(cfg["aoi"]["lat"]), C.to_float(cfg["aoi"]["lon"]))
    slo = C.to_float(cfg["slo_ms"])
    seed = int(cfg["fleet_seed"])
    slack = C.to_float(cfg["slack"])

    rows = []

    for entry in cfg["constellation_sweep"]:
        planes = int(entry["planes"])
        sats = int(entry["sats"])
        total = planes * sats
        pname = f"scale-{planes}x{sats}"
        print(f"[scale] {pname} ({total} sats)...", flush=True)
        _add_scalability_provider(planes, sats, pname)
        result = _run_castor_single(pname, aoi, slo, seed, slack)
        result["planes"] = planes
        result["sats_per_plane"] = sats
        result["kind"] = "constellation"
        rows.append(result)
        print(f"  -> {result['n_plans']} plans in {result['castor_time_s']:.1f}s",
              flush=True)

    # Workflow depth sweep: vary chain length on the reference fleet
    wf_fleet = cfg.get("workflow_depth_fleet")
    if wf_fleet:
        wf_planes = int(wf_fleet["planes"])
        wf_sats = int(wf_fleet["sats"])
        wf_pname = f"scale-{wf_planes}x{wf_sats}"
        _add_scalability_provider(wf_planes, wf_sats, wf_pname)
        for depth in cfg.get("workflow_depth_sweep", []):
            depth = int(depth)
            print(f"[scale] workflow depth {depth} on {wf_pname}...", flush=True)
            inst = build_provider(wf_pname, aoi, t=0.0, seed=seed)
            profiles = load_profiles()
            io = load_io()
            comps, edges = load_chain()
            # Extend or truncate the chain to the desired depth
            if depth <= len(comps):
                use_comps = comps[:depth]
                use_edges = edges[:depth - 1]
            else:
                extra = depth - len(comps)
                use_comps = list(comps) + list(comps[1:1 + extra])
                use_edges = list(edges) + list(edges[:extra])

            t0 = time.perf_counter()
            results = castor.solve_label(
                inst, slo, profiles=profiles, io=io,
                keep_all=True, cost_slack=slack,
            )
            elapsed = time.perf_counter() - t0

            if isinstance(results, list):
                n_plans = len(results)
            elif results is not None:
                n_plans = 1
            else:
                n_plans = 0

            rows.append({
                "kind": "workflow_depth",
                "planes": wf_planes,
                "sats_per_plane": wf_sats,
                "total_satellites": wf_planes * wf_sats,
                "workflow_depth": depth,
                "n_plans": n_plans,
                "castor_time_s": elapsed,
            })
            print(f"  -> {n_plans} plans in {elapsed:.1f}s", flush=True)

    df = pd.DataFrame(rows)
    run.save_dataframe("scalability.csv", df)
    print(df.to_string())


if __name__ == "__main__":
    main()
