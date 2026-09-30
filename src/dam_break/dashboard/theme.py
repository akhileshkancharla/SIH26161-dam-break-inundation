"""Look and small HTML components for the dashboard.

Night-survey palette: toned blue-green slate ground, one cyan accent for
actions and the current step, amber for caveats, and the hydro depth ramp
kept for data. IBM Plex Sans for text, IBM Plex Mono for numbers (fonts are
loaded by .streamlit/config.toml; this CSS only restyles).
"""

from __future__ import annotations

from html import escape

BG, PANEL, PANEL2, LINE = "#0D1417", "#131C21", "#1A252B", "#26343C"
TEXT, DIM, ACCENT, INK = "#E4EBEE", "#9AABB4", "#6FD0E4", "#062630"
OK, WARN, DANGER = "#5BC592", "#E7A13A", "#EF6A5E"
MONO = "'IBM Plex Mono', ui-monospace, monospace"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
[data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: {BG}; }}
[data-testid="stHeader"] {{ background: transparent; height: 0; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stMainBlockContainer"], .block-container {{
  padding-top: 0.9rem; padding-bottom: 3rem; max-width: 1520px;
}}
h1 {{ font-size: 1.9rem !important; font-weight: 600 !important; letter-spacing: -0.02em; padding: 0 !important; }}
h2 {{ font-size: 1.15rem !important; font-weight: 600 !important; padding: 0.2rem 0 !important; }}
h3 {{ font-size: 1rem !important; font-weight: 600 !important; }}

/* top bar: brand, step links, solver dots */
.hi-brand {{ display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 17px; color: {TEXT}; white-space: nowrap; }}
.hi-brand .tag {{ font-family: {MONO}; font-size: 11px; font-weight: 400; color: {DIM};
  padding: 2px 7px; border: 1px solid #33444E; border-radius: 4px; }}
.hi-dots {{ display: flex; gap: 14px; justify-content: flex-end; font-family: {MONO}; font-size: 12px; color: {DIM}; white-space: nowrap; }}
.hi-dots span {{ display: inline-flex; align-items: center; gap: 6px; }}
.hi-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
.hi-topline {{ border-bottom: 1px solid {LINE}; margin: 0.2rem 0 1.4rem 0; }}
[data-testid="stPageLink"] a {{ border-radius: 6px; padding: 6px 10px; }}
[data-testid="stPageLink"] a p {{ font-size: 14px; white-space: nowrap; }}

/* buttons: dark ink on the cyan accent for contrast */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
  color: {INK} !important; font-weight: 600; border: none;
}}
[data-testid="stBaseButton-primary"] p {{ color: {INK} !important; font-weight: 600; }}
[data-testid="stBaseButton-primary"]:disabled {{ background: {PANEL2} !important; }}
[data-testid="stBaseButton-primary"]:disabled p {{ color: {DIM} !important; }}
button {{ min-height: 2.6rem; }}

/* reusable blocks */
.hi-eyebrow {{ font-family: {MONO}; font-size: 11.5px; letter-spacing: .08em; color: {DIM}; text-transform: uppercase; margin-bottom: 4px; }}
.hi-muted {{ color: {DIM}; font-size: 14px; line-height: 1.5; }}
.hi-stats {{ display: grid; grid-template-columns: repeat(var(--cols, 2), minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }}
.hi-stat {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 12px 14px; }}
.hi-stat .l {{ font-size: 12px; color: {DIM}; }}
.hi-stat .v {{ font-family: {MONO}; font-size: 22px; font-weight: 600; color: {TEXT}; line-height: 1.3; }}
.hi-stat .v small {{ font-size: 12px; font-weight: 400; color: {DIM}; }}
.hi-stat .n {{ font-size: 11.5px; color: {DIM}; }}
.hi-badge {{ font-family: {MONO}; font-size: 11px; letter-spacing: .06em; padding: 4px 9px; border-radius: 4px; white-space: nowrap; display: inline-block; }}
.hi-badge.warn {{ color: #F2C27A; background: #2E2414; border: 1px solid #6B4C1C; }}
.hi-badge.ok {{ color: #8FE0B6; background: #12291F; border: 1px solid #245A40; }}
.hi-badge.info {{ color: #A5E4F1; background: #13252B; border: 1px solid #2B5561; }}
.hi-badge.danger {{ color: #FFB4AC; background: #2E1614; border: 1px solid #7A2E27; }}
.hi-bars {{ display: grid; grid-template-columns: 12px auto 1fr auto; gap: 8px 10px; align-items: center; font-size: 12.5px; margin: 6px 0 4px; }}
.hi-bars .sw {{ width: 12px; height: 12px; border-radius: 3px; }}
.hi-bars .track {{ height: 6px; border-radius: 3px; background: {LINE}; overflow: hidden; }}
.hi-bars .track i {{ display: block; height: 100%; border-radius: 3px; }}
.hi-bars .num {{ font-family: {MONO}; color: #B8C6CD; text-align: right; }}
.hi-ramp {{ height: 10px; border-radius: 3px; margin: 6px 0 3px; }}
.hi-ramp-labels {{ display: flex; justify-content: space-between; font-family: {MONO}; font-size: 11px; color: {DIM}; }}
.hi-stages {{ list-style: none; margin: 0; padding: 6px 0; background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
.hi-stages li {{ display: flex; gap: 14px; padding: 10px 18px; align-items: flex-start; }}
.hi-stages li.running {{ background: #13252B; box-shadow: inset 2px 0 0 {ACCENT}; }}
.hi-stages .ic {{ width: 22px; height: 22px; flex-shrink: 0; border-radius: 50%; display: flex; align-items: center; justify-content: center; box-sizing: border-box; font-size: 12px; }}
.hi-stages .done .ic {{ background: #183A2C; color: {OK}; }}
.hi-stages .running .ic {{ border: 2px solid {ACCENT}; border-right-color: transparent; animation: hi-spin 1s linear infinite; }}
.hi-stages .queued .ic {{ border: 1.5px solid #33444E; }}
.hi-stages .skipped .ic {{ border: 1.5px dashed #33444E; }}
.hi-stages .failed .ic {{ background: #3A1916; color: {DANGER}; }}
.hi-stages .t {{ font-size: 14px; font-weight: 500; color: {TEXT}; }}
.hi-stages .queued .t, .hi-stages .skipped .t {{ color: {DIM}; font-weight: 400; }}
.hi-stages .skipped .t {{ text-decoration: line-through; }}
.hi-stages .d {{ font-size: 12.5px; color: {DIM}; }}
@keyframes hi-spin {{ to {{ transform: rotate(360deg); }} }}
.hi-caveat {{ background: #1C1A14; border: 1px solid #4A3B1C; border-radius: 8px; padding: 12px 14px; color: #D7CBB3; font-size: 13px; line-height: 1.5; }}
.hi-caveat b {{ color: #F2C27A; }}
.hi-caveat ul {{ margin: 6px 0 0; padding-left: 18px; }}
.hi-solver {{ display: flex; gap: 12px; align-items: flex-start; margin: 10px 0; }}
.hi-solver .t {{ font-size: 14px; font-weight: 500; }}
.hi-solver .d {{ font-size: 12.5px; color: {DIM}; line-height: 1.4; }}
.hi-solver .hi-dot {{ margin-top: 6px; width: 10px; height: 10px; flex-shrink: 0; }}
.hi-step {{ font-size: 12.5px; color: {DIM}; margin: -6px 0 10px 4px; line-height: 1.35; }}
</style>
"""

STATE_COLORS = {"ready": OK, "build": WARN, "missing": None}


def brand_html() -> str:
    return f'<div class="hi-brand">HydroInundate<span class="tag">SIH 26161</span></div>'


def _dot(color: str | None) -> str:
    if color:
        return f'<span class="hi-dot" style="background:{color}"></span>'
    return f'<span class="hi-dot" style="border:1.5px solid {DIM};box-sizing:border-box"></span>'


def solver_dots_html(status: dict[str, tuple[str, str, str]]) -> str:
    """status: {key: (state, title, detail)} with state ready|build|missing."""
    items = "".join(
        f'<span title="{escape(detail)}">{_dot(STATE_COLORS.get(state))}{escape(title)}</span>'
        for state, title, detail in status.values())
    return f'<div class="hi-dots">{items}</div>'


def solver_list_html(status: dict[str, tuple[str, str, str]]) -> str:
    rows = []
    for state, title, detail in status.values():
        word = {"ready": "ready", "build": "build only", "missing": "not available"}[state]
        rows.append(
            f'<div class="hi-solver">{_dot(STATE_COLORS.get(state))}<div>'
            f'<div class="t">{escape(title)} · {word}</div>'
            f'<div class="d">{escape(detail)}</div></div></div>')
    return "".join(rows)


def badge(text: str, kind: str = "info") -> str:
    return f'<span class="hi-badge {kind}">{escape(text)}</span>'


def stat_grid(stats: list[tuple[str, str, str, str | None]], cols: int = 2) -> str:
    """stats: [(label, value, unit, note)]."""
    cards = "".join(
        f'<div class="hi-stat"><div class="l">{escape(l)}</div>'
        f'<div class="v">{escape(v)} <small>{escape(u)}</small></div>'
        + (f'<div class="n">{escape(n)}</div>' if n else "") + "</div>"
        for l, v, u, n in stats)
    return f'<div class="hi-stats" style="--cols:{cols}">{cards}</div>'


def class_bars_html(rows: list[dict]) -> str:
    """rows: [{label, color, area_ha}] -> swatch, label, bar, area."""
    top = max((r["area_ha"] for r in rows), default=0) or 1.0
    out = []
    for r in rows:
        pct = 100.0 * r["area_ha"] / top
        out.append(
            f'<span class="sw" style="background:{r["color"]}"></span>'
            f'<span>{escape(r["label"])}</span>'
            f'<span class="track"><i style="width:{pct:.0f}%;background:{r["color"]}"></i></span>'
            f'<span class="num">{r["area_ha"]:,.0f} ha</span>')
    return f'<div class="hi-bars">{"".join(out)}</div>'


def legend_html(legend: dict) -> str:
    if legend["type"] == "classes":
        items = "".join(
            f'<span class="sw" style="background:{c}"></span><span>{escape(l)}</span>'
            '<span></span><span></span>'
            for c, l in zip(legend["colors"], legend["labels"]))
        return f'<div class="hi-bars">{items}</div>'
    grad = ", ".join(legend["colors"])
    return (f'<div class="hi-ramp" style="background:linear-gradient(90deg, {grad})"></div>'
            f'<div class="hi-ramp-labels"><span>{legend["vmin"]:,.0f}</span>'
            f'<span>{legend["vmax"]:,.0f}</span></div>')


_STAGE_ICONS = {"done": "&#10003;", "failed": "!", "running": "", "queued": "", "skipped": ""}


def stages_html(stages) -> str:
    items = "".join(
        f'<li class="{s.state}"><span class="ic">{_STAGE_ICONS[s.state]}</span>'
        f'<span><div class="t">{escape(s.title)}</div>'
        + (f'<div class="d">{escape(s.detail)}</div>' if s.detail else "")
        + "</span></li>"
        for s in stages)
    return f'<ol class="hi-stages" aria-label="Pipeline stages">{items}</ol>'


def caveat_html(caveats: list[str], title: str = "Read before sharing") -> str:
    if not caveats:
        return ""
    items = "".join(f"<li>{escape(c[0].upper() + c[1:])}.</li>" for c in caveats)
    return f'<div class="hi-caveat"><b>{escape(title)} ({len(caveats)})</b><ul>{items}</ul></div>'
