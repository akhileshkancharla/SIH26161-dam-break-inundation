"""Near-real-time flood mapping from Sentinel-1 in Google Earth Engine.

Implements the UN-SPIDER recommended practice: pre/post change detection on
VV backscatter [dB], exclusion of permanent water (JRC GSW) and steep slopes
(Copernicus GLO-30), then vectorisation and exposure overlay.

Needs the ``gee`` extra and an authenticated session
(``earthengine authenticate`` / ``ee.Authenticate()``).
"""

from __future__ import annotations


def _require_ee():
    try:
        import ee
        return ee
    except ImportError as exc:
        raise ImportError("GEE module needs the 'gee' extra: pip install .[gee]") from exc


def init_ee(project: str | None = None) -> None:
    """Authenticate/initialize; call once per session."""
    ee = _require_ee()
    try:
        ee.Initialize(project=project) if project else ee.Initialize()
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project) if project else ee.Initialize()


def s1_median(aoi, start: str, end: str):
    """Median VV mosaic over the AOI in the given date window [dB]."""
    from ..nrt import flood_map as fm
    return fm.s1_composite(aoi, start, end)[0]


def flood_mask(aoi, before: tuple[str, str], after: tuple[str, str],
               drop_db: float = -3.0, after_max_db: float = -15.0):
    """Flooded-area mask (unmasked where valid), excluding permanent water
    and slopes over 5 degrees. ``before``/``after`` are (start, end) dates.

    Single-AOI convenience wrapper; the detection core lives in
    ``dam_break.nrt.flood_map`` (shared with the automated watchlist).
    """
    from ..nrt import flood_map as fm

    flood01, _, _, _ = fm.detect_flood(
        aoi, after[0], after[1], before[0], before[1],
        change_db=drop_db, water_db=after_max_db, slope_max_deg=5.0)
    return flood01.selfMask().rename("flood")


def flood_area_km2(mask, aoi) -> float:
    ee = _require_ee()
    area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=aoi, scale=30, maxPixels=1e10
    )
    return float(area.getInfo().get("flood", 0.0)) / 1e6


def flood_polygons_gdf(mask, aoi, max_pixels: int = 3e6):
    """Small-AOI helper: vectorise the mask to a WGS84 GeoDataFrame."""
    import geopandas as gpd
    import shapely.geometry

    ee = _require_ee()
    vectors = mask.reduceToVectors(
        geometry=aoi, scale=30, eightConnected=True, maxPixels=int(max_pixels),
        geometryType="polygon", reducer=ee.Reducer.countEvery(),
    )
    feats = vectors.getInfo().get("features", [])
    geoms = [shapely.geometry.Polygon(f["geometry"]["coordinates"][0]) for f in feats]
    if not geoms:
        return gpd.GeoDataFrame(columns=["geometry"], crs="EPSG:4326")
    return gpd.GeoDataFrame({"pixel_count": [1] * len(geoms)}, geometry=geoms, crs="EPSG:4326")


def export_mask_drive(mask, aoi, description: str, folder: str = "SIH26161_flood") -> None:
    """Kick off a Drive export of the flood mask as GeoTIFF."""
    ee = _require_ee()
    task = ee.batch.Export.image.toDrive(
        image=mask, description=description, folder=folder,
        region=aoi, scale=30, maxPixels=1e10,
    )
    task.start()
