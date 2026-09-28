"""Solver-vs-solver (and solver-vs-observed) raster comparison.

Compares two maximum-depth rasters that may live on different grids:
the second raster is resampled onto the first's grid over the overlapping
extent, then binary flood masks (depth > threshold) are scored with
CSI / POD / FAR / F1 / bias and the depth fields are compared where both
are wet. ``comparison_map`` renders a three-colour overlap map (both wet /
reference only / other only).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio.warp
from rasterio.warp import reproject, Resampling

from .metrics import extent_scores


@dataclass
class RasterField:
    array: np.ndarray
    transform: object
    crs: object
    name: str = ""


def align_to_reference(ref: RasterField, other: RasterField) -> np.ndarray:
    """Resample ``other`` onto the grid of ``ref`` (bilinear), NaN outside.

    Nodata is NaN only — dry cells carry a legitimate 0.0 depth and must
    stay 0, otherwise the overlap mask would shrink to the union of wet
    cells and miss/false-alarm counts would be wrong.
    """
    dst = np.full(ref.array.shape, np.nan, dtype=np.float64)
    src = np.where(np.isfinite(other.array), other.array, np.nan)
    reproject(
        source=src,
        destination=dst,
        src_transform=other.transform, src_crs=other.crs,
        dst_transform=ref.transform, dst_crs=ref.crs,
        src_nodata=np.nan, dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return dst


def compare_depth(
    ref: RasterField,
    other: RasterField,
    threshold_m: float = 0.5,
) -> dict:
    """Score ``other`` against ``ref`` on the reference grid.

    Cells where either raster has no data (outside the overlap) are
    excluded, so a near-field SPH raster can be compared against the
    corridor-wide screening raster on the shared reach.
    """
    aligned = align_to_reference(ref, other)
    valid = np.isfinite(ref.array) & np.isfinite(aligned)
    if not valid.any():
        return {"overlap_cells": 0}

    ref_v = np.where(valid, ref.array, 0.0)
    other_v = np.where(valid, aligned, 0.0)
    scores = extent_scores(ref_v > threshold_m, other_v > threshold_m)

    both_wet = valid & (ref_v > threshold_m) & (other_v > threshold_m)
    cell_area = abs(ref.transform.a * ref.transform.e)
    result = {
        "reference": ref.name or "reference",
        "other": other.name or "other",
        "threshold_m": threshold_m,
        "overlap_cells": int(valid.sum()),
        "overlap_area_km2": float(valid.sum() * cell_area / 1e6),
        **{k: v for k, v in scores.items()},
        "ref_wet_area_km2": float((ref_v > threshold_m).sum() * cell_area / 1e6),
        "other_wet_area_km2": float((other_v > threshold_m).sum() * cell_area / 1e6),
    }
    if both_wet.any():
        diff = other_v[both_wet] - ref_v[both_wet]
        result.update({
            "depth_bias_m": float(np.mean(diff)),
            "depth_rmse_m": float(np.sqrt(np.mean(diff**2))),
            "depth_ref_mean_m": float(np.mean(ref_v[both_wet])),
            "depth_other_mean_m": float(np.mean(other_v[both_wet])),
        })
    return result


def comparison_map(
    ref: RasterField,
    other: RasterField,
    path: str | Path,
    threshold_m: float = 0.5,
    title: str = "Flood extent comparison",
) -> Path | None:
    """Three-colour overlap map: blue = both, orange = ref only, red = other only."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    aligned = align_to_reference(ref, other)
    valid = np.isfinite(ref.array) & np.isfinite(aligned)
    if not valid.any():
        return None
    ref_wet = (ref.array > threshold_m) & valid
    other_wet = (aligned > threshold_m) & valid

    rgb = np.zeros((*ref.array.shape, 3), dtype=float)
    rgb[ref_wet & other_wet] = mcolors.to_rgb("#2166ac")   # both
    rgb[ref_wet & ~other_wet] = mcolors.to_rgb("#e08214")  # reference only
    rgb[~ref_wet & other_wet] = mcolors.to_rgb("#c51b7d")  # other only

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.imshow(rgb, extent=_extent(ref.transform, ref.array.shape))
    ax.set_title(title)
    ax.set_xlabel("easting [m]")
    ax.set_ylabel("northing [m]")
    import matplotlib.patches as mpatches
    ax.legend(handles=[
        mpatches.Patch(color="#2166ac", label="both wet"),
        mpatches.Patch(color="#e08214", label=f"{ref.name or 'ref'} only"),
        mpatches.Patch(color="#c51b7d", label=f"{other.name or 'other'} only"),
    ], loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _extent(transform, shape) -> tuple[float, float, float, float]:
    ny, nx = shape
    left = transform.c
    right = transform.c + transform.a * nx
    top = transform.f
    bottom = transform.f + transform.e * ny
    return (left, right, bottom, top)
