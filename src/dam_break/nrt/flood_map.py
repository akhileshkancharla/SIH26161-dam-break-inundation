"""Sentinel-1 flood mapping on Google Earth Engine (UN-SPIDER practice).

Follows the team technical guide (Section 7): COPERNICUS/S1_GRD VV median
composites for before/after windows with a 50 m circular focal-median
despeckle; flood = (after - before < change_db) AND (after < water_db);
exclude JRC permanent water (occurrence > 80) and terrain steeper than
``slope_max_deg`` (GLO-30). Sentinel-1 revisit is on the order of days, so
this is near-real-time, not live. dB thresholds are site-tunable.

Known caveats (state them wherever results are shown): SAR shadow/layover
in mountains, wind-roughened water, urban double-bounce misses floods
under buildings, and thresholds need per-site tuning.
"""

from __future__ import annotations

import datetime as dt

S1_COLLECTION = "COPERNICUS/S1_GRD"
GSW = "JRC/GSW1_4/GlobalSurfaceWater"
GLO30 = "COPERNICUS/DEM/GLO30"

DEFAULT_CHANGE_DB = -3.0   # after - before drop indicating new water
DEFAULT_WATER_DB = -15.0   # absolute backscatter of open water
PERM_OCCURRENCE = 80       # JRC occurrence above this = permanent water


def _ee():
    import ee  # deferred: tests and non-GEE runs never touch this module path
    return ee


def aoi_box(lon: float, lat: float, size_km: float):
    """Square WGS84 box of side ``size_km`` centred on the dam."""
    d = float(size_km) / 111.0
    return _ee().Geometry.Rectangle(
        [lon - d, lat - d, lon + d, lat + d], proj="EPSG:4326", evenOdd=False)


def s1_composite(aoi, start: str, end: str):
    """Despeckled VV median composite over [start, end] plus its collection."""
    ee = _ee()
    col = (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .select("VV")
    )
    return col.median().focal_median(50, "circle", "meters"), col


def collection_meta(col) -> dict:
    """Scene count and first/last acquisition times (one getInfo call)."""
    ee = _ee()
    info = ee.Dictionary({
        "n": col.size(),
        "first_ms": col.aggregate_min("system:time_start"),
        "last_ms": col.aggregate_max("system:time_start"),
    }).getInfo()
    out = {"n": int(info["n"])}
    for k in ("first", "last"):
        ms = info.get(f"{k}_ms")
        out[k] = (
            dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC") if ms is not None else None
        )
    return out


def detect_flood(aoi, after_start: str, after_end: str,
                 before_start: str, before_end: str,
                 change_db: float = DEFAULT_CHANGE_DB,
                 water_db: float = DEFAULT_WATER_DB,
                 slope_max_deg: float | None = 5.0):
    """Build the flood/water/permanent masks over the AOI (server-side).

    Returns ``(flood01, water01, perm01, meta)`` where masks are unmasked
    0/1 ee.Images; ``meta`` holds both windows' scene counts and dates
    (one getInfo round-trip) so callers can report data freshness.
    """
    ee = _ee()
    after, col_after = s1_composite(aoi, after_start, after_end)
    before, col_before = s1_composite(aoi, before_start, before_end)

    new_water = after.subtract(before).lt(change_db).And(after.lt(water_db))
    perm = ee.Image(GSW).select("occurrence").gt(PERM_OCCURRENCE)
    masks = new_water.updateMask(perm.Not())
    if slope_max_deg is not None:
        dem = ee.ImageCollection(GLO30).select("DEM").mosaic()
        masks = masks.updateMask(ee.Terrain.slope(dem).lt(slope_max_deg))

    flood01 = masks.unmask(0)
    water01 = after.lt(water_db).unmask(0)
    perm01 = perm.unmask(0)
    meta = {
        "after": collection_meta(col_after),
        "before": collection_meta(col_before),
    }
    return flood01, water01, perm01, meta


def area_stats(flood01, water01, perm01, aoi, scale_m: float = 100):
    """km2 areas of flood / all surface water / permanent water (one call)."""
    ee = _ee()
    area = ee.Image.pixelArea()
    stacked = (
        area.multiply(flood01.rename("flood"))
        .addBands(area.multiply(water01.rename("water")))
        .addBands(area.multiply(perm01.rename("perm")))
    )
    res = stacked.reduceRegion(
        ee.Reducer.sum(), aoi, scale=scale_m, maxPixels=1e10
    ).getInfo()
    return {k: float(v or 0.0) / 1e6 for k, v in res.items()}


def flood_vectors(flood01, aoi, scale_m: float = 100, max_features: int = 5000):
    """Flood polygons as a GeoJSON dict (empty dict when nothing is flooded)."""
    ee = _ee()
    vec = flood01.selfMask().reduceToVectors(
        geometry=aoi, scale=scale_m, geometryType="polygon",
        eightConnected=True, maxPixels=1e10,
    ).limit(max_features)
    return vec.getInfo()
