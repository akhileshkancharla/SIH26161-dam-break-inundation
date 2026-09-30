"""Step 3 · Run: live pipeline stages, progress and log for a background run."""

from __future__ import annotations

import streamlit as st

from dam_break.dashboard.runs import parse_progress
from dam_break.dashboard.theme import badge, stages_html
from dam_break.dashboard.views import common


def _fmt_elapsed(s: float) -> str:
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def _config_line(c: dict) -> str:
    b = c.get("breach") or {}
    t = c.get("terrain") or {}
    return (f"{b.get('mode', 'overtopping')} · {b.get('case', 'expected')} · "
            f"{float(b.get('release_fraction', 0.6)) * 100:.0f} % released · "
            f"{t.get('corridor_length_km', 30):g} × {t.get('corridor_width_km', 6):g} km corridor · "
            f"{' + '.join(c.get('solvers') or ['screening'])}")


def _idle() -> None:
    c = common.cfg()
    st.markdown("# Nothing running")
    st.markdown(f'<div class="hi-muted">Ready to run <b>{common.scenario_title(c)}</b>: '
                f'{_config_line(c)}.</div>', unsafe_allow_html=True)
    _, err = common.validate(c)
    if err:
        st.error(f"The scenario needs fixing first: {err}")
    a, b, _ = st.columns([1, 1, 3])
    if a.button("Start run", type="primary", width="stretch", disabled=bool(err)):
        common.launch(c)
        st.rerun()
    if b.button("Edit scenario", width="stretch"):
        common.go("scenario")


def _live(job) -> bool:
    rc = job.returncode
    log = job.log_text()
    prog = parse_progress(log, job.cfg, rc)
    running = rc is None and not prog["finished"]

    top, clock = st.columns([4, 1.2], vertical_alignment="bottom")
    with top:
        st.markdown(f'<div class="hi-eyebrow">Run {job.job_id}</div>', unsafe_allow_html=True)
        verb = ("Running" if running else "Cancelled" if job.cancelled
                else "Failed" if prog["failed"] else "Finished")
        st.markdown(f"# {verb}: {common.scenario_title(job.cfg)}")
        st.markdown(f'<div class="hi-muted">{_config_line(job.cfg)}</div>', unsafe_allow_html=True)
    with clock:
        st.markdown(f'<div style="text-align:right;font-family:\'IBM Plex Mono\',monospace;'
                    f'font-size:34px;font-weight:600;line-height:1">{_fmt_elapsed(job.elapsed_s)}</div>'
                    f'<div class="hi-muted" style="text-align:right;font-size:12.5px">elapsed</div>',
                    unsafe_allow_html=True)
    st.progress(prog["fraction"])

    left, right = st.columns([1.15, 1.6], gap="large")
    with left:
        st.markdown(stages_html(prog["stages"]), unsafe_allow_html=True)
    with right:
        if running:
            cur = next((s for s in prog["stages"] if s.state == "running"), None)
            with st.container(border=True):
                st.markdown(f"### {cur.title if cur else 'Starting up'}")
                st.markdown(f'<div class="hi-muted">{cur.detail if cur else "Launching the pipeline…"}</div>',
                            unsafe_allow_html=True)
                if st.button("Cancel run"):
                    job.cancel()
                    st.rerun()
        elif prog["finished"]:
            with st.container(border=True):
                st.markdown("### " + badge("COMPLETE", "ok") + " Results are ready",
                            unsafe_allow_html=True)
                if prog["run_dir"]:
                    common.open_run(common.REPO / prog["run_dir"].replace("\\", "/"))
                    common.runs.clear()
                    if not st.session_state.get("job_opened") == job.job_id:
                        st.session_state.job_opened = job.job_id
                        common.go("results")
                    if st.button("Open results", type="primary"):
                        common.go("results")
        else:
            with st.container(border=True):
                st.markdown("### " + badge("CANCELLED" if job.cancelled else "FAILED", "danger")
                            + " The run stopped", unsafe_allow_html=True)
                tail = [ln for ln in log.strip().splitlines() if ln.strip()][-1:] or ["no output"]
                st.markdown(f'<div class="hi-muted">{tail[0]}</div>', unsafe_allow_html=True)
                a, b = st.columns(2)
                if a.button("Edit scenario", width="stretch"):
                    common.set_cfg(job.cfg, step=4)
                    common.go("scenario")
                if b.button("Try again", type="primary", width="stretch"):
                    common.launch(job.cfg)
                    st.rerun()
        st.markdown("##### Log")
        prefix = f"[{job.cfg.get('scenario_id', '')}] "
        lines = [ln.removeprefix(prefix) for ln in log.splitlines()]
        st.code("\n".join(lines[-40:]) or "waiting for output…", language="text", height=320,
                wrap_lines=True)
        if running:
            st.caption("Results open automatically. You can leave this page; the run keeps going "
                       "and appears under Recent runs.")
    return running


@st.fragment(run_every=1.0)
def _poll(job) -> None:
    if not _live(job):
        st.rerun()  # job ended: redraw the whole page once, without polling


def render() -> None:
    job = common.current_job()
    if job is None:
        _idle()
    elif job.returncode is None:
        _poll(job)
    else:
        _live(job)
