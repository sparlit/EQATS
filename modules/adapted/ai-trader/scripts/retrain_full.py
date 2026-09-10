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
Full retrain of macro model on entire available candle history.
Run this whenever the incremental model has drifted badly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from features.indicators import compute_all_macro_indicators
from models.strategy_models import train_all_strategy_models
from models.train_model import MacroModelTrainer
from utils.logger import get_logger

from database.db import read_sql

logger = get_logger("retrain_full")

MODEL_PATH = Path("models/saved/macro_model.pkl")
BACKUP_DIR = Path("models/saved/backups")


def backup_existing():
    """Keep a timestamped backup before overwriting."""
    if MODEL_PATH.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = BACKUP_DIR / f"macro_model_{ts}.pkl"
        shutil.copy2(MODEL_PATH, dst)
        print(f"  Backed up existing model → {dst}")
        return dst
    return None


def main():
    print("=" * 60)
    print("  FULL MACRO MODEL RETRAIN (6-month history)")
    print("=" * 60)

    # ── Backup current model ──────────────────────────────────────
    backup_existing()

    # ── Load full candle history ──────────────────────────────────
    print("\n  Loading candle history...")
    candles = read_sql(
        "SELECT timestamp, symbol, open, high, low, close, volume, vwap, oi "
        "FROM minute_candles WHERE symbol = 'NIFTY-I' ORDER BY timestamp"
    )
    candles["timestamp"] = pd.to_datetime(candles["timestamp"])
    days = candles["timestamp"].dt.date.nunique()
    print(f"  Candles : {len(candles):,}")
    print(f"  Range   : {candles['timestamp'].min().date()} → {candles['timestamp'].max().date()}")
    print(f"  Days    : {days}")

    if len(candles) < 5000:
        print("  ERROR: Not enough candle data for a reliable model. Need 5,000+ bars.")
        return 1

    # ── Compute features ─────────────────────────────────────────
    print("\n  Computing macro features...")
    featured = compute_all_macro_indicators(candles)
    print(f"  Featured rows  : {len(featured):,}")
    print(f"  Feature columns: {len(featured.columns)}")

    # ── Prepare labels ───────────────────────────────────────────
    print("\n  Preparing labels (forward_periods=15, threshold=0.001)...")
    trainer = MacroModelTrainer()
    df = trainer.prepare_data(featured.copy(), forward_periods=15, threshold=0.001)
    pos = int(df["target"].sum())
    neg = len(df) - pos
    print(f"  Labeled samples: {len(df):,}")
    print(f"  Positive (bullish): {pos:,} ({pos / len(df) * 100:.1f}%)")
    print(f"  Negative (bearish): {neg:,} ({neg / len(df) * 100:.1f}%)")

    # ── Train with walk-forward validation ───────────────────────
    n_splits = 5
    print(f"\n  Training with {n_splits}-fold walk-forward validation...")
    metrics = trainer.train(df, walk_forward=True, n_splits=n_splits)
    print("\n  Walk-forward metrics:")
    for k, v in metrics.items():
        print(f"    {k:12s}: {v:.4f}")

    # ── Save ─────────────────────────────────────────────────────
    print("\n  Saving model...")
    trainer.save()
    print(f"  Saved → {MODEL_PATH}")

    # ── Feature importance ───────────────────────────────────────
    fi = trainer.get_feature_importance()
    print("\n  Top 15 feature importances:")
    for _, row in fi.head(15).iterrows():
        print(f"    {row['feature']:30s}  {row['importance']:.4f}")

    # ── Retrain strategy models on full data ─────────────────────
    print("\n  Retraining strategy models...")
    try:
        results = train_all_strategy_models(featured.copy())
        for name, info in results.items():
            if info:
                print(f"  {name}: {info.get('metrics', 'trained')}")
            else:
                print(f"  {name}: skipped (insufficient data)")
    except Exception as e:
        print(f"  Strategy model error: {e}")

    print("\n" + "=" * 60)
    print("  RETRAIN COMPLETE")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
