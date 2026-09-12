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

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import DatabaseManager, MomentumHistory

CLOSE_STOP_PCT = -0.10  # Close below -10% from entry → sell next morning at open
GTT_STOP_PCT = -0.15  # Hard GTT: if open or intraday low hits -15%, exit that day


def get_month_ends():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    dates = []
    current = datetime(2017, 12, 1) + relativedelta(months=1)
    while current <= today:
        dates.append(current - timedelta(days=1))
        current += relativedelta(months=1)
    return dates


def calculate_quick_momentum_for_date(session, target_date, stocks_df, valid_stock_ids=None):
    """Quick Momentum Score: volatility-adjusted 1M + 3M + 6M returns (equal weight)."""
    scores = []
    unique_stocks = stocks_df.index.get_level_values("stock_id").unique()

    for stock_id in unique_stocks:
        if valid_stock_ids is not None and stock_id not in valid_stock_ids:
            continue
        try:
            df = stocks_df.loc[stock_id]
            df = df[df.index <= target_date].sort_index()

            if len(df) < 252:
                continue

            df["log_ret"] = np.log(df["close_price"] / df["close_price"].shift(1))
            volatility = df["log_ret"].tail(252).std() * np.sqrt(252)

            if pd.isna(volatility) or volatility == 0:
                continue

            current_price = df["close_price"].iloc[-1]

            def get_ret(days):
                if len(df) <= days:
                    return None
                return (current_price / df["close_price"].iloc[-(days + 1)]) - 1

            r1m = get_ret(21)
            r3m = get_ret(63)
            r6m = get_ret(126)
            r1y = get_ret(252)

            if None in [r1m, r3m, r6m, r1y]:
                continue

            scores.append(
                {
                    "stock_id": stock_id,
                    "mr_1m": r1m / volatility,
                    "mr_3m": r3m / volatility,
                    "mr_6m": r6m / volatility,
                    "mr_1y": r1y / volatility,
                }
            )

        except KeyError:
            continue

    if not scores:
        return []

    df_scores = pd.DataFrame(scores)

    for period in ["1m", "3m", "6m", "1y"]:
        col = f"mr_{period}"
        mean = df_scores[col].mean()
        std = df_scores[col].std()
        df_scores[f"z_{period}"] = (df_scores[col] - mean) / std if std > 0 else 0

    df_scores["weighted_z"] = (df_scores["z_1m"] + df_scores["z_3m"] + df_scores["z_6m"] + df_scores["z_1y"]) / 4
    return df_scores.sort_values("weighted_z", ascending=False)


def calculate_comprehensive_metrics(monthly_results, benchmark_results):
    if not monthly_results:
        return {
            "time_metrics": {"start": "-", "end": "-", "period": "-"},
            "capital_metrics": {"start_value": 0, "end_value": 0, "total_fees_paid": 0, "open_trade_pnl": 0},
            "return_metrics": {"total_return": 0, "benchmark_return": 0, "expectancy": 0, "net_return_after_fees": 0},
            "risk_metrics": {
                "max_drawdown": 0,
                "max_drawdown_duration": 0,
                "sharpe_ratio": 0,
                "calmar_ratio": 0,
                "omega_ratio": 0,
                "sortino_ratio": 0,
            },
            "exposure_metrics": {"max_gross_exposure": 0},
            "trade_statistics": {
                "total_trades": 0,
                "total_stock_transactions": 0,
                "win_rate": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "avg_winning_trade": 0,
                "avg_losing_trade": 0,
                "profit_factor": 0,
            },
        }

    portfolio_returns = np.array([r["portfolio_return"] / 100 for r in monthly_results])
    benchmark_returns = np.array([r["benchmark_return"] / 100 for r in monthly_results])

    start_date = monthly_results[0]["month"]
    end_date = monthly_results[-1]["month"]
    period_months = len(monthly_results)
    period_years = period_months / 12

    start_value = 100000
    cumulative_portfolio = np.cumprod(1 + portfolio_returns)
    cumulative_benchmark = np.cumprod(1 + benchmark_returns)
    end_value = start_value * cumulative_portfolio[-1]

    total_return = (end_value - start_value) / start_value
    benchmark_total_return = (start_value * cumulative_benchmark[-1] - start_value) / start_value
    expectancy = np.mean(portfolio_returns)

    cumulative_values = start_value * cumulative_portfolio
    running_max = np.maximum.accumulate(cumulative_values)
    drawdowns = (cumulative_values - running_max) / running_max
    max_drawdown = np.min(drawdowns)

    dd_duration = 0
    current_dd_duration = 0
    for dd in drawdowns:
        if dd < 0:
            current_dd_duration += 1
            dd_duration = max(dd_duration, current_dd_duration)
        else:
            current_dd_duration = 0
    dd_duration = dd_duration

    excess_returns = portfolio_returns
    sharpe_ratio = (
        (np.mean(excess_returns) * 12) / (np.std(excess_returns) * np.sqrt(12)) if np.std(excess_returns) > 0 else 0
    )
    annualized_return = (1 + total_return) ** (1 / period_years) - 1
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0

    downside_returns = portfolio_returns[portfolio_returns < 0]
    downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 0
    sortino_ratio = (np.mean(excess_returns) * 12) / (downside_std * np.sqrt(12)) if downside_std > 0 else 0

    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    omega_ratio = np.sum(gains) / abs(np.sum(losses)) if len(losses) > 0 and np.sum(losses) != 0 else 0

    total_trades = period_months
    winning_trades = np.sum(portfolio_returns > 0)
    losing_trades = np.sum(portfolio_returns < 0)
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

    best_trade = np.max(portfolio_returns) * 100
    worst_trade = np.min(portfolio_returns) * 100
    avg_winning_trade = np.mean(portfolio_returns[portfolio_returns > 0]) * 100 if winning_trades > 0 else 0
    avg_losing_trade = np.mean(portfolio_returns[portfolio_returns < 0]) * 100 if losing_trades > 0 else 0

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
            "total_fees_paid": 0,
            "open_trade_pnl": 0,
        },
        "return_metrics": {
            "total_return": round(total_return * 100, 2),
            "benchmark_return": round(benchmark_total_return * 100, 2),
            "expectancy": round(expectancy * 100, 2),
            "net_return_after_fees": 0,
        },
        "risk_metrics": {
            "max_drawdown": round(max_drawdown * 100, 2),
            "max_drawdown_duration": dd_duration,
            "sharpe_ratio": round(sharpe_ratio, 2),
            "calmar_ratio": round(calmar_ratio, 2),
            "omega_ratio": round(omega_ratio, 2),
            "sortino_ratio": round(sortino_ratio, 2),
        },
        "exposure_metrics": {"max_gross_exposure": 100},
        "trade_statistics": {
            "total_trades": total_trades,
            "total_closed_trades": total_trades - 1,
            "total_open_trades": 1,
            "win_rate": round(win_rate, 2),
            "best_trade": round(best_trade, 2),
            "worst_trade": round(worst_trade, 2),
            "avg_winning_trade": round(avg_winning_trade, 2),
            "avg_losing_trade": round(avg_losing_trade, 2),
            "avg_winning_trade_duration": 1,
            "avg_losing_trade_duration": 1,
            "profit_factor": round(profit_factor, 2),
            "total_stock_transactions": 0,
        },
    }


def run_backtest():
    print("Starting Quick Momentum + 10% Stop Loss Backtest (1M+3M+6M)...")
    db = DatabaseManager()

    from app.database import Base

    Base.metadata.create_all(db.engine)

    session = db.Session()

    print("Fetching Benchmark Data...")
    try:
        nifty = yf.download(
            "^NSEI", start=(datetime.now() - relativedelta(years=10)).strftime("%Y-%m-%d"), progress=False
        )
        if nifty.empty:
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
            else:
                nifty = pd.DataFrame(columns=["close"])
    except Exception as e:
        print(f"Error fetching benchmark: {e}")
        nifty = pd.DataFrame(columns=["close"])

    print("Loading ALL price data into memory...")
    all_prices_result = session.execute(
        text("SELECT stock_id, date, close_price, open_price, low_price FROM daily_prices ORDER BY date ASC")
    ).fetchall()

    master_df = pd.DataFrame(all_prices_result, columns=["stock_id", "date", "close_price", "open_price", "low_price"])
    master_df["date"] = pd.to_datetime(master_df["date"])
    master_df = master_df.set_index("date")
    print(f"Loaded {len(master_df)} price records into memory.")

    stock_map = {s.id: s.nse_symbol for s in session.execute(text("SELECT id, nse_symbol FROM stocks")).fetchall()}

    dates = get_month_ends()
    all_results = []

    min_mcap_cr = float(os.getenv("MIN_MARKET_CAP_CR", 2000))
    min_mcap = min_mcap_cr * 10000000
    valid_stock_ids = [
        r[0]
        for r in session.execute(
            text(f"SELECT id FROM stocks WHERE is_active = true AND market_cap >= {min_mcap}")
        ).fetchall()
    ]
    print(f"Applying Market Cap Filter (> {min_mcap_cr} Cr). Eligible Stocks: {len(valid_stock_ids)}")

    def process_period(
        rebalance_date, next_rebalance_date, label_date=None, valid_stock_ids=None, use_close_to_close=False
    ):
        print(f"Processing {rebalance_date.date()} -> {next_rebalance_date.date()}")

        start_window = rebalance_date - timedelta(days=400)
        try:
            df_slice = master_df.loc[start_window:rebalance_date]
        except KeyError:
            return None

        if df_slice.empty:
            return None

        df_window = df_slice.reset_index()
        df_window = df_window.set_index(["stock_id", "date"])

        top_stocks_df = calculate_quick_momentum_for_date(
            session, rebalance_date, df_window, valid_stock_ids=valid_stock_ids
        )
        if top_stocks_df.empty:
            return None

        top_stocks = top_stocks_df.head(15)
        selected_stock_ids = top_stocks["stock_id"].tolist()
        score_map = top_stocks.set_index("stock_id")["weighted_z"].to_dict()

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
                    stock_data_next = df_next[df_next["stock_id"] == stock_id].sort_values("date")

                    if use_close_to_close:
                        try:
                            prev_close_row = df_window.xs(stock_id, level="stock_id").iloc[-1]
                            start_price = prev_close_row["close_price"]
                        except (KeyError, IndexError):
                            if not stock_data_next.empty:
                                start_price = stock_data_next.iloc[0]["open_price"]
                            else:
                                raise IndexError
                    else:
                        if stock_data_next.empty:
                            stock_returns_detail.append(
                                {
                                    "symbol": stock_map.get(stock_id, "Unknown"),
                                    "return": 0.0,
                                    "score": round(score_map.get(stock_id, 0), 2),
                                    "entry_price": None,
                                    "stop_triggered": False,
                                }
                            )
                            continue
                        start_price = stock_data_next.iloc[0]["open_price"]

                    # Combined stop logic (evaluated each day in order):
                    # 1. GTT -15%: if open <= GTT level → gap-down, fill at open (actual loss).
                    #              if intraday low <= GTT level → fill at exactly -15%.
                    # 2. Close -10%: if GTT not hit but close <= -10% → sell next morning at open.
                    stop_triggered = False
                    stop_ret = CLOSE_STOP_PCT
                    if not stock_data_next.empty:
                        gtt_price = start_price * (1 + GTT_STOP_PCT)
                        close_price_trigger = start_price * (1 + CLOSE_STOP_PCT)
                        rows = list(stock_data_next.iterrows())
                        for idx, (_, daily_row) in enumerate(rows):
                            open_p = daily_row["open_price"]
                            low_p = daily_row["low_price"]
                            close_p = daily_row["close_price"]
                            if pd.notna(open_p) and open_p <= gtt_price:
                                stop_triggered = True
                                stop_ret = (open_p - start_price) / start_price
                                break
                            if pd.notna(low_p) and low_p <= gtt_price:
                                stop_triggered = True
                                stop_ret = GTT_STOP_PCT
                                break
                            if pd.notna(close_p) and close_p <= close_price_trigger:
                                stop_triggered = True
                                if idx + 1 < len(rows):
                                    next_open = rows[idx + 1][1]["open_price"]
                                    stop_ret = (
                                        (next_open - start_price) / start_price
                                        if pd.notna(next_open)
                                        else (close_p - start_price) / start_price
                                    )
                                else:
                                    stop_ret = (close_p - start_price) / start_price
                                break

                    if stop_triggered:
                        ret = stop_ret
                    elif stock_data_next.empty:
                        ret = 0.0
                    else:
                        end_price = stock_data_next.iloc[-1]["close_price"]
                        ret = (end_price - start_price) / start_price

                    portfolio_returns.append(ret)
                    stock_returns_detail.append(
                        {
                            "symbol": stock_map.get(stock_id, "Unknown"),
                            "return": round(ret * 100, 2),
                            "score": round(score_map.get(stock_id, 0), 2),
                            "entry_price": round(float(start_price), 2)
                            if start_price and not pd.isna(start_price)
                            else None,
                            "stop_triggered": stop_triggered,
                        }
                    )

                except (KeyError, IndexError):
                    stock_returns_detail.append(
                        {
                            "symbol": stock_map.get(stock_id, "Unknown"),
                            "return": 0.0,
                            "score": round(score_map.get(stock_id, 0), 2),
                            "entry_price": None,
                            "stop_triggered": False,
                        }
                    )
                    continue

        if not portfolio_returns:
            port_ret = 0
            if not stock_returns_detail:
                for stock_id in selected_stock_ids:
                    stock_returns_detail.append(
                        {
                            "symbol": stock_map.get(stock_id, "Unknown"),
                            "return": 0.0,
                            "score": round(score_map.get(stock_id, 0), 2),
                            "entry_price": None,
                            "stop_triggered": False,
                        }
                    )
        else:
            port_ret = sum(portfolio_returns) / len(portfolio_returns)

        if not nifty.empty:
            n_prev = nifty[nifty["date"] <= rebalance_date]
            n_curr = nifty[nifty["date"] <= next_rebalance_date]
            if not n_prev.empty and not n_curr.empty:
                bench_ret = (n_curr.iloc[-1]["close"] - n_prev.iloc[-1]["close"]) / n_prev.iloc[-1]["close"]
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

    output_path = os.path.join(base_dir, "web", "src", "data", "backtest_results_quick_momentum_10pct_stop.json")

    existing_results_map = {}
    if os.path.exists(output_path):
        try:
            with open(output_path) as f:
                data = json.load(f)
            combined = (
                data.get("backtest_results", []) + data.get("current_performance", [])
                if isinstance(data, dict)
                else data
            )
            for r in combined:
                if "month" in r:
                    existing_results_map[r["month"]] = r
            print(f"Loaded existing results for {len(existing_results_map)} months.")
        except Exception as e:
            print(f"Could not load existing results: {e}")

    for i, rebalance_date in enumerate(dates[:-1]):
        next_rebalance_date = dates[i + 1]
        month_label = next_rebalance_date.strftime("%Y-%m")

        if month_label in existing_results_map:
            all_results.append(existing_results_map[month_label])
            continue

        res = process_period(rebalance_date, next_rebalance_date, valid_stock_ids=valid_stock_ids)
        if res:
            all_results.append(res)

    last_rebalance_date = dates[-1]
    today = datetime.now()
    if today > last_rebalance_date:
        current_month_label = today.strftime("%Y-%m")
        all_results = [r for r in all_results if r["month"] != current_month_label]
        res = process_period(
            last_rebalance_date,
            today,
            label_date=current_month_label,
            valid_stock_ids=valid_stock_ids,
            use_close_to_close=True,
        )
        if res:
            all_results.append(res)

    all_results.sort(key=lambda x: x["month"])

    backtest_cutoff = "2025-12"
    backtest_results = [r for r in all_results if r["month"] <= backtest_cutoff]
    current_results = [r for r in all_results if r["month"] > backtest_cutoff]

    def calculate_stats_for_period(results, start_value=100000, initial_holdings=None):
        total_transactions = 0
        previous_holdings = initial_holdings or set()
        for result in results:
            current_holdings = {h["symbol"] for h in result["holdings"]}
            if previous_holdings:
                total_transactions += len(current_holdings - previous_holdings) + len(
                    previous_holdings - current_holdings
                )
            else:
                total_transactions += len(current_holdings)
            previous_holdings = current_holdings

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
        net_return_after_fees = ((final_value - total_fees_paid - start_value) / start_value) * 100
        return total_transactions, total_fees_paid, net_return_after_fees

    bt_transactions, bt_fees, bt_net_return = calculate_stats_for_period(backtest_results)
    backtest_metrics = calculate_comprehensive_metrics(backtest_results, backtest_results)
    backtest_metrics["trade_statistics"]["total_stock_transactions"] = bt_transactions
    backtest_metrics["capital_metrics"]["total_fees_paid"] = round(bt_fees, 2)
    backtest_metrics["return_metrics"]["net_return_after_fees"] = round(bt_net_return, 2)

    last_backtest_holdings = {h["symbol"] for h in backtest_results[-1]["holdings"]} if backtest_results else set()
    cur_transactions, cur_fees, cur_net_return = calculate_stats_for_period(
        current_results, initial_holdings=last_backtest_holdings
    )

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

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nBacktest saved to {output_path}")
    print(f"Backtest period: {len(backtest_results)} months")
    print(f"Current performance: {len(current_results)} months")


if __name__ == "__main__":
    run_backtest()
