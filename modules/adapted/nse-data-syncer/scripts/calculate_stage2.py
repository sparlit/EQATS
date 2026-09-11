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

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

# Load env from web/.env
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import DatabaseManager


def calculate_stage2_candidates():
    """
    Identifies stocks in Stage 2 uptrend based on Mark Minervini's Trend Template.

    Criteria:
    1. Current price > 150 DMA (30-week) AND > 200 DMA (40-week)
    2. 150 DMA > 200 DMA
    3. 200 DMA is trending up for at least 1 month (~21 trading days)
    4. 50 DMA (10-week) > 150 DMA AND > 200 DMA
    5. Current price > 50 DMA
    6. Current price >= 30% above its 52-week low
    7. Current price is within 25% of its 52-week high (>= 75% of 52W high)
    8. Relative Strength rank >= 70 (computed as 63-day return percentile across all stocks)
    """
    print("Starting Stage 2 (Minervini Trend Template) Screen...")
    db = DatabaseManager()
    session = db.Session()

    try:
        # Optional market cap filter (defaults to 0 = no filter)
        min_mcap_cr = float(os.getenv("MIN_MARKET_CAP_CR", 2000))
        min_mcap = min_mcap_cr * 10_000_000

        print(f"Fetching stocks (Market Cap >= {min_mcap_cr} Cr)...")
        query = text("""
            SELECT id, nse_symbol, name
            FROM stocks
            WHERE is_active = true AND market_cap >= :min_mcap
        """)
        stocks = session.execute(query, {"min_mcap": min_mcap}).fetchall()
        print(f"Analyzing {len(stocks)} stocks...")

        # We need ~252 days for 52W calcs + 200 for SMA + 21 for trend check = ~473 days.
        # Use 520 for a safe buffer.
        start_date = datetime.now() - timedelta(days=520)

        print("Loading price data...")
        prices_query = text("""
            SELECT stock_id, date, close_price, high_price, low_price
            FROM daily_prices
            WHERE date >= :start_date
            ORDER BY stock_id, date ASC
        """)
        all_prices = session.execute(prices_query, {"start_date": start_date}).fetchall()

        if not all_prices:
            print("No price data found.")
            return

        cols = ["stock_id", "date", "close", "high", "low"]
        master_df = pd.DataFrame(all_prices, columns=cols)
        master_df["date"] = pd.to_datetime(master_df["date"])

        # --- Step 1: Compute RS Rank across all stocks ---
        # RS Rank = percentile rank of 63-day (3-month) price return in the full universe
        print("Calculating Relative Strength ranks...")
        rs_ranks = {}

        latest_prices = master_df.sort_values("date").groupby("stock_id").tail(1).set_index("stock_id")["close"]

        # Price ~63 trading days ago
        prices_63d_ago = (
            master_df.sort_values("date")
            .groupby("stock_id")
            .apply(lambda g: g.iloc[-63]["close"] if len(g) >= 63 else None, include_groups=False)
        )

        returns_63d = {}
        for sid in latest_prices.index:
            past = prices_63d_ago.get(sid)
            curr = latest_prices.get(sid)
            if past and curr and past > 0:
                returns_63d[sid] = (curr - past) / past * 100

        if returns_63d:
            returns_series = pd.Series(returns_63d)
            # Percentile rank 0–100
            rs_rank_series = returns_series.rank(pct=True) * 100
            rs_ranks = rs_rank_series.to_dict()

        # --- Step 2: Snapshot current Stage 2 set before any reset ---
        prev_rows = session.execute(
            text("""
            SELECT sp.stock_id, s.nse_symbol, s.name
            FROM stock_performance sp
            JOIN stocks s ON s.id = sp.stock_id
            WHERE sp.is_stage2 = true
        """)
        ).fetchall()
        prev_stage2 = {row.stock_id: {"nse_symbol": row.nse_symbol, "name": row.name} for row in prev_rows}
        print(f"Previous Stage 2 count: {len(prev_stage2)}")

        # --- Save RS rank for ALL eligible stocks (>= 63 days of data) ---
        print(f"Saving RS ranks for {len(rs_ranks)} eligible stocks...")
        session.execute(
            text("""
            UPDATE stock_performance
            SET is_stage2 = false,
                stage2_rs_rank = NULL,
                stage2_pct_from_52w_high = NULL,
                stage2_pct_above_52w_low = NULL
        """)
        )
        for stock_id, rs_rank in rs_ranks.items():
            session.execute(
                text("""
                UPDATE stock_performance
                SET stage2_rs_rank = :rs_rank
                WHERE stock_id = :stock_id
            """),
                {"stock_id": int(stock_id), "rs_rank": float(round(rs_rank, 2))},
            )

        # --- Step 3: Apply Trend Template to each stock ---
        grouped = master_df.groupby("stock_id")

        stage2_candidates = []
        count = 0
        total = len(stocks)

        for stock in stocks:
            stock_id = stock.id
            count += 1
            if count % 200 == 0:
                print(f"  Processed {count}/{total}...")

            try:
                df = grouped.get_group(stock_id).copy()
            except KeyError:
                continue

            df = df.set_index("date")
            df = df.sort_index()

            # --- Moving Averages (NaN if insufficient history for the window) ---
            sma_50 = df["close"].rolling(window=50).mean()
            sma_150 = df["close"].rolling(window=150).mean()
            sma_200 = df["close"].rolling(window=200).mean()

            current_close = df["close"].iloc[-1]
            current_sma_50 = sma_50.iloc[-1]
            current_sma_150 = sma_150.iloc[-1]
            current_sma_200 = sma_200.iloc[-1]

            # 200 SMA from 21 trading days ago (1 calendar month proxy)
            sma_200_1m_ago = sma_200.iloc[-22] if len(sma_200) >= 22 else float("nan")

            # --- 52-Week High / Low (last 252 trading days, or however many we have) ---
            last_252 = df.tail(252)
            high_52w = last_252["high"].max()
            low_52w = last_252["low"].min()

            # Criteria where the required moving averages aren't available yet (not
            # enough trading history) are treated as satisfied rather than failing
            # the stock outright — this lets recently-listed stocks qualify based on
            # whatever criteria CAN be evaluated.

            # --- Criterion 1: Price > 150 DMA and > 200 DMA ---
            cond1 = (pd.isna(current_sma_150) or pd.isna(current_sma_200)) or (
                current_close > current_sma_150 and current_close > current_sma_200
            )

            # --- Criterion 2: 150 DMA > 200 DMA ---
            cond2 = (pd.isna(current_sma_150) or pd.isna(current_sma_200)) or (current_sma_150 > current_sma_200)

            # --- Criterion 3: 200 DMA trending up for at least 1 month ---
            cond3 = (pd.isna(current_sma_200) or pd.isna(sma_200_1m_ago)) or (current_sma_200 > sma_200_1m_ago)

            # --- Criterion 4: 50 DMA > 150 DMA and > 200 DMA ---
            cond4 = (pd.isna(current_sma_50) or pd.isna(current_sma_150) or pd.isna(current_sma_200)) or (
                current_sma_50 > current_sma_150 and current_sma_50 > current_sma_200
            )

            # --- Criterion 5: Price > 50 DMA ---
            cond5 = pd.isna(current_sma_50) or (current_close > current_sma_50)

            # --- Criterion 6: Price >= 30% above 52-week low ---
            cond6 = current_close >= (1.30 * low_52w)

            # --- Criterion 7: Price within 25% of 52-week high (>= 75% of high) ---
            cond7 = current_close >= (0.75 * high_52w)

            # --- Criterion 8: RS Rank >= 70 ---
            cond8 = (stock_id not in rs_ranks) or (rs_ranks[stock_id] >= 70)

            if not (cond1 and cond2 and cond3 and cond4 and cond5 and cond6 and cond7 and cond8):
                continue

            # Compute % from 52W high (for display in UI)
            pct_from_52w_high = ((current_close - high_52w) / high_52w) * 100  # negative = below high
            pct_above_52w_low = ((current_close - low_52w) / low_52w) * 100

            stage2_candidates.append(
                {
                    "stock_id": stock_id,
                    "stage2_pct_from_52w_high": float(round(pct_from_52w_high, 2)),
                    "stage2_pct_above_52w_low": float(round(pct_above_52w_low, 2)),
                }
            )

        print(f"Found {len(stage2_candidates)} Stage 2 candidates.")

        # Mark Stage 2 candidates (RS rank already written above for all stocks)
        if stage2_candidates:
            for cand in stage2_candidates:
                session.execute(
                    text("""
                    UPDATE stock_performance
                    SET is_stage2 = true,
                        stage2_pct_from_52w_high = :pct_high,
                        stage2_pct_above_52w_low = :pct_low,
                        updated_at = NOW()
                    WHERE stock_id = :stock_id
                """),
                    {
                        "pct_high": cand["stage2_pct_from_52w_high"],
                        "pct_low": cand["stage2_pct_above_52w_low"],
                        "stock_id": cand["stock_id"],
                    },
                )

        # --- Compute and persist daily diff ---
        new_stage2_ids = {c["stock_id"] for c in stage2_candidates}
        prev_stage2_ids = set(prev_stage2.keys())
        added_ids = new_stage2_ids - prev_stage2_ids
        removed_ids = prev_stage2_ids - new_stage2_ids

        if added_ids or removed_ids:
            # Fetch stock info for any IDs not already in prev_stage2
            missing_ids = added_ids - set(prev_stage2.keys())
            if missing_ids:
                info_rows = session.execute(
                    text("SELECT id, nse_symbol, name FROM stocks WHERE id = ANY(:ids)"), {"ids": list(missing_ids)}
                ).fetchall()
                for row in info_rows:
                    prev_stage2[row.id] = {"nse_symbol": row.nse_symbol, "name": row.name}

            # Build combined lookup
            stock_map_local = {s.id: s for s in stocks}

            def get_info(sid):
                if sid in prev_stage2:
                    return prev_stage2[sid]["nse_symbol"], prev_stage2[sid]["name"]
                s = stock_map_local.get(sid)
                return (s.nse_symbol, s.name) if s else (str(sid), "")

            today = datetime.now().date()
            # Remove any existing records for today (handles re-runs)
            session.execute(text("DELETE FROM stage2_changes WHERE run_date = :today"), {"today": today})

            for sid in added_ids:
                sym, name = get_info(sid)
                session.execute(
                    text("""
                    INSERT INTO stage2_changes (stock_id, nse_symbol, stock_name, change_type, run_date)
                    VALUES (:sid, :sym, :name, 'added', :today)
                """),
                    {"sid": sid, "sym": sym, "name": name, "today": today},
                )

            for sid in removed_ids:
                sym, name = get_info(sid)
                session.execute(
                    text("""
                    INSERT INTO stage2_changes (stock_id, nse_symbol, stock_name, change_type, run_date)
                    VALUES (:sid, :sym, :name, 'removed', :today)
                """),
                    {"sid": sid, "sym": sym, "name": name, "today": today},
                )

            print(f"Stage 2 changes: +{len(added_ids)} added, -{len(removed_ids)} removed.")
        else:
            print("No Stage 2 changes today.")

        session.commit()
        print("Stage 2 screen complete.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    calculate_stage2_candidates()
