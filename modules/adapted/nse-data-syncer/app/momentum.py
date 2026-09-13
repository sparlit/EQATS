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


from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from .database import DatabaseManager, StockPerformance


def calculate_momentum():
    print("Starting Momentum Score Calculation (Optimized)...")
    db = DatabaseManager()
    session = db.Session()

    try:
        # 1. Start Transaction

        # 2. Get all active stocks
        print("Fetching active stocks...")
        stocks = session.execute(text("SELECT id FROM stocks WHERE is_active = true")).fetchall()
        active_stock_ids = [s[0] for s in stocks]
        print(f"Found {len(active_stock_ids)} active stocks.")

        if not active_stock_ids:
            return

        # 3. Ensure StockPerformance records exist for all active stocks
        # Efficient checking: Get existing stock_ids from stock_performance
        existing_perfs = session.execute(text("SELECT stock_id, id FROM stock_performance")).fetchall()
        existing_map = {p[0]: p[1] for p in existing_perfs}

        missing_ids = [sid for sid in active_stock_ids if sid not in existing_map]

        if missing_ids:
            print(f"Creating {len(missing_ids)} missing StockPerformance records...")
            new_perfs = [{"stock_id": sid} for sid in missing_ids]
            session.bulk_insert_mappings(StockPerformance, new_perfs)
            session.commit()

            # Refresh map
            existing_perfs = session.execute(text("SELECT stock_id, id FROM stock_performance")).fetchall()
            existing_map = {p[0]: p[1] for p in existing_perfs}

        # 4. Fetch Price History for ALL stocks (last ~400 days)
        print("Fetching price history...")
        start_date = datetime.now() - timedelta(days=400)

        # We need a way to fetch efficiently. Reading 200k rows is fine.
        query = text("""
            SELECT stock_id, date, close_price
            FROM daily_prices
            WHERE date >= :start_date
        """)

        price_rows = session.execute(query, {"start_date": start_date}).fetchall()

        if not price_rows:
            print("No price data found.")
            return

        df = pd.DataFrame(price_rows, columns=["stock_id", "date", "close"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["stock_id", "date"])

        print(f"Loaded {len(df)} price records. Calculating metrics...")

        # 5. Vectorized Calculation
        # Calculate Log Returns efficiently
        # Shift close price by 1 within each stock group to get previous day's close
        df["prev_close"] = df.groupby("stock_id")["close"].shift(1)
        df["log_ret"] = np.log(df["close"] / df["prev_close"])

        # Calculate Volatility (Annualized Std Dev of last 252 days)
        # We can take the last year slice per stock

        # To make it efficient, we can compute stats per group
        # Using groupby is easiest, though might be slightly slower than pure numpy reshaping, usually fine.

        def calc_metrics(g):
            if len(g) < 20:  # Minimum data requirement
                return None

            # Filter last 252 days for volatility
            # Assuming sorted by date
            last_year = g.iloc[-252:]
            volatility = last_year["log_ret"].std() * np.sqrt(252)

            if pd.isna(volatility) or volatility == 0:
                return None

            current_price = g["close"].iloc[-1]

            # Helper for returns
            def get_ret(days):
                if len(g) <= days:
                    return None
                prev_price = g["close"].iloc[-(days + 1)]
                return (current_price / prev_price) - 1

            ret_1m = get_ret(21)
            ret_3m = get_ret(63)
            ret_6m = get_ret(126)
            ret_1y = get_ret(252)  # avoiding var name conflict

            return pd.Series(
                {
                    "volatility": volatility,
                    "mr_1m": ret_1m / volatility if ret_1m is not None else None,
                    "mr_3m": ret_3m / volatility if ret_3m is not None else None,
                    "mr_6m": ret_6m / volatility if ret_6m is not None else None,
                    "mr_1y": ret_1y / volatility if ret_1y is not None else None,
                }
            )

        # Apply calculation
        # Note: apply can be slow. iterating groups might be faster?
        # But let's try apply first. 400 stocks is small.
        metrics_df = df.groupby("stock_id").apply(calc_metrics)

        # metrics_df index is stock_id (or None if skipped)
        metrics_df = metrics_df.dropna(how="all")

        print(f"Calculated metrics for {len(metrics_df)} stocks.")

        # 6. Global Stats for Z-Scores
        stats = {}
        for period in ["1m", "3m", "6m", "1y"]:
            col = f"mr_{period}"
            if col in metrics_df:
                stats[period] = {"mean": metrics_df[col].mean(), "std": metrics_df[col].std()}
            else:
                stats[period] = {"mean": 0, "std": 1}

        # 7. Z-Scores Calculation
        updates = []

        for stock_id, row in metrics_df.iterrows():
            perf_id = existing_map.get(stock_id)
            if not perf_id:
                continue

            up = {
                "id": perf_id,
                "volatility": float(row["volatility"]) if pd.notna(row["volatility"]) else None,
                "mr_1m": float(row["mr_1m"]) if pd.notna(row["mr_1m"]) else None,
                "mr_3m": float(row["mr_3m"]) if pd.notna(row["mr_3m"]) else None,
                "mr_6m": float(row["mr_6m"]) if pd.notna(row["mr_6m"]) else None,
                "mr_1y": float(row["mr_1y"]) if pd.notna(row["mr_1y"]) else None,
            }

            # Z-Scores
            z_list = []
            for period in ["3m", "6m", "1y"]:  # Exclude 1M
                val = row[f"mr_{period}"]
                if pd.notna(val) and stats[period]["std"] > 0:
                    z = (val - stats[period]["mean"]) / stats[period]["std"]
                    up[f"z_{period}"] = float(z)
                    z_list.append(z)
                else:
                    up[f"z_{period}"] = None

            # 1M Z-Score (stored but not used in score)
            if pd.notna(row["mr_1m"]) and stats["1m"]["std"] > 0:
                up["z_1m"] = float((row["mr_1m"] - stats["1m"]["mean"]) / stats["1m"]["std"])
            else:
                up["z_1m"] = None

            # Final Score
            if len(z_list) == 3:
                weighted_z = sum(z_list) / 3
                score = 1 + weighted_z if weighted_z >= 0 else 1 / (1 - weighted_z)
                up["momentum_score"] = float(score)
            else:
                up["momentum_score"] = None

            # Simple Momentum Score (6M + 1Y only)
            simple_z_list = []
            for period in ["6m", "1y"]:
                val = row[f"mr_{period}"]
                if pd.notna(val) and stats[period]["std"] > 0:
                    z = (val - stats[period]["mean"]) / stats[period]["std"]
                    simple_z_list.append(z)

            if len(simple_z_list) == 2:
                weighted_simple = sum(simple_z_list) / 2
                simple_score = 1 + weighted_simple if weighted_simple >= 0 else 1 / (1 - weighted_simple)
                up["simple_momentum_score"] = float(simple_score)
            else:
                up["simple_momentum_score"] = None

            # Add to list for history processing
            updates.append(up)

        # 8. Bulk Update DB (StockPerformance)
        if updates:
            print(f"Updating StockPerformance for {len(updates)} records...")
            # We use bulk_update_mappings. Requires PK 'id' in dicts.
            session.bulk_update_mappings(StockPerformance, updates)

            # 9. Save to MomentumHistory (Daily Snapshot)
            print("Saving daily momentum history...")
            from sqlalchemy.dialects.postgresql import insert

            from .database import MomentumHistory

            today = datetime.now().date()

            # Prepare history records

            # Filter valid scores and keep stock_id
            # updates list has 'id' (perf_id), NOT stock_id directly usually.
            # But wait, we iterate existing_map to get perf_id from stock_id.
            # So we need to map back or store stock_id in updates.
            # Let's rely on metrics_df again which has everything.

            valid_rows = []

            # Iterate metrics_df again to get scores + stock_id
            # Note: We computed scores in the loop above but didn't save to df.
            # Let's re-use the computed 'updates' list but we need to map perf_id back to stock_id?
            # Or easier: just add stock_id to 'updates' list!

            # Map perf_id -> stock_id (inverse of existing_map)
            perf_to_stock = {v: k for k, v in existing_map.items()}

            for up in updates:
                sid = perf_to_stock.get(up["id"])
                score = up.get("momentum_score")

                if sid is not None and score is not None:
                    valid_rows.append({"stock_id": sid, "momentum_score": score, "date": today})

            # Calculate Ranks
            valid_rows.sort(key=lambda x: x["momentum_score"], reverse=True)

            for i, row in enumerate(valid_rows, 1):
                row["rank"] = i

            if valid_rows:
                print(f"Inserting {len(valid_rows)} history records...")

                # Use PostgreSQL UPSERT to handle re-runs on same day
                stmt = insert(MomentumHistory).values(valid_rows)

                stmt = stmt.on_conflict_do_update(
                    index_elements=["stock_id", "date"],
                    set_={"momentum_score": stmt.excluded.momentum_score, "rank": stmt.excluded.rank},
                )

                session.execute(stmt)
                session.commit()
                print("History saved successfully.")
            else:
                print("No valid scores to save to history.")

        else:
            print("No updates to save.")

    except Exception as e:
        session.rollback()
        print(f"Error in momentum calculation: {e}")
        import traceback

        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    calculate_momentum()
