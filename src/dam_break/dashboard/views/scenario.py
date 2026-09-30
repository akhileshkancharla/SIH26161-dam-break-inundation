"""Step 2 · Scenario: dam, breach, corridor, solvers, review - with a live
breach hydrograph preview that needs no pipeline run."""

from __future__ import annotations

import copy
import json

import pandas as pd
import streamlit as st

from dam_break.config import BREACH_CASES, BREACH_MODES
from dam_break.dashboard.theme import badge, caveat_html, stat_grid
from dam_break.dashboard.util import scenario_from_registry
from dam_break.dashboard.views import common
from dam_break.ingestion.dams import load_registry, lookup_dam

STEPS = ["Dam", "Breach", "Corridor & terrain", "Solvers", "Review & run"]
MODE_HELP = {
    "overtopping": "Water spills over the crest and erodes it down.",
    "piping": "Internal erosion opens a channel through the embankment.",
    "instantaneous": "Sudden collapse of the whole failed section (weir flow). Worst case; needs the dam length.",
}
CASE_HELP = "Brackets the spread in Froehlich's breach parameters. Run Low and High to show a range."
SOLVER_HELP = {
    "screening": "Volume-conserving fill along the traced river.",
    "delft3d_fm": "Regional 2D hydrodynamics (D-Flow FM).",
    "dualsphysics": "Near-field SPH around the breach.",
}


def _step() -> int:
    return int(st.session_state.get("scn_step", 0))


def _set_step(i: int) -> None:
    st.session_state.scn_step = max(0, min(i, len(STEPS) - 1))


def _dam_attrs(c: dict) -> dict:
    """Registry attributes merged with overrides (or the inline dam)."""
    d = c.get("dam") or {}
    if "lat" in d and "lon" in d:
        base = dict(d)
    else:
        base = dict(lookup_dam(d.get("name", "")) or {})
    base.update(d.get("override") or {})
    return base


def _summaries(c: dict) -> list[str]:
    a = _dam_attrs(c)
    b = c.get("breach") or {}
    t = c.get("terrain") or {}
    h, s = a.get("height_m"), a.get("storage_mcm")
    return [
        f"{a.get('name', '?')} · {common.stat_value(h, '{:.1f}')} m · {common.stat_value(s, '{:,.1f}')} Mm³",
        f"{b.get('mode', 'overtopping')} · {b.get('case', 'expected')} · "
        f"{float(b.get('release_fraction', 0.6)) * 100:.0f} %",
        f"{t.get('corridor_length_km', 30):g} × {t.get('corridor_width_km', 6):g} km · "
        f"{t.get('dem', 'aws_terrarium')}",
        ", ".join(c.get("solvers") or ["screening"]),
        "Check and launch",
    ]


# ------------------------------------------------------------------ steps


def _dam_step(c: dict) -> None:
    st.markdown("# Which dam?")
    source = st.segmented_control(
        "Dam source", ["Registry dam", "Custom location"], key="dam_source",
        default="Custom location" if "lat" in (c.get("dam") or {}) else "Registry dam")
    reg = load_registry()
    if source == "Custom location":
        d = c.setdefault("dam", {})
        if "lat" not in d:
            a = _dam_attrs(c)
            d.clear()
            d.update({k: a[k] for k in ("name", "lat", "lon", "height_m", "storage_mcm", "length_m")
                      if a.get(k) is not None})
            d["name"] = f"{d.get('name', 'Custom')} (custom)"
        d["name"] = st.text_input("Dam name", d.get("name", "Custom dam"))
        c1, c2 = st.columns(2)
        d["lat"] = c1.number_input("Latitude", -90.0, 90.0, float(d.get("lat", 22.81)), 0.001, format="%.4f")
        d["lon"] = c2.number_input("Longitude", -180.0, 180.0, float(d.get("lon", 70.90)), 0.001, format="%.4f")
        target = d
        c.setdefault("scenario_id", "custom_dam")
    else:
        d = c.setdefault("dam", {})
        if "lat" in d:  # coming back from a custom dam: fall back to the registry
            new = scenario_from_registry(reg["name"].iloc[0])
            c["dam"] = new["dam"]
            d = c["dam"]
        names = sorted(reg["name"].tolist())
        current = (lookup_dam(d.get("name", "")) or {}).get("name", names[0])
        picked = st.selectbox("Registry dam", names, index=names.index(current))
        if picked != current:
            new = scenario_from_registry(picked)
            c["dam"], c["scenario_id"], c["description"] = new["dam"], new["scenario_id"], new["description"]
            st.rerun()
        hit = lookup_dam(picked) or {}
        verified = str(hit.get("verified")).lower() == "true"
        st.markdown(
            f"{hit.get('type', '')} · {hit.get('river', '')} · {hit.get('state', '')} · "
            f"{float(hit.get('lat', 0)):.3f}, {float(hit.get('lon', 0)):.3f} &nbsp; "
            + badge("REGISTRY CHECKED" if verified else "UNVERIFIED", "ok" if verified else "warn"),
            unsafe_allow_html=True)
        if hit.get("notes"):
            st.caption(str(hit["notes"]))
        target = d.setdefault("override", {})

    a = _dam_attrs(c)
    c1, c2, c3 = st.columns(3)
    target["height_m"] = c1.number_input("Height (m)", 1.0, 350.0, float(a.get("height_m") or 25.0), 0.5)
    target["storage_mcm"] = c2.number_input("Storage (Mm³)", 0.1, 100000.0,
                                            float(a.get("storage_mcm") or 50.0), 1.0)
    length = c3.number_input("Crest length (m, 0 = unknown)", 0.0, 20000.0,
                             float(a.get("length_m") or 0.0), 10.0)
    if length > 0:
        target["length_m"] = length
    else:
        target.pop("length_m", None)
    c["scenario_id"] = st.text_input(
        "Scenario name (used for the output folder)", c.get("scenario_id", "scenario"),
        help="Letters, digits and underscores work best.")


def _breach_step(c: dict) -> None:
    b = c.setdefault("breach", {})
    st.markdown("# How does the dam fail?")
    st.markdown('<div class="hi-muted">These choices shape the breach hydrograph. The preview '
                'updates as you change them, with no run needed.</div>', unsafe_allow_html=True)
    mode = st.segmented_control("Failure mode", list(BREACH_MODES), key="scn_mode",
                                default=b.get("mode", "overtopping"), format_func=str.capitalize)
    b["mode"] = mode or b.get("mode", "overtopping")
    st.caption(MODE_HELP[b["mode"]])
    case = st.segmented_control("Uncertainty bracket", list(BREACH_CASES), key="scn_case",
                                default=b.get("case", "expected"), format_func=str.capitalize)
    b["case"] = case or b.get("case", "expected")
    st.caption(CASE_HELP)
    pct = st.slider("Share of storage released", 10, 100,
                    int(round(float(b.get("release_fraction", 0.6)) * 100)), 5, format="%d %%")
    b["release_fraction"] = pct / 100.0
    storage = _dam_attrs(c).get("storage_mcm")
    if storage:
        st.caption(f"{float(storage) * pct / 100:,.1f} Mm³ of the {float(storage):,.1f} Mm³ "
                   "reservoir leaves through the breach.")
    b.setdefault("method", "froehlich_2008")
    with st.expander("Advanced: failure fraction, duration, time step"):
        b["failure_fraction"] = st.slider(
            "Failed share of the crest (instantaneous mode)", 0.05, 1.0,
            float(b.get("failure_fraction", 1.0)), 0.05)
        r = c.setdefault("run", {})
        c1, c2 = st.columns(2)
        r["duration_h"] = c1.number_input("Duration (h)", 1.0, 96.0, float(r.get("duration_h", 24.0)), 1.0)
        r["dt_s"] = c2.select_slider("Time step (s)", [15, 30, 60, 120, 300],
                                     value=int(r.get("dt_s", 60)))
        st.caption("Peak flow uses Froehlich (1995); breach width and failure time use "
                   "Froehlich (2008).")


def _corridor_step(c: dict) -> None:
    t = c.setdefault("terrain", {})
    rough = c.setdefault("roughness", {})
    r = c.setdefault("run", {})
    st.markdown("# How far downstream?")
    c1, c2 = st.columns(2)
    t["corridor_length_km"] = c1.slider("Reach (km)", 5, 80, int(t.get("corridor_length_km", 30)))
    t["corridor_width_km"] = c2.slider("Width (km)", 1, 20, int(t.get("corridor_width_km", 6)))
    dems = {"aws_terrarium": "AWS Terrarium (no sign-in)", "gee_glo30": "Copernicus GLO-30 (Earth Engine)"}
    cur = t.get("dem", "aws_terrarium")
    if cur.startswith("file:"):
        dems[cur] = f"Local file: {cur[5:]}"
    t["dem"] = st.selectbox("Terrain source", list(dems), index=list(dems).index(cur),
                            format_func=dems.get)
    lc = st.radio("Land cover", ["none", "worldcover_gee"], horizontal=True,
                  index=0 if rough.get("landcover", "none") == "none" else 1,
                  format_func={"none": "None (uniform roughness)",
                               "worldcover_gee": "ESA WorldCover (Earth Engine)"}.get)
    rough["landcover"] = lc
    st.caption("Land cover sets roughness per cell and enables exposure and loss figures. "
               "It needs an authenticated Earth Engine session.")
    c1, c2 = st.columns(2)
    rough["default_n"] = c1.number_input("Manning's n (uniform / fallback)", 0.01, 0.30,
                                         float(rough.get("default_n", 0.05)), 0.005, format="%.3f")
    att = c2.number_input("Attenuation length (km, 0 = off)", 0, 500,
                          int(r.get("attenuation_km") or 0),
                          help="Optional exponential volume loss along the reach (screening only).")
    r["attenuation_km"] = att or None


def _solvers_step(c: dict) -> None:
    st.markdown("# Which solvers?")
    status = common.solver_status()
    chosen = []
    for key in ("screening", "delft3d_fm", "dualsphysics"):
        state, title, detail = status[key]
        on = st.checkbox(f"**{title}** — {SOLVER_HELP[key]}", value=key in (c.get("solvers") or []),
                         key=f"solver_{key}")
        st.caption(detail)
        if on:
            chosen.append(key)
            if state != "ready":
                st.warning(f"{title} can't run to completion on this machine: {detail}")
    if not chosen:
        st.error("Pick at least one solver. Screening runs anywhere.")
    c["solvers"] = chosen or ["screening"]
    if len(chosen) > 1:
        st.caption("Runs with two or more solvers also produce a depth comparison map.")


def _review_step(c: dict) -> None:
    st.markdown("# Review & run")
    scen, err = common.validate(c)
    if err:
        st.error(f"This scenario won't run yet: {err}")
    else:
        rows = [(s, v) for s, v in zip(STEPS[:4], _summaries(c)[:4])]
        st.table(pd.DataFrame(rows, columns=["Step", "Setting"]).set_index("Step"))
        if not scen.dam.registry_verified:
            st.markdown(caveat_html(["dam attributes are demo-grade until verified against "
                                     "NRLD/GeoDAR; results will carry this caveat"],
                                    "Heads-up"), unsafe_allow_html=True)
    with st.expander("Scenario JSON"):
        st.code(json.dumps(c, indent=2), language="json")
    c1, c2 = st.columns(2)
    if c2.button("Save to configs/scenarios", width="stretch", disabled=bool(err)):
        path = common.SCENARIO_DIR / f"{c['scenario_id']}.json"
        path.write_text(json.dumps(c, indent=2), encoding="utf-8")
        st.toast(f"Saved {path.name}")


# ------------------------------------------------------------------ preview


@st.cache_data(show_spinner=False)
def _preview(cfg_json: str):
    from dam_break.breach.empirical import breach_parameters
    from dam_break.breach.hydrograph import hydrograph_from_breach, hydrograph_volume
    from dam_break.config import load_scenario

    scen = load_scenario(json.loads(cfg_json))
    br = breach_parameters(
        mode=scen.breach.mode, case=scen.breach.case, storage_m3=scen.dam.storage_m3,
        release_fraction=scen.breach.release_fraction, dam_height_m=scen.dam.height_m,
        dam_length_m=scen.dam.length_m, failure_fraction=scen.breach.failure_fraction,
        method=scen.breach.method)
    t, q = hydrograph_from_breach(br, dt_s=scen.run.dt_s, duration_h=scen.run.duration_h)
    stats = {"qp": br.peak_flow_m3s, "tf": br.failure_time_min, "b": br.breach_width_m,
             "v": hydrograph_volume(t, q) / 1e6}
    return stats, pd.DataFrame({"Hours after breach": t / 3600.0, "Discharge (m³/s)": q})


def _preview_panel(c: dict) -> None:
    head, live = st.columns([3, 1], vertical_alignment="center")
    head.markdown("### Breach hydrograph")
    live.markdown(f'<div style="text-align:right">{badge("LIVE", "ok")}</div>', unsafe_allow_html=True)
    try:
        stats, df = _preview(json.dumps(c, sort_keys=True))
    except Exception as exc:  # noqa: BLE001
        st.warning(f"No preview yet: {exc}")
        return
    st.area_chart(df, x="Hours after breach", y="Discharge (m³/s)", color="#6FD0E4", height=240)
    st.markdown(stat_grid([
        ("Peak discharge", f"{stats['qp']:,.0f}", "m³/s", None),
        ("Failure time", f"{stats['tf']:,.0f}", "min", None),
        ("Breach width", f"{stats['b']:,.0f}", "m", None),
        ("Released volume", f"{stats['v']:,.1f}", "Mm³", None),
    ]), unsafe_allow_html=True)
    st.caption("Linear rise over the failure time, then an exponential recession matched to "
               "the released volume.")


# ------------------------------------------------------------------ page


def render() -> None:
    c = common.cfg()
    step = _step()
    rail, body, preview = st.columns([1.05, 2.5, 1.55], gap="large")

    with body:
        st.markdown(f'<div class="hi-eyebrow">Step {step + 1} of {len(STEPS)}</div>',
                    unsafe_allow_html=True)
        [_dam_step, _breach_step, _corridor_step, _solvers_step, _review_step][step](c)
        st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
        back, _, save, nxt = st.columns([1.1, 0.9, 1.2, 1.6])
        if step > 0 and back.button(f"Back: {STEPS[step - 1]}", width="stretch"):
            _set_step(step - 1)
            st.rerun()
        save.download_button("Download JSON", json.dumps(c, indent=2),
                             file_name=f"{c.get('scenario_id', 'scenario')}.json",
                             mime="application/json", width="stretch")
        if step < len(STEPS) - 1:
            if nxt.button(f"Next: {STEPS[step + 1]}", type="primary", width="stretch"):
                _set_step(step + 1)
                st.rerun()
        else:
            _, err = common.validate(c)
            busy = common.running_job() is not None
            if nxt.button("Start run", type="primary", width="stretch",
                          disabled=bool(err) or busy,
                          help="Another run is still going" if busy else None):
                common.launch(copy.deepcopy(c))
                common.go("run")

    # The rail is drawn last so its summaries reflect this run's edits.
    with rail:
        st.markdown('<div class="hi-eyebrow">Scenario</div>', unsafe_allow_html=True)
        st.markdown(f"**{common.scenario_title(c)}**")
        for i, (name, summary) in enumerate(zip(STEPS, _summaries(c))):
            if st.button(f"{i + 1}  {name}", key=f"step_{i}", width="stretch",
                         type="primary" if i == step else "secondary"):
                _set_step(i)
                st.rerun()
            st.markdown(f'<div class="hi-step">{summary}</div>', unsafe_allow_html=True)

    with preview:
        _preview_panel(c)
