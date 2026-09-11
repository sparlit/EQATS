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
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from sqlalchemy import text

# Load env
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, DatabaseManager, MomentumHistory


def get_month_ends(years=8):
    """Get list of month-end dates for the last N years"""
    end_date = datetime.now()
    start_date = end_date - relativedelta(years=years)

    dates = []
    current = start_date.replace(day=1)
    while current <= end_date:
        # Get last day of month
        next_month = current + relativedelta(months=1)
        month_end = next_month - timedelta(days=1)
        if month_end <= end_date:
            dates.append(month_end)
        current = next_month

    return dates


def calculate_momentum_for_date(session, as_of_date, df_window):
    """Calculate momentum scores for all stocks as of a specific date"""

    # Calculate returns for each stock
    results = []

    for stock_id in df_window.index.get_level_values("stock_id").unique():
        try:
            stock_data = df_window.loc[stock_id].sort_values("date")

            if len(stock_data) < 252:  # Need at least 1 year of data
                continue

            prices = stock_data["close_price"].values

            # Calculate log returns
            log_returns = np.diff(np.log(prices))

            # Volatility (annualized std dev of daily returns)
            volatility = np.std(log_returns) * np.sqrt(252)

            if volatility == 0:
                continue

            # Momentum Ratios (excluding 1M as per updated formula)
            # 3M, 6M, 1Y
            mr_3m = (prices[-1] / prices[-63] - 1) if len(prices) >= 63 else None
            mr_6m = (prices[-1] / prices[-126] - 1) if len(prices) >= 126 else None
            mr_1y = (prices[-1] / prices[-252] - 1) if len(prices) >= 252 else None

            if mr_3m is None or mr_6m is None or mr_1y is None:
                continue

            results.append(
                {"stock_id": stock_id, "volatility": volatility, "mr_3m": mr_3m, "mr_6m": mr_6m, "mr_1y": mr_1y}
            )

        except Exception:
            continue

    if not results:
        return pd.DataFrame()

    df_scores = pd.DataFrame(results)

    # Calculate Z-scores for each momentum ratio
    for period, col in [("3m", "mr_3m"), ("6m", "mr_6m"), ("1y", "mr_1y")]:
        mean = df_scores[col].mean()
        std = df_scores[col].std()
        if std > 0:
            df_scores[f"z_{period}"] = (df_scores[col] - mean) / std
        else:
            df_scores[f"z_{period}"] = 0

    # Weighted Score (equal weights: 1/3 each for 3M, 6M, 1Y)
    df_scores["weighted_z"] = (df_scores["z_3m"] + df_scores["z_6m"] + df_scores["z_1y"]) / 3

    # Sort by weighted Z (descending)
    return df_scores.sort_values("weighted_z", ascending=False)


def populate_history():
    print("Populating Momentum History...")
    db = DatabaseManager()

    # Ensure table exists
    Base.metadata.create_all(db.engine)

    session = db.Session()

    # Get month-end dates
    month_ends = get_month_ends(years=8)
    print(f"Processing {len(month_ends)} months...")

    # Clear existing history
    print("Clearing existing history...")
    session.execute(text("DELETE FROM momentum_history"))
    session.commit()

    total_records = 0

    for i, rebalance_date in enumerate(month_ends):
        print(f"[{i + 1}/{len(month_ends)}] Processing {rebalance_date.strftime('%Y-%m-%d')}...", end=" ")

        # Fetch price data for the window
        window_start = rebalance_date - timedelta(days=400)  # ~1.5 years

        query = text("""
            SELECT stock_id, date, close_price
            FROM daily_prices
            WHERE date >= :start_date AND date <= :end_date
            ORDER BY stock_id, date
        """)

        prices = session.execute(query, {"start_date": window_start, "end_date": rebalance_date}).fetchall()

        if not prices:
            print("No data")
            continue

        df_window = pd.DataFrame(prices, columns=["stock_id", "date", "close_price"])
        df_window["date"] = pd.to_datetime(df_window["date"])
        df_window = df_window.set_index(["stock_id", "date"])

        # Calculate momentum
        scores_df = calculate_momentum_for_date(session, rebalance_date, df_window)

        if scores_df.empty:
            print("No scores")
            continue

        # Prepare batch insert
        history_records = []
        for rank, row in enumerate(scores_df.itertuples(), 1):
            history_records.append(
                {
                    "stock_id": row.stock_id,
                    "date": rebalance_date.date(),
                    "momentum_score": float(row.weighted_z),
                    "rank": rank,
                }
            )

        # Bulk insert
        if history_records:
            session.execute(
                text("""
                    INSERT INTO momentum_history (stock_id, date, momentum_score, rank)
                    VALUES (:stock_id, :date, :momentum_score, :rank)
                    ON CONFLICT (stock_id, date) DO UPDATE
                    SET momentum_score = EXCLUDED.momentum_score,
                        rank = EXCLUDED.rank
                """),
                history_records,
            )
            session.commit()
            total_records += len(history_records)
            print(f"Saved {len(history_records)} records")

    session.close()
    print(f"\nDone! Total records: {total_records}")


if __name__ == "__main__":
    populate_history()
