"""Step 1 · Start: presets, registry dams, imports, recent runs."""

from __future__ import annotations

import json
import re

import pandas as pd
import streamlit as st

from dam_break.dashboard.runs import format_stamp
from dam_break.dashboard.theme import solver_list_html
from dam_break.dashboard.util import scenario_from_registry
from dam_break.dashboard.views import common
from dam_break.ingestion.dams import load_registry


def _preset_card() -> None:
    with st.container(border=True):
        st.markdown("### Replay a historic event")
        st.markdown('<div class="hi-muted">Presets with documented volumes. '
                    'The fastest way to a first map.</div>', unsafe_allow_html=True)
        for stem, pcfg in common.presets().items():
            dam = (pcfg.get("dam") or {}).get("name", stem)
            desc = str(pcfg.get("description", "")).split(". ")[0]
            year = re.search(r"(19|20)\d\d", str(pcfg.get("scenario_id", "")))
            label = f"**{dam}** · {year.group(0)}" if year else f"**{dam}**"
            if st.button(label, key=f"preset_{stem}",
                         width="stretch", help=desc):
                common.set_cfg(pcfg, step=1)
                common.go("scenario")


def _registry_card() -> None:
    reg = load_registry()
    with st.container(border=True):
        st.markdown("### Pick a registry dam")
        q = st.text_input(f"Search {len(reg)} dams (NRLD/GeoDAR subset)",
                          placeholder="Name, river or state")
        view = reg
        if q:
            hay = (reg["name"] + " " + reg["river"].fillna("") + " " + reg["state"].fillna("")).str.lower()
            view = reg[hay.str.contains(q.lower(), regex=False)]
        table = pd.DataFrame({
            "Dam": view["name"],
            "State": view["state"].fillna(""),
            "Checked": view["verified"].map(lambda v: "yes" if str(v).lower() == "true" else "no"),
        })
        sel = st.dataframe(table, hide_index=True, width="stretch", height=190,
                           on_select="rerun", selection_mode="single-row", key="reg_table")
        rows = sel.selection.rows if sel else []
        picked = table.iloc[rows[0]]["Dam"] if rows else None
        if st.button(f"Model {picked}" if picked else "Select a dam above",
                     disabled=picked is None, type="primary", width="stretch"):
            new = scenario_from_registry(picked)
            base = common.cfg()
            for block in ("breach", "terrain", "roughness", "run"):
                if block in base:
                    new[block] = base[block]
            common.set_cfg(new, step=0)
            common.go("scenario")


def _import_card() -> None:
    with st.container(border=True):
        st.markdown("### Bring your own")
        st.markdown('<div class="hi-muted">A scenario JSON from Colab or the CLI, or a dam '
                    'that is not in the registry.</div>', unsafe_allow_html=True)
        up = st.file_uploader("Scenario JSON", type=["json"], label_visibility="collapsed")
        if up is not None:
            try:
                new = json.loads(up.getvalue().decode("utf-8"))
            except ValueError as exc:
                st.error(f"Not valid JSON: {exc}")
            else:
                _, err = common.validate(new)
                if err:
                    st.error(f"This scenario won't load: {err}")
                elif st.button("Open imported scenario", type="primary", width="stretch"):
                    common.set_cfg(new, step=4)
                    common.go("scenario")
        if st.button("Enter dam coordinates", width="stretch"):
            common.set_cfg({
                "scenario_id": "custom_dam",
                "description": "custom dam entered in the dashboard",
                "dam": {"name": "Custom dam", "lat": 22.81, "lon": 70.90,
                        "type": "earthfill", "height_m": 25.0, "storage_mcm": 50.0},
                "solvers": ["screening"],
                "exports": ["shp", "kml", "gpkg", "tif", "csv"],
            }, step=0)
            common.go("scenario")


def _recent_runs() -> None:
    head, link = st.columns([4, 1], vertical_alignment="bottom")
    head.markdown("## Recent runs")
    runs = common.runs()
    if not runs:
        st.info("No runs yet. Start from a preset above; results are saved under outputs/.")
        return
    df = pd.DataFrame({
        "Run": [format_stamp(r.stamp) for r in runs],
        "Scenario": [common.scenario_title({"scenario_id": r.scenario_id}) for r in runs],
        "Solvers": [", ".join(r.solvers) for r in runs],
        "Peak Q (m³/s)": [r.peak_flow_m3s for r in runs],
        "Flooded (km²)": [r.area_km2 for r in runs],
        "Runtime (s)": [r.runtime_s for r in runs],
    })
    for col in ("Peak Q (m³/s)", "Flooded (km²)", "Runtime (s)"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    link.caption(f"{len(runs)} runs on disk")
    sel = st.dataframe(
        df, hide_index=True, width="stretch", height=min(38 + 35 * len(df), 290),
        on_select="rerun", selection_mode="single-row", key="runs_table",
        column_config={
            "Peak Q (m³/s)": st.column_config.NumberColumn(format="%,.0f"),
            "Flooded (km²)": st.column_config.NumberColumn(format="%.1f"),
            "Runtime (s)": st.column_config.NumberColumn(format="%.0f"),
        })
    rows = sel.selection.rows if sel else []
    if rows:
        rec = runs[rows[0]]
        if st.button(f"Open results · {rec.label}", type="primary"):
            common.open_run(rec.run_dir)
            common.go("results")
    else:
        st.caption("Select a run to reopen its results without re-running.")


def _watchlist_card() -> None:
    nrt_root = common.OUTPUTS_DIR / "nrt"
    sweeps = sorted(nrt_root.glob("*/watchlist.csv")) if nrt_root.is_dir() else []
    with st.container(border=True):
        st.markdown("### Satellite watchlist")
        if not sweeps:
            st.markdown('<div class="hi-muted">No Sentinel-1 sweeps yet. A sweep compares radar '
                        'backscatter before and after around each watched dam and raises an '
                        'alert when new water appears. Needs Google Earth Engine.</div>',
                        unsafe_allow_html=True)
            st.code("python scripts/run_nrt_watchlist.py", language="bash")
            return
        latest = sweeps[-1]
        df = pd.read_csv(latest)
        alerts = int((df.get("status") == "ALERT").sum()) if "status" in df else 0
        st.markdown(f"Latest sweep **{latest.parent.name}** · {len(df)} dams · "
                    f"**{alerts} alert{'s' if alerts != 1 else ''}**")
        if alerts:
            st.error("Alert: " + ", ".join(df.loc[df["status"] == "ALERT", "dam"].astype(str)))
        with st.expander("Sweep table"):
            st.dataframe(df, hide_index=True, width="stretch")


def render() -> None:
    job = common.running_job()
    if job is not None:
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.info(f"A run is in progress: {common.scenario_title(job.cfg)}.")
        if c2.button("Watch run", width="stretch"):
            common.go("run")

    main, side = st.columns([2.4, 1], gap="large")
    with main:
        st.markdown("# Model a dam failure")
        st.markdown('<div class="hi-muted" style="margin-bottom:18px">Pick a starting point. '
                    'Every run is saved with its scenario, so you can reopen results without '
                    're-running the pipeline.</div>', unsafe_allow_html=True)
        a, b, c = st.columns(3)
        with a:
            _preset_card()
        with b:
            _registry_card()
        with c:
            _import_card()
        _recent_runs()
    with side:
        with st.container(border=True):
            st.markdown("### What this machine can run")
            st.markdown(solver_list_html(common.solver_status()), unsafe_allow_html=True)
        _watchlist_card()
        st.caption("Most registry values are demo-grade until checked against NRLD/GeoDAR. "
                   "Unchecked dams are flagged in the scenario builder and on every result.")
