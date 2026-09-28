"""Land cover -> Manning's n roughness mapping (ESA WorldCover v200 classes)."""

from __future__ import annotations

import numpy as np

# WorldCover class code -> Manning's n (starter values from the technical
# guide; calibrate per reach before quoting results).
WORLDCOVER_N: dict[int, float] = {
    10: 0.10,   # tree cover
    20: 0.12,   # shrubland
    30: 0.10,   # grassland
    40: 0.10,   # cropland
    50: 0.04,   # built-up
    60: 0.035,  # bare/sparse vegetation
    70: 0.07,   # snow/ice
    80: 0.03,   # permanent water bodies
    90: 0.06,   # herbaceous wetland
    95: 0.10,   # mangroves
    100: 0.15,  # moss/lichen
}


def roughness_from_landcover(landcover: np.ndarray | None, default_n: float = 0.05) -> np.ndarray:
    """Map WorldCover codes to Manning's n; constant where no land cover exists."""
    if landcover is None:
        raise ValueError("landcover array is None")
    n = np.full(landcover.shape, default_n, dtype=np.float64)
    for code, value in WORLDCOVER_N.items():
        n[landcover == code] = value
    return n
