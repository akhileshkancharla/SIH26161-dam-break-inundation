"""DEM ingestion.

Three sources, all returning a common DEMData object on a UTM grid:

- ``aws_terrarium``: Mapzen/AWS Open Data "Terrain Tiles" (terrarium PNG).
  No authentication; elevation = R*256 + G + B/256 - 32768. Resolution at
  zoom 12 is ~38 m at the equator (finer at higher latitude), zoom 13 ~19 m.
  Sources merged by Mapzen include SRTM and ETOPO1. Attribution: AWS Open
  Data / Mapzen terrain tiles.
- ``gee_glo30``: Copernicus DEM GLO-30 via Google Earth Engine
  (``COPERNICUS/DEM/GLO30``). Requires an authenticated `ee` session
  (``earthengine-api`` extra).
- ``file:<path>``: any GDAL-readable raster (GeoTIFF, etc.).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import rasterio.warp
import requests
from PIL import Image
from pyproj import CRS
from rasterio.transform import Affine
from rasterio.warp import reproject, Resampling, calculate_default_transform

from ..preparation.terrain import utm_crs_for

TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
WEB_MERCATOR = CRS.from_epsg(3857)


@dataclass
class DEMData:
    z: np.ndarray          # elevation [m], 2-D, UTM grid
    transform: Affine
    crs: CRS
    source: str
    bbox_wgs84: tuple[float, float, float, float]  # (west, south, east, north)

    @property
    def shape(self) -> tuple[int, int]:
        return self.z.shape

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(left, bottom, right, top) in the DEM's own CRS."""
        r, c = self.z.shape
        return (
            self.transform.c,
            self.transform.f + self.transform.e * r,
            self.transform.c + self.transform.a * c,
            self.transform.f,
        )


def _slippy_tiles(bbox_wgs84, zoom: int) -> tuple[range, range]:
    west, south, east, north = bbox_wgs84

    def x_of(lon):
        return int((lon + 180.0) / 360.0 * 2**zoom)

    def y_of(lat):
        lat = max(min(lat, 85.05112878), -85.05112878)
        return int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * 2**zoom)

    x0, x1 = sorted((x_of(west), x_of(east)))
    y0, y1 = sorted((y_of(north), y_of(south)))  # y grows southwards
    return range(x0, x1 + 1), range(y0, y1 + 1)


def _tile_mercator_bounds(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    """Tile bounds in Web-Mercator meters: (west, south, east, north)."""
    n = 2**z

    def mx_of(x):
        return x / n * (2 * math.pi * 6378137.0) - math.pi * 6378137.0

    def lat_of(y):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))

    west, east = mx_of(x), mx_of(x + 1)
    north = _wgs84_to_mercator(0.0, lat_of(y))[1]
    south = _wgs84_to_mercator(0.0, lat_of(y + 1))[1]
    return west, south, east, north


def _wgs84_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    r = 6378137.0
    x = r * math.radians(lon)
    y = r * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def fetch_dem_terrarium(bbox_wgs84, zoom: int = 12, timeout: int = 60) -> DEMData:
    """Download and stitch AWS terrarium tiles, returning a Web-Mercator grid."""
    xs, ys = _slippy_tiles(bbox_wgs84, zoom)
    nx, ny = len(xs), len(ys)
    if nx * ny > 900:
        raise ValueError(
            f"DEM request too large ({nx}x{ny} tiles); lower the zoom or shrink the AOI"
        )

    mosaic = np.full((ny * 256, nx * 256), np.nan, dtype=np.float64)
    session = requests.Session()
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            url = TERRARIUM_URL.format(z=zoom, x=x, y=y)
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            img = np.asarray(Image.open(io.BytesIO(resp.content)).convert("RGB"), dtype=np.float64)
            r, g, b = img[..., 0], img[..., 1], img[..., 2]
            elev = r * 256.0 + g + b / 256.0 - 32768.0
            mosaic[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = elev

    west, south, east, north = bbox_wgs84
    mx0, my1 = _wgs84_to_mercator(west, north)   # top-left
    mx1, my0 = _wgs84_to_mercator(east, south)   # bottom-right
    # Exact mercator extent of the fetched tile block (snaps outward).
    tw, ts, te, tn = _tile_mercator_bounds(xs.start, ys.start, zoom)
    tw2, ts2, te2, tn2 = _tile_mercator_bounds(xs.stop - 1, ys.stop - 1, zoom)
    left, right = min(tw, tw2), max(te, te2)
    bottom, top = min(ts, ts2), max(tn, tn2)
    px = (right - left) / mosaic.shape[1]
    py = (top - bottom) / mosaic.shape[0]
    transform = Affine(px, 0.0, left, 0.0, -py, top)
    # Trim to the requested bbox (in tile-snapped mercator coords).
    col0 = max(int((max(mx0, left) - left) / px), 0)
    col1 = min(int((min(mx1, right) - left) / px) + 1, mosaic.shape[1])
    row0 = max(int((top - min(my1, top)) / py), 0)
    row1 = min(int((top - max(my0, bottom)) / py) + 1, mosaic.shape[0])
    mosaic = mosaic[row0:row1, col0:col1]
    transform = transform @ Affine.translation(col0, row0)
    return DEMData(
        z=mosaic, transform=transform, crs=WEB_MERCATOR,
        source=f"aws_terrarium(z{zoom})", bbox_wgs84=tuple(bbox_wgs84),
    )


def fetch_dem_gee(bbox_wgs84, timeout: int = 120) -> DEMData:
    """Copernicus GLO-30 via Earth Engine (needs ee authenticated)."""
    try:
        import ee
    except ImportError as exc:
        raise ImportError("gee_glo30 needs the 'gee' extra: pip install .[gee]") from exc
    west, south, east, north = bbox_wgs84
    region = ee.Geometry.Rectangle([west, south, east, north])
    image = ee.Image("COPERNICUS/DEM/GLO30").select("DEM").clip(region)
    url = image.getDownloadURL(
        {"format": "GEO_TIFF", "region": region, "scale": 30, "crs": "EPSG:4326"}
    )
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    with rasterio.MemoryFile(resp.content) as mem:
        with mem.open() as src:
            z = src.read(1).astype(np.float64)
            transform = src.transform
    return DEMData(
        z=z, transform=transform, crs=CRS.from_epsg(4326),
        source="copernicus_glo30_gee", bbox_wgs84=tuple(bbox_wgs84),
    )


def load_dem_file(path: str | Path, bbox_wgs84=None) -> DEMData:
    with rasterio.open(path) as src:
        z = src.read(1).astype(np.float64)
        bounds = src.bounds
        try:
            bbox_wgs84 = tuple(bbox_wgs84) if bbox_wgs84 else tuple(
                rasterio.warp.transform_bounds(src.crs, "EPSG:4326", *bounds)
            )
        except Exception:
            bbox_wgs84 = (bounds.left, bounds.bottom, bounds.right, bounds.top)
        return DEMData(
            z=z, transform=src.transform, crs=CRS.from_user_input(src.crs),
            source=f"file:{Path(path).name}", bbox_wgs84=bbox_wgs84,
        )


def to_utm_grid(dem: DEMData, resolution_m: float, target_crs: CRS | None = None) -> DEMData:
    """Reproject a DEM onto a clean UTM grid at a fixed spacing."""
    if target_crs is None:
        left, bottom, right, top = dem.bounds
        if dem.crs != CRS.from_epsg(4326):
            cx, cy = rasterio.warp.transform(
                dem.crs, "EPSG:4326", [(left + right) / 2], [(bottom + top) / 2]
            )
            lon, lat = cx[0], cy[0]
        else:
            lon, lat = (left + right) / 2, (bottom + top) / 2
        target_crs = utm_crs_for(lat, lon)
    dst_transform, width, height = calculate_default_transform(
        dem.crs, target_crs, dem.z.shape[1], dem.z.shape[0], *dem.bounds,
        resolution=resolution_m,
    )
    dst = np.full((height, width), np.nan, dtype=np.float64)
    src_nodata = np.nan
    reproject(
        source=dem.z, destination=dst,
        src_transform=dem.transform, src_crs=dem.crs, src_nodata=src_nodata,
        dst_transform=dst_transform, dst_crs=target_crs, dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return DEMData(
        z=dst, transform=dst_transform, crs=target_crs,
        source=dem.source, bbox_wgs84=dem.bbox_wgs84,
    )


def fetch_dem(spec, bbox_wgs84) -> DEMData:
    """Dispatch on TerrainSpec.dem; returns a UTM-grid DEMData when possible."""
    source = spec.dem
    if source.startswith("file:"):
        return to_utm_grid(load_dem_file(spec.dem_path, bbox_wgs84), spec.resolution_m)
    if source == "aws_terrarium":
        raw = fetch_dem_terrarium(bbox_wgs84, zoom=spec.zoom)
    elif source == "gee_glo30":
        raw = fetch_dem_gee(bbox_wgs84)
    else:
        raise ValueError(f"unknown DEM source '{source}'")
    return to_utm_grid(raw, spec.resolution_m)
