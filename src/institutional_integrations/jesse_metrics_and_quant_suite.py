"""
Jesse Metrics & Quant Strategy Suite (EQATS Institutional Adaptation)
Adapted from jesse-ai/jesse (services/metrics.py) and je-suis-tm/quant-trading

Provides:
- JesseMetricsEngine:
  - Smart Sharpe Ratio (penalized for low sample size)
  - Smart Sortino Ratio (downside risk adjusted)
  - Omega Ratio (probability weighted ratio of gains vs. losses)
  - Serenity Index (return / (ulcer index * max drawdown))
- JesseQuantStrategyLibrary:
  - London Breakout Strategy
  - Heikin-Ashi Trend Strategy
  - Awesome Oscillator Strategy
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class JessePerformanceReport:
    total_trades: int
    win_rate: float
    sharpe_ratio: float
    smart_sharpe_ratio: float
    sortino_ratio: float
    smart_sortino_ratio: float
    omega_ratio: float
    serenity_index: float
    max_drawdown_pct: float
    expected_value_usd: float


@dataclass
class QuantStrategySignal:
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    strategy_name: str
    reason: str


class JesseMetricsEngine:
    """Jesse Advanced Metrics & Performance Evaluator."""

    def evaluate_performance(
        self,
        returns: list[float],
        trade_pnls: list[float],
        initial_balance: float = 100000.0,
        risk_free_rate: float = 0.0,
    ) -> JessePerformanceReport:
        """Calculates Smart Sharpe, Smart Sortino, Omega Ratio, and Serenity Index."""
        if not trade_pnls or len(trade_pnls) < 2:
            return JessePerformanceReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        pnl_arr = np.array(trade_pnls)
        n = len(pnl_arr)
        wins = np.sum(pnl_arr > 0)
        win_rate = wins / float(n) * 100.0
        ret_arr = np.array(returns) if returns else pnl_arr / initial_balance
        mean_ret = float(np.mean(ret_arr))
        std_ret = float(np.std(ret_arr, ddof=1)) if n > 1 else 1e-06
        sharpe = mean_ret / (std_ret + 1e-06) * math.sqrt(252)
        sample_penalty = 1.0 - 1.0 / math.log10(max(10, n)) if n > 1 else 0.5
        smart_sharpe = sharpe * max(0.1, sample_penalty)
        downside_rets = ret_arr[ret_arr < 0]
        downside_std = float(np.std(downside_rets, ddof=1)) if len(downside_rets) > 1 else 1e-06
        sortino = mean_ret / (downside_std + 1e-06) * math.sqrt(252)
        smart_sortino = sortino * max(0.1, sample_penalty)
        gains = np.sum(ret_arr[ret_arr > 0])
        losses = abs(np.sum(ret_arr[ret_arr < 0]))
        omega = float(gains / losses) if losses > 0 else 10.0
        cum_pnl = np.cumsum(pnl_arr)
        equity_curve = initial_balance + cum_pnl
        peak = np.maximum.accumulate(equity_curve)
        dd = (peak - equity_curve) / peak * 100.0
        max_dd_pct = float(np.max(dd)) if len(dd) > 0 else 0.0
        ulcer_index = math.sqrt(float(np.mean(dd**2))) if len(dd) > 0 else 1e-06
        tot_ret_pct = float(np.sum(pnl_arr)) / initial_balance * 100.0
        serenity_index = tot_ret_pct / (ulcer_index * max(1.0, max_dd_pct)) if max_dd_pct > 0 else 0.0
        expected_val = float(np.mean(pnl_arr))
        return JessePerformanceReport(
            total_trades=n,
            win_rate=round(win_rate, 1),
            sharpe_ratio=round(sharpe, 2),
            smart_sharpe_ratio=round(smart_sharpe, 2),
            sortino_ratio=round(sortino, 2),
            smart_sortino_ratio=round(smart_sortino, 2),
            omega_ratio=round(omega, 2),
            serenity_index=round(serenity_index, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            expected_value_usd=round(expected_val, 2),
        )


class JesseQuantStrategyLibrary:
    """London Breakout, Heikin-Ashi, and Awesome Oscillator Strategy Engines."""

    def london_breakout(
        self, current_price: float, asian_high: float, asian_low: float, atr: float,
    ) -> QuantStrategySignal:
        """London Session Asian Range Breakout Strategy."""
        if atr <= 0 or asian_high <= asian_low:
            return QuantStrategySignal("HOLD", current_price, 0.0, 0.0, 0.0, "london_breakout", "Invalid range")
        if current_price > asian_high:
            stop = asian_high - 1.0 * atr
            target = current_price + 2.5 * atr
            return QuantStrategySignal(
                "BUY", current_price, stop, target, 0.82, "london_breakout", "Bullish breakout of Asian High",
            )
        if current_price < asian_low:
            stop = asian_low + 1.0 * atr
            target = current_price - 2.5 * atr
            return QuantStrategySignal(
                "SELL", current_price, stop, target, 0.82, "london_breakout", "Bearish breakout of Asian Low",
            )
        return QuantStrategySignal(
            "HOLD", current_price, 0.0, 0.0, 0.0, "london_breakout", "Consolidating inside Asian range",
        )

    def heikin_ashi_trend(self, ha_opens: list[float], ha_closes: list[float], atr: float) -> QuantStrategySignal:
        """Smoothed Heikin-Ashi Trend Follower."""
        if len(ha_opens) < 3 or len(ha_closes) < 3 or atr <= 0:
            return QuantStrategySignal("HOLD", 0.0, 0.0, 0.0, 0.0, "heikin_ashi", "Insufficient bars")
        curr_open, curr_close = (ha_opens[-1], ha_closes[-1])
        prev_open, prev_close = (ha_opens[-2], ha_closes[-2])
        if curr_close > curr_open and prev_close > prev_open:
            stop = curr_close - 1.5 * atr
            target = curr_close + 3.0 * atr
            return QuantStrategySignal(
                "BUY", curr_close, stop, target, 0.8, "heikin_ashi", "Strong Bullish Heikin-Ashi Trend",
            )
        if curr_close < curr_open and prev_close < prev_open:
            stop = curr_close + 1.5 * atr
            target = curr_close - 3.0 * atr
            return QuantStrategySignal(
                "SELL", curr_close, stop, target, 0.8, "heikin_ashi", "Strong Bearish Heikin-Ashi Trend",
            )
        return QuantStrategySignal("HOLD", curr_close, 0.0, 0.0, 0.0, "heikin_ashi", "No clear HA trend momentum")

    def awesome_oscillator(
        self, highs: list[float], lows: list[float], current_price: float, atr: float,
    ) -> QuantStrategySignal:
        """Bill Williams Awesome Oscillator Zero-Line Crossover Strategy."""
        if len(highs) < 34 or len(lows) < 34 or atr <= 0:
            return QuantStrategySignal("HOLD", current_price, 0.0, 0.0, 0.0, "awesome_oscillator", "Insufficient bars")
        mid_prices = [(h + l) / 2.0 for h, l in zip(highs, lows)]
        sma5_curr = np.mean(mid_prices[-5:])
        sma34_curr = np.mean(mid_prices[-34:])
        ao_curr = sma5_curr - sma34_curr
        sma5_prev = np.mean(mid_prices[-6:-1])
        sma34_prev = np.mean(mid_prices[-35:-1])
        ao_prev = sma5_prev - sma34_prev
        if ao_prev < 0 and ao_curr > 0:
            stop = current_price - 1.5 * atr
            target = current_price + 3.0 * atr
            return QuantStrategySignal(
                "BUY", current_price, stop, target, 0.83, "awesome_oscillator", "Bullish AO Zero-Line Crossover",
            )
        if ao_prev > 0 and ao_curr < 0:
            stop = current_price + 1.5 * atr
            target = current_price - 3.0 * atr
            return QuantStrategySignal(
                "SELL", current_price, stop, target, 0.83, "awesome_oscillator", "Bearish AO Zero-Line Crossover",
            )
        return QuantStrategySignal("HOLD", current_price, 0.0, 0.0, 0.0, "awesome_oscillator", "No AO crossover")
