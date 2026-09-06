"""
AXIOM Intraday Monitor — 15-min watchlist signal watcher.
Runs during market hours (9:30–15:15 IST), polls every 5 minutes.
Detects: BREAKOUT, BB_SQUEEZE_SETUP, MOMENTUM_CONT on 15-min timeframe.
Fires Telegram alerts on first trigger per symbol per session.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from loguru import logger

from config import (
    ADX_PERIOD,
    BB_PERIOD,
    BB_STD_DEV,
    BREAKOUT_LOOKBACK,
    EMA_PERIODS,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    MIN_ADX,
    RSI_PERIOD,
    VOLUME_SMA_PERIOD,
)
from monitors.telegram_bot import is_configured, send_alert, send_message
from utils.indicators import adx_full, atr, bollinger_bands, ema, macd, rsi

IST = ZoneInfo("Asia/Kolkata")
POLL_INTERVAL_SECONDS = 300   # 5 minutes
MARKET_OPEN_HOUR  = 9
MARKET_OPEN_MIN   = 30
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MIN  = 15


# ─────────────────────────────────────────────────────────────────
# DATA FETCH
# ─────────────────────────────────────────────────────────────────

def _fetch_15m(symbol: str, days: int = 5) -> pd.DataFrame:
    """Fetch last N days of 15-min OHLCV for a symbol via yfinance."""
    try:
        df = yf.Ticker(symbol).history(period=f"{days}d", interval="15m")
        if df.empty:
            return df
        df.columns = [c.lower() for c in df.columns]
        if hasattr(df.index, "tzinfo") and df.index.tzinfo:
            df.index = df.index.tz_localize(None)
        df = df.dropna(subset=["close", "high", "low", "volume"])
        return df
    except Exception as exc:
        logger.debug("15m fetch failed for {}: {}", symbol, exc)
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────
# SIGNAL DETECTION
# ─────────────────────────────────────────────────────────────────

def _compute_signals(df: pd.DataFrame) -> dict[str, object]:
    """
    Run all indicators on 15-min data and return a signal dict.
    Returns empty dict if insufficient data.
    """
    if len(df) < max(BREAKOUT_LOOKBACK + 1, BB_PERIOD, ADX_PERIOD * 2):
        return {}

    bb  = bollinger_bands(df["close"], BB_PERIOD, BB_STD_DEV)
    mac = macd(df["close"], MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    adx_df = adx_full(df, ADX_PERIOD)
    rsi_s  = rsi(df["close"], RSI_PERIOD)
    atr_s  = atr(df, ADX_PERIOD)
    vol_sma = df["volume"].rolling(window=VOLUME_SMA_PERIOD, min_periods=VOLUME_SMA_PERIOD).mean()
    ema9   = ema(df["close"], EMA_PERIODS[0])
    ema21  = ema(df["close"], EMA_PERIODS[1])
    ema50  = ema(df["close"], EMA_PERIODS[2])

    last = df.iloc[-1]
    close   = float(last["close"])
    volume  = float(last["volume"])
    vol_avg = float(vol_sma.iloc[-1]) if pd.notna(vol_sma.iloc[-1]) else 0
    vol_ratio = volume / vol_avg if vol_avg > 0 else 0

    adx_val  = float(adx_df["adx"].iloc[-1])
    di_plus  = float(adx_df["di_plus"].iloc[-1])
    di_minus = float(adx_df["di_minus"].iloc[-1])
    rsi_val  = float(rsi_s.iloc[-1])
    atr_val  = float(atr_s.iloc[-1]) if pd.notna(atr_s.iloc[-1]) else 0

    bb_upper  = float(bb["bb_upper"].iloc[-1])
    bb_lower  = float(bb["bb_lower"].iloc[-1])
    bb_middle = float(bb["bb_middle"].iloc[-1])
    bb_width_pct = (bb_upper - bb_lower) / close * 100 if close > 0 else 0

    macd_line = float(mac["macd"].iloc[-1])
    macd_sig  = float(mac["signal"].iloc[-1])
    macd_hist = float(mac["histogram"].iloc[-1])

    ema9_val  = float(ema9.iloc[-1])
    ema21_val = float(ema21.iloc[-1])
    ema50_val = float(ema50.iloc[-1])

    lookback_high = float(df["close"].iloc[-(BREAKOUT_LOOKBACK + 1):-1].max()) if len(df) > BREAKOUT_LOOKBACK else 0

    signals: list[str] = []

    # BREAKOUT: close > 20-bar high + vol surge + ADX >= 20
    if lookback_high > 0 and close > lookback_high and vol_ratio >= 1.5 and adx_val >= 20:
        signals.append("BREAKOUT")

    # BB_SQUEEZE_SETUP: tight bands + RSI > 50 + close above midline
    if bb_width_pct < 4.0 and rsi_val > 50 and close > bb_middle:
        signals.append("BB_SQUEEZE_SETUP")

    # MOMENTUM_CONT: EMA aligned + MACD bullish + RSI in sweet spot
    if (ema9_val > ema21_val > ema50_val
            and macd_hist > 0
            and macd_line > macd_sig
            and 50 <= rsi_val <= 75):
        signals.append("MOMENTUM_CONT")

    return {
        "signals":    signals,
        "close":      close,
        "rsi":        round(rsi_val, 1),
        "adx":        round(adx_val, 1),
        "di_plus":    round(di_plus, 1),
        "di_minus":   round(di_minus, 1),
        "vol_ratio":  round(vol_ratio, 2),
        "macd_hist":  round(macd_hist, 3),
        "bb_width":   round(bb_width_pct, 2),
        "atr":        round(atr_val, 2),
    }


# ─────────────────────────────────────────────────────────────────
# MONITOR STATE
# ─────────────────────────────────────────────────────────────────

class IntradayMonitor:
    """
    Stateful monitor that tracks which alerts have already fired
    this session to avoid duplicate notifications.
    """

    def __init__(self, symbols: list[str]) -> None:
        self.symbols   = symbols
        self.fired:    dict[str, set[str]] = {s: set() for s in symbols}
        self.last_scan: datetime | None = None
        self.scan_results: dict[str, dict] = {}

    def _is_market_hours(self) -> bool:
        now = datetime.now(IST)
        if now.weekday() >= 5:
            return False
        open_  = now.replace(hour=MARKET_OPEN_HOUR,  minute=MARKET_OPEN_MIN,  second=0, microsecond=0)
        close_ = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
        return open_ <= now <= close_

    def scan_once(self) -> dict[str, dict]:
        """Scan all symbols once, fire alerts for new signals, return results."""
        results: dict[str, dict] = {}
        new_alerts = 0

        for symbol in self.symbols:
            df = _fetch_15m(symbol)
            if df.empty:
                results[symbol] = {"signals": [], "error": "no data"}
                continue

            data = _compute_signals(df)
            if not data:
                results[symbol] = {"signals": [], "error": "insufficient bars"}
                continue

            results[symbol] = data

            # Fire alerts for signals not yet sent this session
            for sig in data.get("signals", []):
                if sig not in self.fired[symbol]:
                    self.fired[symbol].add(sig)
                    details = (
                        f"RSI: {data['rsi']} · ADX: {data['adx']} · "
                        f"Vol: {data['vol_ratio']}x · MACD hist: {data['macd_hist']}"
                    )
                    if send_alert(symbol, sig, data["close"], details):
                        logger.info("Telegram alert sent: {} — {}", symbol, sig)
                        new_alerts += 1
                    else:
                        logger.debug("Alert not sent (Telegram unconfigured): {} — {}", symbol, sig)

        self.last_scan = datetime.now(IST)
        self.scan_results = results
        if new_alerts:
            logger.success("Fired {} new alerts this scan cycle", new_alerts)
        return results

    def reset_session(self) -> None:
        """Clear fired-alert state at start of each trading day."""
        self.fired = {s: set() for s in self.symbols}
        logger.info("Intraday monitor session reset for {} symbols", len(self.symbols))

    def run_loop(self, poll_seconds: int = POLL_INTERVAL_SECONDS) -> None:
        """
        Blocking loop — polls every poll_seconds during market hours.
        Exits cleanly on KeyboardInterrupt.
        """
        logger.info("AXIOM Intraday Monitor started — {} symbols", len(self.symbols))
        if not is_configured():
            logger.warning("Telegram not configured — alerts will be logged only")

        last_reset_date: date | None = None

        try:
            while True:
                now_ist = datetime.now(IST)
                today   = now_ist.date()

                # Reset fired state at start of each new trading day
                if last_reset_date != today:
                    self.reset_session()
                    last_reset_date = today

                if self._is_market_hours():
                    logger.info("Scanning {} symbols @ {}", len(self.symbols), now_ist.strftime("%H:%M IST"))
                    self.scan_once()
                else:
                    logger.debug("Outside market hours — sleeping")

                time.sleep(poll_seconds)

        except KeyboardInterrupt:
            logger.info("Intraday monitor stopped by user")


# ─────────────────────────────────────────────────────────────────
# CONVENIENCE FACTORY
# ─────────────────────────────────────────────────────────────────

def make_monitor_from_watchlist() -> IntradayMonitor:
    """
    Build an IntradayMonitor from the watchlist.

    Order of preference:
      1. SQLite DB watchlist (local / persistent-disk deployments)
      2. Committed CSV watchlist (serverless — DB is ephemeral on CI runners)
    """
    symbols: list[str] = []
    try:
        from storage.db import create_connection
        conn = create_connection()
        df = pd.read_sql("SELECT symbol FROM watchlist WHERE status = 'active'", conn)
        conn.close()
        symbols = [s for s in df["symbol"].tolist() if s]
    except Exception as exc:
        logger.warning("Could not load watchlist from DB: {}", exc)

    if not symbols:
        from storage.watchlist_csv import load_watchlist_symbols
        symbols = load_watchlist_symbols()
        if symbols:
            logger.info("Loaded {} symbols from committed watchlist CSV", len(symbols))

    if not symbols:
        logger.warning("Watchlist empty (DB and CSV) — monitor will scan nothing")
    return IntradayMonitor(symbols)
