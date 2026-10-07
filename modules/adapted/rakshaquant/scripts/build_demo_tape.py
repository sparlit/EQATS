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
(Re)write the demo's bundled fixture tape, ``src/engine/demo_tape/`` (plan M9.6), from the
deterministic generator in ``src/engine/demo.py``. Only needed after changing the generator;
``tests/test_demo_tape.py`` fails until the committed tape matches it again.

    uv run python scripts/build_demo_tape.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engine.demo import DEMO_TAPE, write_demo_tape  # noqa: E402


def main() -> int:
    for path in write_demo_tape():
        print(f"wrote {path.relative_to(DEMO_TAPE.parent.parent.parent)} "
              f"({path.stat().st_size:,} bytes)")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
