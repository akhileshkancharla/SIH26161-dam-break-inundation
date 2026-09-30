"""Step 4 · Results: map-first workspace for one finished run."""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from dam_break.dashboard.runs import cfg_from_run, format_stamp, relevant_caveats
from dam_break.dashboard.theme import (badge, caveat_html, class_bars_html, legend_html,
                                       stat_grid)
from dam_break.dashboard.util import depth_class_areas, layer_png_bytes
from dam_break.dashboard.views import common

LAYERS = {"depth": ("Maximum depth", "depth_max.tif"),
          "arrival": ("Arrival time", "arrival_min.tif"),
          "velocity": ("Maximum velocity", "velocity_max.tif"),
          "hazard": ("Hazard class", "hazard_class.tif")}
BASEMAPS = {
    "Dark": ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
             "World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", "Esri, HERE, Garmin, OpenStreetMap"),
    "Street": ("OpenStreetMap", None),
    "Satellite": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
                  "MapServer/tile/{z}/{y}/{x}", "Esri World Imagery"),
}


@st.cache_data(show_spinner=False, max_entries=12)
def _raster(path: str, mtime: float):
    import rasterio

    with rasterio.open(path) as ds:
        a = ds.read(1).astype(float)
        if ds.nodata is not None and not np.isnan(ds.nodata):
            a[a == ds.nodata] = np.nan
        return a, ds.transform, ds.crs.to_wkt()


def _load(path: Path):
    return _raster(str(path), path.stat().st_mtime)


@st.cache_data(show_spinner=False, max_entries=6)
def _outlines(path: str, mtime: float) -> str | None:
    from dam_break.postprocess.polygons import depth_polygons

    a, tr, crs = _raster(path, mtime)
    gdf = depth_polygons(a, tr, crs, min_patch_ha=5.0)
    if not len(gdf):
        return None
    if gdf.crs is None:
        gdf = gdf.set_crs(crs)
    return gdf.to_crs(4326).to_json()


def _map_html(png: bytes, bounds, dam: dict, basemap: str, outlines: str | None) -> str:
    import folium

    west, south, east, north = bounds
    m = folium.Map(location=[(south + north) / 2, (west + east) / 2], tiles=None,
                   control_scale=True, zoom_control=True)
    url, attr = BASEMAPS[basemap]
    folium.TileLayer(url, attr=attr, name=basemap).add_to(m)
    folium.raster_layers.ImageOverlay(
        image=f"data:image/png;base64,{base64.b64encode(png).decode()}",
        bounds=[[south, west], [north, east]], opacity=0.9).add_to(m)
    if outlines:
        folium.GeoJson(outlines, style_function=lambda _: {
            "fillOpacity": 0.0, "weight": 1.1, "color": "#CFEFF7"},
            tooltip=folium.GeoJsonTooltip(fields=["dclass", "area_ha", "maxdepth"],
                                          aliases=["class", "area (ha)", "max depth (m)"])
        ).add_to(m)
    if dam.get("lat") is not None:
        folium.CircleMarker([dam["lat"], dam["lon"]], radius=7, color="#0D1417", weight=2,
                            fill=True, fill_color="#F4F7F8", fill_opacity=1,
                            tooltip=f"{dam.get('name', 'dam')} (registry location)").add_to(m)
    m.fit_bounds([[south, west], [north, east]])
    return m.get_root().render()


def _empty() -> None:
    st.markdown("# No results yet")
    st.markdown('<div class="hi-muted">Run a scenario, or reopen a past run from Start.</div>',
                unsafe_allow_html=True)
    a, b, _ = st.columns([1, 1, 3])
    if a.button("Go to Start", width="stretch"):
        common.go("start")
    if b.button("Run the current scenario", type="primary", width="stretch"):
        common.go("run")


def _header(rec) -> None:
    same = [r for r in common.runs() if r.scenario_id == rec.scenario_id] or [rec]
    labels = {str(r.run_dir): r.label for r in same}
    if str(rec.run_dir) not in labels:
        labels = {str(rec.run_dir): rec.label, **labels}
    title, pick, tag, sp, b1, b2 = st.columns([2.1, 2.2, 1.3, 0.3, 1.1, 0.9],
                                              vertical_alignment="center")
    title.markdown(f"## {common.scenario_title({'scenario_id': rec.scenario_id})}")
    chosen = pick.selectbox("Run", list(labels), index=list(labels).index(str(rec.run_dir)),
                            format_func=labels.get, label_visibility="collapsed")
    if chosen != str(rec.run_dir):
        common.open_run(chosen)
        st.rerun()
    indicative = rec.solvers == ["screening"]
    tag.markdown(badge("SCREENING · INDICATIVE", "warn") if indicative
                 else badge(" + ".join(rec.solvers).upper(), "info"), unsafe_allow_html=True)
    if b1.button("Tweak & re-run", width="stretch"):
        common.set_cfg(cfg_from_run(rec.run_dir), step=1)
        common.go("scenario")
    if b2.button("Export", type="primary", width="stretch", icon=":material/download:"):
        common.go("export")


def render() -> None:
    rec = common.current_run()
    if rec is None:
        _empty()
        return
    _header(rec)
    summary = rec.summary
    solvers = [s for s in rec.solvers if (rec.run_dir / s / "depth_max.tif").exists()]

    left, centre, right = st.columns([1.05, 3.3, 1.35], gap="medium")
    with left:
        if not solvers:
            st.info("This run has no depth raster to map.")
            layer, solver = None, None
        else:
            solver = (st.segmented_control("Solver", solvers, default=solvers[0], key="res_solver")
                      if len(solvers) > 1 else solvers[0]) or solvers[0]
            sdir = rec.run_dir / solver
            avail = [k for k, (_, f) in LAYERS.items() if (sdir / f).exists()]
            layer = st.radio("Map layer", avail, format_func=lambda k: LAYERS[k][0], key="res_layer")
        basemap = st.segmented_control("Basemap", list(BASEMAPS), default="Dark", key="res_base") or "Dark"
        show_outlines = st.checkbox("Depth-class outlines", value=False,
                                    help="Polygons of each depth class; patches under 5 ha are left out.")

    if layer is None:
        return
    depth, tr, crs = _load(sdir / "depth_max.tif")
    arr_path = sdir / "arrival_min.tif"
    arrival = _load(arr_path)[0] if arr_path.exists() else None
    shown = depth if layer == "depth" else _load(sdir / LAYERS[layer][1])[0]

    with centre:
        mask, t_now, t_max = None, None, None
        if arrival is not None:
            wet_arr = arrival[np.isfinite(arrival) & (np.nan_to_num(depth) > 0)]
            if wet_arr.size:
                t_max = int(np.ceil(wet_arr.max()))
        png, bounds, legend = layer_png_bytes(shown, tr, crs, layer, mask=None)
        slot = st.empty()
        if t_max:
            t_now = st.slider("Flood extent at minutes after breach", 0, t_max, t_max,
                              step=max(1, t_max // 60), format="T+%d min", key="res_time")
            if t_now < t_max:
                mask = np.isfinite(arrival) & (arrival <= t_now)
                png, bounds, legend = layer_png_bytes(shown, tr, crs, layer, mask=mask)
        outlines = _outlines(str(sdir / "depth_max.tif"), (sdir / "depth_max.tif").stat().st_mtime) \
            if show_outlines else None
        with slot:
            st.iframe(_map_html(png, bounds, summary.get("dam") or {}, basemap, outlines),
                                  height=600)

    cell_area = abs(tr.a * tr.e)
    classes = depth_class_areas(depth, cell_area, mask=mask)
    with left:
        st.markdown(f'<div class="hi-eyebrow" style="margin-top:14px">{legend["title"]}</div>',
                    unsafe_allow_html=True)
        if layer == "depth":
            st.markdown(class_bars_html(classes), unsafe_allow_html=True)
            peak = float(np.nanmax(depth)) if np.isfinite(depth).any() else 0.0
            st.caption(f"Area per depth class{f' at T+{t_now} min' if mask is not None else ''}. "
                       f"Deepest cell {peak:.1f} m.")
        else:
            st.markdown(legend_html(legend), unsafe_allow_html=True)

    with right:
        br = summary.get("breach") or {}
        diag = ((summary.get("solvers") or {}).get(solver) or {}).get("diagnostics") or {}
        wet_km2 = sum(c["area_ha"] for c in classes) / 100.0
        path_km = diag.get("path_length_km")
        front = f"Front reaches {path_km:.1f} km" if path_km else "Front at corridor end"
        st.markdown(stat_grid([
            ("Flooded area" + (f" at T+{t_now}" if mask is not None else ""),
             f"{wet_km2:,.1f}", "km²", None),
            (front, common.stat_value(t_max, "{:,.0f}"), "min", None),
            ("Peak discharge", common.stat_value(br.get("peak_flow_m3s")), "m³/s",
             f"failure time {common.stat_value(br.get('failure_time_min'))} min"),
            ("Released volume", common.stat_value((br.get("volume_m3") or 0) / 1e6, "{:,.1f}"),
             "Mm³", None),
        ]), unsafe_allow_html=True)

        hyd = rec.run_dir / "hydrograph.csv"
        if hyd.exists():
            with st.container(border=True):
                st.markdown("**Breach hydrograph**")
                h = pd.read_csv(hyd)
                st.area_chart(pd.DataFrame({"Hours": h["t_s"] / 3600.0, "Q (m³/s)": h["q_m3s"]}),
                              x="Hours", y="Q (m³/s)", color="#6FD0E4", height=150)

        loss_csv = rec.run_dir / "screening" / "loss.csv"
        with st.container(border=True):
            st.markdown("**People & assets exposed**")
            if loss_csv.exists():
                df = pd.read_csv(loss_csv)
                st.dataframe(df, hide_index=True, width="stretch")
                if "indicative_loss_inr" in df:
                    st.metric("Indicative loss", f"₹ {df['indicative_loss_inr'].sum() / 1e7:,.1f} crore",
                              help="Starter damage curves; calibration pending.")
            else:
                st.caption("Not computed for this run: the scenario uses no land cover. Add ESA "
                           "WorldCover (needs Earth Engine) to get exposed area and indicative loss.")
                if st.button("Add land cover and re-run", key="add_lc"):
                    new = cfg_from_run(rec.run_dir)
                    new.setdefault("roughness", {})["landcover"] = "worldcover_gee"
                    common.set_cfg(new, step=2)
                    common.go("scenario")

        st.markdown(caveat_html(relevant_caveats(summary)), unsafe_allow_html=True)

        comp = summary.get("comparison")
        others = [r for r in common.runs() if r.scenario_id == rec.scenario_id]
        if comp or len(others) > 1:
            with st.expander("Compare"):
                if comp:
                    for key, res in comp.items():
                        st.markdown(f"**{key.replace('_', ' ')}**")
                        if res.get("map") and Path(res["map"]).exists():
                            st.image(res["map"])
                        st.json({k: v for k, v in res.items() if k != "map"}, expanded=False)
                if len(others) > 1:
                    st.dataframe(pd.DataFrame({
                        "Run": [format_stamp(r.stamp) for r in others],
                        "Solvers": [", ".join(r.solvers) for r in others],
                        "Qp (m³/s)": [r.peak_flow_m3s for r in others],
                        "km²": [r.area_km2 for r in others],
                    }), hide_index=True, width="stretch",
                        column_config={"Qp (m³/s)": st.column_config.NumberColumn(format="%,.0f"),
                                       "km²": st.column_config.NumberColumn(format="%.1f")})
