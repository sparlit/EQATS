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


import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.adapters.announcements import AnnouncementScanner, PaperOrderExecutor, Watchlist
from indian_quant.config.settings import UpstoxConfig


def order(args: argparse.Namespace) -> None:
    config = UpstoxConfig(sandbox=True)
    executor = PaperOrderExecutor(config=config)
    watchlist = Watchlist()
    scanner = AnnouncementScanner(
        data_dir=args.data_dir,
        instrument_master=args.instrument_master,
        watchlist=watchlist.symbols,
    )
    now_ist = datetime.now()
    result = scanner.scan(date_str=args.date, now_ist=now_ist)
    print(
        f"Scanning {result.date_str}: {len(result.signals)} watchlist signals found (from {result.total_announcements} total)"
    )
    print(f"Watchlist: {len(watchlist)} symbols loaded")
    orders_placed = 0
    for signal in result.signals:
        instrument = scanner.find_instrument(signal.symbol, signal.exchange)
        if not instrument:
            print(f"  SKIP: No instrument for {signal.symbol} on {signal.exchange}")
            continue
        instrument_key = instrument.get("instrument_key", "")
        try:
            order_resp = executor.place_order(
                signal=signal,
                quantity=args.quantity,
                price=float(instrument.get("last_price", 0)) or 100.0,
                instrument_key=instrument_key,
                tag=f"announcement_alpha_{signal.symbol}",
            )
            orders_placed += 1
            print(
                f"  ORDER: {signal.symbol} ({signal.exchange}) -> {order_resp.get('order_id', 'pending')}"
            )
        except Exception as e:
            print(f"  ERROR: {signal.symbol}: {e}")
    print(f"Paper orders placed: {orders_placed}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Place paper orders on BSE announcement alpha signals from watchlist"
    )
    parser.add_argument("--date", default=None, help="Date to scan (YYYY-MM-DD)")
    parser.add_argument("--data-dir", default="./Bse_Nse_announcement_downloads")
    parser.add_argument("--instrument-master", default="data/upstox_master.csv.gz")
    parser.add_argument("--quantity", type=int, default=1)
    args = parser.parse_args()
    order(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
