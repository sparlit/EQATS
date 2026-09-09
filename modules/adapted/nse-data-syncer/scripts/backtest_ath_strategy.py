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


import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load env
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import DatabaseManager


def get_trading_dates(start_date, end_date):
    """Helper to generate expected trading dates (approx)"""
    return pd.date_range(start=start_date, end=end_date, freq="B")


def run_backtest():
    print("Starting **ATH Breakout** Strategy Backtest...")
    db = DatabaseManager()

    # 1. Load All Stocks
    print("Fetching stock list...")
    session = db.Session()
    try:
        query = text("SELECT id, nse_symbol, name FROM stocks WHERE is_active = true")
        stocks = session.execute(query).fetchall()
        stock_map = {s.id: s.nse_symbol for s in stocks}
    finally:
        session.close()

    print(f"Loaded {len(stocks)} stocks.")

    # Load Market Cap Filter (Global)
    min_mcap_cr = float(os.getenv("MIN_MARKET_CAP_CR", 2000))
    min_mcap = min_mcap_cr * 10000000

    valid_stocks_query = text(f"SELECT id FROM stocks WHERE is_active = true AND market_cap >= {min_mcap}")
    valid_stock_ids = [r[0] for r in session.execute(valid_stocks_query).fetchall()]
    print(f"Loaded {len(valid_stock_ids)} eligible stocks (> {min_mcap_cr} Cr) for Backtest & Live Signals.")

    # 2. Load Price Data (OPTIMIZED with Chunking)
    print("Loading daily price data for eligible stocks (Chunks of 200)...")
    stock_map = {s.id: s.nse_symbol for s in stocks}

    session = db.Session()
    df_list = []
    try:
        if valid_stock_ids:
            # Chunking to prevent memory issues and huge query timeouts
            ids_list = list(valid_stock_ids)
            chunk_size = 200

            for i in range(0, len(ids_list), chunk_size):
                chunk = ids_list[i : i + chunk_size]
                if not chunk:
                    continue

                # Make tuple for SQL (handle single item case carefully)
                ids_tuple = f"({chunk[0]})" if len(chunk) == 1 else tuple(chunk)

                query = text(f"""
                    SELECT stock_id, date, open_price, high_price, low_price, close_price
                    FROM daily_prices
                    WHERE stock_id IN {ids_tuple}
                    ORDER BY stock_id, date
                """)
                result = session.execute(query)
                df_chunk = pd.DataFrame(result.fetchall(), columns=["stock_id", "date", "open", "high", "low", "close"])

                if not df_chunk.empty:
                    df_chunk["date"] = pd.to_datetime(df_chunk["date"])
                    df_chunk = df_chunk.set_index(["stock_id", "date"])
                    df_list.append(df_chunk)

                print(f"  Loaded chunk {i} - {i + len(chunk)}")

    finally:
        session.close()

    if df_list:
        df_all = pd.concat(df_list)
        df_all = df_all.sort_index()
    else:
        df_all = pd.DataFrame(columns=["stock_id", "date", "open", "high", "low", "close"])
        df_all = df_all.set_index(["stock_id", "date"])

    # optimize lookup
    valid_stock_ids = set(valid_stock_ids)

    # Pre-calculate simple metrics if possible, but ATH is path-dependent

    trades = []
    eligible_stocks = []  # Stocks with breakout signal waiting for entry

    print("Processing stocks...")

    for stock_id, symbol in stock_map.items():
        # Global Filter: Skip if not in valid list
        if stock_id not in valid_stock_ids:
            continue

        try:
            # Fast Lookup using MultiIndex
            df = df_all.loc[stock_id]  # Result is indexed by 'date'

            if symbol == "NETWEB":
                print(f"DEBUG NETWEB: Data Length {len(df)}")
            if len(df) < 500:  # Need some history for ATH
                if symbol == "NETWEB":
                    print("DEBUG NETWEB: Skipped due to length < 500")
                continue

            # Calculate 30-Week SMA
            # Resample to Weekly (Ending Friday)
            weekly_df = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            weekly_df["sma_30_weekly"] = weekly_df["close"].rolling(window=30).mean()

            # Resample to Monthly for ATH Detection (as before)
            monthly = df.resample("ME").agg({"high": "max", "close": "last"})

            # Start logic from 2017, but need prior history for ATH
            start_backtest = pd.Timestamp("2017-01-01")

            monthly["prev_ath"] = monthly["high"].expanding().max().shift(1)

            current_ath = 0
            current_ath_date = df.index[0]

            monthly_records = monthly.reset_index().to_dict("records")

            for i, month in enumerate(monthly_records):
                if i == 0:
                    current_ath = month["high"]
                    current_ath_date = month["date"]
                    continue

                month_date = month["date"]

                # Update ATH if this month made a new one
                # CAREFUL: Strategy says "Monthly Close > Prev ATH".

                # Check Breakout Condition
                is_breakout = False
                if month_date >= start_backtest:
                    if month["close"] > current_ath:
                        # Gap Condition: current_ath must be at least 2 months old
                        # Approx 60 days
                        if (month_date - current_ath_date).days > 60:
                            is_breakout = True
                        else:
                            pass
                # Before backtest start, just update ATH
                elif month["high"] > current_ath:
                    current_ath = month["high"]
                    current_ath_date = month_date

                if is_breakout:
                    entry_trigger = month["high"]

                    next_month_start = month_date + timedelta(days=1)

                    # Track eligible stocks (recent breakouts waiting for entry)
                    # Only track if breakout happened in last 2 months
                    today = pd.Timestamp(datetime.now())
                    months_since_breakout = (today.year - month_date.year) * 12 + (today.month - month_date.month)

                    # We'll check later if this breakout actually resulted in a trade
                    # For now, just mark it as a potential eligible stock
                    potential_eligible = None
                    if months_since_breakout <= 2 and months_since_breakout >= 0:
                        # Get current price for reference
                        current_price = df["close"].iloc[-1] if len(df) > 0 else 0

                        # Market Cap Filter: Already applied globally at loop start
                        potential_eligible = {
                            "symbol": symbol,
                            "breakout_month": month_date.strftime("%Y-%m"),
                            "breakout_date": month_date.strftime("%Y-%m-%d"),
                            "entry_trigger": round(entry_trigger, 2),
                            "previous_ath": round(current_ath, 2),
                            "ath_date": current_ath_date.strftime("%Y-%m-%d"),
                            "gap_days": (month_date - current_ath_date).days,
                            "close_price": round(month["close"], 2),
                            "current_price": round(current_price, 2),
                            "entry_month": next_month_start.strftime("%Y-%m"),
                        }

                    # Get daily data for next month onwards (for entry and exit)
                    future_data = df[df.index >= next_month_start]

                    if future_data.empty:
                        continue

                    # 1. Entry Check
                    entry_date = None
                    entry_price = 0.0

                    # We look for entry in the NEXT MONTH only
                    entry_window = future_data[
                        (future_data.index.month == next_month_start.month)
                        & (future_data.index.year == next_month_start.year)
                    ]

                    if symbol == "NETWEB" and is_breakout:
                        pass

                    # LOGIC CHANGE: Prevent Overlapping Trades
                    # If we have a last_exit_date for this stock, and the potential entry window starts BEFORE that exit,
                    # we must skip this setup or carefully check dates.
                    # Simplest robust check: Don't take a new setup if the Entry Window overlaps with an active trade.
                    # Since we don't know the NEW entry date yet, we check if we are "clear" of the last trade.

                    last_trade = None
                    last_trade_exit = None

                    # Find the last trade for this stock in our list
                    stock_trades = [t for t in trades if t["symbol"] == symbol]
                    if stock_trades:
                        last_trade = stock_trades[-1]  # List is appended chronologically
                        if last_trade["exit_date"]:
                            last_trade_exit = pd.Timestamp(last_trade["exit_date"])
                        else:
                            # Last trade is OPEN. Cannot take new one.
                            continue

                    # If the last trade exited after the start of this entry window,
                    # we might be overlapping.
                    # Actually, we just need to ensure new Entry Date > Last Exit Date.

                    for date, row in entry_window.iterrows():
                        # Overlap Check
                        if last_trade_exit and date <= last_trade_exit:
                            continue

                        if row["high"] > entry_trigger:
                            # TRIGGERED
                            entry_date = date
                            entry_price = max(entry_trigger, row["open"])

                            # SANITY CHECK: Entry Price must be > Current ATH (Prev ATH)
                            # This filters out invalid setups caused by unadjusted splits or data glitches
                            if entry_price <= current_ath:
                                entry_date = None
                                continue

                            break

                    if entry_date:
                        # Trade is ON. Now scan for Weekly Exit.
                        exit_date = None
                        exit_price = 0.0
                        status = "OPEN"

                        # Get Weekly Data after Entry Date
                        trade_weekly = weekly_df[weekly_df.index > entry_date].copy()

                        # Check Exit Condition: Close < 30 Week SMA
                        exit_signals = trade_weekly[trade_weekly["close"] < trade_weekly["sma_30_weekly"]]

                        if not exit_signals.empty:
                            signal_date = exit_signals.index[0]  # This is a Friday

                            # Exit next trading day (Monday usually)
                            # Find first daily candle AFTER signal_date
                            next_days = df[df.index > signal_date]
                            if not next_days.empty:
                                exit_row = next_days.iloc[0]
                                exit_date = exit_row.name
                                exit_price = exit_row["open"]
                                status = "CLOSED"
                            else:
                                status = "OPEN"

                        # Record Trade
                        pnl = 0.0
                        pnl_pct = 0.0

                        current_price = df["close"].iloc[-1]

                        if status == "CLOSED":
                            gross_pnl = exit_price - entry_price
                            # Fee: 0.25% on Entry + 0.25% on Exit
                            fees = (entry_price * 0.0025) + (exit_price * 0.0025)
                            pnl = gross_pnl - fees
                            pnl_pct = (pnl / entry_price) * 100
                        else:
                            gross_pnl = current_price - entry_price
                            # Fee: 0.25% on Entry + 0.25% on Current Value (Unrealized Exit)
                            fees = (entry_price * 0.0025) + (current_price * 0.0025)
                            pnl = gross_pnl - fees
                            pnl_pct = (pnl / entry_price) * 100

                        trades.append(
                            {
                                "symbol": symbol,
                                "entry_date": entry_date.strftime("%Y-%m-%d"),
                                "entry_price": round(entry_price, 2),
                                "exit_date": exit_date.strftime("%Y-%m-%d") if exit_date else None,
                                "exit_price": round(exit_price, 2) if exit_date else None,
                                "status": status,
                                "pnl": round(pnl, 2),
                                "pnl_pct": round(pnl_pct, 2),
                                "duration_days": (exit_date - entry_date).days
                                if exit_date
                                else (df.index[-1] - entry_date).days,
                            }
                        )

                        # This breakout resulted in a trade, so it's not "eligible" anymore
                        potential_eligible = None

                        # Since we consumed this setup, we stop scanning this month (entry_window).
                        # break  <-- REMOVED (Was breaking stock loop)

                        # IMPORTANT: Strategy says we buy. Assuming only 1 position per stock at a time?
                        # If we held a position, we wouldn't take another setup until exited?
                        # For simplicity in this logic: if we took a trade, we skip months until it's closed?
                        # The iteration above is independent. It might generate overlapping trades if breakout happens again while holding.
                        # Realistically, if you hold it, you hold it.
                        # Optimization: Skip `i` until exit_date month.

                        # Note: `i` is index of monthly_records. We need to jump ahead.
                        # But `monthly_records` logic updates ATH.
                        # We should just block Taking New Trades for this stock if `entry_date` > existing trade `exit_date`?
                        # Let's keep it simple: Multiple pyramiding is allowed OR simple filter later.
                        # Given "All Time High" logic, it's unlikely to trigger again quickly unless it crashes and recovers.
                        # Actually, if it keeps making new ATHs, `current_ath` updates.
                        # But Setup requires `Close > Prev_ATH`. If we are in a trade, we are likely making new ATHs.
                        # But the "Prev ATH" must be 2 months OLD.
                        # If we are rallying, the "Prev ATH" is just last month. So Gap condition < 60 days fails.
                        # So NATURALLY, this strategy filters pyramiding during strong trends!

                    # If we had a potential eligible stock and it didn't result in a trade, add it to the list
                    if potential_eligible is not None:
                        eligible_stocks.append(potential_eligible)

                # Update ATH tracking
                if month["high"] > current_ath:
                    current_ath = month["high"]
                    current_ath_date = month_date

        except Exception:
            # print(f"Error processing {symbol}: {str(e)}")
            continue

    print(f"Total Trades Found: {len(trades)}")
    print(f"Eligible Stocks (Recent Breakouts): {len(eligible_stocks)}")

    # Save Results
    output = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trades": sorted(trades, key=lambda x: x["entry_date"], reverse=True),
        "eligible_stocks": sorted(eligible_stocks, key=lambda x: x["breakout_date"], reverse=True),
    }

    # Calc Summary
    # 1. Fetch Benchmark (Nifty 50)
    print("Fetching Benchmark Data...")
    import yfinance as yf
    from dateutil.relativedelta import relativedelta

    try:
        nifty = yf.download(
            "^NSEI", start=(datetime.now() - relativedelta(years=10)).strftime("%Y-%m-%d"), progress=False
        )
        if nifty.empty:
            print("Warning: Could not fetch Nifty data.")
            nifty = pd.DataFrame(columns=["close"])
        else:
            if isinstance(nifty.columns, pd.MultiIndex):
                nifty.columns = nifty.columns.get_level_values(0)
            nifty = nifty.reset_index()
            nifty.columns = [c.lower() for c in nifty.columns]
            if "date" not in nifty.columns:
                nifty = nifty.rename(columns={"index": "date"})
            if "close" in nifty.columns:
                nifty = nifty[["date", "close"]]
            elif "adj close" in nifty.columns:
                nifty = nifty[["date", "adj close"]]
                nifty = nifty.rename(columns={"adj close": "close"})

            nifty = nifty.set_index("date")
    except Exception as e:
        print(f"Error fetching benchmark: {e}")
        nifty = pd.DataFrame(columns=["close"])

    # ... (Rest of simulate_portfolio logic inside generate_daily_equity_curve) ...

    # Portfolio Simulation for Total Return % AND Daily Equity Curve
    def simulate_portfolio_daily(
        trade_list, df_prices, benchmark_df, stock_map, initial_capital=10000000, max_positions=2000
    ):
        executed_trades_count = 0
        symbol_to_id = {v: k for k, v in stock_map.items()}
        # Sort trades by entry date
        sorted_trades = sorted(trade_list, key=lambda x: x["entry_date"])
        if not sorted_trades:
            return 0, initial_capital, [], 0

        start_date = pd.Timestamp(sorted_trades[0]["entry_date"])
        end_date = pd.Timestamp(datetime.now().date())
        date_range = pd.date_range(start=start_date, end=end_date, freq="B")

        cash = initial_capital
        positions = {}  # symbol -> {shares, stock_id}
        equity_curve = []

        # Benchmark scaling
        nifty_factor = 0
        if not benchmark_df.empty:
            try:
                # Get close of start date (or nearest before)
                base_idx = benchmark_df.index.get_indexer([start_date], method="nearest")[0]
                base_val = benchmark_df.iloc[base_idx]["close"]
                nifty_factor = initial_capital / base_val
            except:
                nifty_factor = 0

        # Events Dictionary
        events = {}
        for t in sorted_trades:
            ed = pd.Timestamp(t["entry_date"])
            xd = pd.Timestamp(t["exit_date"]) if t["exit_date"] else None

            if ed not in events:
                events[ed] = []
            events[ed].append({"type": "ENTRY", "trade": t})

            if xd:
                if xd not in events:
                    events[xd] = []
                events[xd].append({"type": "EXIT", "trade": t})

        for d in date_range:
            # Process Events
            if d in events:
                for action in events[d]:
                    t = action["trade"]
                    sym = t["symbol"]

                    if action["type"] == "ENTRY":
                        # Check cash and slots
                        # Estimate current equity for sizing (Cash + current positions)
                        # We calculate mtm later, so use 'yesterday's' estimate or just current components
                        # For speed, just use Cash + Sum(Cost) as approximation for allocation base?
                        # Or simpler: Fixed 100k allocation? No, 10% of CURRENT equity.
                        # We need MTM sum.
                        mtm_val = 0
                        for p in positions.values():
                            # Lookup price
                            sid = p["stock_id"]
                            try:
                                # idx = (sid, d) -> if missing, use last?
                                # df_prices is MultiIndex
                                val = df_prices.loc[(sid, d)]["close"]
                                price = float(val.iloc[0]) if isinstance(val, pd.Series) else float(val)
                            except:
                                price = float(p.get("last_price", 0))  # fallback safety

                            mtm_val += p["shares"] * price

                        curr_eq = cash + mtm_val
                        # Alloc: 1 Share per trade
                        # We verify we have enough cash for 1 share.
                        price = t["entry_price"]
                        cost = price

                        if cash >= cost:
                            shares = 1
                            fee = cost * 0.0025
                            cash -= cost + fee
                            executed_trades_count += 1
                            sid = symbol_to_id.get(sym)
                            if sid:
                                positions[sym] = {"shares": shares, "stock_id": sid, "last_price": price}
                        else:
                            # Not enough cash for even 1 share
                            pass

                    # Skip the old dynamic alloc logic block
                    elif action["type"] == "EXIT":
                        if sym in positions:
                            pos = positions[sym]
                            shares = pos["shares"]
                            price = t["exit_price"]
                            proceeds = shares * price
                            fee = proceeds * 0.0025
                            cash += proceeds - fee
                            del positions[sym]

            # End of Day Valuation
            pos_value = 0
            for sym, pos in positions.items():
                sid = pos["stock_id"]
                try:
                    # Try to get today's close
                    val = df_prices.loc[(sid, d)]["close"]
                    price = float(val.iloc[0]) if isinstance(val, pd.Series) else float(val)
                    pos["last_price"] = price
                except:
                    # If missing (holiday/data gap), keep last
                    price = float(pos.get("last_price", 0))

                pos_value += pos["shares"] * price

            total_equity = cash + pos_value
            invested_capital = initial_capital - cash

            # Benchmark
            # Benchmark
            bench_val = 0
            if nifty_factor > 0:
                try:
                    # Strict lookup or propagate?
                    if d in benchmark_df.index:
                        b_val_series = benchmark_df.loc[d]["close"]
                        if isinstance(b_val_series, pd.Series):
                            b_price = float(b_val_series.iloc[0])
                        else:
                            b_price = float(b_val_series)
                        bench_val = b_price * nifty_factor
                        last_bench_val = bench_val  # store for fill
                    else:
                        # Forward fill if missing (holidays etc)
                        # But wait, date_range is business days 'B'. Nifty might match?
                        # If mismatch, use last known.
                        bench_val = last_bench_val if "last_bench_val" in locals() else 0

                except Exception:
                    # fallback
                    bench_val = last_bench_val if "last_bench_val" in locals() else 0

        equity_curve.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "equity": round(total_equity, 2),
                "invested": round(invested_capital, 2),
                "benchmark": round(bench_val, 2),
            }
        )

        final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital

        # Recalculate Return based on Peak Invested Capital (Realistic Capital Required)
        # Filter 0 to avoid div by zero if no trades
        peak_invested = max([d["invested"] for d in equity_curve]) if equity_curve else 0
        if peak_invested == 0:
            peak_invested = initial_capital  # Fallback

        # Total Profit = Final Equity - Initial Capital
        total_profit = final_equity - initial_capital

        # Adjusted Return %
        ret_pct = total_profit / peak_invested * 100

        # Re-normalize Equity Curve for display
        # We want the curve to look like we started with 'peak_invested' (plus maybe a buffer?)
        # or just show the growth relative to it.
        # Current Equity = Initial (1Cr) + Profit.
        # Display Equity = Peak_Invested + Profit.

        adjusted_equity_curve = []
        for pt in equity_curve:
            profit = pt["equity"] - initial_capital
            adj_eq = peak_invested + profit
            pt["equity"] = round(adj_eq, 2)
            # We don't change benchmark here, it's relative?
            # Actually benchmark factor was calc on Initial Capital (1Cr).
            # We need to re-scale benchmark too?
            # Yes, strictly speaking.
            # But let's fix the Equity first.
            adjusted_equity_curve.append(pt)

        final_equity_adjusted = adjusted_equity_curve[-1]["equity"]

        # Fix Benchmark Scaling to match new base
        # Bench Factor = Base / Start_Index_Val
        # New Base = Peak Invested
        if not benchmark_df.empty:
            try:
                first_date = pd.Timestamp(adjusted_equity_curve[0]["date"])
                base_idx = benchmark_df.index.get_indexer([first_date], method="nearest")[0]
                base_val = benchmark_df.iloc[base_idx]["close"]
                new_nifty_factor = peak_invested / base_val

                # Re-apply
                for pt in adjusted_equity_curve:
                    d = pd.Timestamp(pt["date"])
                    if d in benchmark_df.index:
                        val = benchmark_df.loc[d]["close"]
                        if isinstance(val, pd.Series):
                            val = val.iloc[0]
                        pt["benchmark"] = round(float(val) * new_nifty_factor, 2)
                    else:
                        # If missing, use prev or 0
                        pass
            except:
                pass

        print(f"Max Capital Deployed: {peak_invested}")

        return round(ret_pct, 2), round(final_equity_adjusted, 2), adjusted_equity_curve, executed_trades_count

    # Execute
    total_ret_pct, final_eq_val, eq_data, executed_trades_count = simulate_portfolio_daily(
        sorted(trades, key=lambda x: x["entry_date"]), df_all, nifty, stock_map
    )

    # Pre-calculate trade stats
    closed_trades = [t for t in trades if t["status"] == "CLOSED"]
    wins = len([t for t in closed_trades if t["pnl"] > 0])
    total_pnl = sum([t["pnl"] for t in trades])

    output["summary"] = {
        "total_trades": len(trades),
        "executed_trades": executed_trades_count,
        "closed_trades": len(closed_trades),
        "active_trades": len(trades) - len(closed_trades),
        "win_rate": round(wins / len(closed_trades) * 100, 2) if closed_trades else 0,
        "total_pnl_abs": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / len(trades), 2) if trades else 0,
        "total_return_pct": total_ret_pct,
        "portfolio_value": final_eq_val,
        # Recalculate advanced stats from equity curve if needed or keep existing trade-based one?
        # Trade-based profit factor is fine.
    }

    # 2. Profit Factor
    gross_profit = sum([t["pnl"] for t in closed_trades if t["pnl"] > 0])
    gross_loss = abs(sum([t["pnl"] for t in closed_trades if t["pnl"] < 0]))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0

    # 3. Avg Win / Loss
    winning_trades = [t["pnl"] for t in closed_trades if t["pnl"] > 0]
    losing_trades = [t["pnl"] for t in closed_trades if t["pnl"] <= 0]

    avg_win = round(sum(winning_trades) / len(winning_trades), 2) if winning_trades else 0
    avg_loss = round(sum(losing_trades) / len(losing_trades), 2) if losing_trades else 0

    # Max Drawdown from Daily Equity Curve (More Accurate)
    if eq_data:
        peak = -float("inf")
        max_dd = 0
        for pt in eq_data:
            val = pt["equity"]
            peak = max(peak, val)
            dd = peak - val
            max_dd = max(max_dd, dd)
    else:
        max_dd = 0

    output["equity_curve"] = eq_data
    output["summary"].update(
        {"profit_factor": profit_factor, "max_drawdown": round(max_dd, 2), "avg_win": avg_win, "avg_loss": avg_loss}
    )

    out_path = os.path.join(base_dir, "web", "src", "data", "backtest_results_ath.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Backtest Complete. Total Return: {total_ret_pct}%")
    print(f"Total Signals: {len(trades)}")
    print(f"Executed Trades (Portfolio): {executed_trades_count}")
    print(f"Saved results to {out_path}")


if __name__ == "__main__":
    run_backtest()
