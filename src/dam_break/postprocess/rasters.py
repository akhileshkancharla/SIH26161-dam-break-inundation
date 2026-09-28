"""Raster post-processing: hazard classes and GeoTIFF/COG output."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine

from ..solvers.base import RasterLayer

# Depth classes [m]: labels used across polygons, exports and the dashboard.
DEPTH_CLASSES: list[tuple[float, float | None, str]] = [
    (0.1, 0.5, "0.1-0.5 m"),
    (0.5, 1.0, "0.5-1 m"),
    (1.0, 2.0, "1-2 m"),
    (2.0, 4.0, "2-4 m"),
    (4.0, None, "> 4 m"),
]

# h*v [m2/s] thresholds for people/vehicles (low) and buildings (high).
HAZARD_HV = {"low": 0.5, "high": 2.0}


def classify_depth(depth: np.ndarray) -> np.ndarray:
    """Class codes 1..N matching DEPTH_CLASSES; 0 = dry."""
    out = np.zeros(depth.shape, dtype=np.uint8)
    for i, (lo, hi, _label) in enumerate(DEPTH_CLASSES, start=1):
        mask = depth >= lo if hi is None else (depth >= lo) & (depth < hi)
        out[mask] = i
    return out


def classify_hazard(depth: np.ndarray, velocity: np.ndarray) -> np.ndarray:
    """0 dry, 1 low, 2 medium, 3 high by depth x velocity."""
    hv = depth * velocity
    out = np.zeros(depth.shape, dtype=np.uint8)
    out[depth > 0.1] = 1
    out[hv >= HAZARD_HV["low"]] = 2
    out[hv >= HAZARD_HV["high"]] = 3
    return out


def write_raster(
    path: str | Path,
    array: np.ndarray,
    transform: Affine,
    crs,
    nodata=np.nan,
    cog: bool = True,
) -> Path:
    """Write a single-band GeoTIFF (COG when rasterio supports it)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dtype = "float32" if np.issubdtype(array.dtype, np.floating) else str(array.dtype)
    profile = {
        "driver": "GTiff",
        "height": array.shape[0],
        "width": array.shape[1],
        "count": 1,
        "dtype": dtype,
        "crs": crs,
        "transform": transform,
        "nodata": None if (nodata is not None and np.isnan(nodata)) else nodata,
        "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype(dtype), 1)
        try:
            dst.build_overviews([2, 4, 8, 16], rasterio.enums.Resampling.nearest)
            dst.update_tags(NS="rasterio", COG="true")
        except Exception:
            pass
    if cog:
        try:
            tmp = path.with_suffix(".cog.tmp")
            rasterio.shutil.copy(path, tmp, driver="COG", compress="deflate")
            tmp.replace(path)
        except Exception:
            pass  # plain GTiff is fine if the COG driver is unavailable
    return path


def write_layer(path: str | Path, layer: RasterLayer) -> Path:
    return write_raster(path, layer.array, layer.transform, layer.crs)
