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


#!/usr/bin/env python3
"""
Algo Trader — Indian Stock Market Backtester
Just run:  python3 main.py
"""

from engine import apply_crossover, apply_price_vs_ema, build_chart, fetch, print_report, run_backtest

# Popular NSE stocks (name → yfinance ticker)
STOCKS = {
    "1": ("Reliance Industries", "RELIANCE.NS"),
    "2": ("TCS", "TCS.NS"),
    "3": ("Infosys", "INFY.NS"),
    "4": ("HDFC Bank", "HDFCBANK.NS"),
    "5": ("ICICI Bank", "ICICIBANK.NS"),
    "6": ("Wipro", "WIPRO.NS"),
    "7": ("Bajaj Finance", "BAJFINANCE.NS"),
    "8": ("Nifty 50 Index", "^NSEI"),
}

DATE_RANGES = {
    "1": ("Last 1 year", 365),
    "2": ("Last 2 years", 730),
    "3": ("Last 3 years", 1095),
    "4": ("Last 5 years", 1825),
}


def ask(prompt: str, valid: list) -> str:
    while True:
        val = input(prompt).strip()
        if val in valid:
            return val
        print(f"  Please enter one of: {', '.join(valid)}")


def main():
    print("\n" + "=" * 50)
    print("  Welcome to Algo Trader!")
    print("  Backtest EMA strategies on Indian stocks")
    print("=" * 50)

    # ── Pick stock ──────────────────────────────────────
    print("\nWhich stock do you want to test?\n")
    for k, (name, ticker) in STOCKS.items():
        print(f"  {k}. {name:25s} ({ticker})")
    print("  9. Enter a custom NSE ticker (e.g. TATAMOTORS.NS)")

    choice = ask("\nEnter number: ", [*list(STOCKS.keys()), "9"])

    if choice == "9":
        ticker = input("  Enter ticker symbol (e.g. TATAMOTORS.NS): ").strip().upper()
        stock_name = ticker
    else:
        stock_name, ticker = STOCKS[choice]

    # ── Pick date range ─────────────────────────────────
    print("\nHow far back should we test?\n")
    for k, (label, _) in DATE_RANGES.items():
        print(f"  {k}. {label}")

    days = DATE_RANGES[ask("\nEnter number: ", list(DATE_RANGES.keys()))][1]

    # ── Pick strategy ────────────────────────────────────
    print("\nWhich strategy do you want to use?\n")
    print("  1. EMA Crossover")
    print("     Buy when the short-term average crosses above the long-term average.")
    print("     Sell when it crosses back below.")
    print()
    print("  2. Price vs EMA")
    print("     Buy when the stock price rises above its moving average.")
    print("     Sell when it falls below.")

    strat = ask("\nEnter number: ", ["1", "2"])

    # ── Starting capital ─────────────────────────────────
    print("\nHow much money do you want to start with (in ₹)?")
    print("  Press Enter for default ₹1,00,000")
    cap_input = input("  ₹ ").strip()
    capital = float(cap_input.replace(",", "")) if cap_input else 100_000.0

    # ── Run ──────────────────────────────────────────────
    print(f"\nFetching data for {stock_name} ...")
    try:
        df, interval = fetch(ticker, days)
    except ValueError as e:
        print(f"\nError: {e}")
        return

    print(f"Got {len(df)} bars ({interval})  ({df.index[0].date()} to {df.index[-1].date()})\n")

    if strat == "1":
        df = apply_crossover(df, fast=12, slow=26)
        strategy_label = "EMA Crossover (12-day / 26-day)"
    else:
        df = apply_price_vs_ema(df, period=20)
        strategy_label = "Price vs EMA (20-day)"

    result = run_backtest(df, capital=capital)
    print_report(result, ticker=stock_name, strategy=strategy_label)

    # ── Chart ────────────────────────────────────────────
    show_chart_input = ask("Show chart? (y/n): ", ["y", "n", "Y", "N"])
    if show_chart_input.lower() == "y":
        fig = build_chart(df, result, ticker=stock_name, strategy=strategy_label)
        fig.show()

    # ── Run again? ───────────────────────────────────────
    again = ask("\nTest another stock or strategy? (y/n): ", ["y", "n", "Y", "N"])
    if again.lower() == "y":
        print()
        main()


if __name__ == "__main__":
    main()
