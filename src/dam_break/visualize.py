"""Quick-look plots (matplotlib, Agg-safe)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def plot_hydrograph(t_s, q, path: str | Path, title: str = "Breach outflow hydrograph") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t_h = np.asarray(t_s) / 3600.0
    q = np.asarray(q)
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(t_h, q, color="#2166ac", lw=1.8)
    ax.set_xlabel("time [h]")
    ax.set_ylabel("Q [m$^3$/s]")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    ax.set_xlim(0, max(t_h.max(), 1e-9))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


_DEPTHS_CMAP = [
    (0.00, "#f7fbff"),
    (0.05, "#c6dbef"),
    (0.20, "#6baed6"),
    (0.50, "#2171b5"),
    (1.00, "#08306b"),
    (2.00, "#081d5c"),
    (4.00, "#050f3d"),
]


def _depth_colormap():
    from matplotlib.colors import LinearSegmentedColormap

    vmax = _DEPTHS_CMAP[-1][0]
    return LinearSegmentedColormap.from_list(
        "flooddepth", [(p / vmax, c) for p, c in _DEPTHS_CMAP]
    )


def plot_raster(
    array,
    transform,
    path: str | Path,
    title: str = "",
    units: str = "",
    cmap=None,
    vmin=None,
    vmax=None,
    hillshade_under: np.ndarray | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 7))
    if hillshade_under is not None:
        ax.imshow(_hillshade(hillshade_under), cmap="gray", alpha=0.35,
                  extent=_extent(transform, hillshade_under.shape))
    im = ax.imshow(
        np.ma.masked_invalid(array), cmap=cmap or _depth_colormap(),
        vmin=0.0 if vmin is None and cmap is None else vmin,
        vmax=vmax,
        extent=_extent(transform, array.shape),
    )
    ax.set_title(title)
    ax.set_xlabel("easting [m]")
    ax.set_ylabel("northing [m]")
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label(units)
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


def _hillshade(z: np.ndarray, azimuth: float = 315.0, altitude: float = 45.0) -> np.ndarray:
    z = np.asarray(z, dtype=np.float64)
    gy, gx = np.gradient(z)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = np.radians(360.0 - azimuth + 90.0)
    alt = np.radians(altitude)
    shaded = np.sin(alt) * np.sin(slope) + np.cos(alt) * np.cos(slope) * np.cos(az - aspect + np.pi / 2.0)
    return np.clip(shaded / np.nanmax(shaded), 0, 1)
