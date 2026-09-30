"""HydroInundate dashboard: five steps over one pipeline.

Start -> Scenario -> Run -> Results -> Export. Each step is its own page
(src/dam_break/dashboard/views/); runs execute in a background process and
are read back from outputs/, so results survive a refresh.

Run from the repo root:  streamlit run src/dam_break/dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, "") or __package__.split(".")[0] != "dam_break":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from dam_break.dashboard.theme import CSS, brand_html, solver_dots_html  # noqa: E402
from dam_break.dashboard.views import common, export, results, run, scenario, start  # noqa: E402

STEPS = [
    ("start", "Start", start.render, ":material/home:"),
    ("scenario", "Scenario", scenario.render, ":material/tune:"),
    ("run", "Run", run.render, ":material/play_circle:"),
    ("results", "Results", results.render, ":material/map:"),
    ("export", "Export", export.render, ":material/download:"),
]


def main() -> None:
    st.set_page_config(page_title="HydroInundate · SIH 26161",
                       page_icon=":material/water:", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    pages = {key: st.Page(fn, title=title, url_path=key, default=(key == "start"))
             for key, title, fn, _ in STEPS}
    common.PAGES.update(pages)
    nav = st.navigation(list(pages.values()), position="hidden")

    brand, steps, dots = st.columns([1.7, 5.3, 2.0], vertical_alignment="center")
    with brand:
        st.html(brand_html())
    with steps:
        for col, (i, (key, title, _, icon)) in zip(st.columns(len(STEPS)), enumerate(STEPS, 1)):
            col.page_link(pages[key], label=f"{i} · {title}", icon=icon)
    dots.markdown(solver_dots_html(common.solver_status()), unsafe_allow_html=True)
    st.markdown('<div class="hi-topline"></div>', unsafe_allow_html=True)

    nav.run()


if __name__ == "__main__":  # streamlit runs the entry script as __main__
    main()
