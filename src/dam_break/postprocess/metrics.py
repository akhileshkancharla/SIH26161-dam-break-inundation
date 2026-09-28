"""Flood-extent comparison metrics (simulated vs observed)."""

from __future__ import annotations

import numpy as np


def extent_scores(observed: np.ndarray, simulated: np.ndarray) -> dict[str, float]:
    """CSI/F1, hit rate (POD), false-alarm ratio and bias for binary masks."""
    obs = np.asarray(observed, dtype=bool)
    sim = np.asarray(simulated, dtype=bool)
    if obs.shape != sim.shape:
        raise ValueError(f"mask shapes differ: {obs.shape} vs {sim.shape}")
    hits = int((obs & sim).sum())
    misses = int((obs & ~sim).sum())
    false = int((~obs & sim).sum())
    denom_csi = hits + misses + false
    denom_pod = hits + misses
    denom_far = hits + false
    return {
        "hits": hits,
        "misses": misses,
        "false_alarms": false,
        "csi": hits / denom_csi if denom_csi else float("nan"),
        "pod": hits / denom_pod if denom_pod else float("nan"),
        "far": false / denom_far if denom_far else float("nan"),
        "bias": (hits + false) / denom_pod if denom_pod else float("nan"),
        "f1": 2 * hits / (2 * hits + false + misses) if (2 * hits + false + misses) else float("nan"),
    }
