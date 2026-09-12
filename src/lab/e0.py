"""Worked-example model for the accuracy-placement hypothesis.

One wildfire instance on ref-star, sparse-strong fleet (2% H100, rest iX10). Two
placements meet the same SLO:
  A  packed: every component on iX10 nodes adjacent to the sensor.
  B  detour: the detect component is sent k hops to the nearest H100, rest as A.

For each placement we pick the largest detect variant whose end-to-end latency
fits the SLO, and compare achieved accuracy. At equal SLO, achievable accuracy
is placement-dependent.

Latency of a component chain = sum of stage compute + routing propagation +
transmission. Detect compute and delivered accuracy come from lab.profiles:
published per-device measurements, with the analytic roofline only as the
fallback for unprofiled devices. Accuracy is device-aware.

CPU only, pure arithmetic. k (the detour hop count) is measured from the substrate
by the experiment and passed in, so this module has no geometry dependency.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from lab import constants as C
from lab import profiles as P
from lab.profiles import Variant, load_ladder  # re-exported for tests and callers

# --- roofline + link helpers -------------------------------------------------
def compute_ms(flops: float, device: C.Device) -> float:
    """Roofline compute time in ms (the fallback path; see lab.profiles)."""
    return P.roofline_ms(flops, device)


def transmission_ms(nbytes: float, isl_gbps: float) -> float:
    """Serialization time in ms for nbytes over an ISL of isl_gbps."""
    return nbytes * 8.0 / (isl_gbps * 1e9) * 1e3


# --- E0 configuration view over constants ------------------------------------
@dataclass(frozen=True)
class E0Config:
    slo_ms: float
    isl_gbps: float
    crops: int
    recall_factor: float
    screen_flops: float
    spread_flops: float
    tile_bytes: float        # ingest -> screen
    screen_out_bytes: float  # screen -> detect
    detect_out_bytes: float  # detect -> spread
    spread_out_bytes: float  # spread -> alert
    weak_name: str
    strong_name: str
    weak_device: C.Device
    strong_device: C.Device
    ladder_name: str


def load_e0_config() -> E0Config:
    k = C.load_constants()
    e0 = k["e0"]
    pipe = e0["pipeline"]
    con = C.constellation(e0["constellation"])
    mix = k["fleet_mixes"][e0["fleet"]]
    return E0Config(
        slo_ms=C.to_float(C.val(e0["slo_seconds"])) * 1e3,
        isl_gbps=con.isl_rate_gbps,
        crops=int(C.val(pipe["detect"]["crops_per_tile"])),
        recall_factor=C.to_float(C.val(pipe["screen"]["recall_factor"])),
        screen_flops=C.to_float(C.val(pipe["screen"]["flops"])),
        spread_flops=C.to_float(C.val(pipe["spread"]["flops"])),
        tile_bytes=C.to_float(C.val(pipe["ingest"]["tile_bytes"])),
        screen_out_bytes=C.to_float(C.val(pipe["screen"]["out_bytes"])),
        detect_out_bytes=C.to_float(C.val(pipe["detect"]["out_bytes"])),
        spread_out_bytes=C.to_float(C.val(pipe["spread"]["out_bytes"])),
        weak_name=mix["rest_device"],
        strong_name=mix["strong_device"],
        weak_device=C.device(mix["rest_device"]),
        strong_device=C.device(mix["strong_device"]),
        ladder_name=pipe["detect"]["ladder"],
    )


# --- placement evaluation ----------------------------------------------------
@dataclass(frozen=True)
class PlacementEval:
    placement: str
    variant: Variant
    map: float               # delivered mAP on the detect device (quantization-aware)
    compute_ms: float
    propagation_ms: float
    transmission_ms: float
    total_ms: float
    feasible: bool           # total <= SLO
    detect_source: str       # profiles.MEASURED or profiles.ROOFLINE


def evaluate(cfg: E0Config, placement: str, v: Variant, k: int,
             t_hop_ms: float) -> PlacementEval:
    """End-to-end latency of one placement running detect variant v.

    placement "A": detect on the weak device, all edges 1 hop (packed cluster).
    placement "B": detect on the strong device, the two edges touching detect
    cost k hops each (out to the H100 and back), the rest 1 hop.
    """
    if placement == "A":
        detect_name, detect_dev, detect_hops = cfg.weak_name, cfg.weak_device, 1
    else:
        detect_name, detect_dev, detect_hops = cfg.strong_name, cfg.strong_device, k

    detect_ms, detect_source = P.batch_ms(v, detect_name, detect_dev, cfg.crops)

    # Stage compute (ms). ingest and alert are I/O, no compute.
    comp = (compute_ms(cfg.screen_flops, cfg.weak_device)      # screen on weak
            + detect_ms                                        # detect
            + compute_ms(cfg.spread_flops, cfg.weak_device))   # spread on weak

    # Edge (inbound_bytes, hop_count): ingest->screen, screen->detect,
    # detect->spread, spread->alert.
    edges = [
        (cfg.tile_bytes, 1),
        (cfg.screen_out_bytes, detect_hops),
        (cfg.detect_out_bytes, detect_hops),
        (cfg.spread_out_bytes, 1),
    ]
    prop = sum(hops * t_hop_ms for _, hops in edges)
    trans = sum(transmission_ms(nbytes, cfg.isl_gbps) for nbytes, _ in edges)

    total = comp + prop + trans
    return PlacementEval(placement, v, P.accuracy_on(v, detect_name), comp, prop,
                         trans, total, total <= cfg.slo_ms, detect_source)


def choose_variant(cfg: E0Config, placement: str, k: int, t_hop_ms: float,
                   ladder: List[Variant], slo_ms: Optional[float] = None
                   ) -> Optional[PlacementEval]:
    """Largest-accuracy feasible variant for a placement at the given SLO."""
    slo = cfg.slo_ms if slo_ms is None else slo_ms
    feasible = [
        e for v in ladder
        if (e := evaluate(cfg, placement, v, k, t_hop_ms)).total_ms <= slo
    ]
    if not feasible:
        return None
    return max(feasible, key=lambda e: e.map)


# --- the verdict -------------------------------------------------------------
SEVERAL_MAP = 3.0  # "several mAP points" threshold for PASS


@dataclass
class E0Result:
    k_hops: int
    t_hop_ms: float
    slo_ms: float
    chosen_a: PlacementEval
    chosen_b: PlacementEval
    gap_map: float
    workflow_gap_map: float
    verdict: str        # "PASS" or "FAIL"
    sweep: List[Dict]   # gap across a range of SLOs


def run_e0(k: int, t_hop_ms: float, sweep_slos_ms: Optional[List[float]] = None
           ) -> E0Result:
    cfg = load_e0_config()
    ladder = load_ladder(cfg.ladder_name)

    a = choose_variant(cfg, "A", k, t_hop_ms, ladder)
    b = choose_variant(cfg, "B", k, t_hop_ms, ladder)
    if a is None or b is None:
        raise RuntimeError("a placement has no SLO-feasible variant; check the SLO")

    gap = b.map - a.map
    workflow_gap = (b.map - a.map) * cfg.recall_factor  # recall multiplies both
    verdict = "PASS" if gap >= SEVERAL_MAP else "FAIL"

    # Sweep range chosen to bracket the measured-profile feasibility boundaries
    # (the tightest SLO where anything fits, up past where A affords YOLOv8x).
    if sweep_slos_ms is None:
        sweep_slos_ms = [0.55e3, 1.1e3, 2.0e3, 3.5e3, 7.6e3, 14.0e3, 21.0e3]
    sweep = []
    for slo in sweep_slos_ms:
        sa = choose_variant(cfg, "A", k, t_hop_ms, ladder, slo_ms=slo)
        sb = choose_variant(cfg, "B", k, t_hop_ms, ladder, slo_ms=slo)
        sweep.append({
            "slo_ms": slo,
            "a_variant": sa.variant.name if sa else None,
            "a_map": sa.map if sa else None,
            "b_variant": sb.variant.name if sb else None,
            "b_map": sb.map if sb else None,
            "gap_map": (sb.map - sa.map) if (sa and sb) else None,
        })

    return E0Result(
        k_hops=k, t_hop_ms=t_hop_ms, slo_ms=cfg.slo_ms,
        chosen_a=a, chosen_b=b, gap_map=gap, workflow_gap_map=workflow_gap,
        verdict=verdict, sweep=sweep,
    )
