"""State and helpers shared by the dashboard pages."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import streamlit as st

from dam_break.config import load_scenario
from dam_break.dashboard.runs import Job, RunRecord, list_runs, load_run, start_job
from dam_break.paths import repo_root

REPO = repo_root()
SCENARIO_DIR = REPO / "configs" / "scenarios"
OUTPUTS_DIR = REPO / "outputs"
JOBS_DIR = OUTPUTS_DIR / "_jobs"
DEFAULT_PRESET = "machhu2_1979"

# Filled by app.py: page key -> st.Page, so pages can link to each other.
PAGES: dict = {}


def go(page: str) -> None:
    st.switch_page(PAGES[page])


# ------------------------------------------------------------- scenario


def presets() -> dict[str, dict]:
    out = {}
    for p in sorted(SCENARIO_DIR.glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return out


def cfg() -> dict:
    """The scenario being edited (a plain dict in the scenario JSON schema)."""
    if "cfg" not in st.session_state:
        st.session_state.cfg = presets().get(DEFAULT_PRESET) or next(iter(presets().values()))
    return st.session_state.cfg


def set_cfg(new_cfg: dict, step: int = 0) -> None:
    st.session_state.cfg = copy.deepcopy(new_cfg)
    st.session_state.scn_step = step


def validate(c: dict):
    """(Scenario, None) or (None, error message)."""
    try:
        return load_scenario(copy.deepcopy(c)), None
    except Exception as exc:  # noqa: BLE001 - shown to the user
        return None, str(exc)


def scenario_title(c: dict) -> str:
    sid = str(c.get("scenario_id", "scenario"))
    return sid.replace("_", " ").strip().capitalize()


# ------------------------------------------------------------- solvers


@st.cache_data(ttl=60, show_spinner=False)
def solver_status() -> dict[str, tuple[str, str, str]]:
    """{solver: (state, title, detail)}; state is ready | build | missing."""
    from dam_break.solvers.delft3d.adapter import dflowfm_binary

    status = {"screening": ("ready", "Screening",
                            "Volume-fill along the traced river. About a minute. Indicative only.")}
    try:
        import hydrolib.core  # noqa: F401
        has_builder = True
    except ImportError:
        has_builder = False
    if dflowfm_binary():
        status["delft3d_fm"] = ("ready", "Delft3D FM", "dflowfm found: builds and runs the 2D model.")
    elif has_builder:
        status["delft3d_fm"] = ("build", "Delft3D FM",
                                "Model files are built here; running needs the dflowfm binary "
                                "(Linux, WSL or Colab; set DFLOWFM_BIN).")
    else:
        status["delft3d_fm"] = ("missing", "Delft3D FM",
                                'Install the delft3d extra: pip install ".[delft3d]".')
    try:
        from dam_break.solvers.sph.adapter import find_tools
        tools = find_tools()
        if tools.solver:
            status["dualsphysics"] = ("ready", "DualSPHysics",
                                      "SPH solver found. Near-field runs need a CUDA GPU.")
        elif tools.gencase:
            status["dualsphysics"] = ("build", "DualSPHysics",
                                      "GenCase found but no solver binary; run on a GPU (Colab T4).")
        else:
            status["dualsphysics"] = ("missing", "DualSPHysics",
                                      "No DualSPHysics folder found; run it from the Colab notebook.")
    except Exception:  # noqa: BLE001
        status["dualsphysics"] = ("missing", "DualSPHysics", "Could not check for DualSPHysics.")
    return status


# ------------------------------------------------------------- runs


@st.cache_data(ttl=10, show_spinner=False)
def runs() -> list[RunRecord]:
    return [r for r in list_runs(OUTPUTS_DIR) if r.run_dir.parent.parent == OUTPUTS_DIR]


def current_run() -> RunRecord | None:
    """The run the Results/Export pages show: the chosen one, else the
    newest run of the current scenario, else the newest run overall."""
    chosen = st.session_state.get("run_dir")
    if chosen:
        rec = load_run(chosen)
        if rec:
            return rec
    all_runs = runs()
    sid = cfg().get("scenario_id")
    same = [r for r in all_runs if r.scenario_id == sid]
    return (same or all_runs or [None])[0]


def open_run(run_dir: str | Path) -> None:
    st.session_state.run_dir = str(run_dir)


# ------------------------------------------------------------- jobs


@st.cache_resource
def _job_registry() -> dict[str, Job]:
    """Jobs live in the server process, so a run survives a page refresh."""
    return {}


def launch(c: dict) -> Job:
    job = start_job(copy.deepcopy(c), REPO, JOBS_DIR)
    _job_registry()[job.job_id] = job
    st.session_state.job_id = job.job_id
    st.session_state.pop("job_opened", None)
    return job


def current_job() -> Job | None:
    reg = _job_registry()
    jid = st.session_state.get("job_id")
    if jid in reg:
        return reg[jid]
    live = [j for j in reg.values() if j.returncode is None]
    return max(live, key=lambda j: j.started) if live else None


def running_job() -> Job | None:
    job = current_job()
    return job if job is not None and job.returncode is None else None


def stat_value(v, fmt: str = "{:,.0f}", missing: str = "–") -> str:
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return missing
