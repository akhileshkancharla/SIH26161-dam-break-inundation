"""Terrain preparation: UTM CRS selection, depression filling, flow-path tracing."""

from __future__ import annotations

import heapq

import numpy as np
from pyproj import CRS


def utm_crs_for(lat: float, lon: float) -> CRS:
    """UTM CRS (north/south by latitude) for a WGS84 point."""
    zone = int((lon + 180.0) // 6.0) + 1
    south = lat < 0
    return CRS.from_epsg(32700 + zone if south else 32600 + zone)


def priority_flood_fill(z: np.ndarray, epsilon: float = 1e-6) -> np.ndarray:
    """Depression-filled DEM (Barnes et al. priority-flood, epsilon variant).

    Pure-Python heapq implementation; fine up to a few million cells.
    """
    z = np.asarray(z, dtype=np.float64)
    ny, nx = z.shape
    filled = np.full_like(z, np.inf)
    visited = np.zeros(z.shape, dtype=bool)
    heap: list[tuple[float, int, int]] = []

    def push(row: int, col: int) -> None:
        if not visited[row, col]:
            visited[row, col] = True
            heapq.heappush(heap, (float(z[row, col]), row, col))

    for col in range(nx):
        push(0, col)
        push(ny - 1, col)
    for row in range(ny):
        push(row, 0)
        push(row, nx - 1)

    neighbours = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    while heap:
        zc, r, c = heapq.heappop(heap)
        filled[r, c] = zc
        for dr, dc in neighbours:
            rr, cc = r + dr, c + dc
            if 0 <= rr < ny and 0 <= cc < nx and not visited[rr, cc]:
                visited[rr, cc] = True
                heapq.heappush(heap, (max(float(z[rr, cc]), zc + epsilon), rr, cc))
    return filled


def trace_flow_path(
    filled_dem: np.ndarray,
    start_row: int,
    start_col: int,
    transform,
    max_length_m: float,
    cell_size_m: float | None = None,
) -> list[tuple[float, float]]:
    """D8 steepest-descent path on a filled DEM, as a list of (x, y) CRS coords."""
    z = np.asarray(filled_dem, dtype=np.float64)
    ny, nx = z.shape
    # Diagonals cost sqrt(2) * cell size.
    if cell_size_m is None:
        a, b, c, d, e, f = transform.a, transform.b, transform.c, transform.d, transform.e, transform.f
        cell_size_m = float(np.hypot(a, b))

    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    diag = 2**0.5
    r, c = int(start_row), int(start_col)
    path = [(r, c)]
    dist = 0.0
    seen = {(r, c)}
    while dist < max_length_m:
        zc = z[r, c]
        best, best_slope = None, 0.0
        for dr, dc in offsets:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < ny and 0 <= cc < nx) or (rr, cc) in seen:
                continue
            step = diag if (dr != 0 and dc != 0) else 1.0
            slope = (zc - z[rr, cc]) / step
            if slope > best_slope:
                best_slope, best = slope, (rr, cc)
        if best is None:
            break  # reached a divide or exhausted neighbours
        r, c = best
        seen.add((r, c))
        path.append((r, c))
        dist += (diag if (r - path[-2][0] != 0 and c - path[-2][1] != 0) else 1.0) * cell_size_m
    coords = [transform @ (col, row) for row, col in path]
    return coords


def coarsen(z: np.ndarray, factor: int) -> tuple[np.ndarray, float]:
    """Block-min downsample; returns (array, factor) for tracing on big DEMs."""
    if factor <= 1:
        return z, 1.0
    ny, nx = z.shape
    ny2, nx2 = ny // factor, nx // factor
    trimmed = z[: ny2 * factor, : nx2 * factor]
    small = trimmed.reshape(ny2, factor, nx2, factor).min(axis=(1, 3))
    return small, float(factor)


def slope_magnitude(z: np.ndarray, cell_size_m: float) -> np.ndarray:
    """Terrain slope magnitude [m/m] via central differences."""
    gy, gx = np.gradient(z, cell_size_m, cell_size_m)
    return np.hypot(gx, gy)
