"""Tests for the dashboard's run history, live stage parsing and exports
(dam_break.dashboard.runs) and the map-layer helpers. No Streamlit needed."""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pytest
from affine import Affine

from dam_break.dashboard.runs import (
    bundle_zip,
    caveats_text,
    cfg_from_run,
    export_files,
    format_stamp,
    human_size,
    list_runs,
    parse_progress,
    plan_stages,
    relevant_caveats,
)
from dam_break.dashboard.util import depth_class_areas, layer_png_bytes

CFG = {"scenario_id": "demo", "dam": {"name": "Machhu-II"}, "solvers": ["screening"]}

LOG = """\
[demo] run directory: outputs\\demo\\20260930T132153Z
[demo] fetching DEM (aws_terrarium) over bbox (70.4, 22.3, 71.3, 23.2)
[demo] DEM grid (1251, 1251) @ 30 m (aws_terrarium(z12))
[demo] dam snapped to thalweg: 566 m from registry coordinate
[demo] computing breach parameters
[demo] Qp=6,652 m3/s, tf=101 min, V=59.1 Mm3
[demo] running screening solver (volume-fill)
[demo]   note: flow path traced: 30.8 km (4.0x coarsened grid)
"""


def _summary(run_dir, stamp, solvers=("screening",), area=19.7, exposure=None):
    run_dir.mkdir(parents=True)
    s = {
        "scenario_id": run_dir.parent.name, "generated_utc": stamp,
        "dam": {"name": "Machhu-II", "registry_verified": False},
        "breach": {"peak_flow_m3s": 6651.7, "volume_m3": 59.1e6},
        "solvers": {k: {"diagnostics": {"inundated_area_km2": area}} for k in solvers},
        "exposure": exposure, "runtime_s": 61.2,
        "caveats": ["screening solver outputs are indicative, not hydrodynamic results",
                    "dam registry attributes are demo-grade until verified against NRLD/GeoDAR",
                    "loss figures are indicative: starter damage curves and asset values"],
    }
    (run_dir / "summary.json").write_text(json.dumps(s), encoding="utf-8")
    return s


class TestHistory:
    def test_newest_first_and_bad_json_skipped(self, tmp_path):
        _summary(tmp_path / "demo" / "20260928T080000Z", "20260928T080000Z")
        _summary(tmp_path / "demo" / "20260930T132153Z", "20260930T132153Z", area=20.1)
        broken = tmp_path / "demo" / "20260929T000000Z"
        broken.mkdir()
        (broken / "summary.json").write_text("{not json", encoding="utf-8")
        runs = list_runs(tmp_path)
        assert [r.stamp for r in runs] == ["20260930T132153Z", "20260928T080000Z"]
        assert runs[0].area_km2 == 20.1
        assert runs[0].solvers == ["screening"]

    def test_missing_outputs_dir(self, tmp_path):
        assert list_runs(tmp_path / "nope") == []

    def test_format_stamp(self):
        assert format_stamp("20260930T132153Z") == "30 Sep 2026 · 13:21 UTC"
        assert format_stamp("not-a-stamp") == "not-a-stamp"


class TestProgress:
    def test_mid_run_stages(self):
        p = parse_progress(LOG, CFG, returncode=None)
        states = {s.key: s.state for s in p["stages"]}
        assert states == {"terrain": "done", "landcover": "skipped", "breach": "done",
                          "screening": "running", "outputs": "queued", "exposure": "skipped"}
        terrain = p["stages"][0]
        assert "1251 × 1251 cells at 30 m" in terrain.detail
        assert "snapped 566 m" in terrain.detail
        assert next(s for s in p["stages"] if s.key == "breach").detail.startswith("Qp 6,652")
        assert next(s for s in p["stages"] if s.key == "screening").detail.startswith("flow path traced")
        assert not p["finished"] and 0 < p["fraction"] < 1

    def test_finished_run_reports_dir(self):
        log = LOG + ("[demo] writing rasters, polygons and exports\n"
                     "[demo] done in 61.2 s -> outputs\\demo\\20260930T132153Z\n")
        p = parse_progress(log, CFG, returncode=0)
        assert p["finished"] and p["fraction"] == 1.0
        assert p["run_dir"] == "outputs\\demo\\20260930T132153Z"
        assert all(s.state in ("done", "skipped") for s in p["stages"])

    def test_failure_marks_running_stage(self):
        log = LOG.split("[demo] computing")[0] + "Traceback ...\nRuntimeError: DEM came back empty\n"
        p = parse_progress(log, CFG, returncode=1)
        assert p["failed"]
        assert next(s for s in p["stages"] if s.key == "terrain").state == "failed"

    def test_plan_includes_each_solver_and_landcover(self):
        cfg = dict(CFG, solvers=["screening", "dualsphysics"],
                   roughness={"landcover": "worldcover_gee"})
        keys = [s.key for s in plan_stages(cfg)]
        assert keys == ["terrain", "landcover", "breach", "screening", "dualsphysics",
                        "outputs", "exposure"]
        assert all(s.state == "queued" for s in plan_stages(cfg))


class TestExports:
    def _run(self, tmp_path):
        run = tmp_path / "demo" / "20260930T132153Z"
        summary = _summary(run, "20260930T132153Z")
        sdir = run / "screening"
        sdir.mkdir()
        for name in ("depth_max.tif", "arrival_min.tif", "velocity_max.tif", "demo_screening.kml",
                     "demo_screening.shp.zip", "demo_screening.shp", "demo_screening.dbf",
                     "demo_screening.gpkg", "demo_screening_classes.csv", "depth_max.png"):
            (sdir / name).write_bytes(b"x" * 100)
        (run / "hydrograph.csv").write_text("t_s,q_m3s\n0,0\n", encoding="utf-8")
        (run / "scenario.json").write_text(json.dumps({
            "scenario_id": "demo", "dam": {"name": "Machhu-II", "lat": 22.81, "lon": 70.902,
                                           "dam_type": "earthfill", "height_m": 25.6,
                                           "storage_mcm": 99.2, "length_m": 3571.0},
            "terrain": {"dem": "aws_terrarium", "dem_path": None, "corridor_length_km": 30.0},
            "breach": {"mode": "overtopping", "case": "expected", "release_fraction": 0.6},
            "solvers": ["screening"]}), encoding="utf-8")
        return run, summary

    def test_grouping_and_presets(self, tmp_path):
        run, _ = self._run(tmp_path)
        files = export_files(run)
        names = {f.path.name for f in files}
        assert "demo_screening.shp" not in names   # shipped inside the zip
        by = {f.path.name: f for f in files}
        assert by["demo_screening.kml"].tags >= {"recommended", "field"}
        assert "recommended" in by["depth_max.tif"].tags
        assert "recommended" not in by["velocity_max.tif"].tags
        assert by["scenario.json"].group == "Reproduce this run"
        assert by["hydrograph.csv"].label == "Breach hydrograph (CSV)"

    def test_zip_has_files_and_caveats(self, tmp_path):
        run, summary = self._run(tmp_path)
        files = [f.path for f in export_files(run) if "field" in f.tags]
        data = bundle_zip(run, files, caveats_text(summary))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert set(zf.namelist()) == {"screening/demo_screening.kml", "CAVEATS.txt"}
            text = zf.read("CAVEATS.txt").decode()
        assert "indicative" in text and "loss" not in text

    def test_caveats_drop_loss_without_exposure(self, tmp_path):
        _, summary = self._run(tmp_path)
        assert not any("loss" in c for c in relevant_caveats(summary))
        summary["exposure"] = {"loss": {}}
        assert any("loss" in c for c in relevant_caveats(summary))

    def test_cfg_from_run_is_loadable(self, tmp_path):
        from dam_break.config import load_scenario
        run, _ = self._run(tmp_path)
        cfg = cfg_from_run(run)
        assert cfg["dam"] == {"name": "Machhu-II",
                              "override": {"height_m": 25.6, "storage_mcm": 99.2, "length_m": 3571.0}}
        assert "dem_path" not in cfg["terrain"]
        assert load_scenario(cfg).breach.release_fraction == 0.6

    def test_human_size(self):
        assert human_size(249) == "249 B"
        assert human_size(210385) == "205 KB"
        assert human_size(3868267) == "3.7 MB"


class TestLayers:
    TR = Affine(0.01, 0, 70.0, 0, -0.01, 23.0)

    def test_class_areas_use_solver_wet_threshold(self):
        depth = np.zeros((10, 10))
        depth[0, :5] = 0.05      # below 0.1 m: not counted
        depth[1, :4] = 0.3
        depth[2, :3] = 2.0
        depth[3, :2] = 9.0
        rows = depth_class_areas(depth, cell_area_m2=1e4)   # 1 ha cells
        assert [r["area_ha"] for r in rows] == [4.0, 0.0, 3.0, 0.0, 2.0]

    def test_class_areas_respect_mask(self):
        depth = np.full((4, 4), 1.0)
        mask = np.zeros((4, 4), bool)
        mask[0] = True
        assert sum(r["area_ha"] for r in depth_class_areas(depth, 1e4, mask)) == 4.0

    @pytest.mark.parametrize("kind", ["depth", "arrival", "velocity", "hazard"])
    def test_every_layer_renders_with_legend(self, kind):
        a = np.full((20, 20), np.nan)
        a[5:10, 5:10] = {"depth": 2.0, "arrival": 30.0, "velocity": 1.5, "hazard": 2}[kind]
        a[6, 6] = {"depth": 7.0, "arrival": 80.0, "velocity": 4.0, "hazard": 3}[kind]
        png, bounds, legend = layer_png_bytes(a, self.TR, "EPSG:4326", kind)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert bounds == (70.0, 22.8, 70.2, 23.0)
        assert legend["title"]

    def test_mask_hides_cells(self):
        from dam_break.dashboard.util import layer_rgba
        a = np.full((4, 4), 2.0)
        mask = np.zeros((4, 4), bool)
        mask[0, 0] = True
        rgba, _ = layer_rgba(a, "depth", mask)
        assert (rgba[..., 3] > 0).sum() == 1
