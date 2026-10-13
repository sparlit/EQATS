from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
The running code's version (plan M12.4): the package version plus the git commit, so every
session's ``ProcessStarted`` event records exactly which code ran. During the month run that is
how a P0 fix shows up in the experiment's own record (audit §U: "each such fix is logged").
"""


import subprocess
from functools import lru_cache
from pathlib import Path

import src

REPO = Path(__file__).resolve().parents[2]
GIT_TIMEOUT_S = 2.0


def _git(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_S, check=False)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None


@lru_cache(maxsize=1)
def code_version() -> str:
    """``0.1.0+g<12-hex commit>``, with ``.dirty`` when tracked files' content differs from the
    commit (line endings alone don't count); just the package version where git or the
    repository is unavailable."""
    head = _git("rev-parse", "--short=12", "HEAD")
    if head is None or head.returncode != 0 or not head.stdout.strip():
        return src.__version__
    diff = _git("diff", "--ignore-cr-at-eol", "--quiet", "HEAD")
    dirty = diff is None or diff.returncode != 0
    return f"{src.__version__}+g{head.stdout.strip()}{'.dirty' if dirty else ''}"
