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


"""Plan M12.1: the legacy stack is gone - and stays gone."""


import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DELETED = ("src.api", "src.execution", "src.finops", "src.legacy", "src.market",
           "src.memory", "src.observability", "src.profit", "src.live",
           "src.engine.view_model")  # fmt: skip
IMPORT = re.compile(r"^\s*(?:from|import)\s+(src(?:\.\w+)+)", re.M)


def test_the_legacy_packages_do_not_exist():
    for module in DELETED:
        path = ROOT / Path(*module.split("."))
        assert not path.exists() and not path.with_suffix(".py").exists(), module


def test_nothing_imports_them():
    offenders = []
    for path in [
        *SRC.rglob("*.py"),
        *(ROOT / "scripts").rglob("*.py"),
        *(ROOT / "tests").glob("*.py"),
    ]:
        if path.name == Path(__file__).name:
            continue
        for module in IMPORT.findall(path.read_text(encoding="utf-8")):
            if any(module == gone or module.startswith(f"{gone}.") for gone in DELETED):
                offenders.append(f"{path.relative_to(ROOT)}: {module}")
    assert offenders == []
