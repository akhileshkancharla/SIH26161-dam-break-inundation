"""Filesystem locations shared across the package (avoids import cycles)."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Locate the repository root (works for editable installs and notebooks)."""
    env = os.environ.get("DAM_BREAK_REPO_ROOT")
    if env:
        return Path(env).resolve()
    p = Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "src" / "dam_break").is_dir() and (parent / "configs").is_dir():
            return parent
        if (parent / "pyproject.toml").exists() and (parent / "src" / "dam_break").is_dir():
            return parent
    return Path.cwd()
