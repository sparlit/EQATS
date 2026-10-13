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
Replay a recorded day through the engine (plan M8.5): the day's tape, the reference snapshots
cached for it, the announcements the live run stored, and cached LLM and decision-model responses
(no network). Writes a fresh event store and the day's report.

    uv run python scripts/replay_day.py --date 2026-10-05 [--out var/replays/2026-10-05]
                                        [--source var/paper/rakshaquant.db]
"""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src.engine.live import DEMO, demo_store_path
from src.engine.replay import replay_day
from src.ops.exit_codes import ExitCode
from src.ops.process import run_entry_point

from src.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--source", type=Path, default=None, help="the live run's event store")
    args = parser.parse_args()
    settings = get_settings()
    out = args.out or settings.var_dir / "replays" / args.date.isoformat()
    # The engine's store: the environment's db_path, or the demo's own store.
    recorded = demo_store_path(settings) if settings.environment == DEMO else settings.db_path
    db = asyncio.run(replay_day(settings, args.date, out_dir=out,
                                source_db=args.source or recorded))  # fmt: skip
    print(f"replayed {args.date}: {db} (report in {out})")
    return ExitCode.OK


if __name__ == "__main__":
    run_entry_point("replay_day", main, console_log_level="WARNING")
