"""Tests for dashboard helpers (no Streamlit import needed)."""

from __future__ import annotations

import numpy as np
import pytest
from affine import Affine

from dam_break.dashboard.util import (
    depth_png_bytes,
    list_run_artifacts,
    scenario_from_registry,
    wgs84_bounds,
)


class TestBounds:
    def test_wgs84_passthrough(self):
        tr = Affine(0.01, 0, 70.0, 0, -0.01, 23.0)
        assert wgs84_bounds((100, 200), tr, "EPSG:4326") == (70.0, 22.0, 72.0, 23.0)

    def test_utm_corners_reprojected(self):
        # 334 cells x 30 m ~ 10 km window in UTM 42N (Machhu area)
        tr = Affine(30.0, 0, 600_000.0, 0, -30.0, 2_500_000.0)
        w, s, e, n = wgs84_bounds((334, 334), tr, "EPSG:32642")
        assert w < e and s < n
        # 10 km at this latitude is ~0.09-0.11 degrees
        assert 0.05 < (e - w) < 0.15
        assert 0.05 < (n - s) < 0.15


class TestDepthPng:
    def test_png_and_bounds_roundtrip(self):
        tr = Affine(0.01, 0, 70.0, 0, -0.01, 23.0)
        depth = np.zeros((40, 60))
        depth[10:20, 10:50] = 2.5
        png, bounds = depth_png_bytes(depth, tr, "EPSG:4326")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert bounds == (70.0, 22.6, 70.6, 23.0)

    def test_all_dry_raster_still_renders(self):
        tr = Affine(0.01, 0, 0.0, 0, -0.01, 1.0)
        png, _ = depth_png_bytes(np.zeros((10, 10)), tr, "EPSG:4326")
        assert png[:4] == b"\x89PNG"


class TestScenarioFromRegistry:
    def test_builds_loadable_scenario(self):
        cfg = scenario_from_registry("Tehri")
        assert cfg["dam"]["name"] == "Tehri"
        assert cfg["solvers"] == ["screening"]
        assert cfg["scenario_id"] == "tehri"
        # must be consumable by the real loader
        from dam_break.config import load_scenario
        scen = load_scenario(cfg)
        assert scen.dam.name == "Tehri"

    def test_override_wins(self):
        cfg = scenario_from_registry("Tehri", height_m=123.0)
        assert cfg["dam"]["override"]["height_m"] == 123.0

    def test_unknown_dam_raises(self):
        with pytest.raises(ValueError, match="not in the registry"):
            scenario_from_registry("Hoover")


class TestArtifacts:
    def test_groups_and_skips_absent(self, tmp_path):
        (tmp_path / "screening").mkdir()
        (tmp_path / "screening" / "depth_max.tif").write_bytes(b"x" * 10)
        (tmp_path / "screening" / "flood.kml").write_bytes(b"x" * 10)
        (tmp_path / "loss.csv").write_bytes(b"x" * 10)
        groups = list_run_artifacts(tmp_path)
        assert set(groups) == {"GeoTIFF", "KML", "Tables (CSV/JSON)"}
        assert len(groups["KML"]) == 1

    def test_missing_dir_is_empty(self, tmp_path):
        assert list_run_artifacts(tmp_path / "nope") == {}
