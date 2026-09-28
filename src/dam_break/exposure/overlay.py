"""Exposure overlay: flood polygons against land cover (and optional rasters).

Offline path uses the WorldCover grid already fetched with the DEM (class 40
cropland, 50 built-up, 20/30/10 vegetation). Population/building exposure
via GEE/GHSL lives in the satellite module for the near-real-time workflow.
"""

from __future__ import annotations

import numpy as np
import geopandas as gpd
import rasterio.features

# WorldCover v200 class labels.
WORLDCOVER_CLASSES = {
    10: "tree_cover", 20: "shrubland", 30: "grassland", 40: "cropland",
    50: "built_up", 60: "bare_sparse", 70: "snow_ice", 80: "water",
    90: "wetland", 95: "mangroves", 100: "moss_lichen",
}


def exposure_from_landcover(
    flood_mask: np.ndarray,
    landcover: np.ndarray | None,
    transform,
    cell_area_m2: float,
) -> dict[str, dict[str, float]]:
    """Area of each land-cover class inside the flood mask [ha]."""
    if landcover is None:
        return {"note": "no land-cover grid supplied; exposure skipped"}
    out: dict[str, dict[str, float]] = {}
    wet = flood_mask & np.isfinite(landcover) & (landcover > 0)
    for code, label in WORLDCOVER_CLASSES.items():
        cells = int((wet & (landcover == code)).sum())
        if cells:
            out[label] = {
                "cells": cells,
                "area_ha": cells * cell_area_m2 / 1e4,
            }
    return out


def zonal_depth_by_class(
    depth: np.ndarray,
    landcover: np.ndarray,
    transform,
) -> dict[str, float]:
    """Mean flood depth per land-cover class (m)."""
    wet = depth > 0.1
    out: dict[str, float] = {}
    for code, label in WORLDCOVER_CLASSES.items():
        m = wet & (landcover == code)
        if m.any():
            out[label] = float(np.nanmean(depth[m]))
    return out
