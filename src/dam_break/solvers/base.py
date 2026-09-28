"""Shared solver result containers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from rasterio.transform import Affine


@dataclass
class RasterLayer:
    array: np.ndarray
    transform: Affine
    crs: Any
    units: str = "m"
    long_name: str = ""
    nodata: float = float("nan")


@dataclass
class SolverResult:
    solver: str
    layers: dict[str, RasterLayer] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
