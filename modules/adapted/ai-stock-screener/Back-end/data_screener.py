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


# data_screener.py
import numpy as np
import pandas as pd
import yfinance as yf


def calculate_rsi(data: pd.Series, window: int = 14) -> pd.Series:
    """Calculates the Relative Strength Index (RSI) using price changes."""
    delta = data.diff()
    # Separate gains and losses
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()

    # Calculate Relative Strength (RS)
    rs = gain / loss
    # Convert RS into the 0-100 RSI scale
    return 100 - (100 / (1 + rs))


def fetch_and_screen_stocks(tickers: list) -> list:
    """
    Downloads historical data for a list of tickers, calculates technical indicators,
    and filters out stocks that do not meet the momentum criteria.
    """
    screened_stocks = []

    for ticker in tickers:
        # Append .NS to target the Indian National Stock Exchange on Yahoo Finance
        ns_ticker = f"{ticker}.NS"
        try:
            # Download the last 3 months of daily price data
            data = yf.download(ns_ticker, period="3mo", progress=False)

            if data.empty or len(data) < 50:
                continue  # Skip if there isn't enough data to calculate a 50-day moving average

            # Extract the closing prices
            close_prices = data["Close"].squeeze()

            # Calculate 20-day and 50-day Exponential Moving Averages (EMA)
            ema_20 = close_prices.ewm(span=20, adjust=False).mean()
            ema_50 = close_prices.ewm(span=50, adjust=False).mean()

            # Calculate the 14-day RSI
            rsi = calculate_rsi(close_prices, 14)

            # Get the most recent day's values for our indicators
            latest_close = float(close_prices.iloc[-1])
            latest_ema20 = float(ema_20.iloc[-1])
            latest_ema50 = float(ema_50.iloc[-1])
            latest_rsi = float(rsi.iloc[-1])

            # --- THE SCREENING RULES ---
            # 1. Price must be above the 20 EMA (Short-term bullish)
            # 2. 20 EMA must be above 50 EMA (Medium-term trend is up)
            # 3. RSI must be between 40 and 80 (Not deeply oversold, not extremely overbought)
            if (latest_close > latest_ema20 > latest_ema50) and (40 <= latest_rsi <= 80):
                # Calculate basic trade setup levels based on current price
                target = round(latest_close * 1.08, 2)  # 8% profit target
                stop_loss = round(latest_close * 0.95, 2)  # 5% stop loss risk

                # Save the passing stock to our list
                screened_stocks.append(
                    {
                        "ticker": ticker,
                        "close": round(latest_close, 2),
                        "rsi": round(latest_rsi, 2),
                        "trend": "Bullish",
                        "target": target,
                        "stop_loss": stop_loss,
                    }
                )
                print(f"✅ {ticker} passed technicals (RSI: {latest_rsi:.2f})")

        except Exception:
            # Silently skip tickers that fail to download or error out
            continue

    return screened_stocks
