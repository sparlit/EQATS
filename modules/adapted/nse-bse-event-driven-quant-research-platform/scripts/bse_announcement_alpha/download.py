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
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.adapters.announcements import BSEAnnouncementClient


def download(args: argparse.Namespace) -> None:
    client = BSEAnnouncementClient(download_folder=args.output_dir)
    from_date = datetime.now() - timedelta(days=args.days)
    all_ann = client.fetch_all_announcements(
        from_date=from_date,
        segment=args.segment,
        output_path=args.output_file,
    )
    print(f"Downloaded {len(all_ann)} announcements")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download BSE announcements")
    parser.add_argument("--output-dir", default="./Bse_Nse_announcement_downloads")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--segment", default="equity")
    parser.add_argument("--output-file", default=None)
    args = parser.parse_args()
    download(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
