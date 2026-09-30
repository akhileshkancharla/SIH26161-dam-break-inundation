"""Step 5 · Export: files grouped by who needs them, one zip, caveats on."""

from __future__ import annotations

import json

import streamlit as st

from dam_break.dashboard.runs import (EXPORT_GROUPS, EXPORT_PRESETS, bundle_zip, caveats_text,
                                      cfg_from_run, export_files, human_size)
from dam_break.dashboard.views import common


def _key(f, run_dir) -> str:
    return "exp_" + f.path.relative_to(run_dir).as_posix()


def _apply_preset(files, run_dir, tag: str) -> None:
    for f in files:
        st.session_state[_key(f, run_dir)] = tag in f.tags


@st.cache_data(show_spinner=False, max_entries=4)
def _zip(run_dir: str, paths: tuple[str, ...], stamp: tuple[float, ...], caveats: str | None) -> bytes:
    from pathlib import Path
    return bundle_zip(run_dir, [Path(p) for p in paths], caveats)


def render() -> None:
    rec = common.current_run()
    if rec is None:
        st.markdown("# Nothing to export yet")
        if st.button("Go to Start", type="primary"):
            common.go("start")
        return
    run_dir = rec.run_dir
    files = export_files(run_dir)

    if st.session_state.get("exp_run") != str(run_dir):
        st.session_state.exp_run = str(run_dir)
        st.session_state.exp_preset = "Recommended"
        _apply_preset(files, run_dir, "recommended")

    main, side = st.columns([2.5, 1], gap="large")
    with main:
        st.markdown("# Export & share")
        st.markdown(f'<div class="hi-muted">{common.scenario_title({"scenario_id": rec.scenario_id})} · '
                    f'run of {rec.label}</div>', unsafe_allow_html=True)
        st.pills("Pick for", list(EXPORT_PRESETS), key="exp_preset",
                 on_change=lambda: _apply_preset(
                     files, run_dir, EXPORT_PRESETS.get(st.session_state.exp_preset or "", "")))
        groups = [g for g in EXPORT_GROUPS if any(f.group == g for f in files)]
        cols = st.columns(2)
        for i, g in enumerate(groups):
            with cols[i % 2].container(border=True):
                st.markdown(f"**{g}**")
                for f in (f for f in files if f.group == g):
                    st.checkbox(f"{f.label}  ·  {human_size(f.size)}", key=_key(f, run_dir),
                                help=f.path.relative_to(run_dir).as_posix())
                if g == "Reproduce this run":
                    st.caption("Anyone can re-run it with `python scripts/run_pipeline.py "
                               "scenario.json` or the Colab notebook.")

    chosen = [f for f in files if st.session_state.get(_key(f, run_dir))]
    total = sum(f.size for f in chosen)
    with side:
        with st.container(border=True):
            st.markdown("### Your bundle")
            st.markdown(f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:24px;'
                        f'font-weight:600">{len(chosen)} file{"s" if len(chosen) != 1 else ""} · {human_size(total)}</div>',
                        unsafe_allow_html=True)
            with_caveats = st.checkbox(
                "Include caveats sheet (recommended)", value=True,
                help="CAVEATS.txt says this is screening output and which registry values are "
                     "unverified. Keep it whenever results leave the team.")
            if chosen:
                data = _zip(str(run_dir), tuple(str(f.path) for f in chosen),
                            tuple(f.path.stat().st_mtime for f in chosen),
                            caveats_text(rec.summary) if with_caveats else None)
                st.download_button("Download .zip", data,
                                   file_name=f"{rec.scenario_id}_{rec.stamp}.zip",
                                   mime="application/zip", type="primary",
                                   width="stretch", icon=":material/download:")
            else:
                st.button("Download .zip", disabled=True, width="stretch",
                          help="Tick at least one file")
            kml = next((f for f in files if f.path.suffix.lower() == ".kml"), None)
            if kml:
                st.download_button("KML for Google Earth", kml.path.read_bytes(),
                                   file_name=kml.path.name, width="stretch")
        with st.expander("Scenario JSON (copy)"):
            try:
                st.code(json.dumps(cfg_from_run(run_dir), indent=2), language="json")
            except (OSError, ValueError):
                st.caption("This run has no scenario.json.")
        with st.container(border=True):
            st.markdown("**What next**")
            if st.button("Run the High case for a range", width="stretch"):
                new = cfg_from_run(run_dir)
                new.setdefault("breach", {})["case"] = "high"
                common.set_cfg(new, step=4)
                common.go("scenario")
            if "delft3d_fm" not in rec.solvers and st.button(
                    "Add Delft3D FM for a 2D result", width="stretch"):
                new = cfg_from_run(run_dir)
                new["solvers"] = list(dict.fromkeys(new.get("solvers", []) + ["delft3d_fm"]))
                common.set_cfg(new, step=3)
                common.go("scenario")
            if st.button("Back to all runs", width="stretch"):
                common.go("start")
