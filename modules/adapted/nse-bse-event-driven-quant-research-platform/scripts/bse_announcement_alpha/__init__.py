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
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.adapters.announcements import AnnouncementFilter, AnnouncementScanner, BSEAnnouncementClient
from indian_quant.config.connections import get_engine
from indian_quant.hypotheses.registry import HypothesisRegistry


def download_announcements(args: argparse.Namespace) -> None:
    client = BSEAnnouncementClient(download_folder=args.output_dir)
    from_date = datetime.now() - timedelta(days=args.days)
    all_ann = client.fetch_all_announcements(
        from_date=from_date,
        segment=args.segment,
        output_path=args.output_file,
    )
    print(f"Downloaded {len(all_ann)} announcements to {args.output_dir}")


def scan_announcements(args: argparse.Namespace) -> None:
    scanner = AnnouncementScanner(
        data_dir=args.data_dir,
        instrument_master=args.instrument_master,
    )
    now_ist = datetime.now()
    result = scanner.scan(date_str=args.date, now_ist=now_ist)
    print(f"Date: {result.date_str}")
    print(f"Total announcements: {result.total_announcements}")
    print(f"Filtered (alpha): {result.filtered_announcements}")
    print(f"Signals generated: {len(result.signals)}")
    for s in result.signals:
        print(f"  {s.exchange} {s.symbol} ({s.scrip_code}) [{s.category}]")
    if args.save:
        output_path = scanner.save_results(result, args.save)
        print(f"Saved to {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="BSE Announcement Alpha - modular CLI")
    sub = parser.add_subparsers(dest="command")

    p_download = sub.add_parser("download", help="Download BSE announcements")
    p_download.add_argument("--output-dir", default="./Bse_Nse_announcement_downloads")
    p_download.add_argument("--days", type=int, default=1)
    p_download.add_argument("--segment", default="equity")
    p_download.add_argument("--output-file", default=None)

    p_scan = sub.add_parser("scan", help="Scan announcements for alpha signals")
    p_scan.add_argument("--date", default=None)
    p_scan.add_argument("--data-dir", default="./Bse_Nse_announcement_downloads")
    p_scan.add_argument("--instrument-master", default="data/upstox_master.csv.gz")
    p_scan.add_argument("--save", default=None)

    args = parser.parse_args()
    if args.command == "download":
        download_announcements(args)
    elif args.command == "scan":
        scan_announcements(args)
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
