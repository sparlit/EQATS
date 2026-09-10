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
import yfinance as yf
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from sqlalchemy import text

# Load env
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.constants import CSV_FILENAME, FULL_EQUITY_LIST_FILENAME
from app.database import DatabaseManager, MomentumHistory
from app.helpers import get_data_path
from app.utils import get_remaining_symbols


def get_month_ends():
    """Get list of month-end dates from 2018-01 through today."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    dates = []
    current = datetime(2017, 12, 1) + relativedelta(months=1)

    while current <= today:
        last_month_end = current - timedelta(days=1)
        dates.append(last_month_end)
        current += relativedelta(months=1)

    return dates


def calculate_momentum_for_date(session, target_date, stocks_df, valid_stock_ids=None):
    """
    Calculate momentum scores for all stocks as of target_date.
    stocks_df should contain all daily prices up to target_date.
    """
    scores = []

    # Filter for data up to target_date
    target_date - timedelta(days=365 + 30)  # Buffer

    unique_stocks = stocks_df.index.get_level_values("stock_id").unique()

    for stock_id in unique_stocks:
        if valid_stock_ids is not None and stock_id not in valid_stock_ids:
            continue
        try:
            # Get stock data
            df = stocks_df.loc[stock_id]
            df = df[df.index <= target_date].sort_index()

            if len(df) < 252:
                continue

            # Calculate metrics
            # Log returns
            df["log_ret"] = np.log(df["close_price"] / df["close_price"].shift(1))

            # Volatility (last 252 days)
            volatility = df["log_ret"].tail(252).std() * np.sqrt(252)

            if pd.isna(volatility) or volatility == 0:
                continue

            current_price = df["close_price"].iloc[-1]

            def get_ret(days):
                if len(df) <= days:
                    return None
                past_price = df["close_price"].iloc[-(days + 1)]
                return (current_price / past_price) - 1

            r6m = get_ret(126)
            r1y = get_ret(252)

            if None in [r6m, r1y]:
                continue

            # Only use 6M, 1Y (exclude 3M)
            mr_6m = r6m / volatility
            mr_1y = r1y / volatility

            scores.append({"stock_id": stock_id, "mr_6m": mr_6m, "mr_1y": mr_1y})

        except KeyError:
            continue

    if not scores:
        return []

    # Calculate Z-Scores (only for 6M, 1Y)
    df_scores = pd.DataFrame(scores)

    for period in ["6m", "1y"]:
        col = f"mr_{period}"
        mean = df_scores[col].mean()
        std = df_scores[col].std()
        if std > 0:
            df_scores[f"z_{period}"] = (df_scores[col] - mean) / std
        else:
            df_scores[f"z_{period}"] = 0

    # Weighted Score (equal weights: 1/2 each)
    df_scores["weighted_z"] = (df_scores["z_6m"] + df_scores["z_1y"]) / 2

    # Sort by weighted Z (descending)
    return df_scores.sort_values("weighted_z", ascending=False)


def calculate_comprehensive_metrics(monthly_results, benchmark_results):
    """Calculate comprehensive backtest metrics"""

    # Convert to numpy arrays for calculations
    portfolio_returns = np.array([r["portfolio_return"] / 100 for r in monthly_results])
    benchmark_returns = np.array([r["benchmark_return"] / 100 for r in monthly_results])

    # Time Metrics
    start_date = monthly_results[0]["month"]
    end_date = monthly_results[-1]["month"]
    period_months = len(monthly_results)
    period_years = period_months / 12

    # Capital Metrics
    start_value = 100000  # Changed to 1 lakh
    cumulative_portfolio = np.cumprod(1 + portfolio_returns)
    cumulative_benchmark = np.cumprod(1 + benchmark_returns)
    end_value = start_value * cumulative_portfolio[-1]
    total_fees_paid = 0  # Will be updated later with actual fees
    open_trade_pnl = 0  # No open trades at end of backtest period

    # Return Metrics
    total_return = (end_value - start_value) / start_value
    benchmark_total_return = (start_value * cumulative_benchmark[-1] - start_value) / start_value

    # Expectancy (average return per trade/month)
    expectancy = np.mean(portfolio_returns)

    # Risk Metrics
    # Max Drawdown
    cumulative_values = start_value * cumulative_portfolio
    running_max = np.maximum.accumulate(cumulative_values)
    drawdowns = (cumulative_values - running_max) / running_max
    max_drawdown = np.min(drawdowns)

    # Max Drawdown Duration (in months)
    dd_duration = 0
    current_dd_duration = 0
    for dd in drawdowns:
        if dd < 0:
            current_dd_duration += 1
            dd_duration = max(dd_duration, current_dd_duration)
        else:
            current_dd_duration = 0

    # Sharpe Ratio (annualized, assuming risk-free rate = 0)
    excess_returns = portfolio_returns - 0  # Assuming risk-free rate = 0
    sharpe_ratio = (
        (np.mean(excess_returns) * 12) / (np.std(excess_returns) * np.sqrt(12)) if np.std(excess_returns) > 0 else 0
    )

    # Calmar Ratio (annualized return / max drawdown)
    annualized_return = (1 + total_return) ** (1 / period_years) - 1
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0

    # Sortino Ratio (using downside deviation)
    downside_returns = portfolio_returns[portfolio_returns < 0]
    downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 0
    sortino_ratio = (np.mean(excess_returns) * 12) / (downside_std * np.sqrt(12)) if downside_std > 0 else 0

    # Omega Ratio (probability weighted ratio of gains vs losses)
    threshold = 0
    gains = portfolio_returns[portfolio_returns > threshold]
    losses = portfolio_returns[portfolio_returns < threshold]
    omega_ratio = (
        np.sum(gains - threshold) / abs(np.sum(losses - threshold))
        if len(losses) > 0 and np.sum(losses - threshold) != 0
        else 0
    )

    # Exposure Metrics
    max_gross_exposure = 100  # Always 100% invested in this strategy

    # Trade Statistics
    total_trades = period_months  # One trade per month (rebalancing)
    total_closed_trades = period_months - 1  # All except current month
    total_open_trades = 1  # Current month position

    winning_trades = np.sum(portfolio_returns > 0)
    losing_trades = np.sum(portfolio_returns < 0)
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

    best_trade = np.max(portfolio_returns) * 100
    worst_trade = np.min(portfolio_returns) * 100

    avg_winning_trade = np.mean(portfolio_returns[portfolio_returns > 0]) * 100 if winning_trades > 0 else 0
    avg_losing_trade = np.mean(portfolio_returns[portfolio_returns < 0]) * 100 if losing_trades > 0 else 0

    # Trade durations (all trades are 1 month)
    avg_winning_trade_duration = 1
    avg_losing_trade_duration = 1

    # Profit Factor
    gross_profit = np.sum(portfolio_returns[portfolio_returns > 0])
    gross_loss = abs(np.sum(portfolio_returns[portfolio_returns < 0]))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    return {
        "time_metrics": {
            "start": start_date,
            "end": end_date,
            "period": f"{period_months} months ({period_years:.1f} years)",
        },
        "capital_metrics": {
            "start_value": start_value,
            "end_value": round(end_value, 2),
            "total_fees_paid": total_fees_paid,
            "open_trade_pnl": open_trade_pnl,
        },
        "return_metrics": {
            "total_return": round(total_return * 100, 2),
            "benchmark_return": round(benchmark_total_return * 100, 2),
            "expectancy": round(expectancy * 100, 2),
        },
        "risk_metrics": {
            "max_drawdown": round(max_drawdown * 100, 2),
            "max_drawdown_duration": dd_duration,
            "sharpe_ratio": round(sharpe_ratio, 2),
            "calmar_ratio": round(calmar_ratio, 2),
            "omega_ratio": round(omega_ratio, 2),
            "sortino_ratio": round(sortino_ratio, 2),
        },
        "exposure_metrics": {"max_gross_exposure": max_gross_exposure},
        "trade_statistics": {
            "total_trades": total_trades,
            "total_closed_trades": total_closed_trades,
            "total_open_trades": total_open_trades,
            "win_rate": round(win_rate, 2),
            "best_trade": round(best_trade, 2),
            "worst_trade": round(worst_trade, 2),
            "avg_winning_trade": round(avg_winning_trade, 2),
            "avg_losing_trade": round(avg_losing_trade, 2),
            "avg_winning_trade_duration": avg_winning_trade_duration,
            "avg_losing_trade_duration": avg_losing_trade_duration,
            "profit_factor": round(profit_factor, 2),
        },
    }


def run_backtest():
    print("Starting **Simple** Momentum Backtest (All Nifty)...")
    db = DatabaseManager()

    # Ensure tables exist
    from app.database import Base

    Base.metadata.create_all(db.engine)

    session = db.Session()

    # 1. Fetch Benchmark (Nifty 50)
    print("Fetching Benchmark Data...")
    try:
        nifty = yf.download(
            "^NSEI", start=(datetime.now() - relativedelta(years=10)).strftime("%Y-%m-%d"), progress=False
        )
        if nifty.empty:
            print("Warning: Could not fetch Nifty data. Benchmark returns will be 0.")
            nifty = pd.DataFrame(columns=["close"])
        else:
            nifty["date"] = nifty.index
            nifty = nifty[["date", "Close"]]
            if isinstance(nifty.columns, pd.MultiIndex):
                nifty.columns = nifty.columns.get_level_values(0)
            nifty = nifty.rename(columns={"Close": "close"})
    except Exception as e:
        print(f"Error fetching benchmark: {e}")
        nifty = pd.DataFrame(columns=["close"])

    # Load ALL daily prices into memory once
    print("Loading ALL price data into memory (this may take a moment)...")
    all_prices_query = text("SELECT stock_id, date, close_price, open_price FROM daily_prices ORDER BY date ASC")
    all_prices_result = session.execute(all_prices_query).fetchall()

    master_df = pd.DataFrame(all_prices_result, columns=["stock_id", "date", "close_price", "open_price"])
    master_df["date"] = pd.to_datetime(master_df["date"])
    master_df = master_df.set_index("date")
    print(f"Loaded {len(master_df)} price records into memory.")

    # Load Stock Names
    stock_map = {}
    stocks = session.execute(text("SELECT id, nse_symbol FROM stocks")).fetchall()
    for s in stocks:
        stock_map[s.id] = s.nse_symbol

    # 2. Iterate Months (from 2018 to present)
    dates = get_month_ends()
    all_results = []

    # Pre-calculate eligible stocks based on Market Cap (Global Filter)
    min_mcap_cr = float(os.getenv("MIN_MARKET_CAP_CR", 2000))
    min_mcap = min_mcap_cr * 10000000

    # We fetch all active stocks > mcap
    valid_stocks_query = text(f"SELECT id FROM stocks WHERE is_active = true AND market_cap >= {min_mcap}")
    valid_stock_ids = [r[0] for r in session.execute(valid_stocks_query).fetchall()]

    print(f"Applying Filters: Market Cap (> {min_mcap_cr} Cr) ONLY.")
    print(f"Eligible Stocks: {len(valid_stock_ids)}")

    def process_period(
        rebalance_date, next_rebalance_date, label_date=None, valid_stock_ids=None, use_close_to_close=False
    ):
        print(f"Processing {rebalance_date.date()} -> {next_rebalance_date.date()}")

        start_window = rebalance_date - timedelta(days=400)

        try:
            df_slice = master_df.loc[start_window:rebalance_date]
        except KeyError:
            print("  No price data found for this period.")
            return None

        if df_slice.empty:
            print("  No price data found for this period.")
            return None

        df_window = df_slice.reset_index()
        df_window = df_window.set_index(["stock_id", "date"])

        # Calculate Momentum
        top_stocks_df = calculate_momentum_for_date(session, rebalance_date, df_window, valid_stock_ids=valid_stock_ids)

        if top_stocks_df.empty:
            print("  No stocks found.")
            return None

        # Select Top 15 (Standard)
        top_stocks = top_stocks_df.head(15)
        selected_stock_ids = top_stocks["stock_id"].tolist()

        score_map = top_stocks.set_index("stock_id")["weighted_z"].to_dict()

        # Calculate Portfolio Return
        portfolio_returns = []
        stock_returns_detail = []

        try:
            df_next_slice = master_df.loc[rebalance_date + timedelta(days=1) : next_rebalance_date]
            df_next = df_next_slice[df_next_slice["stock_id"].isin(selected_stock_ids)].reset_index()
        except KeyError:
            df_next = pd.DataFrame()

        if not df_next.empty:
            for stock_id in selected_stock_ids:
                try:
                    # Determine Start Price
                    if use_close_to_close:
                        try:
                            prev_close_row = df_window.xs(stock_id, level="stock_id").iloc[-1]
                            start_price = prev_close_row["close_price"]
                        except (KeyError, IndexError):
                            stock_data_next = df_next[df_next["stock_id"] == stock_id].sort_values("date")
                            if not stock_data_next.empty:
                                start_price = stock_data_next.iloc[0]["open_price"]
                            else:
                                raise IndexError
                    else:
                        stock_data_next = df_next[df_next["stock_id"] == stock_id].sort_values("date")
                        if stock_data_next.empty:
                            stock_returns_detail.append(
                                {
                                    "symbol": stock_map.get(stock_id, "Unknown"),
                                    "return": 0.0,
                                    "score": round(score_map.get(stock_id, 0), 2),
                                }
                            )
                            continue

                        start_price = stock_data_next.iloc[0]["open_price"]
                except (KeyError, IndexError):
                    stock_returns_detail.append(
                        {
                            "symbol": stock_map.get(stock_id, "Unknown"),
                            "return": 0.0,
                            "score": round(score_map.get(stock_id, 0), 2),
                        }
                    )
                    continue

                # Exit at End of Month Close
                stock_data_next = df_next[df_next["stock_id"] == stock_id].sort_values("date")
                end_price = start_price if stock_data_next.empty else stock_data_next.iloc[-1]["close_price"]

                ret = (end_price - start_price) / start_price
                portfolio_returns.append(ret)
                stock_returns_detail.append(
                    {
                        "symbol": stock_map.get(stock_id, "Unknown"),
                        "return": round(ret * 100, 2),
                        "score": round(score_map.get(stock_id, 0), 2),
                    }
                )

        if not portfolio_returns:
            port_ret = 0
            if not stock_returns_detail:
                for stock_id in selected_stock_ids:
                    stock_returns_detail.append(
                        {
                            "symbol": stock_map.get(stock_id, "Unknown"),
                            "return": 0.0,
                            "score": round(score_map.get(stock_id, 0), 2),
                        }
                    )
        else:
            port_ret = sum(portfolio_returns) / len(portfolio_returns)

        # Benchmark Return
        if not nifty.empty:
            n_prev = nifty[nifty["date"] <= rebalance_date]
            n_curr = nifty[nifty["date"] <= next_rebalance_date]

            if not n_prev.empty and not n_curr.empty:
                n_start_price = n_prev.iloc[-1]["close"]
                n_end_price = n_curr.iloc[-1]["close"]
                bench_ret = (n_end_price - n_start_price) / n_start_price
            else:
                bench_ret = 0
        else:
            bench_ret = 0

        print(f"  Port: {port_ret:.2%}, Bench: {bench_ret:.2%}")

        month_label = label_date or next_rebalance_date.strftime("%Y-%m")

        return {
            "month": month_label,
            "portfolio_return": round(port_ret * 100, 2),
            "benchmark_return": round(bench_ret * 100, 2),
            "holdings": stock_returns_detail,
        }

    # 3. Load Existing Data (Freeze check)
    output_path = os.path.join(base_dir, "web", "src", "data", "backtest_results_simple_all_nifty.json")

    existing_results_map = {}
    existing_backtest_metrics = None

    if os.path.exists(output_path):
        try:
            with open(output_path) as f:
                existing_data = json.load(f)
                # Combine backtest and current to find all existing completed months
                combined_results = existing_data.get("backtest_results", []) + existing_data.get(
                    "current_performance", []
                )
                for r in combined_results:
                    if "month" in r:
                        existing_results_map[r["month"]] = r

                existing_backtest_metrics = existing_data.get("backtest_metrics")
                print(f"Loaded {len(existing_results_map)} existing monthly records.")
        except Exception as e:
            print(f"Could not load existing data: {e}")

    # Processing Loop
    for i, rebalance_date in enumerate(dates[:-1]):
        next_rebalance_date = dates[i + 1]
        month_label = next_rebalance_date.strftime("%Y-%m")

        # Check if already exists in JSON
        if month_label in existing_results_map:
            # Skip calculation, use existing
            all_results.append(existing_results_map[month_label])
            continue

        print(f"Processing {rebalance_date.date()} -> {next_rebalance_date.date()} ({month_label})")
        res = process_period(
            rebalance_date, next_rebalance_date, valid_stock_ids=valid_stock_ids, use_close_to_close=False
        )
        if res:
            all_results.append(res)

    # Current Month (Live) - ALWAYS Recalculate if it's the current open month
    last_rebalance_date = dates[-1]
    today = datetime.now()

    # Only process current partial month if today is AFTER the last standard backtest period
    if today > last_rebalance_date:
        current_month_label = today.strftime("%Y-%m")
        print(f"Processing Current Month (Live): {last_rebalance_date.date()} -> {today.date()}")
        res = process_period(
            last_rebalance_date,
            today,
            label_date=current_month_label,
            valid_stock_ids=valid_stock_ids,
            use_close_to_close=True,
        )

        if res:
            # Always update/replace current month
            all_results = [r for r in all_results if r["month"] != current_month_label]
            all_results.append(res)

    # Sort all results
    all_results.sort(key=lambda x: x["month"])

    # Split results
    backtest_cutoff = "2025-12"
    backtest_results = [r for r in all_results if r["month"] <= backtest_cutoff]
    current_results = [r for r in all_results if r["month"] > backtest_cutoff]

    print("\nCalculating stats...")

    def calculate_stats_for_period(results, start_value=100000, initial_holdings=None):
        total_transactions = 0
        previous_holdings = initial_holdings or set()

        for result in results:
            current_holdings = {h["symbol"] for h in result["holdings"]}
            if previous_holdings:
                stocks_to_sell = previous_holdings - current_holdings
                stocks_to_buy = current_holdings - previous_holdings
                transactions_this_month = len(stocks_to_sell) + len(stocks_to_buy)
                total_transactions += transactions_this_month
            else:
                total_transactions += len(current_holdings)
            previous_holdings = current_holdings

        # Calculate fees
        cumulative_values = []
        port_value = start_value
        for r in results:
            port_value = port_value * (1 + r["portfolio_return"] / 100)
            cumulative_values.append(port_value)

        if not cumulative_values:
            return 0, 0, 0

        avg_portfolio_value = np.mean(cumulative_values)
        fee_per_transaction = (avg_portfolio_value / 15) * 0.0025
        total_fees_paid = total_transactions * fee_per_transaction

        final_value = cumulative_values[-1]
        net_value_after_fees = final_value - total_fees_paid
        net_return_after_fees = ((net_value_after_fees - start_value) / start_value) * 100

        return total_transactions, total_fees_paid, net_return_after_fees

    # Backtest Stats
    # Reuse metrics if data length matches (crude check, but effective for freezing)
    if existing_backtest_metrics and len(backtest_results) == 94:
        # Actually, it's safer to always Recalculate METRICS locally, as it's fast.
        # The expensive part is 'process_period' which queries DB and momentum.
        # So we can just recalculate metrics on the frozen result set.
        pass

    print("Calculating Comprehensive Metrics...")

    bt_transactions, bt_fees, bt_net_return = calculate_stats_for_period(backtest_results)
    print(f"Backtest Transactions: {bt_transactions}")
    print(f"Backtest Net Return: {bt_net_return:.2f}%")

    backtest_metrics = calculate_comprehensive_metrics(backtest_results, backtest_results)
    backtest_metrics["trade_statistics"]["total_stock_transactions"] = bt_transactions
    backtest_metrics["capital_metrics"]["total_fees_paid"] = round(bt_fees, 2)
    backtest_metrics["return_metrics"]["net_return_after_fees"] = round(bt_net_return, 2)

    # Current Stats
    last_backtest_holdings = {h["symbol"] for h in backtest_results[-1]["holdings"]} if backtest_results else set()
    cur_transactions, cur_fees, cur_net_return = calculate_stats_for_period(
        current_results, start_value=100000, initial_holdings=last_backtest_holdings
    )
    print(f"Current Transactions: {cur_transactions}")

    current_metrics = None
    if current_results:
        current_metrics = calculate_comprehensive_metrics(current_results, current_results)
        current_metrics["trade_statistics"]["total_stock_transactions"] = cur_transactions
        current_metrics["capital_metrics"]["total_fees_paid"] = round(cur_fees, 2)
        current_metrics["return_metrics"]["net_return_after_fees"] = round(cur_net_return, 2)

    output_data = {
        "backtest_metrics": backtest_metrics,
        "current_metrics": current_metrics,
        "backtest_results": sorted(backtest_results, key=lambda x: x["month"], reverse=True),
        "current_performance": sorted(current_results, key=lambda x: x["month"], reverse=True),
    }

    # Output to separate file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nBacktest saved to {output_path}")


if __name__ == "__main__":
    run_backtest()
