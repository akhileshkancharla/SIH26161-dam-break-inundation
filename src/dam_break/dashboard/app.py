"""Streamlit dashboard for the dam-break inundation framework (milestone 6).

Run:  streamlit run src/dam_break/dashboard/app.py
(inside the repo, with the package installed: pip install ".[dashboard]")

Screens follow the technical guide (Section 10): scenario setup -> run ->
results map -> impact & loss -> NRT watchlist browser -> exports.
Heavy compute stays in the dam_break library; Streamlit only renders.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

if __package__ in (None, "") or __package__.split(".")[0] != "dam_break":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dam_break.config import load_scenario
from dam_break.dashboard.util import (
    depth_png_bytes,
    list_run_artifacts,
    scenario_from_registry,
)
from dam_break.ingestion.dams import load_registry
from dam_break.paths import repo_root

st.set_page_config(page_title="SIH 26161 - Dam Break Inundation", layout="wide")

SCENARIO_DIR = repo_root() / "configs" / "scenarios"
OUTPUTS_DIR = repo_root() / "outputs"


# ---------------------------------------------------------------- state
if "cfg" not in st.session_state:
    st.session_state.cfg = json.loads(
        (SCENARIO_DIR / "machhu2_1979.json").read_text(encoding="utf-8"))
if "summary" not in st.session_state:
    st.session_state.summary = None


def save_cfg(cfg: dict) -> None:
    st.session_state.cfg = cfg


# ---------------------------------------------------------------- sidebar
st.sidebar.title("Scenario")

presets = sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))
picked = st.sidebar.selectbox("Load preset", presets,
                              index=presets.index("machhu2_1979")
                              if "machhu2_1979" in presets else 0)
if st.sidebar.button("Load preset into editor"):
    save_cfg(json.loads((SCENARIO_DIR / f"{picked}.json").read_text(encoding="utf-8")))
    st.rerun()

registry = load_registry()
dam_names = sorted(registry["name"].tolist())
cfg = dict(st.session_state.cfg)

st.sidebar.subheader("Dam")
dam_name = st.sidebar.selectbox(
    "Registry dam", dam_names,
    index=dam_names.index(cfg["dam"]["name"])
    if cfg["dam"]["name"] in dam_names else 0)
if dam_name != cfg["dam"]["name"]:
    save_cfg(scenario_from_registry(dam_name))
    st.rerun()

cfg = dict(st.session_state.cfg)
height = st.sidebar.number_input(
    "Dam height (m)", 1.0, 350.0,
    float(cfg["dam"].get("override", {}).get("height_m", 25.0)), 1.0)
storage = st.sidebar.number_input(
    "Storage (Mm3)", 0.1, 100000.0,
    float(cfg["dam"].get("override", {}).get("storage_mcm", 50.0)), 1.0)

st.sidebar.subheader("Breach")
breach_cfg = cfg.setdefault("breach", {})
breach_cfg["mode"] = st.sidebar.selectbox(
    "Mode", ["overtopping", "piping", "instantaneous"],
    index=["overtopping", "piping", "instantaneous"].index(breach_cfg.get("mode", "overtopping")))
breach_cfg["case"] = st.sidebar.selectbox(
    "Uncertainty case", ["low", "expected", "high"],
    index=["low", "expected", "high"].index(breach_cfg.get("case", "expected")))
breach_cfg.setdefault("release_fraction",
                      float(st.sidebar.slider("Release fraction", 0.1, 1.0, 0.6, 0.05)))

st.sidebar.subheader("Terrain & solvers")
terrain_cfg = cfg.setdefault("terrain", {})
terrain_cfg["dem"] = st.sidebar.selectbox(
    "DEM source", ["aws_terrarium", "copernicus_glo30 Gee", "file"],
    index=0 if terrain_cfg.get("dem", "aws_terrarium") == "aws_terrarium" else 0)
terrain_cfg["corridor_length_km"] = st.sidebar.slider(
    "Corridor length (km)", 5, 60, int(terrain_cfg.get("corridor_length_km", 30)))
terrain_cfg["corridor_width_km"] = st.sidebar.slider(
    "Corridor width (km)", 2, 20, int(terrain_cfg.get("corridor_width_km", 6)))
solvers = st.sidebar.multiselect(
    "Solvers", ["screening", "dualsphysics"], default=cfg.get("solvers", ["screening"]))
cfg["solvers"] = solvers or ["screening"]

cfg["dam"].setdefault("override", {}).update({"height_m": height, "storage_mcm": storage})
save_cfg(cfg)

if st.sidebar.button("Save scenario JSON", help="Writes configs/scenarios/<id>.json"):
    path = SCENARIO_DIR / f"{cfg['scenario_id']}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    st.sidebar.success(f"saved {path.name}")

st.sidebar.caption(
    "SPH runs locally only if the DualSPHysics package is present; "
    "D-Flow FM needs the dflowfm binary. Screening always works.")

# ---------------------------------------------------------------- run
st.title("Dam-break inundation - SIH 26161")
st.caption("Breach (Froehlich) -> terrain -> solvers -> exposure & loss -> "
           "NRT Sentinel-1 watchlist")

col_run, col_info = st.columns([1, 3])
with col_run:
    if st.button("Run pipeline", type="primary"):
        from dam_break.pipeline import run_pipeline

        try:
            with st.spinner("running pipeline (screening ~2-5 min locally)"):
                st.session_state.summary = run_pipeline(
                    load_scenario(st.session_state.cfg), out_root="outputs")
        except Exception as exc:  # noqa: BLE001 - surface every failure in the UI
            st.error(f"pipeline failed: {exc}")

summary = st.session_state.summary
if summary:
    st.success(f"run complete -> {summary.get('run_dir', '')} "
               f"({summary.get('runtime_s', '?')} s)")

tabs = st.tabs(["Overview", "Results map", "Impact & loss",
                "Comparison", "NRT watchlist", "Exports"])

# ---------------------------------------------------------------- overview
with tabs[0]:
    if not summary:
        st.info("Configure a scenario on the left and press **Run pipeline**. "
                "Or explore a previous run's outputs in the other tabs.")
    else:
        b = summary.get("breach", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Peak flow Qp", f"{b.get('peak_flow_m3s', 0):,.0f} m3/s")
        c2.metric("Failure time", f"{b.get('failure_time_min', 0):.0f} min")
        c3.metric("Released volume", f"{b.get('volume_m3', 0)/1e6:,.1f} Mm3")
        loss = (summary.get("exposure") or {}).get("loss") or {}
        c4.metric("Indicative loss",
                  f"Rs {loss.get('total_indicative_loss_crore_inr', 0):,.0f} cr",
                  help="starter depth-damage curves - indicative only")
        st.json({k: v for k, v in summary.items()
                 if k in ("scenario_id", "terrain", "breach", "solvers", "caveats")})

# ---------------------------------------------------------------- map
with tabs[1]:
    run_dir = Path(summary["run_dir"]) if summary else None
    if run_dir and (run_dir / "screening" / "depth_max.tif").exists():
        import folium
        import rasterio
        from dam_break.postprocess.polygons import depth_polygons
        from streamlit import components

        with rasterio.open(run_dir / "screening" / "depth_max.tif") as ds:
            depth = ds.read(1)
            tr, crs = ds.transform, ds.crs
        png, bounds = depth_png_bytes(depth, tr, crs)
        west, south, east, north = bounds
        import base64
        from dam_break.ingestion.dams import lookup_dam
        dam = lookup_dam(cfg["dam"]["name"]) or {}
        m = folium.Map(location=[(south + north) / 2, (west + east) / 2],
                       zoom_start=10, tiles="OpenStreetMap")
        folium.raster_layers.ImageOverlay(
            image=f"data:image/png;base64,{base64.b64encode(png).decode()}",
            bounds=[[south, west], [north, east]],
            name="max depth (screening)", opacity=0.75,
        ).add_to(m)
        gdf = depth_polygons(depth, tr, crs, min_patch_ha=2.0)
        if len(gdf):
            style = {"fillOpacity": 0.0, "weight": 1.2, "color": "#08519c"}
            folium.GeoJson(
                gdf.to_json(), name="depth-class polygons",
                style_function=lambda _: style,
                tooltip=folium.GeoJsonTooltip(
                    fields=["dclass", "area_ha", "maxdepth"],
                    aliases=["class", "area (ha)", "max depth (m)"]),
            ).add_to(m)
        folium.Marker([dam.get("lat", 0), dam.get("lon", 0)],
                      popup=cfg["dam"]["name"], icon=folium.Icon(color="red")).add_to(m)
        folium.LayerControl().add_to(m)
        components.html(m.get_root().render(), height=560)
        st.caption("Raster overlay: screening max depth. Polygons: depth classes "
                   "(sieved 2 ha). Red marker: registry dam coordinate.")
    else:
        st.info("No screening raster yet - run the pipeline (or a scenario "
                "that includes the screening solver).")

# ---------------------------------------------------------------- loss
with tabs[2]:
    run_dir = Path(summary["run_dir"]) if summary else None
    loss_csv = run_dir / "screening" / "loss.csv" if run_dir else None
    if loss_csv and loss_csv.exists():
        df = pd.read_csv(loss_csv)
        st.dataframe(df, use_container_width=True)
        if "indicative_loss_inr" in df:
            total = df["indicative_loss_inr"].sum() / 1e7
            st.metric("Total indicative loss", f"Rs {total:,.1f} crore")
        st.caption("Starter JRC-style curves and asset values - calibration "
                   "against JRC/NDMA sources is pending (see verification log).")
    else:
        st.info("No loss table - run with land cover enabled "
                "(roughness.landcover=worldcover_gee needs GEE auth).")

# ---------------------------------------------------------------- comparison
with tabs[3]:
    run_dir = Path(summary["run_dir"]) if summary else None
    if run_dir:
        comp = run_dir / "comparison_dualsphysics_vs_screening.json"
        pngs = sorted(run_dir.glob("comparison_*.png"))
        if comp.exists():
            st.json(json.loads(comp.read_text(encoding="utf-8")))
        for p in pngs:
            st.image(str(p), width=760)
        if not comp.exists() and not pngs:
            st.info("Comparison output appears when a run has 2+ solvers "
                    "with depth layers (e.g. screening + SPH).")

# ---------------------------------------------------------------- NRT
with tabs[4]:
    nrt_root = OUTPUTS_DIR / "nrt"
    sweeps = sorted(nrt_root.glob("*/watchlist.csv")) if nrt_root.is_dir() else []
    if sweeps:
        picked_sweep = st.selectbox("Sweep", [str(p.parent.name) for p in sweeps],
                                    index=len(sweeps) - 1)
        df = pd.read_csv(nrt_root / picked_sweep / "watchlist.csv")
        st.dataframe(df, use_container_width=True)
        alerts_file = nrt_root / picked_sweep / "alerts.json"
        if alerts_file.exists():
            alerts = json.loads(alerts_file.read_text(encoding="utf-8"))
            st.warning(f"{alerts.get('n_alerts', 0)} alert(s): "
                       f"{[a['dam'] for a in alerts.get('alerts', [])] or 'none'}")
        st.caption("Sentinel-1 change detection (UN-SPIDER practice); revisit is "
                   "days, dB thresholds are site-tunable defaults.")
    else:
        st.info("No NRT sweeps yet - run the Milestone-5 notebook cells or "
                "scripts/run_nrt_watchlist.py.")

# ---------------------------------------------------------------- exports
with tabs[5]:
    run_dir = Path(summary["run_dir"]) if summary else None
    artifacts = list_run_artifacts(run_dir) if run_dir else {}
    if not artifacts:
        st.info("Run the pipeline to generate downloadable exports "
                "(.shp zip, .kml, .gpkg, .tif, .csv).")
    for kind, files in artifacts.items():
        st.subheader(kind)
        for f in files:
            st.download_button(f"{f.name}  ({f.stat().st_size/1024:.0f} KB)",
                               data=f.read_bytes(), file_name=f.name,
                               key=f"{f}")
