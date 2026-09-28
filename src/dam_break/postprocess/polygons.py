"""Inundation polygons and exports (.shp / .gpkg / .kml / .geojson)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio.features
from shapely.geometry import shape

from .rasters import DEPTH_CLASSES, classify_depth

# Class colours (hex, without #) for KML; blue ramp light -> dark.
CLASS_COLORS = ["67a9cf", "2166ac", "1b4a8b", "123566", "0a1f3d"]


def depth_polygons(
    depth: np.ndarray,
    transform,
    crs,
    min_depth: float = 0.1,
    min_patch_ha: float = 0.25,
) -> gpd.GeoDataFrame:
    """Dissolved inundation polygons per depth class.

    Patches smaller than ``min_patch_ha`` are sieved away before
    polygonisation to avoid sliver polygons from raster noise.

    Fields (kept shapefile-safe, <= 10 chars): dclass, dlo_m, dhi_m,
    area_ha, maxdepth.
    """
    cell_area = abs(transform.a * transform.e)
    sieve_size = max(2, int(min_patch_ha * 1e4 / cell_area))
    classes = classify_depth(np.where(depth >= min_depth, depth, 0.0))
    records = []
    for i, (lo, hi, label) in enumerate(DEPTH_CLASSES, start=1):
        mask = classes == i
        if not mask.any():
            continue
        mask = rasterio.features.sieve(
            mask.astype(np.uint8), size=sieve_size
        ).astype(bool)
        if not mask.any():
            continue
        geoms = [shape(g) for g, v in rasterio.features.shapes(
            classes, mask=mask, transform=transform, connectivity=8
        ) if v == i]
        if not geoms:
            continue
        from shapely.ops import unary_union
        geom = unary_union(geoms)
        records.append({
            "dclass": label,
            "dlo_m": lo,
            "dhi_m": hi if hi is not None else -1.0,
            "maxdepth": float(np.nanmax(depth[mask])),
            "area_ha": geom.area / 1e4,
            "geometry": geom,
        })
    if not records:
        return gpd.GeoDataFrame(columns=["dclass", "geometry"], crs=crs)
    gdf = gpd.GeoDataFrame(records, crs=crs)
    return gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf


def export_shp(gdf: gpd.GeoDataFrame, path: str | Path) -> Path:
    """Write a shapefile and zip it with all sidecars (.shp/.shx/.dbf/.prj)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="ESRI Shapefile")
    stem = path.with_suffix("")
    sides = [p for p in path.parent.glob(stem.name + ".*")
             if p.suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg")]
    zip_path = path.with_suffix(".shp.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sides:
            zf.write(p, arcname=p.name)
    return zip_path


def export_kml(gdf: gpd.GeoDataFrame, path: str | Path, name: str = "inundation") -> Path:
    """KML coloured by depth class (simplekml; expects WGS84 input gdf).

    Boundaries are set via simplekml's outerboundaryis API — assigning a
    shapely ``__geo_interface__`` to ``pol.geometry`` silently writes
    degenerate 0,0 rings.
    """
    import simplekml

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kml = simplekml.Kml()
    kml.document.name = name
    for _, row in gdf.iterrows():
        idx = _class_index(row.get("dclass"))
        color = f"ff{CLASS_COLORS[idx]}"
        geom = row.geometry
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for part in parts:
            if part.is_empty or part.exterior is None:
                continue
            pol = kml.newpolygon(name=str(row.get("dclass", "flood")))
            pol.outerboundaryis = [(x, y) for x, y in part.exterior.coords]
            if part.interiors:
                pol.innerboundaryis = [(x, y) for x, y in part.interiors[0].coords]
            pol.style.polystyle.color = color
            pol.style.linestyle.color = color
            pol.style.polystyle.outline = 1
            for field in ("dclass", "maxdepth", "area_ha", "dlo_m", "dhi_m"):
                if field in row:
                    pol.extendeddata.newdata(name=field, value=str(row[field]))
    kml.save(path)
    return path


def export_vectors(
    gdf: gpd.GeoDataFrame,
    out_dir: str | Path,
    stem: str,
    formats: list[str],
    name: str = "inundation",
) -> dict[str, Path]:
    """Write whichever of shp/gpkg/kml/geojson are requested."""
    out_dir = Path(out_dir)
    written: dict[str, Path] = {}
    wgs = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf
    if "shp" in formats:
        written["shp"] = export_shp(wgs, out_dir / f"{stem}.shp")
    if "gpkg" in formats:
        wgs.to_file(out_dir / f"{stem}.gpkg", driver="GPKG")
        written["gpkg"] = out_dir / f"{stem}.gpkg"
    if "kml" in formats:
        written["kml"] = export_kml(wgs, out_dir / f"{stem}.kml", name=name)
    if "geojson" in formats:
        wgs.to_file(out_dir / f"{stem}.geojson", driver="GeoJSON")
        written["geojson"] = out_dir / f"{stem}.geojson"
    return written


def _class_index(label) -> int:
    for i, (_lo, _hi, text) in enumerate(DEPTH_CLASSES):
        if str(label) == text:
            return min(i, len(CLASS_COLORS) - 1)
    return len(CLASS_COLORS) - 1
