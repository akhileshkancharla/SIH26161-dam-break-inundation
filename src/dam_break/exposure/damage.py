"""Indicative depth-damage loss analysis on land-cover exposure.

Applies stage-damage curves to the flood depth raster per land-cover class
and returns damage fractions, areas and an indicative monetary loss. The
curves and asset values shipped here are STARTER VALUES assembled from
JRC-style global flood depth-damage functions (Huizinga et al. 2017) from
background knowledge — they give the machinery and the right shape, but
they must be reviewed against the actual report and regional Indian
sources before quoting any rupee figure (see docs/verification-log.md).
"""

from __future__ import annotations

from pathlib import Path
import json

import numpy as np

# Piecewise-linear damage-fraction knots (depth [m], fraction) per
# WorldCover class group. Indicative; TODO verify vs JRC / NDMA curves.
DAMAGE_CURVES: dict[str, list[tuple[float, float]]] = {
    "built_up": [(0.0, 0.0), (0.5, 0.15), (1.0, 0.25), (1.5, 0.32),
                 (2.0, 0.38), (3.0, 0.45), (4.0, 0.50), (6.0, 0.60)],
    "cropland": [(0.0, 0.0), (0.25, 0.30), (0.5, 0.50), (1.0, 0.70),
                 (1.5, 0.80), (2.0, 0.85), (3.0, 0.90)],
    "tree_cover": [(0.0, 0.0), (0.5, 0.05), (1.0, 0.10), (2.0, 0.15),
                   (4.0, 0.25)],
    "grassland": [(0.0, 0.0), (0.5, 0.05), (1.0, 0.10), (2.0, 0.15)],
    "shrubland": [(0.0, 0.0), (0.5, 0.05), (1.0, 0.10), (2.0, 0.15)],
}

# Indicative replacement/asset values (INR per m2 of class area).
ASSET_VALUES_INR_M2: dict[str, float] = {
    "built_up": 8000.0,
    "cropland": 150.0,       # seasonal crop value per m2
    "tree_cover": 100.0,
    "grassland": 20.0,
    "shrubland": 20.0,
}

# WorldCover class code -> damage curve group.
WORLDCOVER_TO_GROUP = {
    10: "tree_cover", 20: "shrubland", 30: "grassland", 40: "cropland",
    50: "built_up", 60: "grassland", 70: "grassland", 80: "cropland",
    90: "cropland", 95: "tree_cover", 100: "tree_cover",
}


def damage_fraction(group: str, depth_m: np.ndarray | float) -> np.ndarray | float:
    """Piecewise-linear interpolation of the class damage curve."""
    knots = DAMAGE_CURVES.get(group)
    if knots is None:
        return np.zeros_like(depth_m) if isinstance(depth_m, np.ndarray) else 0.0
    xs = [k[0] for k in knots]
    ys = [k[1] for k in knots]
    if isinstance(depth_m, np.ndarray):
        return np.interp(np.clip(depth_m, 0.0, xs[-1]), xs, ys)
    return float(np.interp(min(max(depth_m, 0.0), xs[-1]), xs, ys))


def load_damage_params(path: str | Path) -> dict:
    """Optional overrides: {"curves": {group: [[d, f], ...]},
    "asset_values_inr_m2": {group: v}, "class_map": {code: group}}."""
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    for group, knots in data.get("curves", {}).items():
        DAMAGE_CURVES[group] = [tuple(k) for k in knots]
    ASSET_VALUES_INR_M2.update(data.get("asset_values_inr_m2", {}))
    WORLDCOVER_TO_GROUP.update({int(k): v for k, v in data.get("class_map", {}).items()})
    return data


def loss_from_landcover(
    depth: np.ndarray,
    landcover: np.ndarray,
    cell_area_m2: float,
    min_depth_m: float = 0.1,
) -> dict:
    """Damage fraction, hit area and indicative loss per land-cover group.

    ``depth`` and ``landcover`` must share a grid (the pipeline guarantees
    this by building both on the DEM grid). Classes mapping to the same
    damage group (e.g. WorldCover 40 and 80 -> cropland) are accumulated.
    """
    wet = depth > min_depth_m
    groups: dict[str, dict] = {}
    for code in np.unique(landcover):
        code = int(code)
        if code == 0:
            continue
        group = WORLDCOVER_TO_GROUP.get(code)
        if group is None:
            continue
        mask = wet & (landcover == code)
        if not mask.any():
            continue
        g = groups.setdefault(group, {
            "codes": [], "cells": 0, "area_m2": 0.0,
            "frac_sum": 0.0, "depth_sum": 0.0,
        })
        g["codes"].append(code)
        g["cells"] += int(mask.sum())
        g["area_m2"] += float(mask.sum() * cell_area_m2)
        g["frac_sum"] += float(np.sum(damage_fraction(group, depth[mask])))
        g["depth_sum"] += float(np.sum(depth[mask]))

    by_class: dict[str, dict] = {}
    for group, g in groups.items():
        value = ASSET_VALUES_INR_M2.get(group, 0.0)
        by_class[group] = {
            "worldcover_codes": sorted(g["codes"]),
            "hit_cells": g["cells"],
            "hit_area_ha": g["area_m2"] / 1e4,
            "mean_depth_m": g["depth_sum"] / g["cells"],
            "damage_fraction_area_avg": g["frac_sum"] / g["cells"],
            "asset_value_inr": g["area_m2"] * value,
            "indicative_loss_inr": g["frac_sum"] * cell_area_m2 * value,
        }

    total_loss = sum(r["indicative_loss_inr"] for r in by_class.values())
    return {
        "by_class": by_class,
        "total_indicative_loss_inr": total_loss,
        "total_indicative_loss_crore_inr": total_loss / 1e7,
        "caveat": "indicative only: starter curves and asset values, not calibrated",
    }
