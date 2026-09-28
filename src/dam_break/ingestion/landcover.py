"""ESA WorldCover v2021 (v200) land-cover ingestion via Google Earth Engine."""

from __future__ import annotations

import numpy as np
import requests
import rasterio
from pyproj import CRS
from rasterio.warp import reproject, Resampling

from .dem import DEMData


def fetch_worldcover_gee(dem: DEMData, timeout: int = 120) -> np.ndarray:
    """WorldCover classes resampled onto the DEM's grid (nearest neighbour).

    Requested at the DEM's own resolution: at native 10 m a corridor-sized
    tile exceeds GEE's ~50 MB GeoTIFF download cap. Returns ``None``-free
    class codes; cells outside coverage get 0.
    """
    try:
        import ee
    except ImportError as exc:
        raise ImportError("worldcover_gee needs the 'gee' extra: pip install .[gee]") from exc

    west, south, east, north = dem.bbox_wgs84
    region = ee.Geometry.Rectangle([west, south, east, north])
    image = (
        ee.ImageCollection("ESA/WorldCover/v200")
        .first()
        .select("Map")
        .clip(region)
    )
    scale = float(abs(dem.transform.a)) or 30.0
    url = image.getDownloadURL(
        {"format": "GEO_TIFF", "region": region, "scale": scale, "crs": "EPSG:4326"}
    )
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    with rasterio.MemoryFile(resp.content) as mem:
        with mem.open() as src:
            lc = src.read(1)

    dst = np.zeros(dem.shape, dtype=np.int16)
    reproject(
        source=lc, destination=dst,
        src_transform=src.transform, src_crs=CRS.from_epsg(4326),
        dst_transform=dem.transform, dst_crs=dem.crs,
        resampling=Resampling.nearest,
    )
    return dst
