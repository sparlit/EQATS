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


"""US Simple Momentum Strategy backtest — 6M + 1Y volatility-adjusted scoring,
top 15 stocks, monthly rebalancing, 10% monthly stop-loss.
Benchmark: S&P 500 (^GSPC). Backtest: 2018–2025. Current: 2026+.
"""
STOP_LOSS_PCT = -0.10
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
sys.path.append(base_dir)
from app.database import DatabaseManager

OUTPUT_PATH = os.path.join(base_dir, "web", "src", "data", "backtest_results_us_simple_momentum_10pct_stop.json")
N_STOCKS = 15
BACKTEST_FROM = datetime(2016, 12, 1)  # warmup so Jan-2018 has 1Y lookback
BACKTEST_CUTOFF = "2025-12"
BENCHMARK_TICKER = "^GSPC"


def get_month_ends():
    today = datetime.now()
    dates, cur = [], BACKTEST_FROM + relativedelta(months=1)
    while cur <= today:
        dates.append(cur - timedelta(days=1))
        cur += relativedelta(months=1)
    return dates


def score_stocks(target_date, df_window):
    scores = []
    for stock_id, grp in df_window.groupby(level="stock_id"):
        grp = grp[grp.index.get_level_values("date") <= target_date].droplevel("stock_id")
        grp = grp.sort_index()
        if len(grp) < 252:
            continue
        log_ret = np.log(grp["close_price"] / grp["close_price"].shift(1))
        vol = log_ret.tail(252).std() * np.sqrt(252)
        if pd.isna(vol) or vol == 0:
            continue
        cp = grp["close_price"].iloc[-1]

        def ret(days):
            return (cp / grp["close_price"].iloc[-(days + 1)]) - 1 if len(grp) > days else None

        _r3m, r6m, r1y = ret(63), ret(126), ret(252)
        if None in (r6m, r1y):
            continue
        scores.append({"stock_id": stock_id, "mr_6m": r6m / vol, "mr_1y": r1y / vol})
    if not scores:
        return pd.DataFrame()
    df = pd.DataFrame(scores)
    for p in ["6m", "1y"]:
        col = f"mr_{p}"
        s = df[col].std()
        df[f"z_{p}"] = (df[col] - df[col].mean()) / s if s > 0 else 0.0
    df["weighted_z"] = (df["z_6m"] + df["z_1y"]) / 2
    return df.sort_values("weighted_z", ascending=False)


def process_period(rebalance_date, next_date, master_df, stock_map, benchmark_df, label=None, use_close_to_close=False):
    start_w = rebalance_date - timedelta(days=400)
    slice_w = master_df.loc[start_w:rebalance_date] if not master_df.empty else pd.DataFrame()
    if slice_w.empty:
        return None
    df_window = slice_w.reset_index().set_index(["stock_id", "date"])
    ranked = score_stocks(rebalance_date, df_window)
    if ranked.empty:
        return None

    top = ranked.head(N_STOCKS)
    score_map = top.set_index("stock_id")["weighted_z"].to_dict()
    ids = top["stock_id"].tolist()

    try:
        df_next = master_df.loc[rebalance_date + timedelta(days=1) : next_date]
        df_next = df_next[df_next["stock_id"].isin(ids)].reset_index()
    except KeyError:
        df_next = pd.DataFrame()

    rets, holdings = [], []
    for sid in ids:
        rows = df_next[df_next["stock_id"] == sid].sort_values("date") if not df_next.empty else pd.DataFrame()
        if rows.empty:
            holdings.append(
                {"symbol": stock_map.get(sid, "?"), "return": 0.0, "score": round(score_map.get(sid, 0), 2)}
            )
            continue
        if use_close_to_close:
            try:
                start_p = df_window.xs(sid, level="stock_id").sort_index().iloc[-1]["close_price"]
            except (KeyError, IndexError):
                start_p = rows.iloc[0]["open_price"] or rows.iloc[0]["close_price"]
        else:
            start_p = rows.iloc[0]["open_price"] or rows.iloc[0]["close_price"]
        stop_hit = False
        if start_p and not pd.isna(start_p):
            for _, daily in rows.iterrows():
                cp = daily["close_price"]
                if not pd.isna(cp) and (cp - start_p) / start_p <= STOP_LOSS_PCT:
                    stop_hit = True
                    break
        if stop_hit:
            r = STOP_LOSS_PCT
        elif start_p and not pd.isna(start_p):
            end_p = rows.iloc[-1]["close_price"]
            r = (end_p - start_p) / start_p if not pd.isna(end_p) else 0.0
        else:
            r = 0.0
        rets.append(r)
        holdings.append(
            {
                "symbol": stock_map.get(sid, "?"),
                "return": round(r * 100, 2),
                "score": round(score_map.get(sid, 0), 2),
                "stop_triggered": stop_hit,
            }
        )

    port_ret = float(np.mean(rets)) if rets else 0.0

    # Benchmark
    bn = benchmark_df[benchmark_df["date"] <= rebalance_date]
    bc = benchmark_df[benchmark_df["date"] <= next_date]
    bench_ret = (
        (bc.iloc[-1]["close"] - bn.iloc[-1]["close"]) / bn.iloc[-1]["close"] if (not bn.empty and not bc.empty) else 0.0
    )

    return {
        "month": label or next_date.strftime("%Y-%m"),
        "portfolio_return": round(port_ret * 100, 2),
        "benchmark_return": round(bench_ret * 100, 2),
        "holdings": holdings,
    }


def calc_metrics(results):
    if not results:
        return None
    rets = np.array([r["portfolio_return"] / 100 for r in results])
    bench = np.array([r["benchmark_return"] / 100 for r in results])
    n, yrs = len(rets), len(rets) / 12
    cum = np.cumprod(1 + rets)
    bench_cum = np.cumprod(1 + bench)
    total_ret = (cum[-1] - 1) * 100
    bench_total = (bench_cum[-1] - 1) * 100

    vals = 100000 * cum
    run_max = np.maximum.accumulate(vals)
    dds = (vals - run_max) / run_max
    max_dd = float(np.min(dds)) * 100

    dd_dur = cur_dur = 0
    for d in dds:
        if d < 0:
            cur_dur += 1
            dd_dur = max(dd_dur, cur_dur)
        else:
            cur_dur = 0

    sharpe = (np.mean(rets) * 12) / (np.std(rets) * np.sqrt(12)) if np.std(rets) > 0 else 0
    ann_ret = ((1 + cum[-1] - 1) ** (1 / yrs) - 1) if yrs > 0 else 0
    calmar = ann_ret / abs(max_dd / 100) if max_dd != 0 else 0
    down = rets[rets < 0]
    sortino = (np.mean(rets) * 12) / (np.std(down) * np.sqrt(12)) if len(down) > 0 and np.std(down) > 0 else 0
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    omega = np.sum(wins) / abs(np.sum(losses)) if len(losses) > 0 and np.sum(losses) != 0 else 0

    win_rate = float(np.sum(rets > 0) / n * 100)
    int(np.sum(rets > bench))

    # Fees
    prev_h, txns = set(), 0
    for r in results:
        cur_h = {h["symbol"] for h in r["holdings"]}
        txns += len(cur_h - prev_h) + len(prev_h - cur_h) if prev_h else len(cur_h)
        prev_h = cur_h
    avg_val = float(np.mean(vals))
    fees = txns * (avg_val / N_STOCKS) * 0.0025
    net_ret = ((100000 * cum[-1] - fees - 100000) / 100000) * 100

    return {
        "time_metrics": {
            "start": results[0]["month"],
            "end": results[-1]["month"],
            "period": f"{n} months ({yrs:.1f} years)",
        },
        "capital_metrics": {
            "start_value": 100000,
            "end_value": round(float(100000 * cum[-1]), 2),
            "total_fees_paid": round(fees, 2),
            "open_trade_pnl": 0,
        },
        "return_metrics": {
            "total_return": round(total_ret, 2),
            "benchmark_return": round(bench_total, 2),
            "expectancy": round(float(np.mean(rets) * 100), 2),
            "net_return_after_fees": round(net_ret, 2),
        },
        "risk_metrics": {
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_duration": dd_dur,
            "sharpe_ratio": round(sharpe, 2),
            "calmar_ratio": round(calmar, 2),
            "omega_ratio": round(omega, 2),
            "sortino_ratio": round(sortino, 2),
        },
        "exposure_metrics": {"max_gross_exposure": 100},
        "trade_statistics": {
            "total_trades": n,
            "win_rate": round(win_rate, 2),
            "best_trade": round(float(np.max(rets) * 100), 2),
            "worst_trade": round(float(np.min(rets) * 100), 2),
            "avg_winning_trade": round(float(np.mean(wins) * 100), 2) if len(wins) else 0,
            "avg_losing_trade": round(float(np.mean(losses) * 100), 2) if len(losses) else 0,
            "profit_factor": round(omega, 2),
            "total_stock_transactions": txns,
            "total_closed_trades": n - 1,
            "total_open_trades": 1,
            "avg_winning_trade_duration": 1,
            "avg_losing_trade_duration": 1,
        },
    }


def run_backtest():
    print("=== US Simple Momentum Strategy (6M+1Y, 10% Stop) ===")
    db = DatabaseManager()
    session = db.Session()
    try:
        # Benchmark
        print("Fetching S&P 500 benchmark...")
        bm_raw = yf.download(BENCHMARK_TICKER, start="2016-01-01", progress=False, auto_adjust=True)
        if isinstance(bm_raw.columns, pd.MultiIndex):
            bm_raw.columns = bm_raw.columns.get_level_values(0)
        bm_raw = bm_raw.reset_index()
        bm_raw.columns = [c.lower() for c in bm_raw.columns]
        bm_raw = bm_raw.rename(columns={"price": "close"}) if "price" in bm_raw.columns else bm_raw
        if "close" not in bm_raw.columns and "adj close" in bm_raw.columns:
            bm_raw = bm_raw.rename(columns={"adj close": "close"})
        benchmark_df = bm_raw[["date", "close"]].dropna()
        bm_dates = pd.to_datetime(benchmark_df["date"])
        benchmark_df["date"] = bm_dates.dt.tz_convert(None) if bm_dates.dt.tz is not None else bm_dates

        # Load all prices
        print("Loading US price data...")
        rows = session.execute(
            text("SELECT us_stock_id AS stock_id, date, close_price, open_price FROM us_daily_prices ORDER BY date ASC")
        ).fetchall()
        master_df = pd.DataFrame(rows, columns=["stock_id", "date", "close_price", "open_price"])
        master_df["date"] = pd.to_datetime(master_df["date"])
        master_df = master_df.set_index("date")
        print(f"Loaded {len(master_df):,} price records.")

        stock_map = {r.id: r.ticker for r in session.execute(text("SELECT id, ticker FROM us_stocks")).fetchall()}

        # Load cache
        existing = {}
        if os.path.exists(OUTPUT_PATH):
            try:
                with open(OUTPUT_PATH) as f:
                    d = json.load(f)
                for r in d.get("backtest_results", []) + d.get("current_performance", []):
                    existing[r["month"]] = r
                print(f"Loaded {len(existing)} cached months.")
            except Exception as e:
                print(f"Cache load failed: {e}")

        dates = get_month_ends()
        all_results = []
        for i, rd in enumerate(dates[:-1]):
            nd = dates[i + 1]
            label = nd.strftime("%Y-%m")
            if label in existing and existing[label].get("portfolio_return") is not None:
                all_results.append(existing[label])
                continue
            res = process_period(rd, nd, master_df, stock_map, benchmark_df)
            if res:
                all_results.append(res)

        # Current month (live)
        today = datetime.now()
        last_rd = dates[-1]
        if today > last_rd:
            cur_label = today.strftime("%Y-%m")
            all_results = [r for r in all_results if r["month"] != cur_label]
            res = process_period(
                last_rd, today, master_df, stock_map, benchmark_df, label=cur_label, use_close_to_close=True
            )
            if res:
                all_results.append(res)

        all_results.sort(key=lambda x: x["month"])
        bt = [r for r in all_results if r["month"] >= "2018-01" and r["month"] <= BACKTEST_CUTOFF]
        cur = [r for r in all_results if r["month"] >= "2026-01"]

        output = {
            "backtest_metrics": calc_metrics(bt),
            "current_metrics": calc_metrics(cur) if cur else None,
            "backtest_results": sorted(bt, key=lambda x: x["month"], reverse=True),
            "current_performance": sorted(cur, key=lambda x: x["month"], reverse=True),
        }

        def _sanitize(obj):
            if isinstance(obj, float) and (obj != obj or obj == float("inf") or obj == float("-inf")):
                return None
            if isinstance(obj, dict):
                return {k: _sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize(v) for v in obj]
            return obj

        with open(OUTPUT_PATH, "w") as f:
            json.dump(_sanitize(output), f, indent=2)
        print(f"Saved to {OUTPUT_PATH} — {len(bt)} backtest months, {len(cur)} current months.")
    finally:
        session.close()


if __name__ == "__main__":
    run_backtest()
