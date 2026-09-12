"""Variant ladders with per-device latency and accuracy profiles.

Latency profiles are first-class input data, exactly symmetric with accuracy
profiles. Where a published measurement exists for a (variant, device) pair
the evaluator uses it; the analytic roofline is the fallback for devices
without measurements. Every lookup reports its source so results can disclose
which numbers are measured and which are modeled.

Accuracy is device-aware: an INT8 accelerator delivers its quantized mAP
(map_on_device), a GPU delivers the float mAP. accuracy_on() resolves this.

Invariant (tested): the roofline is an ideal lower bound on latency, so every
measured per-image time must be >= the roofline prediction for that device.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import yaml

from lab import constants as C
from lab.harness.runner import repo_root

MEASURED = "measured"
ROOFLINE = "roofline"


@dataclass(frozen=True)
class DeviceLatency:
    ms_per_image: float           # conservative default (batch-1 where published)
    ms_per_image_batched: float   # batch-8 where published, else = ms_per_image
    map_on_device: Optional[float]
    prov: str
    source: str


@dataclass(frozen=True)
class Variant:
    name: str
    gflops_per_image: float
    map: float                       # float (GPU-side) mAP
    latency: Dict[str, DeviceLatency]  # device name (constants.yaml key) -> profile


def _parse_latency(raw: dict) -> DeviceLatency:
    if "fps_batch1" in raw:
        ms1 = 1e3 / C.to_float(raw["fps_batch1"])
        ms8 = 1e3 / C.to_float(raw.get("fps_batch8", raw["fps_batch1"]))
    else:
        ms1 = C.to_float(raw["ms_per_image"])
        ms8 = C.to_float(raw.get("ms_per_image_batched", raw["ms_per_image"]))
    mod = raw.get("map_on_device")
    return DeviceLatency(
        ms_per_image=ms1,
        ms_per_image_batched=ms8,
        map_on_device=C.to_float(mod) if mod is not None else None,
        prov=raw.get("prov", "estimate"),
        source=raw.get("source", ""),
    )


@lru_cache(maxsize=8)
def load_ladder(name: str) -> List[Variant]:
    path = repo_root() / "ladders" / f"{name}.yaml"
    with path.open("r") as f:
        spec = yaml.safe_load(f)
    return [
        Variant(
            name=v["name"],
            gflops_per_image=C.to_float(v["gflops_per_image"]),
            map=C.to_float(v["map"]),
            latency={d: _parse_latency(raw) for d, raw in (v.get("latency") or {}).items()},
        )
        for v in spec["variants"]
    ]


def roofline_ms(flops: float, device: C.Device) -> float:
    """Ideal compute-bound time in ms: flops / (peak * duty). The fallback."""
    return flops / (device.peak_flops * C.duty_cycle()) * 1e3


def exec_ms_per_image(v: Variant, device_name: str, device: C.Device) -> Tuple[float, str]:
    """Per-image inference time in ms and its source (measured or roofline)."""
    prof = v.latency.get(device_name)
    if prof is not None:
        return prof.ms_per_image, MEASURED
    return roofline_ms(v.gflops_per_image * 1e9, device), ROOFLINE


def batch_ms(v: Variant, device_name: str, device: C.Device, n_images: int) -> Tuple[float, str]:
    """Time in ms to process n_images sequentially at the per-image rate."""
    per_image, source = exec_ms_per_image(v, device_name, device)
    return per_image * n_images, source


def accuracy_on(v: Variant, device_name: str) -> float:
    """Delivered mAP on this device: quantized value where measured, else float."""
    prof = v.latency.get(device_name)
    if prof is not None and prof.map_on_device is not None:
        return prof.map_on_device
    return v.map
