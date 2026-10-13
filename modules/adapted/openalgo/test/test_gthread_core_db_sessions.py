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


"""Every scoped session under database/ is released by the teardown sweep.

Under the gthread worker request threads are pooled and never exit, so a
scoped session the per-request sweep does not know about stays open on its
thread from one request to the next: a connection held, and an identity map
that can be a day's master contract re-download out of date. Under eventlet
each request's greenlet took its sessions with it. The sweep
(utils.db_sessions.remove_all_scoped_sessions) covers a fixed list plus every
loaded broker master-contract module; this tripwire keeps the list complete.
"""


import ast
from pathlib import Path

from utils import db_sessions

REPO = Path(__file__).resolve().parents[1]


def _scoped_sessions_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if called != "scoped_session":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    return names


def test_every_database_scoped_session_is_swept():
    listed = set(db_sessions.SCOPED_SESSION_MODULES)
    missing = []
    for path in sorted((REPO / "database").glob("*.py")):
        module = f"database.{path.stem}"
        for attr in _scoped_sessions_in(path):
            if (module, attr) not in listed:
                missing.append(f"{module}.{attr}")
    assert missing == [], (
        "Add these to utils/db_sessions.SCOPED_SESSION_MODULES so pooled "
        f"request threads release them: {missing}"
    )


def test_broker_master_contract_sessions_are_found_by_name():
    # Loaded broker modules are swept without being listed; the naming rule
    # is what makes that work, so pin it.
    sample = sorted((REPO / "broker").glob("*/database/master_contract_db.py"))
    assert sample, "no broker master contract modules found"
    for path in sample[:5]:
        assert "db_session" in _scoped_sessions_in(path), path
