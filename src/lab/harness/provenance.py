"""Provenance capture: git state + hardware manifest.

Best-effort and dependency-light. Nothing here raises if a tool is missing;
absent facts are recorded as null so a run never fails over provenance.
"""

import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


def _run(cmd, cwd: Optional[Path] = None) -> Optional[str]:
    try:
        out = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=10
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def git_commit(repo: Path) -> Optional[str]:
    return _run(["git", "rev-parse", "HEAD"], cwd=repo)


def git_dirty(repo: Path) -> Optional[bool]:
    status = _run(["git", "status", "--porcelain"], cwd=repo)
    if status is None:
        return None
    return bool(status.strip())


def _total_ram_bytes() -> Optional[int]:
    system = platform.system()
    try:
        if system == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        elif system == "Darwin":
            out = _run(["sysctl", "-n", "hw.memsize"])
            return int(out) if out else None
        # POSIX fallback
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        return None


def _cpu_model() -> Optional[str]:
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    elif platform.system() == "Darwin":
        model = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if model:
            return model
    return platform.processor() or None


def gpu_manifest() -> Optional[list]:
    """nvidia-smi output if present, else None. No GPU is a fact, not an error."""
    if shutil.which("nvidia-smi") is None:
        return None
    out = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
         "--format=csv,noheader"]
    )
    if not out:
        return None
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            gpus.append({"name": parts[0], "memory": parts[1], "driver": parts[2]})
    return gpus or None


def hardware_manifest() -> Dict[str, Any]:
    ram = _total_ram_bytes()
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "ram_gb": round(ram / 1e9, 1) if ram else None,
        "gpu": gpu_manifest(),
        "python": platform.python_version(),
    }


def capture_provenance(repo: Path) -> Dict[str, Any]:
    """Everything needed to know how a result was produced, except the config."""
    return {
        "git_commit": git_commit(repo),
        "git_dirty": git_dirty(repo),
        "hardware": hardware_manifest(),
    }
