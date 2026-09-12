"""Load constants/constants.yaml, the single source of truth.

Nothing in the codebase hardcodes a physical or workload number; it comes from
here. Values in the YAML are tagged nodes of the form ``{value: X, prov: tag}``
or bare scalars. Use :func:`val` to read a number regardless of which form it is.

PyYAML parses a float only when the token carries a decimal point or a signed
exponent, so a stray ``1e14`` would load as a string. :func:`load_constants`
coerces any sci-notation string back to float defensively, so the source stays
robust to that quirk (brief Section 8).
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .harness.runner import repo_root

# Matches a scientific-notation float that PyYAML may have left as a string,
# e.g. "1e14", "3.986e14", "-2.5E-3". Plain integers/words are left untouched.
_SCI = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)[eE][-+]?\d+$")


def to_float(x: Any) -> float:
    """Coerce a scalar (possibly a sci-notation string) to float."""
    if isinstance(x, bool):
        raise TypeError("refusing to coerce a bool to float")
    return float(x)


def _coerce(obj: Any) -> Any:
    """Recursively turn sci-notation strings into floats; leave the rest alone."""
    if isinstance(obj, dict):
        return {k: _coerce(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce(v) for v in obj]
    if isinstance(obj, str) and _SCI.match(obj):
        return float(obj)
    return obj


def constants_path(root: Optional[Path] = None) -> Path:
    root = Path(root) if root else repo_root()
    return root / "constants" / "constants.yaml"


@lru_cache(maxsize=1)
def load_constants() -> Dict[str, Any]:
    """Parse constants.yaml once, with sci-notation coercion applied."""
    with constants_path().open("r") as f:
        raw = yaml.safe_load(f)
    return _coerce(raw)


def val(node: Any) -> Any:
    """Read a value from a ``{value, prov}`` node or a bare scalar."""
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


# --- typed views over the two record tables the substrate and E0 need --------

@dataclass(frozen=True)
class Constellation:
    name: str
    topology: str          # "star" or "delta"
    altitude_km: float
    inclination_deg: float
    n_planes: int          # Nx
    sats_per_plane: int    # Ny
    phasing_f: Optional[int]
    isl_rate_gbps: float


@dataclass(frozen=True)
class Device:
    name: str
    peak_flops: float      # FLOP/s (or OP/s for INT8 devices; see the YAML note)
    mem_bytes: float
    mem_bw_bytes_s: float


def constellation(name: str) -> Constellation:
    c = load_constants()["constellations"][name]
    return Constellation(
        name=name,
        topology=c["topology"],
        altitude_km=to_float(c["altitude_km"]),
        inclination_deg=to_float(c["inclination_deg"]),
        n_planes=int(c["n_planes"]),
        sats_per_plane=int(c["sats_per_plane"]),
        phasing_f=None if c.get("phasing_f") is None else int(c["phasing_f"]),
        isl_rate_gbps=to_float(c["isl_rate_gbps"]),
    )


def device(name: str) -> Device:
    d = load_constants()["devices"][name]
    return Device(
        name=name,
        peak_flops=to_float(val(d["peak_flops"])),
        mem_bytes=to_float(val(d["mem_bytes"])),
        mem_bw_bytes_s=to_float(val(d["mem_bw_bytes_s"])),
    )


def duty_cycle() -> float:
    return to_float(val(load_constants()["duty_cycle"]))


def price(device_name: str) -> float:
    """Provisioning price of one satellite of this device class (cost units)."""
    return to_float(val(load_constants()["prices"][device_name]))
