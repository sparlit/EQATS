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
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

# Load env from web/.env
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))

# Add project root to path
sys.path.append(base_dir)

from app.database import DatabaseManager


def calculate_market_breadth(backfill_days=1):
    """
    Computes daily market breadth metrics for the eligible universe
    (is_active=true, market_cap >= MIN_MARKET_CAP_CR) and upserts one
    row per trading date into market_breadth_history.
    """
    print("Starting Market Breadth calculation...")
    db = DatabaseManager()
    session = db.Session()

    try:
        min_mcap_cr = float(os.getenv("MIN_MARKET_CAP_CR", 2000))
        min_mcap = min_mcap_cr * 10_000_000

        stocks = session.execute(
            text("""
            SELECT id FROM stocks WHERE is_active = true AND market_cap >= :min_mcap
        """),
            {"min_mcap": min_mcap},
        ).fetchall()
        stock_ids = [s.id for s in stocks]
        print(f"Eligible stocks: {len(stock_ids)}")

        if not stock_ids:
            print("No eligible stocks found.")
            return

        # 252 trading days for 52W high/low + EMA200 warm-up + backfill window
        start_date = datetime.now() - timedelta(days=252 * 2 + backfill_days + 30)

        rows = session.execute(
            text("""
            SELECT stock_id, date, close_price AS close, high_price AS high, low_price AS low
            FROM daily_prices
            WHERE stock_id = ANY(:ids) AND date >= :start_date
            ORDER BY stock_id, date ASC
        """),
            {"ids": stock_ids, "start_date": start_date},
        ).fetchall()

        if not rows:
            print("No price data found.")
            return

        df = pd.DataFrame(rows, columns=["stock_id", "date", "close", "high", "low"])
        df["date"] = pd.to_datetime(df["date"]).dt.date

        all_dates = sorted(df["date"].unique())
        target_dates = set(all_dates[-backfill_days:])
        print(f"Computing breadth for {len(target_dates)} date(s): {min(target_dates)} -> {max(target_dates)}")

        per_stock_frames = []
        for _stock_id, g in df.groupby("stock_id"):
            g = g.sort_values("date").reset_index(drop=True)
            if len(g) < 2:
                continue

            g["prev_close"] = g["close"].shift(1)
            g["ema20"] = g["close"].ewm(span=20, adjust=False).mean()
            g["ema50"] = g["close"].ewm(span=50, adjust=False).mean()
            g["ema200"] = g["close"].ewm(span=200, adjust=False).mean()
            g["high_52w"] = g["high"].rolling(252, min_periods=1).max()
            g["low_52w"] = g["low"].rolling(252, min_periods=1).min()
            g["prior_high_252"] = g["high"].shift(1).rolling(252, min_periods=1).max()
            g["prior_low_252"] = g["low"].shift(1).rolling(252, min_periods=1).min()

            per_stock_frames.append(g[g["date"].isin(target_dates)])

        if not per_stock_frames:
            print("Not enough history to compute breadth.")
            return

        merged = pd.concat(per_stock_frames, ignore_index=True)
        merged = merged.dropna(subset=["prev_close"])

        merged["advance"] = merged["close"] > merged["prev_close"]
        merged["decline"] = merged["close"] < merged["prev_close"]
        merged["unchanged"] = merged["close"] == merged["prev_close"]
        merged["near_high"] = merged["close"] >= 0.9 * merged["high_52w"]
        merged["near_low"] = merged["close"] <= 1.1 * merged["low_52w"]
        merged["new_high"] = merged["high"] > merged["prior_high_252"]
        merged["new_low"] = merged["low"] < merged["prior_low_252"]
        merged["above_ema20"] = merged["close"] > merged["ema20"]
        merged["above_ema50"] = merged["close"] > merged["ema50"]
        merged["above_ema200"] = merged["close"] > merged["ema200"]

        # Skip dates where most stocks have no data (holidays/data glitches)
        min_total = len(stock_ids) * 0.5

        for date_val, day_df in merged.groupby("date"):
            total = len(day_df)
            if total < min_total:
                print(f"{date_val}: skipping (only {total} stocks have data)")
                continue

            advances = int(day_df["advance"].sum())
            declines = int(day_df["decline"].sum())
            unchanged = int(day_df["unchanged"].sum())
            near_high = int(day_df["near_high"].sum())
            near_low = int(day_df["near_low"].sum())
            new_highs = int(day_df["new_high"].sum())
            new_lows = int(day_df["new_low"].sum())
            pct_ema20 = round(float(day_df["above_ema20"].mean() * 100), 2)
            pct_ema50 = round(float(day_df["above_ema50"].mean() * 100), 2)
            pct_ema200 = round(float(day_df["above_ema200"].mean() * 100), 2)

            session.execute(
                text("""
                INSERT INTO market_breadth_history
                    (date, total, advances, declines, unchanged, near_52w_high, near_52w_low,
                     pct_above_ema20, pct_above_ema50, pct_above_ema200,
                     new_highs, new_lows, net_highs_lows)
                VALUES
                    (:date, :total, :advances, :declines, :unchanged, :near_high, :near_low,
                     :pct_ema20, :pct_ema50, :pct_ema200,
                     :new_highs, :new_lows, :net)
                ON CONFLICT (date) DO UPDATE SET
                    total = EXCLUDED.total,
                    advances = EXCLUDED.advances,
                    declines = EXCLUDED.declines,
                    unchanged = EXCLUDED.unchanged,
                    near_52w_high = EXCLUDED.near_52w_high,
                    near_52w_low = EXCLUDED.near_52w_low,
                    pct_above_ema20 = EXCLUDED.pct_above_ema20,
                    pct_above_ema50 = EXCLUDED.pct_above_ema50,
                    pct_above_ema200 = EXCLUDED.pct_above_ema200,
                    new_highs = EXCLUDED.new_highs,
                    new_lows = EXCLUDED.new_lows,
                    net_highs_lows = EXCLUDED.net_highs_lows
            """),
                {
                    "date": date_val,
                    "total": total,
                    "advances": advances,
                    "declines": declines,
                    "unchanged": unchanged,
                    "near_high": near_high,
                    "near_low": near_low,
                    "pct_ema20": pct_ema20,
                    "pct_ema50": pct_ema50,
                    "pct_ema200": pct_ema200,
                    "new_highs": new_highs,
                    "new_lows": new_lows,
                    "net": new_highs - new_lows,
                },
            )
            print(
                f"{date_val}: total={total} A={advances} D={declines} U={unchanged} "
                f"NH={new_highs} NL={new_lows} EMA20={pct_ema20}% EMA50={pct_ema50}% EMA200={pct_ema200}%"
            )

        session.commit()
        print("Market breadth calculation complete.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backfill-days", type=int, default=1, help="Number of most recent trading dates to (re)compute"
    )
    args = parser.parse_args()
    calculate_market_breadth(backfill_days=args.backfill_days)
