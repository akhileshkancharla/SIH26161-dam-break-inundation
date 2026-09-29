"""Tests for the NRT watchlist (pure parts only - no Earth Engine needed)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from dam_break.nrt.flood_map import DEFAULT_CHANGE_DB, DEFAULT_WATER_DB
from dam_break.nrt.watchlist import (
    CSV_FIELDS,
    _error_row,
    _select_dams,
    _write_outputs,
    decide_alert,
    windows,
)
from dam_break.ingestion.dams import load_registry


class TestWindows:
    def test_windows_order_and_gap(self):
        now = dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc)
        a_s, a_e, b_s, b_e = windows(now=now, lookback_days=14, baseline_days=45)
        assert (a_s, a_e) == ("2026-09-15", "2026-09-29")
        # before window ends exactly where the after window starts
        assert (b_s, b_e) == ("2026-08-01", "2026-09-15")

    def test_windows_gap_never_zero(self):
        a_s, a_e, b_s, b_e = windows(lookback_days=1, baseline_days=1)
        assert a_s == b_e and b_s < a_s


class TestAlertRule:
    def test_threshold_is_inclusive(self):
        assert decide_alert(25.0, alert_km2=25.0) == "ALERT"
        assert decide_alert(24.9, alert_km2=25.0) == "normal"
        assert decide_alert(0.0) == "normal"


class TestSelectDams:
    def test_select_by_normalized_name(self):
        reg = load_registry()
        hits = _select_dams(reg, ["machhu-ii", "tehri"])
        assert len(hits) == 2
        assert set(hits["state"]) == {"Gujarat", "Uttarakhand"}

    def test_unknown_dam_raises_with_known_list(self):
        with pytest.raises(ValueError, match="not in registry"):
            _select_dams(load_registry(), ["hoover"])


class TestOutputs:
    def test_write_outputs_csv_and_alerts(self, tmp_path: Path):
        now = dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc)
        a_s, a_e, b_s, b_e = windows(now=now)
        rows = [
            {"dam": "A", "river": "r", "state": "s", "lat": 1.0, "lon": 2.0,
             "after_window": f"{a_s}/{a_e}", "after_scenes": 3,
             "latest_scene": "x", "before_window": f"{b_s}/{b_e}",
             "before_scenes": 5, "water_km2": 10, "perm_km2": 8,
             "flood_km2": 40.0, "flood_pct_of_aoi": 2.5,
             "status": "ALERT", "notes": "polygons: 2"},
            _error_row({"name": "B", "river": "", "state": "", "lat": "", "lon": ""},
                       a_s, a_e, b_s, b_e, "boom"),
        ]
        _write_outputs(tmp_path, rows, aoi_km=40.0)
        csv_text = (tmp_path / "watchlist.csv").read_text(encoding="utf-8")
        assert csv_text.splitlines()[0] == ",".join(CSV_FIELDS)
        assert "ALERT" in csv_text and "error" in csv_text

        alerts = json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8"))
        assert alerts["n_alerts"] == 1
        assert alerts["alerts"][0]["dam"] == "A"
        assert any("not live" in c for c in alerts["caveats"])


class TestFloodGdf:
    def test_sieve_keeps_large_drops_small(self, tmp_path):
        from dam_break.nrt.watchlist import _flood_gdf, DEFAULT_MIN_POLYGON_HA

        big = box(0, 0, 0.05, 0.05)      # ~3,000 ha at the equator
        small = box(1, 1, 1.001, 1.001)  # ~120 ha - under the sieve
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"label": 1},
                 "geometry": gpd.GeoSeries([big]).__geo_interface__["features"][0]["geometry"]},
                {"type": "Feature", "properties": {"label": 1},
                 "geometry": gpd.GeoSeries([small]).__geo_interface__["features"][0]["geometry"]},
                {"type": "Feature", "properties": {"label": 0},
                 "geometry": gpd.GeoSeries([big]).__geo_interface__["features"][0]["geometry"]},
            ],
        }
        gdf = _flood_gdf(geojson, min_area_ha=DEFAULT_MIN_POLYGON_HA)
        assert len(gdf) == 1  # large polygon only; label 0 never counted

    def test_empty_geojson_returns_none(self):
        from dam_break.nrt.watchlist import _flood_gdf
        assert _flood_gdf({}, 5.0) is None
        assert _flood_gdf({"features": []}, 5.0) is None


def test_guide_defaults_pinned():
    # UN-SPIDER thresholds from the technical guide (Section 7)
    assert DEFAULT_CHANGE_DB == -3.0
    assert DEFAULT_WATER_DB == -15.0
