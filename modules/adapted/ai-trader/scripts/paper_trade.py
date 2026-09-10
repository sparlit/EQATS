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
Paper Trading Mode
──────────────────
Connects to TrueData real-time WebSocket and runs the full trading pipeline
(features → regime → signals → ML scoring → trade management) on live data,
but only LOGS trades — no real orders are placed.

Validates the system in real-time before going live.

Usage:
  python scripts/paper_trade.py                   # run during market hours
  python scripts/paper_trade.py --test            # test WS connection only
  python scripts/paper_trade.py --replay 2026-03-17  # replay a historical day (offline test)
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()

import numpy as np
import pandas as pd
from data.news_sentiment import NewsSentimentEngine
from data.truedata_adapter import TrueDataAdapter
from features.indicators import compute_all_macro_indicators
from features.option_chain_features import OptionChainFeatureEngine
from models.predict import Predictor
from models.strategy_models import StrategyPredictor
from strategy.regime_detector import MarketRegime, RegimeDetector, get_strategies_for_regime
from strategy.signal_generator import generate_signals
from utils.logger import get_logger

from config.settings import (
    ATM_RANGE,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    MAX_SYMBOLS,
    SCORE_THRESHOLD,
    STRIKE_GAP,
    SYMBOLS,
    TD_INDEX_FUTURES_SYMBOLS,
    TD_INDEX_SPOT_SYMBOLS,
    WEIGHT_ML_PROBABILITY,
    WEIGHT_OPTIONS_FLOW,
    WEIGHT_TECHNICAL_STRENGTH,
)
from database.db import get_engine, read_sql, write_df

# ── Setup logging ────────────────────────────────────────────────────────────
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"paper_trade_{date.today().strftime('%Y%m%d')}.log"
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
logging.getLogger().addHandler(file_handler)

logger = get_logger("paper_trade")

# ── Parameters (same as tick_replay_backtest) ─────────────────────────────────
BASE_LOT_SIZE = 65
SL_PCT = 0.30
TGT_PCT = 0.50
COMMISSION = 40.0
MAX_HOLD_BARS = 30
MAX_TRADES_DAY = 5
SKIP_FIRST_MIN = 5
SKIP_LAST_MIN = 15
MARKET_OPEN_MIN = 555  # 9:15 AM IST
MAX_PREMIUM = 250
AFTERNOON_CUT = 195  # no new trades after 12:30 IST
TRAILING_TRIGGER = 0.15
TRAILING_LOCK = 0.0

ATR_BASELINE = 0.00065
SL_MIN_PCT = 0.20
SL_MAX_PCT = 0.40
TGT_MIN_PCT = 0.35
TGT_MAX_PCT = 0.70

NEWS_LOOKBACK_HOURS = 4
NEWS_BLOCK_THRESHOLD = -0.30
NEWS_BOOST_THRESHOLD = 0.20
NEWS_BOOST_AMOUNT = 0.05

REGIME_LOT_MULTIPLIER = {
    MarketRegime.TRENDING_BULL: 1.25,
    MarketRegime.TRENDING_BEAR: 1.25,
    MarketRegime.HIGH_VOLATILITY: 0.50,
    MarketRegime.LOW_VOLATILITY: 1.00,
    MarketRegime.SIDEWAYS: 0.75,
    MarketRegime.UNKNOWN: 1.00,
}

# ── Global state ──────────────────────────────────────────────────────────────
running = True
tick_buffer = {}  # symbol -> list of tick dicts for current minute
last_minute = {}  # symbol -> last completed minute timestamp
candle_buffer = pd.DataFrame()  # rolling 1-min candle history for NIFTY-I
open_trade = None
completed_trades = []
daily_trades = 0
signals_seen = 0
signals_passed = 0


def signal_handler(signum, frame):
    global running
    print(f"\n  Signal {signum} received. Shutting down...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ── Helper functions ──────────────────────────────────────────────────────────


def minutes_from_open(ts) -> int:
    """Minutes since 9:15 AM IST."""
    t = pd.Timestamp(ts)
    if t.tz is not None:
        t = t.tz_convert("Asia/Kolkata")
    return (t.hour * 60 + t.minute) - MARKET_OPEN_MIN


def dynamic_sl_tgt(atr_pct: float):
    """Scale SL/TGT by ATR ratio."""
    if atr_pct <= 0 or np.isnan(atr_pct):
        return SL_PCT, TGT_PCT
    ratio = atr_pct / ATR_BASELINE
    sl = np.clip(SL_PCT * ratio, SL_MIN_PCT, SL_MAX_PCT)
    tgt = np.clip(TGT_PCT * ratio, TGT_MIN_PCT, TGT_MAX_PCT)
    return sl, tgt


def regime_lot_size(regime: MarketRegime) -> int:
    mult = REGIME_LOT_MULTIPLIER.get(regime, 1.0)
    return max(1, int(BASE_LOT_SIZE * mult))


class PaperTrade:
    """Tracks a simulated open trade."""

    def __init__(
        self,
        entry_time,
        symbol,
        direction,
        strategy,
        entry_premium,
        ml_prob,
        final_score,
        regime,
        sl_pct,
        tgt_pct,
        lot_size,
    ):
        self.entry_time = entry_time
        self.symbol = symbol
        self.direction = direction
        self.strategy = strategy
        self.entry_premium = entry_premium
        self.ml_prob = ml_prob
        self.final_score = final_score
        self.regime = regime
        self.sl_pct = sl_pct
        self.tgt_pct = tgt_pct
        self.lot_size = lot_size

        self.sl = round(entry_premium * (1 - sl_pct), 2)
        self.target = round(entry_premium * (1 + tgt_pct), 2)
        self.trailing_active = False
        self.trailing_sl = self.sl
        self.peak_premium = entry_premium

        self.exit_time = None
        self.exit_premium = None
        self.result = None
        self.pnl = None
        self.bar_count = 0

    def check_exit(self, current_premium: float, current_time) -> bool:
        """Check exit conditions. Returns True if trade should close."""
        self.bar_count += 1

        # Track peak for trailing
        self.peak_premium = max(self.peak_premium, current_premium)

        # Trailing stop activation
        move_pct = (current_premium - self.entry_premium) / self.entry_premium
        if move_pct >= TRAILING_TRIGGER and not self.trailing_active:
            self.trailing_active = True
            self.trailing_sl = self.entry_premium * (1 + TRAILING_LOCK)

        if self.trailing_active:
            new_trail = self.peak_premium * (1 - 0.05)
            self.trailing_sl = max(self.trailing_sl, new_trail)

        # SL hit
        if current_premium <= self.sl:
            self._close(current_premium, current_time, "SL")
            return True

        # Trailing SL hit
        if self.trailing_active and current_premium <= self.trailing_sl:
            self._close(self.trailing_sl, current_time, "TRAILING_SL")
            return True

        # Target hit
        if current_premium >= self.target:
            self._close(current_premium, current_time, "TARGET")
            return True

        # Timeout
        if self.bar_count >= MAX_HOLD_BARS:
            self._close(current_premium, current_time, "TIMEOUT")
            return True

        return False

    def _close(self, exit_prem, exit_time, result):
        self.exit_time = exit_time
        self.exit_premium = round(exit_prem, 2)
        self.result = result
        self.pnl = round((exit_prem - self.entry_premium) * self.lot_size - COMMISSION, 2)

    def to_dict(self):
        return {
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "symbol": self.symbol,
            "direction": self.direction,
            "strategy": self.strategy,
            "entry_premium": self.entry_premium,
            "exit_premium": self.exit_premium,
            "sl": self.sl,
            "target": self.target,
            "lot_size": self.lot_size,
            "ml_prob": self.ml_prob,
            "final_score": self.final_score,
            "regime": self.regime,
            "result": self.result,
            "pnl": self.pnl,
            "bars_held": self.bar_count,
        }


# ── Core pipeline: process each completed minute ─────────────────────────────


def process_minute(
    minute_ts: pd.Timestamp,
    minute_ticks: list,
    predictor: Predictor,
    strategy_predictor: StrategyPredictor,
    regime_detector: RegimeDetector,
    news_engine: NewsSentimentEngine,
    oc_engine: OptionChainFeatureEngine,
):
    """Process a completed 1-minute candle through the full trading pipeline."""
    global candle_buffer, open_trade, completed_trades, daily_trades
    global signals_seen, signals_passed

    if not minute_ticks:
        return

    # Build candle from ticks
    prices = [t["price"] for t in minute_ticks if t.get("price", 0) > 0]
    if not prices:
        return

    candle = {
        "timestamp": minute_ts,
        "symbol": "NIFTY-I",
        "open": prices[0],
        "high": max(prices),
        "low": min(prices),
        "close": prices[-1],
        "volume": sum(t.get("volume", 0) for t in minute_ticks),
        "vwap": 0,
        "oi": minute_ticks[-1].get("oi", 0),
    }
    candle_buffer = pd.concat([candle_buffer, pd.DataFrame([candle])], ignore_index=True).tail(500)

    # ── Check open trade exit ───────────────────────────────────────────
    if open_trade is not None:
        # Use latest price as premium proxy (for NIFTY-I based paper trade)
        current_prem = candle["close"]
        if open_trade.check_exit(current_prem, minute_ts):
            completed_trades.append(open_trade.to_dict())
            t = open_trade
            pnl_str = f"₹{t.pnl:+,.0f}"
            color = "\033[92m" if t.pnl > 0 else "\033[91m"
            reset = "\033[0m"
            print(f"  📤 EXIT  {t.result:7s}  {t.symbol}  {color}{pnl_str}{reset}")
            logger.info(f"EXIT {t.result} {t.symbol} pnl={t.pnl} bars={t.bar_count}")
            open_trade = None

    # ── Guards ──────────────────────────────────────────────────────────
    if open_trade is not None:
        return
    if daily_trades >= MAX_TRADES_DAY:
        return
    if len(candle_buffer) < 60:
        return

    mfo = minutes_from_open(minute_ts)
    if mfo < SKIP_FIRST_MIN or mfo > (375 - SKIP_LAST_MIN):
        return
    if mfo > AFTERNOON_CUT:
        return

    # ── News sentiment gate ─────────────────────────────────────────────
    news_boost = 0.0
    if news_engine is not None:
        try:
            ts_utc = minute_ts.tz_localize("UTC") if minute_ts.tz is None else minute_ts
            sentiment = news_engine.get_market_sentiment(lookback_hours=NEWS_LOOKBACK_HOURS, as_of=ts_utc)
            if sentiment["should_block_trading"]:
                return
            if sentiment["score"] < NEWS_BLOCK_THRESHOLD:
                return
            if sentiment["score"] > NEWS_BOOST_THRESHOLD:
                news_boost = NEWS_BOOST_AMOUNT
        except Exception:
            pass

    # ── Compute features ────────────────────────────────────────────────
    try:
        featured = compute_all_macro_indicators(candle_buffer.tail(300).copy())
        if featured.empty:
            return
        latest = featured.iloc[-1].to_dict()
    except Exception:
        return

    # ── Option chain features ───────────────────────────────────────────
    if oc_engine is not None:
        try:
            oc_feats = oc_engine.compute_for_timestamp(minute_ts, latest["close"])
            for k, v in oc_feats.items():
                if k in latest and (pd.isna(latest[k]) or latest[k] is None):
                    latest[k] = v
        except Exception:
            pass

    # ── Detect regime ───────────────────────────────────────────────────
    regime = MarketRegime.UNKNOWN
    regime_str = "UNKNOWN"
    regime_strategies = None
    try:
        rw = candle_buffer.tail(100)[["open", "high", "low", "close", "volume"]].copy()
        regime = regime_detector.detect(rw)
        regime_str = regime.value
        regime_strategies = get_strategies_for_regime(regime)
    except Exception:
        pass

    # ── Generate signals ────────────────────────────────────────────────
    signals = generate_signals(latest, "NIFTY-I")
    if not signals:
        return

    # ── Score each signal ───────────────────────────────────────────────
    for sig in signals:
        signals_seen += 1

        # ML scoring
        ml_prob = predictor.predict_macro(latest)
        if ml_prob is None:
            ml_prob = 0.5

        if sig.direction == "PUT" and ml_prob > 0.30:
            continue

        strat_prob = strategy_predictor.predict(sig.strategy, latest)
        strat_prob = strat_prob or 0.5

        flow_score = 0.5
        pcr = latest.get("pcr")
        if pcr and not np.isnan(pcr):
            flow_score = min(0.3 * (1 if pcr > 1.2 else 0) + 0.2, 1.0)

        regime_bonus = 0.05 if regime_strategies and sig.strategy in regime_strategies else 0.0

        directional_prob = ml_prob if sig.direction == "CALL" else (1.0 - ml_prob)
        final_score = (
            WEIGHT_ML_PROBABILITY * directional_prob
            + WEIGHT_OPTIONS_FLOW * flow_score
            + WEIGHT_TECHNICAL_STRENGTH * sig.technical_strength
            + regime_bonus
            + news_boost
        )

        min_score = 0.70 if sig.direction == "PUT" else SCORE_THRESHOLD
        if final_score < min_score:
            continue

        signals_passed += 1

        # ── Dynamic SL/TGT ──────────────────────────────────────────
        atr_pct = latest.get("atr_pct", 0)
        sl_pct, tgt_pct = dynamic_sl_tgt(atr_pct)
        lot_sz = regime_lot_size(regime)

        # ── Paper trade entry (use NIFTY level as premium proxy) ────
        entry_prem = latest["close"]  # In real mode, this would be option premium

        open_trade = PaperTrade(
            entry_time=minute_ts,
            symbol=f"NIFTY-PAPER-{sig.direction}",
            direction=sig.direction,
            strategy=sig.strategy,
            entry_premium=entry_prem,
            ml_prob=ml_prob,
            final_score=final_score,
            regime=regime_str,
            sl_pct=sl_pct,
            tgt_pct=tgt_pct,
            lot_size=lot_sz,
        )
        daily_trades += 1

        print(
            f"  📥 ENTRY {sig.direction:4s}  score={final_score:.2f}  "
            f"regime={regime_str}  strat={sig.strategy}  "
            f"SL={sl_pct:.0%}  TGT={tgt_pct:.0%}  lots={lot_sz}"
        )
        logger.info(
            f"ENTRY {sig.direction} score={final_score:.2f} regime={regime_str} "
            f"strat={sig.strategy} premium={entry_prem:.1f}"
        )
        break  # one trade at a time


def on_tick_paper(tick: dict, process_fn):
    """Buffer ticks by minute and process when a new minute starts."""
    global tick_buffer, last_minute

    symbol = tick.get("symbol", "")
    ts = tick.get("timestamp")
    if ts is None:
        return

    # Map spot symbol to futures symbol
    symbol_map = {v: k for k, v in TD_INDEX_SPOT_SYMBOLS.items()}
    if symbol in symbol_map:
        symbol = TD_INDEX_FUTURES_SYMBOLS.get(symbol_map[symbol], symbol)
        tick["symbol"] = symbol

    # Only process NIFTY-I ticks for trading logic
    if symbol != "NIFTY-I":
        return

    minute_ts = ts.replace(second=0, microsecond=0)
    if not isinstance(minute_ts, pd.Timestamp):
        minute_ts = pd.Timestamp(minute_ts)

    if symbol not in tick_buffer:
        tick_buffer[symbol] = []
        last_minute[symbol] = minute_ts

    # New minute → process the completed minute
    if minute_ts > last_minute.get(symbol, minute_ts):
        prev_ticks = tick_buffer[symbol]
        if prev_ticks:
            process_fn(last_minute[symbol], prev_ticks)
        tick_buffer[symbol] = []
        last_minute[symbol] = minute_ts

    tick_buffer[symbol].append(tick)


def print_summary():
    """Print end-of-session summary."""
    print(f"\n{'=' * 60}")
    print("  PAPER TRADING SESSION SUMMARY")
    print(f"  Date: {date.today()}")
    print(f"{'=' * 60}")

    if not completed_trades:
        print("  No trades executed.")
        return

    df = pd.DataFrame(completed_trades)
    total_pnl = df["pnl"].sum()
    n = len(df)
    wins = (df["pnl"] > 0).sum()

    print(f"\n  Total trades:    {n}")
    print(f"  Wins / Losses:   {wins}W / {n - wins}L ({wins / n * 100:.0f}% WR)")
    print(f"  Total P&L:       ₹{total_pnl:+,.0f}")
    print(f"  Avg P&L/trade:   ₹{df['pnl'].mean():+,.0f}")
    print(f"  Signals seen:    {signals_seen}")
    print(f"  Signals passed:  {signals_passed}")

    if n > 0:
        print(f"\n  {'Strategy':<25s} {'Trades':>6s} {'WR':>5s} {'P&L':>10s}")
        print(f"  {'─' * 25} {'─' * 6} {'─' * 5} {'─' * 10}")
        for strat, g in df.groupby("strategy"):
            wr = (g["pnl"] > 0).mean() * 100
            print(f"  {strat:<25s} {len(g):>6d} {wr:>4.0f}% {g['pnl'].sum():>+10,.0f}")

    # Save trades to CSV
    out_dir = Path("backtest_results")
    out_dir.mkdir(exist_ok=True)
    csv_path = out_dir / f"paper_trades_{date.today().strftime('%Y%m%d')}.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n  Trades saved to: {csv_path}")
    print(f"  Full log:        {log_file}")
    print(f"{'=' * 60}")


# ── Main: Live paper trading ──────────────────────────────────────────────────


def run_live_paper():
    """Connect to real-time WebSocket and run paper trading."""
    global running

    # Initialize components
    predictor = Predictor()
    predictor.load()
    strategy_predictor = StrategyPredictor()
    strategy_predictor.load()
    regime_detector = RegimeDetector()
    news_engine = NewsSentimentEngine()
    oc_engine = OptionChainFeatureEngine()

    print(f"  ML model:        {'loaded' if predictor.is_loaded else 'MISSING'}")
    print(f"  Strategy models: {strategy_predictor.available_strategies}")
    print("  News sentiment:  enabled")
    print("  Option chain:    enabled")

    # Load warmup candles from DB
    global candle_buffer
    warmup = read_sql(
        "SELECT timestamp, symbol, open, high, low, close, volume, vwap, oi "
        "FROM minute_candles WHERE symbol = 'NIFTY-I' "
        "ORDER BY timestamp DESC LIMIT 300"
    )
    if not warmup.empty:
        warmup["timestamp"] = pd.to_datetime(warmup["timestamp"])
        candle_buffer = warmup.sort_values("timestamp").reset_index(drop=True)
        print(f"  Warmup candles:  {len(candle_buffer)}")
    else:
        print("  Warmup candles:  0 (cold start)")

    # Connect to TrueData
    td = TrueDataAdapter()
    if not td.authenticate():
        print("  ERROR: TrueData authentication failed.")
        return
    print("  TrueData:        authenticated")

    if not td.ws_connect():
        print("  ERROR: WebSocket connection failed.")
        return
    print("  WebSocket:       connected")

    # Subscribe to NIFTY
    subscribe_symbols = [TD_INDEX_FUTURES_SYMBOLS.get("NIFTY", "NIFTY-I")]
    td.ws_subscribe(subscribe_symbols)

    # Process function with captured components
    def process_fn(minute_ts, minute_ticks):
        process_minute(minute_ts, minute_ticks, predictor, strategy_predictor, regime_detector, news_engine, oc_engine)

    # Tick handler
    def on_tick(tick):
        on_tick_paper(tick, process_fn)

    td.ws_start_streaming(on_tick)

    print(f"\n  {'─' * 60}")
    print("  PAPER TRADING LIVE — Waiting for market signals...")
    print("  Press Ctrl+C to stop")
    print(f"  {'─' * 60}\n")

    close_time = datetime(
        date.today().year, date.today().month, date.today().day, MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE, 0
    ) + timedelta(minutes=2)

    while running and datetime.now() < close_time:
        time.sleep(10)

    # Shutdown
    td.ws_stop_streaming()
    td.ws_disconnect()
    print_summary()


def run_replay_paper(replay_date: date):
    """Run paper trading on a historical day using the full tick replay engine."""
    global completed_trades

    # Import the full tick replay backtest (has proper option resolution)
    from scripts.tick_replay_backtest import replay_day as bt_replay_day

    predictor = Predictor()
    predictor.load()
    strategy_predictor = StrategyPredictor()
    strategy_predictor.load()
    regime_detector = RegimeDetector()
    news_engine = NewsSentimentEngine()
    oc_engine = OptionChainFeatureEngine()

    print(f"  ML model:        {'loaded' if predictor.is_loaded else 'MISSING'}")
    print(f"  Strategy models: {strategy_predictor.available_strategies}")
    print("  News sentiment:  enabled")
    print("  Option chain:    enabled")
    print(f"  Replaying:       {replay_date}")

    # Load warmup candles
    warmup = read_sql(
        "SELECT timestamp, symbol, open, high, low, close, volume, vwap, oi "
        "FROM minute_candles WHERE symbol = 'NIFTY-I' "
        "AND timestamp < :dt ORDER BY timestamp DESC LIMIT 300",
        {"dt": str(replay_date)},
    )
    if not warmup.empty:
        warmup["timestamp"] = pd.to_datetime(warmup["timestamp"])
        warmup = warmup.sort_values("timestamp").reset_index(drop=True)
    print(f"  Warmup candles:  {len(warmup)}")

    # Run the full tick replay (with option resolution, real premiums, etc.)
    day_trades = bt_replay_day(
        replay_date=replay_date,
        predictor=predictor,
        strategy_predictor=strategy_predictor,
        regime_detector=regime_detector,
        warmup_candles=warmup,
        news_engine=news_engine,
        oc_engine=oc_engine,
        verbose=True,
    )
    completed_trades = day_trades
    print_summary()


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Paper trading mode")
    parser.add_argument("--test", action="store_true", help="Test WS connection only")
    parser.add_argument("--replay", type=str, help="Replay historical day (YYYY-MM-DD)")
    args = parser.parse_args()

    print(f"{'=' * 60}")
    print("  🔮 PAPER TRADING MODE")
    print(f"  Date: {date.today()}")
    print(f"  Mode: {'REPLAY' if args.replay else 'LIVE'}")
    print(f"{'=' * 60}")

    if args.test:
        td = TrueDataAdapter()
        if td.authenticate() and td.ws_connect():
            print("  WebSocket connection: OK")
            td.ws_disconnect()
        else:
            print("  WebSocket connection: FAILED")
        return

    if args.replay:
        replay_date = datetime.strptime(args.replay, "%Y-%m-%d").date()
        run_replay_paper(replay_date)
    else:
        run_live_paper()


if __name__ == "__main__":
    main()
