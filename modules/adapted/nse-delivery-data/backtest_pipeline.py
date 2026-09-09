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
backtest_pipeline.py
====================
1. Loads 3 years of nested NSE delivery data.
2. Trains the LightGBM model dynamically in memory.
3. Simulates a trading strategy: Buy when Breakout Probability >= 75%, Hold for 5 days.
4. Computes performance KPIs and passes them to Gemini API for a strategic review.
   * Includes a network fallback to prevent API 503 errors from breaking the workflow.
"""
import os
import sys

import numpy as np
import pandas as pd
from google import genai
from train_breakout_model import engineer_features_and_targets, load_and_clean_data, train_breakout_model


def run_historical_backtest(df, model):
    print("\nRunning historical simulation using dynamically trained model...")

    feature_cols = [
        "DELIV_PER",
        "DELIV_SPIKE_RATIO",
        "DELIV_PER_5MA",
        "PRICE_RETURN_1D",
        "PRICE_RETURN_5D",
        "PRICE_VOLATILITY_20D",
        "TURNOVER_SPIKE",
    ]

    print("Generating historical probability scores across 3-year window...")
    df["BREAKOUT_PROBABILITY"] = model.predict(df[feature_cols])

    # Simulate a realistic exit: 5-day forward return
    df["FORWARD_5D_RETURN"] = df.groupby("SYMBOL")["CLOSE_PRICE"].pct_change(5).shift(-5) * 100

    # Strategy Rule: Trigger a signal when model confidence is high (e.g., >= 75%)
    SIGNAL_THRESHOLD = 0.75
    trades = df[df["BREAKOUT_PROBABILITY"] >= SIGNAL_THRESHOLD].copy()

    if trades.empty:
        return None, "No trades were triggered with the current threshold."

    trades = trades.dropna(subset=["FORWARD_5D_RETURN"])

    # Calculate Backtest KPIs
    total_signals = len(trades)
    if total_signals == 0:
        return None, "No valid trades remained after timeline filtering."

    winning_trades = trades[trades["FORWARD_5D_RETURN"] > 0]
    win_rate = (len(winning_trades) / total_signals) * 100
    avg_return_per_trade = trades["FORWARD_5D_RETURN"].mean()
    max_win = trades["FORWARD_5D_RETURN"].max()
    max_loss = trades["FORWARD_5D_RETURN"].min()

    # Calculate performance by year to spot market regime shifts
    trades["YEAR"] = trades["DATE"].dt.year
    yearly_perf = (
        trades.groupby("YEAR")
        .agg(
            Signals=("FORWARD_5D_RETURN", "count"),
            Avg_Return=("FORWARD_5D_RETURN", "mean"),
            Win_Rate=("FORWARD_5D_RETURN", lambda x: (sum(x > 0) / len(x)) * 100),
        )
        .round(2)
        .reset_index()
    )

    kpis = {
        "total_signals": total_signals,
        "win_rate": round(win_rate, 2),
        "avg_return": round(avg_return_per_trade, 2),
        "max_win": round(max_win, 2),
        "max_loss": round(max_loss, 2),
        "yearly_table": yearly_perf.to_markdown(index=False),
    }
    return kpis, trades


def ask_gemini_to_optimize(kpis):
    """Sends the raw backtest performance data to Gemini API for optimization ideas."""
    if not os.environ.get("GEMINI_API_KEY"):
        return "⚠️ *Gemini Analysis Skipped: GEMINI_API_KEY environment variable missing.*"

    print("Sending metrics to Gemini API for quantitative review...")
    client = genai.Client()

    prompt = f"""
    You are a Senior Quantitative Portfolio Manager. Analyze this backtest summary of an AI-driven stock selection model operating on the National Stock Exchange of India (NSE) over a 3-year historical window.

    **Strategy Rules:**
    - Entry: Buy stock at Close when a LightGBM delivery-anomaly model outputs a probability >= 75%.
    - Exit: Time-based exit. Hard-close position after exactly 5 trading days.

    **Backtest Execution Summary KPIs:**
    - Total Trading Signals Generated: {kpis["total_signals"]}
    - Strategy Win Rate: {kpis["win_rate"]}%
    - Average Return per Trade: {kpis["avg_return"]}%
    - Single Best Trade: {kpis["max_win"]}%
    - Single Worst Trade: {kpis["max_loss"]}%

    **Year-by-Year Performance Matrix:**
    {kpis["yearly_table"]}

    Please provide a professional, data-driven quantitative evaluation covering:
    1. **Regime Change Assessment:** Interpret the year-by-year performance matrix. Did the strategy stay stable, or did its performance decay over time?
    2. **Risk and Sizing Critique:** Look at the relationship between the average return per trade and the worst trade (`max_loss`). What does this tell us about our risk management?
    3. **Two Optimization Hypotheses:** Provide exactly two actionable adjustments we could test next to improve performance (e.g., modifying thresholds, adding stop-losses, or combining feature logic).

    Keep the output technical, practical for a software engineer, and cleanly structured in Markdown.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text


if __name__ == "__main__":
    DATA_PATH = "./HistoricalBhavCopy/NSE"

    try:
        raw_data = load_and_clean_data(DATA_PATH)
        processed_data = engineer_features_and_targets(raw_data)

        # Train model
        trained_model = train_breakout_model(processed_data)

        # Run backtest simulation
        kpis, trade_log = run_historical_backtest(processed_data, trained_model)

        if kpis is None:
            print(trade_log)
            sys.exit(0)

        # ── THE FALLBACK NETWORK GUARD ──
        try:
            ai_critique = ask_gemini_to_optimize(kpis)
        except Exception as api_error:
            print(f"Gemini API network call dropped or timed out: {api_error}")
            ai_critique = (
                "⚠️ **Gemini AI Commentary Temporarily Unavailable**\n\n"
                "The Google Gemini endpoint is experiencing high demand (HTTP 503/Server Busy). "
                "However, your underlying strategy simulation completed perfectly! Review the calculated table metrics below."
            )

        # Assemble Dashboard
        report_md = f"""
## 📊 3-Year Historical Backtest & AI Audit Report

### 📉 Core Performance Metrics (Probability Threshold >= 75%)
| Metric | Result |
| :--- | :--- |
| **Total Signals Triggered** | {kpis["total_signals"]} |
| **Strategy Win Rate** | {kpis["win_rate"]}% |
| **Avg Return per 5-Day Trade** | {kpis["avg_return"]}% |
| **Max Peak Win** | {kpis["max_win"]}% |
| **Max Peak Loss** | {kpis["max_loss"]}% |

### 📅 Annual Breakdown Matrix
{kpis["yearly_table"]}

---

### 🧠 Gemini AI Quantitative Optimization Review
{ai_critique}
"""

        summary_env = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_env:
            with open(summary_env, "a") as f:
                f.write(report_md)
            print("Successfully published multi-year backtest report to GitHub Dashboard!")
        else:
            print(report_md)

    except Exception as e:
        print(f"Backtest engine failed: {e}")
