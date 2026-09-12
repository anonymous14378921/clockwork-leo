"""Config loading. One config.yaml per experiment, loaded as a plain dict."""

from pathlib import Path
from typing import Any, Dict

import yaml


def load_config(path: Path) -> Dict[str, Any]:
    """Load an experiment's config.yaml into a dict.

    No schema, no magic: whatever is in the YAML is what the experiment sees.
    The dict is copied verbatim into the results dir as provenance.
    """
    path = Path(path)
    with path.open("r") as f:
        cfg = yaml.safe_load(f)
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise ValueError(f"{path} must contain a YAML mapping, got {type(cfg).__name__}")
    return cfg
