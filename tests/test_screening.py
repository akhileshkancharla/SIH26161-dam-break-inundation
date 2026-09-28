"""Screening-solver and post-processing tests on a synthetic V-valley DEM."""

import numpy as np
import pytest
from rasterio.transform import Affine

from dam_break.breach import breach_parameters
from dam_break.ingestion.dem import DEMData
from dam_break.postprocess.metrics import extent_scores
from dam_break.postprocess.polygons import depth_polygons
from dam_break.postprocess.rasters import classify_depth
from dam_break.preparation.roughness import roughness_from_landcover
from dam_break.solvers.screening import run_screening

CELL = 25.0
NY, NX = 240, 240


def _valley_dem() -> DEMData:
    """Tilted V-valley: channel along x, valley walls rising laterally."""
    x = np.arange(NX) * CELL
    y = np.arange(NY) * CELL
    xx, yy = np.meshgrid(x, y)
    downstream_slope = 0.005 * xx          # bed drops left -> right
    lateral = np.abs(yy - (NY - 1) / 2 * CELL) * 0.05  # V walls
    z = 100.0 - downstream_slope + lateral
    transform = Affine(CELL, 0.0, 0.0, 0.0, -CELL, NY * CELL)
    return DEMData(z=z, transform=transform, crs="EPSG:32645",
                   source="synthetic", bbox_wgs84=(0, 0, 1, 1))


def _breach():
    return breach_parameters(
        mode="overtopping", case="expected", storage_m3=20e6,
        release_fraction=0.5, dam_height_m=20.0,
    )


def test_screening_confines_water_to_valley_and_conserves_volume():
    dem = _valley_dem()
    start = (NY // 2, 5)
    res = run_screening(
        dem=dem, dam_rowcol=start, breach=_breach(),
        volume_m3=10e6, n_map=0.05, corridor_width_m=1500.0,
        trace_coarsen=4,
    )
    depth = res.layers["depth_max"].array
    assert (depth > 0.1).any()
    # Water stays near the channel centre line.
    rows_wet = np.where((depth > 0.1).any(axis=1))[0]
    assert rows_wet.min() > NY * 0.2 and rows_wet.max() < NY * 0.8
    # Volume roughly conserved (fill tolerance for class cut-off at 5 cm).
    stored = res.diagnostics["stored_volume_m3"]
    assert stored == pytest.approx(10e6, rel=0.25)


def test_screening_arrival_grows_downstream():
    dem = _valley_dem()
    res = run_screening(
        dem=dem, dam_rowcol=(NY // 2, 5), breach=_breach(),
        volume_m3=10e6, n_map=0.05, corridor_width_m=1500.0,
    )
    arrival = res.layers["arrival_min"].array
    mid = NY // 2
    t_near = np.nanmedian(arrival[mid, 20:40])
    t_far = np.nanmedian(arrival[mid, -40:-20])
    assert t_far > t_near


def test_classify_depth_bands():
    depth = np.array([[0.0, 0.3, 0.7, 1.5, 3.0, 5.0]])
    codes = classify_depth(depth)
    assert list(codes[0]) == [0, 1, 2, 3, 4, 5]


def test_depth_polygons_fields(tmp_path):
    dem = _valley_dem()
    res = run_screening(
        dem=dem, dam_rowcol=(NY // 2, 5), breach=_breach(),
        volume_m3=10e6, n_map=0.05, corridor_width_m=1500.0,
    )
    gdf = depth_polygons(res.layers["depth_max"].array, dem.transform, dem.crs)
    assert not gdf.empty
    assert {"dclass", "area_ha", "maxdepth"} <= set(gdf.columns)
    assert gdf.crs.to_epsg() == 4326
    gdf.to_file(tmp_path / "p.gpkg", driver="GPKG")


def test_extent_scores_perfect_and_empty():
    obs = np.zeros((5, 5), bool)
    obs[2, 2] = True
    assert extent_scores(obs, obs)["csi"] == 1.0
    empty = np.zeros((5, 5), bool)
    scores = extent_scores(obs, empty)
    assert scores["pod"] == 0.0 and scores["csi"] == 0.0


def test_roughness_mapping():
    lc = np.array([[10, 50], [80, 0]])
    n = roughness_from_landcover(lc, default_n=0.06)
    assert n[0, 0] == pytest.approx(0.10)
    assert n[0, 1] == pytest.approx(0.04)
    assert n[1, 0] == pytest.approx(0.03)
    assert n[1, 1] == pytest.approx(0.06)


def test_kml_has_real_coordinates(tmp_path):
    """Regression: pol.geometry assignment wrote degenerate 0,0 rings."""
    import geopandas as gpd
    from shapely.geometry import Polygon
    from dam_break.postprocess.polygons import export_kml

    gdf = gpd.GeoDataFrame(
        {"dclass": ["1-2 m"], "maxdepth": [1.5], "area_ha": [10.0],
         "dlo_m": [1.0], "dhi_m": [2.0]},
        geometry=[Polygon([(70.90, 22.81), (70.91, 22.81),
                           (70.91, 22.82), (70.90, 22.82)])],
        crs="EPSG:4326",
    )
    out = export_kml(gdf, tmp_path / "t.kml")
    text = out.read_text()
    assert "<coordinates>70.9" in text
    assert "0.0, 0.0, 0.0" not in text
