"""
AXIOM Backtester — event-driven signal replay on daily OHLCV.

Strategy (mirrors the live screener / CLAUDE.md rules):
  ENTRY  : close > N-bar high  AND  volume > 1.5x 20d avg
           AND  ADX >= MIN_ADX  AND  EMA9 > EMA21 > EMA50  AND  close > EMA200
  STOP   : entry - (atr_mult * ATR)
  TARGET : entry + (rr_target * initial_risk)
  SIZING : shares = (capital * 2%) / (entry - stop)
  TRAIL  : at +1R -> stop to breakeven
           at +2R -> trail stop at 1.5 * ATR below close
  EXIT   : stop hit | target hit | end of data

One position per symbol at a time (no pyramiding, never average down).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config import (
    ADX_PERIOD,
    ATR_PERIOD,
    BREAKOUT_LOOKBACK,
    CAPITAL_RISK_PCT,
    EMA_PERIODS,
    MIN_ADX,
    VOLUME_CONFIRM,
    VOLUME_SMA_PERIOD,
)
from backtest.metrics import calculate_metrics, equity_curve
from utils.indicators import adx_full, atr, ema, validate_dataframe


@dataclass
class BacktestConfig:
    lookback:       int = BREAKOUT_LOOKBACK
    atr_mult:       float = 1.5      # initial stop distance in ATR
    rr_target:      float = 2.5      # reward:risk target
    vol_confirm:    float = VOLUME_CONFIRM
    min_adx:        float = float(MIN_ADX)
    risk_pct:       float = CAPITAL_RISK_PCT
    starting_capital: float = 1_000_000.0
    trail_atr_mult: float = 1.5      # trail distance after 2R
    breakeven_at_r: float = 1.0
    trail_at_r:     float = 2.0


@dataclass
class BacktestResult:
    symbol:   str
    trades:   pd.DataFrame
    metrics:  dict
    equity:   pd.Series = field(default_factory=pd.Series)


def _prepare(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Attach indicator columns needed for signal replay (single assign — CoW safe)."""
    validate_dataframe(df, ["open", "high", "low", "close", "volume"])
    out = df.copy()
    return out.assign(
        ema_9=ema(out["close"], EMA_PERIODS[0]),
        ema_21=ema(out["close"], EMA_PERIODS[1]),
        ema_50=ema(out["close"], EMA_PERIODS[2]),
        ema_200=ema(out["close"], EMA_PERIODS[3]),
        atr=atr(out, ATR_PERIOD),
        adx=adx_full(out, ADX_PERIOD)["adx"],
        vol_sma=out["volume"].rolling(VOLUME_SMA_PERIOD, min_periods=VOLUME_SMA_PERIOD).mean(),
        roll_high=out["high"].rolling(cfg.lookback, min_periods=cfg.lookback).max().shift(1),
    )


def _entry_signal(row: pd.Series, cfg: BacktestConfig) -> bool:
    if any(pd.isna(row.get(c)) for c in
           ["roll_high", "vol_sma", "adx", "atr", "ema_9", "ema_21", "ema_50", "ema_200"]):
        return False
    if row["vol_sma"] <= 0:
        return False
    return bool(
        row["close"] > row["roll_high"]
        and row["volume"] >= cfg.vol_confirm * row["vol_sma"]
        and row["adx"] >= cfg.min_adx
        and row["ema_9"] > row["ema_21"] > row["ema_50"]
        and row["close"] > row["ema_200"]
    )


def backtest_symbol(df: pd.DataFrame, symbol: str = "", cfg: BacktestConfig | None = None) -> BacktestResult:
    """
    Replay the breakout strategy bar-by-bar over a single symbol's daily history.

    Returns a BacktestResult with the closed-trade DataFrame, metrics and equity curve.
    """
    cfg = cfg or BacktestConfig()
    data = _prepare(df, cfg)

    trades: list[dict] = []
    in_pos = False
    entry = stop = target = init_risk = 0.0
    shares = 0
    entry_date = None
    entry_idx = 0
    hit_1r = hit_2r = False

    rows = list(data.iterrows())
    for i, (ts, row) in enumerate(rows):
        if in_pos:
            high, low, close = row["high"], row["low"], row["close"]
            exit_price = None
            reason = ""

            # Stop checked before target (conservative — assume stop hit intrabar first)
            if low <= stop:
                exit_price, reason = stop, "stop"
            elif high >= target:
                exit_price, reason = target, "target"

            if exit_price is None:
                # ── trailing-stop management ──
                r_now = (close - entry) / init_risk if init_risk > 0 else 0.0
                if not hit_1r and r_now >= cfg.breakeven_at_r:
                    stop = max(stop, entry)          # breakeven
                    hit_1r = True
                if r_now >= cfg.trail_at_r:
                    hit_2r = True
                if hit_2r and not pd.isna(row["atr"]):
                    stop = max(stop, close - cfg.trail_atr_mult * row["atr"])

            if exit_price is not None:
                pnl = shares * (exit_price - entry)
                trades.append({
                    "symbol":      symbol,
                    "entry_date":  entry_date,
                    "exit_date":   ts,
                    "entry":       round(entry, 2),
                    "stop":        round(stop, 2),
                    "target":      round(target, 2),
                    "exit_price":  round(exit_price, 2),
                    "shares":      shares,
                    "pnl":         round(pnl, 2),
                    "r_multiple":  round((exit_price - entry) / init_risk, 2) if init_risk > 0 else 0.0,
                    "return_pct":  round((exit_price - entry) / entry * 100, 2) if entry > 0 else 0.0,
                    "bars_held":   i - entry_idx,
                    "exit_reason": reason,
                })
                in_pos = False
                continue

        if not in_pos and _entry_signal(row, cfg):
            entry = float(row["close"])
            atr_val = float(row["atr"])
            stop = entry - cfg.atr_mult * atr_val
            init_risk = entry - stop
            if init_risk <= 0:
                continue
            target = entry + cfg.rr_target * init_risk
            shares = int((cfg.starting_capital * cfg.risk_pct) / init_risk)
            if shares <= 0:
                continue
            entry_date = ts
            entry_idx = i
            hit_1r = hit_2r = False
            in_pos = True

    trades_df = pd.DataFrame(trades)
    metrics = calculate_metrics(trades_df, cfg.starting_capital)
    eq = equity_curve(trades_df, cfg.starting_capital)
    return BacktestResult(symbol=symbol, trades=trades_df, metrics=metrics, equity=eq)


def backtest_portfolio(
    histories: dict[str, pd.DataFrame],
    cfg: BacktestConfig | None = None,
) -> BacktestResult:
    """
    Run the strategy across many symbols and aggregate into one combined result.
    `histories` maps symbol -> daily OHLCV DataFrame.
    """
    cfg = cfg or BacktestConfig()
    all_trades: list[pd.DataFrame] = []
    for sym, hist in histories.items():
        if hist is None or hist.empty:
            continue
        try:
            res = backtest_symbol(hist, symbol=sym, cfg=cfg)
            if not res.trades.empty:
                all_trades.append(res.trades)
        except Exception:
            continue

    combined = (
        pd.concat(all_trades, ignore_index=True).sort_values("exit_date").reset_index(drop=True)
        if all_trades else pd.DataFrame()
    )
    metrics = calculate_metrics(combined, cfg.starting_capital)
    eq = equity_curve(combined, cfg.starting_capital)
    return BacktestResult(symbol="PORTFOLIO", trades=combined, metrics=metrics, equity=eq)


# ── Backward-compatible shim ──────────────────────────────────────
def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    """Legacy entry point — returns the closed-trade DataFrame for a single symbol."""
    if df.empty:
        raise ValueError("Input DataFrame is empty")
    return backtest_symbol(df).trades
