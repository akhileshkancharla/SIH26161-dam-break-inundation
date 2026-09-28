"""SIH 26161 dashboard shell (Streamlit).

Run from the repo root:
    streamlit run dashboard/app.py

Screens (per the technical guide section 10.2):
  1. Scenario setup   - pick a preset or override breach/corridor parameters
  2. Run monitor      - launch the pipeline, tail the log
  3. Results map      - depth/arrival previews + summary + SHP/KML downloads

This is deliberately a thin shell over run_pipeline: heavy work stays in the
backend pipeline, and the demo can run from pre-computed outputs (offline).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from dam_break.config import repo_root, load_scenario  # noqa: E402
from dam_break.ingestion.dams import load_registry  # noqa: E402

st.set_page_config(page_title="SIH 26161 Dam Break", layout="wide")


@st.cache_data
def scenarios() -> list[Path]:
    return sorted((repo_root() / "configs" / "scenarios").glob("*.json"))


def runs_for(scenario_id: str) -> list[Path]:
    root = repo_root() / "outputs" / scenario_id
    return sorted(root.glob("*/summary.json"), reverse=True) if root.exists() else []


# ---------------------------------------------------------------- scenario ---
st.title("SIH 26161 — Dam Break Inundation")
st.caption(
    "Breach -> screening inundation -> SHP/KML. Solver outputs marked "
    "'screening' are indicative; Delft3D FM and DualSPHysics runs are "
    "orchestrated from the same scenario JSON."
)

left, right = st.columns([2, 3])
with left:
    preset = st.selectbox("Scenario preset", scenarios(), format_func=lambda p: p.stem)
    cfg = json.loads(preset.read_text(encoding="utf-8"))
    scenario = load_scenario(cfg)
    st.subheader("Dam")
    st.write(f"**{scenario.dam.name}** — {scenario.dam.dam_type}")
    st.write(f"lat/lon: {scenario.dam.lat:.4f}, {scenario.dam.lon:.4f}")
    if not scenario.dam.registry_verified:
        st.warning("Registry attributes are demo-grade; verify against NRLD/GeoDAR.")
    st.subheader("Overrides")
    cfg.setdefault("breach", {})["case"] = st.selectbox(
        "Breach case", ["low", "expected", "high"],
        index=["low", "expected", "high"].index(scenario.breach.case),
    )
    cfg.setdefault("breach", {})["release_fraction"] = st.slider(
        "Release fraction", 0.1, 1.0, scenario.breach.release_fraction, 0.05
    )
    cfg.setdefault("run", {})["attenuation_km"] = st.number_input(
        "Attenuation length scale (km; 0 = off)",
        min_value=0, value=int(scenario.run.attenuation_km or 0),
    )
    if cfg["run"]["attenuation_km"] == 0:
        cfg["run"]["attenuation_km"] = None

with right:
    with st.expander("Dam registry (demo subset of NRLD/GeoDAR)", expanded=False):
        st.dataframe(load_registry())

# -------------------------------------------------------------------- run ---
st.header("Run")
col1, col2, col3 = st.columns([1, 2, 2])
with col1:
    if st.button("Run pipeline", type="primary"):
        with st.spinner("Running pipeline... check the log below"):
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                json.dump(cfg, fh)
                tmp = fh.name
            proc = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "run_pipeline.py"), tmp],
                capture_output=True, text=True, cwd=str(REPO),
            )
            st.session_state["log"] = proc.stdout + proc.stderr
            st.session_state["rc"] = proc.returncode
with col2:
    if "log" in st.session_state:
        st.code(st.session_state["log"][-4000:], "text")
        if st.session_state.get("rc") != 0:
            st.error(f"pipeline exited with {st.session_state['rc']}")

# ----------------------------------------------------------------- results ---
st.header("Results")
runs = runs_for(scenario.scenario_id)
if not runs:
    st.info("No runs yet — run the pipeline above or from Colab and refresh.")
else:
    picked = st.selectbox("Run", runs, format_func=lambda p: p.parent.name)
    summary = json.loads(picked.read_text(encoding="utf-8"))
    meta, breach_box, solver_box = st.columns(3)
    meta.metric("Runtime (s)", summary.get("runtime_s"))
    b = summary.get("breach", {})
    breach_box.metric("Peak flow (m³/s)", f"{b.get('peak_flow_m3s', 0):,.0f}")
    if "screening" in summary.get("solvers", {}):
        diag = summary["solvers"]["screening"].get("diagnostics", {})
        solver_box.metric("Inundated area (km²)",
                          f"{diag.get('inundated_area_km2', 0):.1f}")
    run_dir = picked.parent
    images = sorted(run_dir.rglob("*.png"))
    if images:
        cols = st.columns(min(3, len(images)))
        for i, img in enumerate(images[:6]):
            with cols[i % len(cols)]:
                st.image(str(img), caption=img.name)
                st.caption(str(img.relative_to(run_dir)))
    st.subheader("Downloads")
    zips = sorted(run_dir.rglob("*.shp.zip"))
    kmls = sorted(run_dir.rglob("*.kml"))
    for f in zips + kmls:
        st.download_button(
            f"⬇ {f.relative_to(run_dir)}", data=f.read_bytes(), file_name=f.name
        )
    with st.expander("summary.json"):
        st.json(summary)
