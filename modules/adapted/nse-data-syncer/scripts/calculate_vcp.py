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
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import DatabaseManager


def calculate_vcp_candidates():
    print("Starting **Strict VCP (Volume Contraction Pattern)** Screen...")
    db = DatabaseManager()
    session = db.Session()

    try:
        # Pre-calculate eligible stocks based on Market Cap (Global Filter)
        # Assuming a reasonable liquidity filter is still desired, though not explicitly requested in the prompt.
        # We will keep the env var usage but default to 0 if not set, to follow the user's "screen universe" instruction.
        min_mcap_cr = float(os.getenv("MIN_MARKET_CAP_CR", 2000))
        min_mcap = min_mcap_cr * 10000000

        # Get active stocks
        print(f"Fetching stocks (Market Cap > {min_mcap_cr} Cr)...")
        query = text(f"""
            SELECT id, nse_symbol, name
            FROM stocks
            WHERE is_active = true AND market_cap >= {min_mcap}
        """)
        stocks = session.execute(query).fetchall()
        print(f"Analyzing {len(stocks)} stocks...")

        vcp_candidates = []

        # Load price data
        # We need at least 252 days for 52-week high/low, plus some buffer for moving averages
        # 500 days is safe.
        print("Loading price data...")
        start_date = datetime.now() - timedelta(days=500)

        prices_query = text("""
            SELECT stock_id, date, close_price, high_price, low_price, volume
            FROM daily_prices
            WHERE date >= :start_date
            ORDER BY stock_id, date ASC
        """)

        all_prices = session.execute(prices_query, {"start_date": start_date}).fetchall()

        if not all_prices:
            print("No price data found.")
            return

        # Convert to DataFrame
        cols = ["stock_id", "date", "close", "high", "low", "volume"]
        master_df = pd.DataFrame(all_prices, columns=cols)
        master_df["date"] = pd.to_datetime(master_df["date"])

        grouped = master_df.groupby("stock_id")

        count = 0
        total = len(stocks)

        for stock in stocks:
            stock_id = stock.id
            count += 1
            if count % 100 == 0:
                print(f"Processed {count}/{total}...")

            try:
                df = grouped.get_group(stock_id).copy()
            except KeyError:
                continue

            # Need enough data for 200 SMA + Trend check (20 days prior)
            # Minimum ~260 trading days? Let's say 250 rows.
            if len(df) < 252:
                continue

            df = df.set_index("date")
            df = df.sort_index()

            # --- Step 1: Calculate Base Metrics ---

            # Current prices
            current_close = df["close"].iloc[-1]
            df["volume"].iloc[-1]  # Not strictly used in filter but good to have

            # Moving Averages
            sma_50 = df["close"].rolling(window=50).mean().iloc[-1]
            sma_150 = df["close"].rolling(window=150).mean().iloc[-1]
            sma_200 = df["close"].rolling(window=200).mean().iloc[-1]

            # 200 SMA from 20 days ago (for trend direction)
            # We use iloc[-21] because iloc[-1] is today, so 20 days ago is -1 - 20 = -21
            sma_200_20days_ago = df["close"].rolling(window=200).mean().iloc[-21]

            # 52-week High/Low (252 trading days)
            # We take the last 252 rows
            last_252 = df.tail(252)
            high_52w = last_252["high"].max()
            low_52w = last_252["low"].min()

            # Volume SMA 50
            vol_sma_50 = df["volume"].rolling(window=50).mean().iloc[-1]

            # --- Step 2: Stage 2 Uptrend (Minervini Trend Template) ---

            # 1. Current Price > 50, 150, 200 SMA
            cond1 = (current_close > sma_50) and (current_close > sma_150) and (current_close > sma_200)

            # 2. 50 SMA > 150 SMA > 200 SMA
            cond2 = sma_50 > sma_150 > sma_200

            # 3. 200 SMA trending up
            cond3 = sma_200 > sma_200_20days_ago

            # 4. Current Price >= 30% above 52-week Low
            cond4 = current_close >= (1.30 * low_52w)

            # 5. Current Price within 25% of 52-week High (>= 75% of High)
            cond5 = current_close >= (0.75 * high_52w)

            if not (cond1 and cond2 and cond3 and cond4 and cond5):
                continue

            # --- Step 3: VCP (Volatility Contraction) Filter ---
            # Analyze last 120 trading days
            df_120 = df.tail(120)

            # 1. Maximum Base Depth < 35%
            # Calculate Max Drawdown in this period
            # We look for the deepest trough from the highest peak WITHIN this 120 day window
            period_high = df_120["high"].max()
            period_low = df_120["low"].min()

            depth = (period_high - period_low) / period_high
            if depth > 0.35:
                continue

            # 2. Right Side Tightness
            # Last 7 trading days
            df_7 = df.tail(7)
            max_high_7 = df_7["high"].max()
            min_low_7 = df_7["low"].min()

            tightness = (max_high_7 - min_low_7) / current_close
            if tightness >= 0.06:  # Must be less than 6%
                continue

            # 3. Volume Dry-Up
            # Average volume of last 7 days < 0.70 * 50-day Volume SMA
            avg_vol_7 = df_7["volume"].mean()

            # Note: vol_sma_50 was calculated on the full series ending today
            if avg_vol_7 >= (0.70 * vol_sma_50):
                continue

            # --- Candidate Found ---

            # Calculate a VCP Score (Optional, for sorting)
            # We can prioritize tightness and volume contraction
            # Lower tightness is better, Lower volume ratio is better
            # Score = (Tightness * 100) + (Vol_Ratio * 100). Lower is better.
            # But frontend sorts by VCP Score DESC (High score = better).
            # So let's inverse it.

            vol_ratio = avg_vol_7 / vol_sma_50 if vol_sma_50 > 0 else 1.0

            # Simple scoring:
            # Perfect tightness (0%) = 100 points
            # Perfect volume dry up (0%) = 100 points
            score = (6 - (tightness * 100)) + (70 - (vol_ratio * 100))

            vcp_candidates.append({"stock_id": stock_id, "vcp_score": float(round(score, 2))})

        print(f"Found {len(vcp_candidates)} VCP candidates.")

        # Reset all is_vcp flags
        session.execute(text("UPDATE stock_performance SET is_vcp = false, vcp_score = NULL"))

        # Update candidates
        if vcp_candidates:
            # Batch update
            for cand in vcp_candidates:
                session.execute(
                    text("""
                    UPDATE stock_performance
                    SET is_vcp = true, vcp_score = :score, updated_at = NOW()
                    WHERE stock_id = :stock_id
                """),
                    {"score": cand["vcp_score"], "stock_id": cand["stock_id"]},
                )

            print("Database updated successfully.")

        session.commit()

    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    calculate_vcp_candidates()
