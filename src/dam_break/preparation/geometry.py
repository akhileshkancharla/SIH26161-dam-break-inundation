"""DEM patch exports for particle-based (SPH) near-field models."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def dem_to_xyz(
    z: np.ndarray,
    transform,
    out_path: str | Path,
    target_spacing_m: float = 2.0,
) -> Path:
    """Write scattered XYZ samples ("x y z" per line) decimated to roughly
    the target spacing — the format DualSPHysics ``zpoints`` ingests."""
    cell = abs(transform.a)
    step = max(1, int(round(target_spacing_m / cell))) if cell > 0 else 1
    zz = z[::step, ::step]
    rows, cols = np.indices(zz.shape)
    xs = transform.c + (cols * step + 0.5) * transform.a
    ys = transform.f + (rows * step + 0.5) * transform.e
    pts = np.column_stack([xs.ravel(), ys.ravel(), zz.ravel()])
    pts = pts[np.isfinite(pts[:, 2])]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(out_path, pts, fmt="%.2f %.2f %.3f")
    return out_path


def dem_to_stl(
    z: np.ndarray,
    transform,
    out_path: str | Path,
    coarsen: int = 4,
    vertical_scale: float = 1.0,
) -> Path:
    """Write a binary STL of the DEM surface (triangulated regular grid).

    ``coarsen`` reduces the grid before triangulation to keep the triangle
    count manageable for DualSPHysics geometry (factor 4 on a 30 m DEM gives
    ~120 m facets, adequate for a 1-3 km near-field box).
    """
    ny, nx = z.shape
    f = max(1, int(coarsen))
    ny2, nx2 = ny // f, nx // f
    zz = z[: ny2 * f, : nx2 * f].reshape(ny2, f, nx2, f).mean(axis=(1, 3))

    xs = transform.c + (np.arange(nx2) * f + 0.5) * transform.a
    ys = transform.f + (np.arange(ny2) * f + 0.5) * transform.e
    xx, yy = np.meshgrid(xs, ys)

    p1 = np.stack([xx[:-1, :-1], yy[:-1, :-1], zz[:-1, :-1] * vertical_scale], axis=-1)
    p2 = np.stack([xx[1:, :-1], yy[1:, :-1], zz[1:, :-1] * vertical_scale], axis=-1)
    p3 = np.stack([xx[1:, 1:], yy[1:, 1:], zz[1:, 1:] * vertical_scale], axis=-1)
    p4 = np.stack([xx[:-1, 1:], yy[:-1, 1:], zz[:-1, 1:] * vertical_scale], axis=-1)

    tri_a = np.concatenate([p1.reshape(-1, 3), p1.reshape(-1, 3)], axis=0)
    tri_b = np.concatenate([p2.reshape(-1, 3), p3.reshape(-1, 3)], axis=0)
    tri_c = np.concatenate([p3.reshape(-1, 3), p4.reshape(-1, 3)], axis=0)

    v1 = tri_b - tri_a
    v2 = tri_c - tri_a
    normals = np.cross(v1, v2)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    normals = normals / lengths

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(b"dam-break dem surface".ljust(80, b" "))
        fh.write(struct.pack("<I", len(tri_a)))
        for nrm, a, b, c in zip(normals, tri_a, tri_b, tri_c):
            fh.write(struct.pack("<3f", *nrm))
            fh.write(struct.pack("<3f", *a))
            fh.write(struct.pack("<3f", *b))
            fh.write(struct.pack("<3f", *c))
            fh.write(struct.pack("<H", 0))
    return out_path
