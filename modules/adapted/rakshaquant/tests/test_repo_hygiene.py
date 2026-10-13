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


"""Plan M0.6: .gitignore keeps runtime state and secrets out, and never hides sources."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _ignored(paths: list[str]) -> set[str]:
    proc = subprocess.run(
        ["git", "check-ignore", "--no-index", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode in (0, 1), proc.stderr  # 128 = git error
    return set(proc.stdout.split())


def test_sources_are_not_ignored():
    sources = [
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/tsconfig.json",
        "frontend/src/lib/api.ts",
        "src/config/nse_calendar.json",
        "src/lib/anything.py",
        "tests/fixtures/data/tape.json",
        "docs/data/table.csv",
    ]
    assert _ignored(sources) == set()


def test_state_and_secrets_are_ignored():
    private = [
        ".env",
        "var/paper/rakshaquant.db",
        "var/paper/paper_wallet.json",
        "var/archive/2026-10-01/paper_wallet.json",
        "journal.db",
        ".coverage",
        "logs/rakshaquant.log",
        "frontend/node_modules/react/index.js",
        "frontend/dist/index.html",
        "frontend/tsconfig.tsbuildinfo",
    ]
    assert _ignored(private) == set(private)
