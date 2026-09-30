"""SIH 26161 dashboard entry point (kept so `streamlit run dashboard/app.py`
still works). The app itself lives in src/dam_break/dashboard/.

Run from the repo root:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dam_break.dashboard.app import main  # noqa: E402

main()
