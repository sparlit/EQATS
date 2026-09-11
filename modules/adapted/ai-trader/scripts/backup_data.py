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


__doc__ = """
Backup AI Trader's important state to one or more destinations.

What gets backed up:
  • DB tables → CSV.gz via psql COPY (NOT pg_dump — broken on hypertables)
  • models/saved/             → models/current/  (verbatim copy)
  • models/saved/*.pkl         → models/by_train_date/YYYY-MM-DD/  (mtime-bucketed)
  • backtest_results/          → backtest_results/
  • config/                    → config/

Not backed up:
  • logs/  (large, regenerable)
  • node_modules, .venv, __pycache__

Output structure:
  <dest>/
    └── 2026-04-08/
        ├── db/                       # gzipped CSVs, restorable via psql \\COPY
        │   ├── tick_data.csv.gz
        │   ├── minute_candles.csv.gz
        │   └── ...
        ├── models/
        │   ├── current/              # exact copy of models/saved/
        │   └── by_train_date/        # bucketed by .pkl mtime for easy rollback
        │       ├── 2026-04-07/
        │       │   ├── bearish_momentum_model.pkl
        │       │   └── ...
        │       └── ...
        ├── backtest_results/
        ├── config/
        └── MANIFEST.txt              # tables, sizes, file counts, git sha

Why CSV?
  • Restorable to ANY PostgreSQL — gunzip + psql \\COPY, no proprietary format
  • Inspectable by anything (pandas, Excel, DuckDB, less)
  • Plain text → ratio-friendly to gzip, diffable across snapshots

Usage:
  python scripts/backup_data.py
  python scripts/backup_data.py --rotate 30
  python scripts/backup_data.py --extra-dest ~/Dropbox/ai-trader-backups
  python scripts/backup_data.py --extra-dest ~/Dropbox/... --extra-dest /Volumes/SSD/...
  python scripts/backup_data.py --no-db
  python scripts/backup_data.py --dest /tmp/test_backup
"""


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import argparse
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("backup_data")

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DEFAULT_DEST = Path.home() / "ai-trader-backups"
