"""Dark hydrographic command-center theme for the dashboard.

Palette and typography follow the team's Stitch design system
("HydroInundate Operations"): dark-slate substrate, hydrodynamic blue
primary, cyan telemetry accents, hazard scale green/amber/red, Space
Grotesk headlines, Inter body, JetBrains Mono for numbers.
"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap');

:root {
  --hydro-bg: #0B0F19; --hydro-panel: #111827; --hydro-elev: #1E293B;
  --hydro-border: #1F2937; --hydro-border-strong: #374151;
  --hydro-primary: #0284C7; --hydro-cyan: #38BDF8;
  --hz-safe: #059669; --hz-warn: #D97706; --hz-danger: #DC2626;
  --txt: #E2E8F0; --txt-dim: #94A3B8;
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif; color: var(--txt); }
section.main > div { padding-top: 1.1rem; }

/* ---------- app header strip ---------- */
.hydro-crisis {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  background: linear-gradient(90deg, rgba(2,132,199,.16), rgba(17,24,39,.9) 55%);
  border: 1px solid var(--hydro-border-strong);
  border-left: 4px solid var(--hz-danger);
  border-radius: 8px; padding: 14px 18px; margin-bottom: 14px;
}
.hydro-crisis h1 {
  font-family: 'Space Grotesk', sans-serif; font-size: 26px; font-weight: 700;
  letter-spacing: -0.02em; margin: 0; color: #F8FAFC;
}
.hydro-crisis .sub { color: var(--txt-dim); font-size: 13px; margin-top: 3px; }
.hydro-badge {
  font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: .08em;
  padding: 5px 10px; border-radius: 4px; white-space: nowrap;
}
.hydro-badge.danger { background: rgba(220,38,38,.18); color: #FCA5A5; border: 1px solid rgba(220,38,38,.55); }
.hydro-badge.warn   { background: rgba(217,119,6,.16); color: #FCD34D; border: 1px solid rgba(217,119,6,.5); }
.hydro-badge.safe   { background: rgba(5,150,105,.15); color: #6EE7B7; border: 1px solid rgba(5,150,105,.5); }
.hydro-badge.info   { background: rgba(56,189,248,.13); color: #7DD3FC; border: 1px solid rgba(56,189,248,.45); }

/* ---------- KPI metric cards ---------- */
[data-testid="stMetric"] {
  background: var(--hydro-panel); border: 1px solid var(--hydro-border);
  border-top: 2px solid var(--hydro-cyan); border-radius: 6px;
  padding: 12px 14px 8px 14px !important; margin: 2px 0;
  box-shadow: 0 4px 16px -2px rgba(0,0,0,.45);
}
[data-testid="stMetric"] label, [data-testid="stMetricLabel"] p {
  font-family: 'JetBrains Mono', monospace !important; font-size: 10.5px !important;
  letter-spacing: .09em; text-transform: uppercase; color: var(--txt-dim) !important;
}
[data-testid="stMetricValue"] {
  font-family: 'JetBrains Mono', monospace !important; font-weight: 700;
  font-size: 30px !important; color: #F8FAFC !important;
}
[data-testid="stMetricDelta"] { font-size: 12px; }

/* ---------- tabs as segmented control ---------- */
.stTabs [data-baseweb="tab-list"] {
  gap: 4px; background: var(--hydro-panel); padding: 5px;
  border: 1px solid var(--hydro-border); border-radius: 8px;
}
.stTabs [data-baseweb="tab"] {
  font-family: 'Inter', sans-serif; font-size: 13.5px; font-weight: 500;
  color: var(--txt-dim); padding: 7px 15px; border-radius: 5px;
}
.stTabs [aria-selected="true"] {
  background: var(--hydro-elev) !important; color: #F8FAFC !important;
  box-shadow: inset 0 -2px 0 var(--hydro-cyan);
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] {
  background: var(--hydro-panel); border-right: 1px solid var(--hydro-border);
}
section[data-testid="stSidebar"] * { font-size: 13.5px; }
.hydro-brand {
  font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 19px;
  color: #F8FAFC; margin: 2px 0 1px 0;
}
.hydro-brand .accent { color: var(--hydro-cyan); }
.hydro-tag {
  font-family: 'JetBrains Mono', monospace; font-size: 10px !important;
  letter-spacing: .06em; color: var(--txt-dim); margin-bottom: 10px;
}

/* ---------- buttons ---------- */
.stButton > button[kind="primary"], div.stButton > button:first-child {
  background: var(--hydro-primary); color: #fff; border: none;
  font-weight: 600; border-radius: 5px; width: 100%;
  box-shadow: 0 2px 10px -2px rgba(2,132,199,.6);
}
.stButton > button:hover { background: #0369A1 !important; }
.stButton > button[kind="secondary"] {
  background: var(--hydro-elev); color: var(--txt);
  border: 1px solid var(--hydro-border-strong); border-radius: 5px;
}

/* ---------- solver status chips ---------- */
.chip-row { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 10px 0; }
.chip {
  font-family: 'JetBrains Mono', monospace; font-size: 10.5px;
  padding: 4px 9px; border-radius: 4px; border: 1px solid;
}
.chip.active  { color: #6EE7B7; border-color: rgba(5,150,105,.6); background: rgba(5,150,105,.12); }
.chip.ready   { color: #7DD3FC; border-color: rgba(56,189,248,.5); background: rgba(56,189,248,.10); }
.chip.standby { color: #94A3B8; border-color: var(--hydro-border-strong); background: rgba(148,163,184,.06); }

/* ---------- data frames ---------- */
[data-testid="stDataFrame"] { border: 1px solid var(--hydro-border); border-radius: 6px; }
.mono-note, .stCaption, p[data-testid="stCaption"] {
  font-family: 'JetBrains Mono', monospace; font-size: 11.5px; color: var(--txt-dim);
}
</style>
"""


def crisis_header(title: str, badge: str, badge_kind: str,
                  subtitle: str, meta: str) -> str:
    """HTML for the mission-control header strip."""
    return (
        f'<div class="hydro-crisis">'
        f'<div><h1>{title}</h1><div class="sub">{subtitle}</div></div>'
        f'<span style="flex:1"></span>'
        f'<span class="hydro-badge {badge_kind}">{badge}</span>'
        f'<span class="hydro-badge info">{meta}</span>'
        f'</div>'
    )


def chip_row(chips: list[tuple[str, str]]) -> str:
    """HTML for solver status chips: [(label, state)] with state in
    active/ready/standby."""
    inner = "".join(
        f'<span class="chip {state}">{label}</span>' for label, state in chips)
    return f'<div class="chip-row">{inner}</div>'
