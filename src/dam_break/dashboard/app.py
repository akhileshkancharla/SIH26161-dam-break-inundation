"""Streamlit dashboard for the dam-break inundation framework (milestone 6).

Design: "HydroInundate Operations" command center (team Stitch design
system) - dark hydrographic substrate, hydro-blue primary, cyan telemetry,
hazard-scale accents, Space Grotesk / Inter / JetBrains Mono typography.

Run:  streamlit run src/dam_break/dashboard/app.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

if __package__ in (None, "") or __package__.split(".")[0] != "dam_break":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dam_break.config import load_scenario
from dam_break.dashboard.theme import CSS, chip_row, crisis_header
from dam_break.dashboard.util import (
    hydrograph_figure,
    kpi_stats,
    list_run_artifacts,
    scenario_from_registry,
)
from dam_break.ingestion.dams import load_registry, lookup_dam
from dam_break.paths import repo_root

st.set_page_config(page_title="SIH 26161 - Dam Break Operations",
                   page_icon="🌊", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

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


# ================================================================ sidebar
st.sidebar.markdown(
    '<p class="hydro-brand">⚡ Hydro<span class="accent">Inundate</span> '
    'Operations</p>'
    '<p class="hydro-tag">SIH26161 STUDIO · CWC/NRLD · D-FLOW FM + SPH</p>',
    unsafe_allow_html=True)

presets = sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))
picked = st.sidebar.selectbox(
    "Preset scenario", presets,
    index=presets.index("machhu2_1979") if "machhu2_1979" in presets else 0)
if st.sidebar.button("Load preset", use_container_width=True):
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
ov = cfg["dam"].get("override", {})
height = st.sidebar.number_input("Height (m)", 1.0, 350.0,
                                 float(ov.get("height_m", 25.0)), 1.0)
storage = st.sidebar.number_input("Storage (Mm³)", 0.1, 100000.0,
                                  float(ov.get("storage_mcm", 50.0)), 1.0)

breach_cfg = cfg.setdefault("breach", {})
breach_cfg["mode"] = st.sidebar.selectbox(
    "Breach mode", ["overtopping", "piping", "instantaneous"],
    index=["overtopping", "piping", "instantaneous"].index(breach_cfg.get("mode", "overtopping")))
breach_cfg["case"] = st.sidebar.selectbox(
    "Uncertainty case", ["low", "expected", "high"],
    index=["low", "expected", "high"].index(breach_cfg.get("case", "expected")))

terrain_cfg = cfg.setdefault("terrain", {})
terrain_cfg["corridor_length_km"] = st.sidebar.slider(
    "Reach (km)", 5, 60, int(terrain_cfg.get("corridor_length_km", 30)))
terrain_cfg["corridor_width_km"] = st.sidebar.slider(
    "Width (km)", 2, 20, int(terrain_cfg.get("corridor_width_km", 6)))
solvers = st.sidebar.multiselect(
    "Solvers", ["screening", "dualsphysics"], default=cfg.get("solvers", ["screening"]))
cfg["solvers"] = solvers or ["screening"]
cfg["dam"].setdefault("override", {}).update({"height_m": height, "storage_mcm": storage})
save_cfg(cfg)

# solver readiness chips
def _solver_chips() -> list[tuple[str, str]]:
    chips = [("SCREENING · VOL-FILL", "active" if "screening" in cfg["solvers"] else "standby")]
    d3d = "ready" if shutil.which("dflowfm") or st.session_state.get("dflowfm") else "standby"
    chips.append(("DELFT3D-FM · 2D", d3d))
    try:
        from dam_break.solvers.sph.adapter import find_tools
        sph = "active" if ("dualsphysics" in cfg["solvers"] and find_tools().solver) else (
            "ready" if find_tools().solver else "standby")
    except Exception:
        sph = "standby"
    chips.append(("DUALSPHYSICS · SPH", sph))
    return chips


st.sidebar.markdown("**Solver framework**")
st.sidebar.markdown(chip_row(_solver_chips()), unsafe_allow_html=True)

if st.sidebar.button("▶  RUN PIPELINE", type="primary", use_container_width=True):
    from dam_break.pipeline import run_pipeline

    try:
        with st.spinner("breach → terrain → solver → exposure …"):
            st.session_state.summary = run_pipeline(
                load_scenario(st.session_state.cfg), out_root="outputs")
    except Exception as exc:  # noqa: BLE001
        st.error(f"pipeline failed: {exc}")

if st.sidebar.button("Save scenario JSON", use_container_width=True):
    path = SCENARIO_DIR / f"{cfg['scenario_id']}.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    st.sidebar.success(f"saved {path.name}")

st.sidebar.caption("streamlit run src/dam_break/dashboard/app.py · PORT 8501")

# ================================================================ header
summary = st.session_state.summary
dam = lookup_dam(cfg["dam"]["name"]) or {}
mode_label = {"overtopping": "OVERTOPPING BREACH", "piping": "PIPING BREACH",
              "instantaneous": "INSTANTANEOUS FAILURE"}[cfg.get("breach", {}).get("mode", "overtopping")]
st.markdown(crisis_header(
    title=f"{cfg['dam']['name']} failure scenario",
    badge=f"⚠ {mode_label} · {cfg.get('breach', {}).get('case', 'expected').upper()}",
    badge_kind="danger",
    subtitle=(f"{dam.get('river', '')} basin · {dam.get('state', '')} · "
              f"reach {cfg.get('terrain', {}).get('corridor_length_km', 30)} km · "
              f"solver: {'+'.join(cfg.get('solvers', ['screening']))}"),
    meta=("RUN COMPLETE" if summary else "STANDBY — press RUN PIPELINE")),
    unsafe_allow_html=True)

# ================================================================ KPIs
kpis = kpi_stats(summary["run_dir"]) if summary else {}
if kpis:
    b = summary.get("breach", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("PEAK FLOOD DEPTH", f"{kpis.get('peak_depth_m', 0):.2f} m",
              f"max over {kpis.get('wet_cells', 0):,} wet cells")
    m2.metric("PEAK BREACH DISCHARGE", f"{b.get('peak_flow_m3s', 0):,.0f} m³/s",
              f"tf {b.get('failure_time_min', 0):.0f} min")
    m3.metric("INUNDATION FOOTPRINT", f"{kpis.get('wet_area_km2', 0):,.1f} km²",
              f"released {b.get('volume_m3', 0)/1e6:,.1f} Mm³")
    if "arrival_front_min" in kpis:
        m4.metric("FRONT AT CORRIDOR END", f"{kpis['arrival_front_min']/60:.1f} h",
                  f"T+{kpis['arrival_front_min']:.0f} min · evacuation window")
    else:
        m4.metric("RELEASED VOLUME", f"{b.get('volume_m3', 0)/1e6:,.1f} Mm³",
                  "Froehlich 2008")

tabs = st.tabs(["🗺️ Inundation & hazard map", "📈 Breach hydrograph",
                "💸 Exposure & damage loss", "⚖️ Solver benchmark",
                "🛰️ NRT watchlist", "📦 Spatial exports"])

# ================================================================ map
with tabs[0]:
    run_dir = Path(summary["run_dir"]) if summary else None
    if run_dir and (run_dir / "screening" / "depth_max.tif").exists():
        try:
            import base64

            import branca
            import folium
            import rasterio

            from dam_break.dashboard.util import depth_png_bytes
            from dam_break.postprocess.polygons import depth_polygons

            with rasterio.open(run_dir / "screening" / "depth_max.tif") as ds:
                depth = ds.read(1)
                tr, crs = ds.transform, ds.crs
            png, bounds = depth_png_bytes(depth, tr, crs)
            west, south, east, north = bounds
            m = folium.Map(location=[(south + north) / 2, (west + east) / 2],
                           zoom_start=10, tiles=None, control_scale=True)
            folium.TileLayer(
                tiles=("https://cartodb-basemaps-a.global.ssl.fastly.net/"
                       "dark_all/{z}/{x}/{y}.png"),
                attr="CARTO dark", name="Dark").add_to(m)
            folium.TileLayer("OpenStreetMap", name="Street").add_to(m)
            folium.TileLayer(
                tiles=("https://server.arcgisonline.com/ArcGIS/rest/services/"
                       "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
                attr="Esri World Imagery", name="Satellite", show=False).add_to(m)
            folium.raster_layers.ImageOverlay(
                image=f"data:image/png;base64,{base64.b64encode(png).decode()}",
                bounds=[[south, west], [north, east]],
                name="max depth", opacity=0.85).add_to(m)
            legend = branca.colormap.StepColormap(
                ["#38BDF8", "#2563EB", "#D97706", "#DC2626", "#C026D3"],
                index=[0.1, 0.5, 1.5, 3.0, 6.0], vmin=0.0, vmax=8.0,
                caption="water depth (m)")
            legend.add_to(m)
            gdf = depth_polygons(depth, tr, crs, min_patch_ha=5.0)
            if len(gdf):
                folium.GeoJson(
                    gdf.to_json(), name="depth-class outlines",
                    style_function=lambda _: {
                        "fillOpacity": 0.0, "weight": 1.2, "color": "#7DD3FC"},
                    tooltip=folium.GeoJsonTooltip(
                        fields=["dclass", "area_ha", "maxdepth"],
                        aliases=["class", "area (ha)", "max (m)"]),
                ).add_to(m)
            folium.Marker(
                [dam.get("lat", 0), dam.get("lon", 0)], popup=cfg["dam"]["name"],
                icon=folium.Icon(color="red", icon="bolt", prefix="fa")).add_to(m)
            folium.LayerControl(collapsed=False).add_to(m)
            st.components.v1.html(m.get_root().render(), height=600)
            st.caption("dark basemap default · toggle street / satellite · "
                       "legend: 0-0.5 cyan · 0.5-1.5 blue · 1.5-3 amber · "
                       "3-6 red · >6 magenta")
        except Exception as exc:  # noqa: BLE001
            st.error(f"map rendering failed: {exc}")
    else:
        st.info("No screening raster yet — press **RUN PIPELINE**.")

# ================================================================ hydrograph
with tabs[1]:
    try:
        from dam_break.breach.empirical import breach_parameters
        from dam_break.breach.hydrograph import hydrograph_from_breach

        scen = load_scenario(st.session_state.cfg)
        breach = breach_parameters(
            mode=scen.breach.mode, case=scen.breach.case,
            storage_m3=scen.dam.storage_m3,
            release_fraction=scen.breach.release_fraction,
            dam_height_m=scen.dam.height_m, dam_length_m=scen.dam.length_m,
            failure_fraction=scen.breach.failure_fraction,
            method=scen.breach.method)
        t, q = hydrograph_from_breach(breach, dt_s=scen.run.dt_s,
                                      duration_h=scen.run.duration_h)
        st.pyplot(hydrograph_figure(t, q, breach.failure_time_s,
                                    breach.peak_flow_m3s))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Qp", f"{breach.peak_flow_m3s:,.0f} m³/s")
        c2.metric("tf", f"{breach.failure_time_min:.0f} min")
        c3.metric("Breach width", f"{breach.breach_width_m:.0f} m")
        c4.metric("Head over breach", f"{breach.water_depth_m:.1f} m")
        st.caption("volume-conserving hydrograph: linear rise over tf, "
                   "exponential recession matched to released volume")
    except Exception as exc:  # noqa: BLE001
        st.error(f"breach computation failed: {exc}")

# ================================================================ loss
with tabs[2]:
    run_dir = Path(summary["run_dir"]) if summary else None
    loss_csv = run_dir / "screening" / "loss.csv" if run_dir else None
    if loss_csv and loss_csv.exists():
        df = pd.read_csv(loss_csv)
        st.dataframe(df, use_container_width=True, hide_index=True)
        if "indicative_loss_inr" in df:
            st.metric("TOTAL INDICATIVE LOSS",
                      f"₹ {df['indicative_loss_inr'].sum()/1e7:,.1f} crore",
                      "starter curves — calibration pending")
    else:
        st.info("No loss table — run with land cover (needs GEE auth).")

# ================================================================ benchmark
with tabs[3]:
    run_dir = Path(summary["run_dir"]) if summary else None
    if run_dir:
        comp = run_dir / "comparison_dualsphysics_vs_screening.json"
        pngs = sorted(run_dir.glob("comparison_*.png"))
        if comp.exists():
            st.json(json.loads(comp.read_text(encoding="utf-8")))
        for p in pngs:
            st.image(str(p), width=780)
        if not comp.exists() and not pngs:
            st.info("Benchmark output appears when a run has 2+ solvers "
                    "with depth layers (screening + SPH).")
    else:
        st.info("No run yet.")

# ================================================================ NRT
with tabs[4]:
    nrt_root = OUTPUTS_DIR / "nrt"
    sweeps = sorted(nrt_root.glob("*/watchlist.csv")) if nrt_root.is_dir() else []
    if sweeps:
        picked_sweep = st.selectbox("Sweep", [str(p.parent.name) for p in sweeps],
                                    index=len(sweeps) - 1)
        df = pd.read_csv(nrt_root / picked_sweep / "watchlist.csv")
        chips = []
        for _, r in df.iterrows():
            kind = ("danger" if r.get("status") == "ALERT"
                    else "warn" if r.get("status") in ("error", "no_data")
                    else "safe")
            label = f"{r['dam']} · flood {r.get('flood_km2', '?')} km² · {r.get('status', '?')}"
            chips.append(f'<span class="hydro-badge {kind}">{label}</span>')
        st.markdown(" ".join(chips), unsafe_allow_html=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
        alerts_file = nrt_root / picked_sweep / "alerts.json"
        if alerts_file.exists():
            alerts = json.loads(alerts_file.read_text(encoding="utf-8"))
            if alerts.get("n_alerts"):
                st.error(f"{alerts['n_alerts']} ALERT(S): "
                         f"{[a['dam'] for a in alerts.get('alerts', [])]}")
        st.caption("Sentinel-1 change detection · revisit is days · dB "
                   "thresholds are site-tunable defaults")
    else:
        st.info("No NRT sweeps yet — Milestone-5 notebook cells or "
                "scripts/run_nrt_watchlist.py.")

# ================================================================ exports
with tabs[5]:
    run_dir = Path(summary["run_dir"]) if summary else None
    artifacts = list_run_artifacts(run_dir) if run_dir else {}
    if not artifacts:
        st.info("Run the pipeline to generate downloadable exports.")
    for kind, files in artifacts.items():
        st.markdown(f"**{kind}**")
        for f in files:
            st.download_button(f"⬇  {f.name}  ({f.stat().st_size/1024:.0f} KB)",
                               data=f.read_bytes(), file_name=f.name, key=str(f))
