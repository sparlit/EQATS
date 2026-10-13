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


"""Record a live Upstox feed session for replay + parity proof (B4).

Usage (run during market hours, e.g. Monday 09:14 IST):
    python scripts/shadow_session.py --keys "NSE_EQ|INE002A01018" \
        --minutes 375 --mode full

Frames are stored raw (immutable) under data/raw/upstox/feed_sessions/
plus decoded JSONL alongside. Replay/parity runs against the recording
afterwards; identical strategy signals on live-vs-replay is the Level-3
exit condition.
"""


import argparse
import asyncio
import contextlib
import json
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.adapters.upstox.feed import ProtoFeedDecoder, UpstoxFeedClient
from indian_quant.config import load_settings


async def record(settings, keys: list[str], minutes: float, mode: str) -> int:
    session_id = time.strftime("%Y%m%d_%H%M%S")
    out_dir = settings.data_root / "raw" / "upstox" / "feed_sessions" / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "session.json"
    jsonl_path = out_dir / "records.jsonl"
    n_frames = 0

    async def on_records(records: list[dict]) -> None:
        nonlocal n_frames
        with jsonl_path.open("a") as fh:
            for rec in records:
                fh.write(json.dumps(rec, default=str) + "\n")

    client = UpstoxFeedClient(
        load_settings_feed_config(settings),
        decoder=ProtoFeedDecoder(include_market_info=False),
        on_records=on_records,
    )
    stop = asyncio.Event()

    def _sig(*_):
        stop.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            asyncio.get_running_loop().add_signal_handler(s, _sig)

    await client.connect()
    await client.subscribe(keys, mode=mode)
    print(
        f"recording session {session_id}: keys={keys} mode={mode} "
        f"for <= {minutes} min (Ctrl-C to stop)"
    )

    async def _stop_after() -> None:
        await asyncio.sleep(minutes * 60)
        stop.set()

    stopper = asyncio.create_task(_stop_after())
    recorder = asyncio.create_task(client.run())
    done, pending = await asyncio.wait(
        {recorder, stopper, asyncio.create_task(stop.wait())},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await client.disconnect()

    meta_path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "instrument_keys": keys,
                "mode": mode,
                "started_at": session_id,
                "stopped_at": time.strftime("%Y%m%d_%H%M%S"),
                "decoded_records": sum(1 for _ in jsonl_path.open()) if jsonl_path.exists() else 0,
            },
            indent=2,
        )
    )
    print(f"session saved -> {out_dir}")
    return n_frames


def load_settings_feed_config(settings):
    from indian_quant.config.settings import UpstoxConfig

    return settings.upstox if isinstance(settings.upstox, UpstoxConfig) else settings.upstox


def main() -> int:
    parser = argparse.ArgumentParser(description="Record live feed session")
    parser.add_argument("--keys", required=True, help="comma-separated instrument keys")
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument(
        "--mode", default="full", choices=["ltpc", "option_greeks", "full", "full_d30"]
    )
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    return asyncio.run(record(settings, keys, args.minutes, args.mode))


if __name__ == "__main__":
    raise SystemExit(main())
